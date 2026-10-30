"""Run each case as a real CLI subprocess and keep raw output, including failures."""
import json
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT
from .trace import write_json


def check_case(case, result, events, exit_code):
    expected = case['expected']
    checks = {'status': result.get('status') == expected['status'],
              'answer_contains': all((re.search(r'(?<![0-9])' + re.escape(s) + r'(?![0-9])', result.get('answer', '')) is not None) if s.isdigit() else s in result.get('answer', '') for s in expected['answer_contains']),
              'citation_ids': set(c.get('doc_id') for c in result.get('citations', [])) == set(expected['citation_ids']),
              'exit_code': exit_code == (2 if expected['status'] == 'incomplete' else 0),
              'trace_present': bool(events)}
    read_evidence = {(e.get('observation', {}).get('doc_id'), e.get('observation', {}).get('chunk_id')): e['observation']
                     for e in events if e.get('action') == 'read_doc' and e.get('observation', {}).get('ok')}
    checks['citations_grounded'] = all(
        isinstance(c.get('quote'), str) and bool(c['quote'].strip())
        and (c.get('doc_id'), c.get('chunk_id')) in read_evidence
        and c.get('version_date') == read_evidence[(c.get('doc_id'), c.get('chunk_id'))].get('version_date')
        and c['quote'] in read_evidence[(c.get('doc_id'), c.get('chunk_id'))].get('text', '')
        for c in result.get('citations', []))
    if expected['status'] != 'answered':
        checks['gaps_present'] = bool(result.get('gaps'))
    if case['id'] in ('T02', 'T09'):
        reads = [(i, e.get('observation', {}).get('doc_id')) for i, e in enumerate(events)
                 if e.get('action') == 'read_doc' and e.get('observation', {}).get('ok')]
        positions = [i for i, doc in reads if doc in {'D01', 'D02'}]
        checks['both_originals_read'] = {'D01', 'D02'} <= {doc for _, doc in reads}
        checks['conflict_followup_search'] = bool(positions) and any(i > max(positions) and e.get('action') == 'search_docs' for i, e in enumerate(events))
        checks['clarification_present'] = bool(result.get('clarification_question', '').strip())
    if case['id'] == 'T06':
        failed = [i for i, e in enumerate(events) if e.get('action') in ('search_docs', 'read_doc') and e.get('observation', {}).get('ok') is False]
        checks['observed_failure_then_recovery'] = bool(failed) and any(i > failed[0] and e.get('action') in ('search_docs', 'read_doc') and e.get('observation', {}).get('ok') is True for i, e in enumerate(events))
    if case['id'] == 'T08':
        checks['changed_quote'] = any('45' in c.get('quote', '') for c in result.get('citations', []))
        checks['no_stale_answer'] = '30' not in result.get('answer', '')
    if case['id'] == 'T10':
        checks['bounded'] = len(events) <= case['max_steps'] and result.get('reason') == 'step_limit'
    return checks


