"""Run each case as a real CLI subprocess and keep raw output, including failures."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT
from .trace import write_json


def _contains(text, term):
    """Numeric facts use token boundaries rather than accidental substrings."""
    return bool(re.search(r'(?<![0-9])' + re.escape(term) + r'(?![0-9])', text)) if term.isdigit() else term in text


def check_case(case, result, events, exit_code):
    """Check declared case expectations; legacy IDs remain backwards compatible.

    These are structural/behavioral checks, not a general semantic entailment
    judge. Correct quote text can still be used to make an unsupported claim.
    """
    expected = case['expected']
    allowed_sets = expected.get('citation_sets', [expected.get('citation_ids', [])])
    actual_ids = set(c.get('doc_id') for c in result.get('citations', []))
    checks = {'status': result.get('status') == expected['status'],
              'answer_contains': all(_contains(result.get('answer', ''), s) for s in expected['answer_contains']),
              'citation_ids': any(actual_ids == set(ids) for ids in allowed_sets),
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
    if expected['status'] == 'needs_clarification':
        checks['clarification_present'] = bool(result.get('clarification_question', '').strip())
    required_ids = set(expected.get('required_read_ids', ['D01', 'D02'] if case['id'] in ('T02', 'T09') else []))
    reads = [(i, e.get('observation', {}).get('doc_id')) for i, e in enumerate(events)
             if e.get('action') == 'read_doc' and e.get('observation', {}).get('ok')]
    if required_ids:
        checks['required_reads'] = required_ids <= {doc for _, doc in reads}
    if expected.get('search_after_reads', case['id'] in ('T02', 'T09')):
        # A valid extra re-read after checking must not erase earlier checking.
        gathered, first_complete = set(), None
        for index, doc in reads:
            gathered.add(doc)
            if required_ids and required_ids <= gathered:
                first_complete = index
                break
        checks['conflict_followup_search'] = first_complete is not None and any(
            i > first_complete and e.get('action') == 'search_docs' for i, e in enumerate(events))
    if expected.get('failure_then_recovery', case['id'] == 'T06'):
        def operation_key(event):
            if event.get('action') == 'search_docs':
                return ('search_docs',)
            if event.get('action') == 'read_doc':
                args = event.get('arguments', {})
                if args.get('doc_id') and args.get('chunk_id'):
                    return ('read_doc', args['doc_id'], args['chunk_id'])
            return None
        failed = [(i, operation_key(e)) for i, e in enumerate(events)
                  if operation_key(e) is not None and e.get('observation', {}).get('ok') is False]
        checks['observed_failure_then_recovery'] = any(
            j > i and operation_key(event) == key and event.get('observation', {}).get('ok') is True
            for i, key in failed for j, event in enumerate(events))
    if 'answer_excludes' in expected:
        checks['answer_excludes'] = not any(_contains(result.get('answer', ''), s) for s in expected['answer_excludes'])
    if 'quote_contains' in expected:
        quotes = [c.get('quote', '') for c in result.get('citations', [])]
        checks['quote_contains'] = all(any(_contains(q, s) for q in quotes) for s in expected['quote_contains'])
    if 'reason' in expected:
        checks['reason'] = result.get('reason') == expected['reason']
    if case['id'] == 'T08':
        # Preserve historical baseline expectations; new cases can declare a
        # more precise policy rather than inheriting this conservative rule.
        checks['changed_quote'] = any(_contains(c.get('quote', ''), '45') for c in result.get('citations', []))
        checks['no_stale_answer'] = '30' not in result.get('answer', '')
    if case['id'] == 'T10':
        # Voluntary incomplete on the last allowed decision is also a safe
        # budget stop; never force a model to spend a tool call just to fail.
        last = events[-1] if events else {}
        voluntary_stop = (result.get('reason') == 'model_finished'
                          and last.get('action') == 'finish'
                          and last.get('arguments', {}).get('status') == 'incomplete'
                          and last.get('observation', {}).get('ok') is True)
        checks['bounded'] = (result.get('status') == 'incomplete'
                             and len(events) == case['max_steps']
                             and (result.get('reason') == 'step_limit' or voluntary_stop))
    return checks


def _source_sha256():
    digest = hashlib.sha256()
    for source in sorted((ROOT / 'src/knowledge_agent').glob('*.py')):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def check_run_evidence(case, result, events, directory, mode, expected_source_sha256=None):
    """Cross-check persisted run artifacts against local inputs and corpus.

    Consistency checks are not cryptographic proof of a remote model identity
    or semantic proof that every statement follows from a valid quotation.
    """
    metadata = result.get('metadata', {})
    checks = {
        'mode_matches': metadata.get('mode') == mode,
        'source_matches': metadata.get('source_sha256') == (expected_source_sha256 or _source_sha256()),
        'step_count_matches': metadata.get('steps') == len(events),
        'step_sequence_valid': [e.get('step') for e in events] == list(range(1, len(events)+1)),
        'budget_respected': metadata.get('max_steps') == case.get('max_steps', 10) and len(events) <= case.get('max_steps', 10),
        'trace_identity_matches': bool(metadata.get('run_id')) and bool(events) and all(e.get('run_id') == metadata.get('run_id') and e.get('mode') == mode for e in events),
    }
    checks['next_action_chain_valid'] = bool(events) and all(
        event.get('next_action') == (events[i+1].get('action') if i+1 < len(events) else 'stop:' + str(result.get('reason')))
        for i, event in enumerate(events))
    directory = Path(directory)
    if (directory / 'process.json').exists():
        try:
            process = json.loads((directory / 'process.json').read_text(encoding='utf-8'))
            code = process.get('exit_code')
            checks['process_exit_matches_state'] = type(code) is int and code == (2 if result.get('status') == 'incomplete' else 0)
        except (OSError, ValueError, AttributeError):
            checks['process_exit_matches_state'] = False
    try:
        checks['stdout_matches_output'] = json.loads((directory / 'stdout.txt').read_text(encoding='utf-8')) == result
    except (OSError, ValueError):
        checks['stdout_matches_output'] = False
    try:
        stored_input = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
        checks['input_matches_case'] = all(stored_input.get(key) == value for key, value in {
            'question': case['question'], 'history': case.get('history', []), 'mode': mode,
            'fault': case.get('fault', 'none'), 'max_steps': case.get('max_steps', 10)}.items())
        checks['input_corpus_matches'] = Path(stored_input['corpus']).resolve() == (ROOT / case['corpus']).resolve()
    except (OSError, ValueError, TypeError, KeyError):
        checks['input_matches_case'] = checks['input_corpus_matches'] = False
    try:
        corpus_bytes = (ROOT / case['corpus']).read_bytes()
        checks['corpus_matches'] = hashlib.sha256(corpus_bytes).hexdigest() == metadata.get('corpus_sha256')
        parsed = json.loads(corpus_bytes.decode('utf-8'))
        documents = parsed['documents'] if isinstance(parsed, dict) else parsed
        originals = {(doc['doc_id'], chunk['chunk_id']): dict(doc, text=chunk['text'])
                     for doc in documents for chunk in doc['chunks']}
        valid_reads = True
        for event in events:
            obs = event.get('observation', {})
            if event.get('action') != 'read_doc' or not obs.get('ok'):
                continue
            args = event.get('arguments', {})
            key = (obs.get('doc_id'), obs.get('chunk_id'))
            original = originals.get(key)
            if original is None or key != (args.get('doc_id'), args.get('chunk_id')) or any(
                    obs.get(field) != original.get(field) for field in ('text', 'title', 'version_date', 'scope', 'priority')):
                valid_reads = False
                break
        checks['read_observations_match_corpus'] = valid_reads
    except (OSError, ValueError, TypeError, KeyError):
        checks['corpus_matches'] = checks['read_observations_match_corpus'] = False
    if result.get('reason') == 'model_finished':
        payload_fields = ('answer', 'citations', 'gaps', 'status', 'clarification_question')
        last = events[-1] if events else {}
        checks['finish_matches_output'] = last.get('action') == 'finish' and last.get('observation', {}).get('ok') is True and all(
            last.get('arguments', {}).get(key) == result.get(key) for key in payload_fields)
    if result.get('reason') == 'step_limit':
        checks['limit_state_matches'] = result.get('status') == 'incomplete' and len(events) == case.get('max_steps', 10)
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
        if not isinstance(e, dict) or not {'status', 'answer_contains'} <= set(e) or not ({'citation_ids', 'citation_sets'} & set(e)):
            raise ValueError('用例缺少预期字段')
        allowed_expected = {'status', 'answer_contains', 'citation_ids', 'citation_sets', 'required_read_ids',
                            'search_after_reads', 'failure_then_recovery', 'answer_excludes', 'quote_contains', 'reason'}
        if set(e) - allowed_expected:
            raise ValueError('expected 包含未知检查字段，可能存在拼写错误')
        if not isinstance(e['status'], str) or e['status'] not in STATUSES:
            raise ValueError('预期状态非法')
        for key in ('answer_contains', 'citation_ids', 'required_read_ids', 'answer_excludes', 'quote_contains'):
            if key in e and (not isinstance(e[key], list) or any(not isinstance(v, str) or not v for v in e[key])):
                raise ValueError('预期内容必须是字符串数组')
        if 'citation_sets' in e and (not isinstance(e['citation_sets'], list) or not e['citation_sets'] or any(
                not isinstance(ids, list) or any(not isinstance(v, str) or not v for v in ids) for ids in e['citation_sets'])):
            raise ValueError('citation_sets 必须是非空的字符串数组列表')
        for key in ('search_after_reads', 'failure_then_recovery'):
            if key in e and type(e[key]) is not bool:
                raise ValueError('行为检查开关必须为布尔值')
        if e.get('search_after_reads') and not e.get('required_read_ids'):
            raise ValueError('search_after_reads 需要非空 required_read_ids')
        if 'reason' in e and (not isinstance(e['reason'], str) or not e['reason']):
            raise ValueError('预期reason必须是非空文本')
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
    batch_source_sha256 = _source_sha256()
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
        evidence_checks = check_run_evidence(case, result, events, case_dir, mode, batch_source_sha256)
        outputs[case['id']], traces[case['id']] = result, events
        report = {'id': case['id'], 'title': case['title'], 'checks': checks, 'evidence_checks': evidence_checks, 'passed': all(checks.values()) and all(evidence_checks.values()),
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
    summary = {'mode': mode, 'source_sha256': batch_source_sha256, 'passed': sum(r['passed'] for r in reports), 'total': len(reports),
               'cases': reports, 'paired_checks': pair_checks,
               'scope': '固定合成样本的工程与行为检查；非统计泛化评测，语义引用支持需人工复核',
               'mock_disclaimer': '仅验证流程，不证明真实模型决策效果' if mode == 'mock' else ''}
    write_json(output / 'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'cases'}, ensure_ascii=False, indent=2))
    return 0 if summary['passed'] == summary['total'] and all(pair_checks.values()) else 1
