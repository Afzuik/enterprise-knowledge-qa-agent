"""Audit fixtures and retrieval properties, not real-model decision evidence."""
import json
from pathlib import Path
import unittest

from knowledge_agent.tools import KnowledgeTools

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


class AuditFixtureTests(unittest.TestCase):
    def test_all_ten_cases_have_resolvable_corpus_and_expected_sources(self):
        cases = json.loads((DATA / 'audit_cases.json').read_text(encoding='utf-8'))
        self.assertEqual({case['id'] for case in cases}, {'A%02d' % i for i in range(1, 11)})
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        for case in cases:
            tools = KnowledgeTools(ROOT / case['corpus'])
            expected = case['expected']
            ids = set(expected['citation_ids']) | set(expected.get('required_read_ids', []))
            for choice in expected.get('citation_sets', []):
                ids.update(choice)
            with self.subTest(case=case['id']):
                self.assertTrue(ids <= set(tools.documents))

    def test_product_question_retrieves_actual_product_source(self):
        tools = KnowledgeTools(DATA / 'corpus_normal.json')
        hits = tools.search_docs('影云标准版 导出 文件格式')['results']
        self.assertIn('D05', {h['doc_id'] for h in hits})
        source = tools.read_doc('D05', 'D05-C01')
        self.assertIn('MP4', source['text'])
        self.assertEqual(source['scope'], '影云标准版')

    def test_outside_fact_has_real_noisy_candidate_but_no_support(self):
        tools = KnowledgeTools(DATA / 'corpus_normal.json')
        hits = tools.search_docs('影云标准版能否导出 8K 分辨率视频')['results']
        self.assertIn('D05', {h['doc_id'] for h in hits})
        self.assertNotIn('8K', tools.read_doc('D05', 'D05-C01')['text'])

    def test_new_paraphrase_retrieves_non_reimbursement_fact(self):
        tools = KnowledgeTools(DATA / 'audit_corpus_product.json')
        hits = tools.search_docs('星舟团队版的一个项目里，最多能拉几位同事作为协作者？')['results']
        self.assertEqual(hits[0]['doc_id'], 'P101')
        self.assertIn('8', tools.read_doc('P101', 'P101-C01')['text'])

    def test_both_non_reimbursement_conflicts_are_retrievable(self):
        tools = KnowledgeTools(DATA / 'audit_corpus_conflict.json')
        hits = tools.search_docs('星舟 协作者 人数')['results']
        self.assertTrue({'P101', 'P102'} <= {h['doc_id'] for h in hits})
        self.assertIsNone(tools.read_doc('P101', 'P101-C01')['priority'])
        self.assertIsNone(tools.read_doc('P102', 'P102-C01')['priority'])

    def test_change_modifies_original_fact_and_source_hash(self):
        original = KnowledgeTools(DATA / 'audit_corpus_product.json')
        changed = KnowledgeTools(DATA / 'audit_corpus_changed.json')
        self.assertNotEqual(original.corpus_hash, changed.corpus_hash)
        self.assertIn('20', changed.read_doc('P101', 'P101-C01')['text'])
        self.assertNotIn('8', changed.read_doc('P101', 'P101-C01')['text'])

    def test_explicit_priority_has_citable_source_not_only_date(self):
        tools = KnowledgeTools(DATA / 'audit_corpus_resolved.json')
        source = tools.read_doc('P103', 'P103-C01')
        self.assertIn('替代 P101 和 P102', source['text'])
        self.assertIn('12', source['text'])
        self.assertTrue(source['priority'])

    def test_read_failure_leaves_snippet_available_but_no_read_evidence(self):
        tools = KnowledgeTools(DATA / 'corpus_normal.json', fault='read_always')
        hits = tools.search_docs('影云 导出 格式')['results']
        product = next(h for h in hits if h['doc_id'] == 'D05')
        self.assertIn('MP4', product['snippet'])
        for _ in range(3):
            self.assertFalse(tools.read_doc('D05', 'D05-C01')['ok'])


if __name__ == '__main__':
    unittest.main()
