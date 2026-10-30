import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from knowledge_agent.config import ROOT
from knowledge_agent.evaluate import check_case, evaluate_cases


class EvaluationChecksTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'T01', 'title': '明确答案', 'question': '报销期限？',
                     'corpus': 'data/corpus_normal.json', 'max_steps': 10,
                     'expected': {'status': 'answered', 'answer_contains': ['30'], 'citation_ids': ['D01']}}
        self.result = {'status': 'answered', 'answer': '报销期限为 30 天。', 'gaps': [],
                       'citations': [{'doc_id': 'D01', 'chunk_id': 'D01-C01',
                                      'version_date': '2026-01-01', 'quote': '报销期限为 30 天。'}]}
        self.events = [{'action': 'read_doc', 'observation': {'ok': True, 'doc_id': 'D01',
                         'chunk_id': 'D01-C01', 'version_date': '2026-01-01', 'text': '报销期限为 30 天。'}}]

    def test_valid_known_answer(self):
        self.assertTrue(all(check_case(self.case, self.result, self.events, 0).values()))

    def test_missing_trace_or_wrong_exit_fails(self):
        self.assertFalse(all(check_case(self.case, self.result, [], 0).values()))
        self.assertFalse(all(check_case(self.case, self.result, self.events, 2).values()))

    def test_wrong_numeric_value_does_not_pass_substring_match(self):
        self.result['answer'] = '报销期限为 130 天。'
        self.assertFalse(all(check_case(self.case, self.result, self.events, 0).values()))

    def test_fabricated_quote_does_not_pass_correct_document_id(self):
        self.result['citations'][0]['quote'] = '不存在于读取结果的原文'
        self.assertFalse(all(check_case(self.case, self.result, self.events, 0).values()))

    def test_unread_citation_does_not_pass(self):
        self.events = [{'action': 'search_docs', 'observation': {'ok': True, 'results': []}}]
        self.assertFalse(all(check_case(self.case, self.result, self.events, 0).values()))

    def test_changed_document_rejects_stale_answer(self):
        self.case['id'] = 'T08'
        self.case['expected']['answer_contains'] = ['45']
        self.result['answer'] = '报销期限为 45 天，不是30天。'
        self.result['citations'][0]['quote'] = '报销期限为 45 天。'
        self.events[0]['observation']['text'] = '报销期限为 45 天。'
        checks = check_case(self.case, self.result, self.events, 0)
        self.assertFalse(checks['no_stale_answer'])

    def test_tool_recovery_requires_observed_failure_first(self):
        self.case['id'] = 'T06'
        failed = {'action': 'search_docs', 'observation': {'ok': False}}
        checks = check_case(self.case, self.result, [failed] + self.events, 0)
        self.assertTrue(checks['observed_failure_then_recovery'])
        checks = check_case(self.case, self.result, self.events + [failed], 0)
        self.assertFalse(checks['observed_failure_then_recovery'])

    def test_conflict_requires_both_reads_then_followup(self):
        self.case['id'] = 'T02'
        self.case['expected']['status'] = 'needs_clarification'
        self.case['expected']['answer_contains'] = ['30', '15']
        self.case['expected']['citation_ids'] = ['D01', 'D02']
        self.result.update(status='needs_clarification', answer='D01 为30天，D02 为15天，缺少适用范围。',
                           gaps=['缺少适用范围'], clarification_question='请确认适用制度。')
        second = copy.deepcopy(self.result['citations'][0])
        second.update(doc_id='D02', chunk_id='D02-C01', quote='报销期限为 15 天。')
        self.result['citations'].append(second)
        read = copy.deepcopy(self.events[0])
        read['observation'].update(doc_id='D02', chunk_id='D02-C01', text='报销期限为 15 天。')
        self.events.append(read)
        check = {'action': 'search_docs', 'observation': {'ok': True, 'results': []}}
        self.assertTrue(all(check_case(self.case, self.result, self.events + [check], 0).values()))
        self.assertFalse(check_case(self.case, self.result, [check] + self.events, 0)['conflict_followup_search'])


class EvaluationRunnerTests(unittest.TestCase):
    def test_full_offline_suite_is_reproducible_and_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            output = Path(tmp) / 'evaluation'
            code = evaluate_cases(ROOT / 'data/cases.json', 'mock', output)
            self.assertEqual(code, 0)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['mode'], 'mock')
            self.assertEqual(summary['passed'], summary['total'])
            self.assertEqual(summary['total'], 10)
            self.assertTrue(summary['mock_disclaimer'])
            self.assertTrue(all(summary['paired_checks'].values()))
            for case in summary['cases']:
                directory = output / case['id']
                for filename in ('input.json', 'output.json', 'trace.jsonl', 'stdout.txt', 'stderr.txt', 'process.json', 'checks.json'):
                    self.assertTrue((directory / filename).is_file(), filename)
            with self.assertRaises(FileExistsError):
                evaluate_cases(ROOT / 'data/cases.json', 'mock', output)

    def test_invalid_cases_are_rejected_before_creating_output(self):
        fixtures = [[], {}, [{}], [{'id': 12}], [{'id': 'T01'}],
                    [{'id': '../outside'}], [{'id': 'T01'}, {'id': 'T01'}]]
        with tempfile.TemporaryDirectory() as tmp:
            for index, cases in enumerate(fixtures):
                with self.subTest(cases=cases):
                    path, output = Path(tmp) / 'cases.json', Path(tmp) / str(index)
                    path.write_text(json.dumps(cases), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        evaluate_cases(path, 'mock', output)
                    self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
