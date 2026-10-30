import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from knowledge_agent.tools import KnowledgeTools

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


class KnowledgeToolsTests(unittest.TestCase):
    def setUp(self):
        self.tools = KnowledgeTools(DATA / 'corpus_normal.json')

    def test_hash_matches_file(self):
        self.assertEqual(self.tools.corpus_hash, hashlib.sha256((DATA / 'corpus_normal.json').read_bytes()).hexdigest())

    def test_search_and_read_normal(self):
        result = self.tools.search_docs('报销期限多久')
        self.assertTrue(result['ok'])
        first = result['results'][0]
        self.assertEqual(first['doc_id'], 'D01')
        read = self.tools.read_doc(first['doc_id'], first['chunk_id'])
        self.assertTrue(read['ok'])
        self.assertEqual(read['text'], '报销期限为 30 天。')
        self.assertIsNone(read['priority'])

    def test_similar_question(self):
        for question in ('费用最迟什么时候能报？', '报账最晚多少天？', '报销期限多久？'):
            with self.subTest(question=question):
                self.assertEqual(self.tools.search_docs(question)['results'][0]['doc_id'], 'D01')

    def test_additional_paraphrases_without_sentence_mapping(self):
        # New phrasings exercise general words, not a full-question synonym.
        for question in ('这笔费用最晚哪一天能报账？', '报帐的期限是多久呀？', '能报销的费用最迟何时提交？'):
            with self.subTest(question=question):
                self.assertEqual(self.tools.search_docs(question)['results'][0]['doc_id'], 'D01')

    def test_conflicting_documents_both_returned(self):
        tools = KnowledgeTools(DATA / 'corpus_conflict.json')
        docs = {x['doc_id'] for x in tools.search_docs('报销期限')['results']}
        self.assertTrue({'D01', 'D02'} <= docs)
        self.assertEqual(tools.read_doc('D02', 'D02-C01')['text'], '报销期限为 15 天。')

    def test_truncated_result_is_explicit(self):
        tools = KnowledgeTools(DATA / 'corpus_conflict.json')
        result = tools.search_docs('报销', top_k=1)
        self.assertEqual(len(result['results']), 1)
        self.assertTrue(result['truncated'])

    def test_outside_corpus_and_empty_token_query(self):
        self.assertEqual(self.tools.search_docs('公司停车政策是什么？')['results'], [])
        self.assertEqual(self.tools.search_docs('停车位如何申请？')['results'], [])
        self.assertEqual(self.tools.search_docs('游泳卡如何申请？')['results'], [])
        self.assertEqual(self.tools.search_docs('？')['results'], [])

    def test_generic_action_word_does_not_remove_subject(self):
        self.assertEqual(self.tools.search_docs('请假如何申请？')['results'][0]['doc_id'], 'D07')

    def test_input_validation(self):
        for query in ('', ' ', None, 3, 'a' * 501):
            self.assertEqual(self.tools.search_docs(query)['error']['code'], 'INVALID_ARGUMENT')
        for top_k in (0, 11, True, '5', 1.5):
            self.assertEqual(self.tools.search_docs('报销', top_k)['error']['code'], 'INVALID_ARGUMENT')

    def test_nonexistent_and_mismatched_ids(self):
        self.assertEqual(self.tools.read_doc('missing', 'D01-C01')['error']['code'], 'DOCUMENT_NOT_FOUND')
        self.assertEqual(self.tools.read_doc('D03', 'D01-C01')['error']['code'], 'CHUNK_NOT_FOUND')
        self.assertEqual(self.tools.read_doc([], 2)['error']['code'], 'INVALID_ARGUMENT')

    def test_search_once_failure_is_recoverable(self):
        tools = KnowledgeTools(DATA / 'corpus_normal.json', fault='search_once')
        first = tools.search_docs('报销')
        self.assertFalse(first['ok'])
        self.assertTrue(first['error']['retryable'])
        self.assertTrue(tools.search_docs('报销')['ok'])

    def test_persistent_search_failure(self):
        tools = KnowledgeTools(DATA / 'corpus_normal.json', fault='search_always')
        for _ in range(3):
            self.assertFalse(tools.search_docs('报销')['ok'])

    def test_read_faults(self):
        once = KnowledgeTools(DATA / 'corpus_normal.json', fault='read_once')
        self.assertFalse(once.read_doc('D01', 'D01-C01')['ok'])
        self.assertTrue(once.read_doc('D01', 'D01-C01')['ok'])
        always = KnowledgeTools(DATA / 'corpus_normal.json', fault='read_always')
        for _ in range(3):
            self.assertFalse(always.read_doc('D01', 'D01-C01')['ok'])

    def test_document_change(self):
        changed = KnowledgeTools(DATA / 'corpus_changed.json')
        self.assertIn('45', changed.read_doc('D01', 'D01-C01')['text'])
        self.assertNotEqual(changed.corpus_hash, self.tools.corpus_hash)

    def test_duplicate_ids_rejected(self):
        corpus = json.loads((DATA / 'corpus_normal.json').read_text())
        corpus['documents'].append(corpus['documents'][0])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'bad.json'
            path.write_text(json.dumps(corpus))
            with self.assertRaises(ValueError):
                KnowledgeTools(path)

    def test_invalid_fault_rejected(self):
        with self.assertRaises(ValueError):
            KnowledgeTools(DATA / 'corpus_normal.json', fault='bad')


if __name__ == '__main__':
    unittest.main()
