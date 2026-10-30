"""Independent audit regressions for declarative and evidence-aware evaluation."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from knowledge_agent.config import ROOT
from knowledge_agent.evaluate import check_case, check_run_evidence, evaluate_cases


def read(doc_id, value):
    return {'action': 'read_doc', 'arguments': {'doc_id': doc_id, 'chunk_id': doc_id+'-C01'},
            'observation': {'ok': True, 'doc_id': doc_id, 'chunk_id': doc_id+'-C01',
                            'version_date': '2026-01-01', 'text': '报销期限为 '+value+' 天。'}}


def citation(doc_id, value):
    return {'doc_id': doc_id, 'chunk_id': doc_id+'-C01', 'version_date': '2026-01-01',
            'quote': '报销期限为 '+value+' 天。'}


class AuditEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'A01', 'max_steps': 10, 'expected': {'status': 'needs_clarification',
                     'answer_contains': ['30', '15'], 'citation_ids': ['D01', 'D02'],
                     'required_read_ids': ['D01', 'D02'], 'search_after_reads': True}}
        self.result = {'status': 'needs_clarification', 'answer': 'D01为30天，D02为15天，无法确认适用规则。',
                       'citations': [citation('D01', '30'), citation('D02', '15')],
                       'gaps': ['缺少优先级'], 'clarification_question': '请确认适用规则。'}
        self.search = {'action': 'search_docs', 'arguments': {'query': '优先级'},
                       'observation': {'ok': True, 'results': []}}
        self.reads = [read('D01', '30'), read('D02', '15')]

    def test_conflict_reread_after_followup_search_is_valid(self):
        self.case['id'] = 'T02'
        events = self.reads + [self.search, copy.deepcopy(self.reads[0])]
        self.assertTrue(all(check_case(self.case, self.result, events, 0).values()))

    def test_declared_conflict_checks_do_not_depend_on_case_id(self):
        self.assertFalse(all(check_case(self.case, self.result, self.reads, 0).values()))
        self.assertTrue(all(check_case(self.case, self.result, self.reads+[self.search], 0).values()))

    def test_declared_required_reads_are_enforced(self):
        self.case['expected']['required_read_ids'].append('D03')
        self.assertFalse(all(check_case(self.case, self.result, self.reads+[self.search], 0).values()))

    def test_declared_alternative_citation_sets(self):
        self.case['expected'].update(citation_sets=[['D01', 'D02'], ['D01', 'D02', 'D03']])
        self.result['citations'].append(citation('D03', '20'))
        events = self.reads+[read('D03', '20'), self.search]
        self.assertTrue(all(check_case(self.case, self.result, events, 0).values()))

    def test_declared_answer_excludes_and_quote_contains(self):
        self.case['expected'].update(answer_excludes=['确定采用15天'], quote_contains=['30', '15'])
        events = self.reads+[self.search]
        self.assertTrue(all(check_case(self.case, self.result, events, 0).values()))
        self.result['answer'] += '确定采用15天。'
        self.assertFalse(all(check_case(self.case, self.result, events, 0).values()))
        self.result['answer'] = 'D01为30天，D02为15天。'
        self.case['expected']['quote_contains'] = ['45']
        self.assertFalse(all(check_case(self.case, self.result, events, 0).values()))

    def test_declared_reason_is_enforced(self):
        self.case['expected']['reason'] = 'model_finished'
        events = self.reads+[self.search]
        self.result['reason'] = 'step_limit'
        self.assertFalse(all(check_case(self.case, self.result, events, 0).values()))

    def test_declared_tool_recovery_is_enforced(self):
        self.case['expected']['failure_then_recovery'] = True
        events = self.reads+[self.search]
        self.assertFalse(all(check_case(self.case, self.result, events, 0).values()))
        failed = {'action': 'search_docs', 'arguments': {'query': '报销'}, 'observation': {'ok': False}}
        self.assertTrue(all(check_case(self.case, self.result, [failed]+events, 0).values()))


    def test_unrelated_success_does_not_prove_failed_read_recovered(self):
        self.case['expected']['failure_then_recovery'] = True
        failed = {'action': 'read_doc', 'arguments': {'doc_id': 'D03', 'chunk_id': 'D03-C01'},
                  'observation': {'ok': False}}
        events = [failed] + self.reads + [self.search]
        self.assertFalse(check_case(self.case, self.result, events, 0)['observed_failure_then_recovery'])
        events.append(read('D03', '20'))
        self.assertTrue(check_case(self.case, self.result, events, 0)['observed_failure_then_recovery'])


class PersistedEvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'run'
        self.case = json.loads((ROOT / 'data/cases.json').read_text(encoding='utf-8'))[0]
        proc = subprocess.run([sys.executable, str(ROOT/'run.py'), 'ask', '--mode', 'mock',
                               '--question', self.case['question'], '--output', str(self.directory)],
                              cwd=str(ROOT), text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0)
        (self.directory/'stdout.txt').write_text(proc.stdout, encoding='utf-8')
        self.result = json.loads((self.directory/'output.json').read_text(encoding='utf-8'))
        self.events = [json.loads(line) for line in (self.directory/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        self.source = self.result['metadata']['source_sha256']

    def checks(self, mode='mock', source=None):
        return check_run_evidence(self.case, self.result, self.events, self.directory, mode, source or self.source)

    def test_complete_run_matches_all_local_evidence(self):
        self.assertTrue(all(self.checks().values()))

    def test_wrong_mode_source_and_run_identity_are_rejected(self):
        self.assertFalse(self.checks(mode='live')['mode_matches'])
        self.assertFalse(self.checks(source='0'*64)['source_matches'])
        self.events[0]['run_id'] = 'different-run'
        self.assertFalse(self.checks()['trace_identity_matches'])

    def test_modified_stdout_or_case_input_is_rejected(self):
        (self.directory/'stdout.txt').write_text('{}', encoding='utf-8')
        self.assertFalse(self.checks()['stdout_matches_output'])
        request = json.loads((self.directory/'input.json').read_text(encoding='utf-8'))
        request['question'] = '另一问题'
        (self.directory/'input.json').write_text(json.dumps(request), encoding='utf-8')
        self.assertFalse(self.checks()['input_matches_case'])

    def test_trace_read_must_match_disk_not_only_citation(self):
        read_event = next(e for e in self.events if e['action'] == 'read_doc')
        read_event['observation']['text'] = '伪造的原文'
        self.assertFalse(self.checks()['read_observations_match_corpus'])

    def test_final_output_matches_validated_finish(self):
        self.result['answer'] = '与模型最后动作不同的答案'
        self.assertFalse(self.checks()['finish_matches_output'])

    def test_budget_and_step_sequence_are_checked(self):
        self.events[0]['step'] = 7
        self.assertFalse(self.checks()['step_sequence_valid'])
        self.result['metadata']['steps'] = 999
        self.assertFalse(self.checks()['step_count_matches'])


    def test_next_action_chain_must_match_actual_next_event(self):
        self.events[0]['next_action'] = 'finish'
        self.assertFalse(self.checks()['next_action_chain_valid'])

    def test_process_exit_code_must_match_final_state(self):
        (self.directory/'process.json').write_text('{"exit_code": 2}', encoding='utf-8')
        self.assertFalse(self.checks()['process_exit_matches_state'])

    def test_unknown_expected_key_is_rejected_before_execution(self):
        case = copy.deepcopy(self.case)
        case['expected']['answer_contians'] = ['wrong-spelling']
        path = Path(self.temp.name)/'bad-cases.json'
        path.write_text(json.dumps([case]), encoding='utf-8')
        output = Path(self.temp.name)/'must-not-exist'
        with self.assertRaises(ValueError):
            evaluate_cases(path, 'mock', output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

class BudgetStopContractTests(unittest.TestCase):
    def test_last_decision_voluntary_incomplete_is_valid_budget_stop(self):
        case = {'id': 'T10', 'max_steps': 1, 'expected': {
            'status': 'incomplete', 'answer_contains': [], 'citation_ids': []}}
        result = {'status': 'incomplete', 'answer': 'Insufficient decision budget.',
                  'gaps': ['budget'], 'citations': [], 'reason': 'model_finished'}
        events = [{'action': 'finish', 'arguments': {'status': 'incomplete'},
                   'observation': {'ok': True}}]
        self.assertTrue(check_case(case, result, events, 2)['bounded'])
        events[0]['observation']['ok'] = False
        self.assertFalse(check_case(case, result, events, 2)['bounded'])

    def test_budget_check_rejects_completed_answer_or_overrun(self):
        case = {'id': 'T10', 'max_steps': 1, 'expected': {
            'status': 'incomplete', 'answer_contains': [], 'citation_ids': []}}
        result = {'status': 'answered', 'answer': 'Unsupported', 'citations': [], 'reason': 'model_finished'}
        event = {'action': 'finish', 'arguments': {'status': 'answered'}, 'observation': {'ok': True}}
        self.assertFalse(check_case(case, result, [event], 0)['bounded'])
        result.update(status='incomplete', reason='step_limit')
        self.assertFalse(check_case(case, result, [event, event], 2)['bounded'])

if __name__ == "__main__":
    unittest.main()