def evaluate_cases(cases_path, mode, output, timeout=30):
    cases = json.loads(Path(cases_path).read_text(encoding='utf-8'))
    if not isinstance(cases, list) or not cases:
        raise ValueError('cases 必须为非空数组')
    from .agent import STATUSES
    from .tools import FAULTS
    for c in cases:
        if not isinstance(c, dict) or not {'id', 'title', 'question', 'corpus', 'expected'} <= set(c):
            raise ValueError('用例缺少必需字段')
        if any(not isinstance(c[k], str) or not c[k].strip() for k in ('id', 'title', 'question', 'corpus')):
            raise ValueError('用例基本字段必须是非空文本')
        if type(c.get('max_steps', 10)) is not int or not 1 <= c.get('max_steps', 10) <= 30:
            raise ValueError('用例步数范围错误')
        if not isinstance(c.get('fault', 'none'), str) or c.get('fault', 'none') not in FAULTS:
            raise ValueError('用例故障模式错误')
        e = c['expected']
        if not isinstance(e, dict) or not {'status', 'answer_contains', 'citation_ids'} <= set(e):
            raise ValueError('用例缺少预期字段')
        if not isinstance(e['status'], str) or e['status'] not in STATUSES:
            raise ValueError('预期状态非法')
        if any(not isinstance(e[k], list) or any(not isinstance(v, str) or not v for v in e[k]) for k in ('answer_contains', 'citation_ids')):
            raise ValueError('预期内容必须是字符串数组')
        history = c.get('history', [])
        if not isinstance(history, list) or len(history) > 20 or any(not isinstance(h, dict) or set(h) != {'role', 'content'} or h['role'] not in ('user', 'assistant') or not isinstance(h['content'], str) for h in history):
            raise ValueError('用例历史非法')
    ids = [c['id'] for c in cases]
    if len(set(ids)) != len(ids) or any(not i.isalnum() for i in ids):
        raise ValueError('用例ID必须为唯一字母数字串')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'cases.json', cases)
    reports, outputs, traces = [], {}, {}
    for case in cases:
        case_dir = output / case['id']
        command = [sys.executable, str(ROOT / 'run.py'), 'ask', '--mode', mode, '--question', case['question'],
                   '--corpus', str(ROOT / case['corpus']), '--fault', case.get('fault', 'none'),
                   '--max-steps', str(case.get('max_steps', 10)), '--timeout', str(timeout), '--output', str(case_dir)]
        if case.get('history'):
            history_path = output / (case['id'] + '-history.json')
            write_json(history_path, case['history'])
            command += ['--history', str(history_path)]
        try:
            proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                  timeout=case.get('max_steps', 10) * timeout + 30)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b''
            stderr = exc.stderr or b''
            stdout = stdout.decode('utf-8', 'replace') if isinstance(stdout, bytes) else stdout
            stderr = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr
            stderr += '\nEvaluation subprocess timed out.'
            code = 124
        case_dir.mkdir(exist_ok=True)
        (case_dir / 'stdout.txt').write_text(stdout, encoding='utf-8')
        (case_dir / 'stderr.txt').write_text(stderr, encoding='utf-8')
        write_json(case_dir / 'process.json', {'command': command, 'cwd': str(ROOT), 'exit_code': code})
        result, events = {}, []
        if (case_dir / 'output.json').exists():
            result = json.loads((case_dir / 'output.json').read_text(encoding='utf-8'))
            events = [json.loads(line) for line in (case_dir / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        checks = check_case(case, result, events, code)
        outputs[case['id']], traces[case['id']] = result, events
        report = {'id': case['id'], 'title': case['title'], 'checks': checks, 'passed': all(checks.values()),
                  'status': result.get('status', 'not_run'), 'steps': len(events), 'artifacts': case['id'] + '/'}
        reports.append(report)
        write_json(case_dir / 'checks.json', report)
        print(case['id'], 'PASS' if report['passed'] else 'FAIL', report['status'], 'steps=' + str(len(events)), flush=True)
    pair_checks = {}
    if all(k in outputs for k in ('T01', 'T08', 'T09')):
        pair_checks = {
            'content_change_changes_answer': bool(outputs['T01']) and bool(outputs['T08']) and outputs['T01'].get('answer') != outputs['T08'].get('answer'),
            'conflict_changes_status': outputs['T01'].get('status') == 'answered' and outputs['T09'].get('status') == 'needs_clarification',
            'conflict_changes_actions': [e['action'] for e in traces['T01']] != [e['action'] for e in traces['T09']],
        }
    summary = {'mode': mode, 'passed': sum(r['passed'] for r in reports), 'total': len(reports),
               'cases': reports, 'paired_checks': pair_checks,
               'scope': '固定合成样本的工程与行为检查；非统计泛化评测，语义引用支持需人工复核',
               'mock_disclaimer': '仅验证流程，不证明真实模型决策效果' if mode == 'mock' else ''}
    write_json(output / 'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'cases'}, ensure_ascii=False, indent=2))
    return 0 if summary['passed'] == summary['total'] and all(pair_checks.values()) else 1
