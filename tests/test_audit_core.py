"""Independent second-pass regressions; deterministic and never call external models."""
import copy
import unittest

from knowledge_agent.agent import Agent


READ = {'ok': True, 'doc_id': 'D01', 'chunk_id': 'D01-C01',
        'version_date': '2026-01-01', 'title': '费用报销制度',
        'text': '报销期限为 30 天。', 'scope': None, 'priority': None}
CITATION = {'doc_id': 'D01', 'chunk_id': 'D01-C01',
            'version_date': '2026-01-01', 'quote': '报销期限为 30 天。'}


def action(name, **arguments):
    return {'action': name, 'arguments': arguments, 'decision_summary': '确定性审计测试，不代表模型决策能力。'}


def finish(answer='报销期限为 30 天。'):
    return action('finish', answer=answer, citations=[CITATION], gaps=[],
                  status='answered', clarification_question='')


class ScriptModel:
    mode = 'mock'
    name = 'audit-script'

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, messages):
        return copy.deepcopy(next(self.actions))


class CandidateTools:
    corpus_hash = '0' * 64

    def search_docs(self, query, top_k=5):
        return {'ok': True, 'results': [
            {'doc_id': 'D01', 'chunk_id': 'D01-C01', 'title': '报销期限', 'version_date': '2026-01-01', 'snippet': '报销期限为 30 天。', 'score': 1.0},
            {'doc_id': 'D02', 'chunk_id': 'D02-C01', 'title': '报销期限补充', 'version_date': '2026-02-01', 'snippet': '报销期限为 15 天。', 'score': 0.9},
        ], 'truncated': False}

    def read_doc(self, doc_id, chunk_id):
        if doc_id == 'D02':
            return {'ok': False, 'error': {'code': 'TOOL_UNAVAILABLE', 'message': '读取失败', 'retryable': True}}
        return copy.deepcopy(READ)


class SecondPassCoreAuditTests(unittest.TestCase):
    def test_unresolved_candidate_read_cannot_be_reported_answered(self):
        model = ScriptModel([
            action('search_docs', query='报销期限'),
            action('read_doc', doc_id='D02', chunk_id='D02-C01'),
            action('read_doc', doc_id='D01', chunk_id='D01-C01'),
            finish(),
        ])
        agent = Agent(model, CandidateTools(), max_steps=4)
        result = agent.run('报销期限多久？')
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(agent.events[-1]['observation']['ok'])

    def test_whitespace_answer_is_not_completed_answer(self):
        model = ScriptModel([
            action('search_docs', query='报销期限'),
            action('read_doc', doc_id='D01', chunk_id='D01-C01'),
            finish(' \t\n'),
        ])
        agent = Agent(model, CandidateTools(), max_steps=3)
        self.assertEqual(agent.run('报销期限多久？')['status'], 'incomplete')

    def test_read_response_identity_must_match_requested_fragment(self):
        class WrongIdentityTools(CandidateTools):
            def read_doc(self, doc_id, chunk_id):
                # A misrouted tool response must not become trusted evidence.
                return copy.deepcopy(READ)
        model = ScriptModel([
            action('search_docs', query='报销期限'),
            action('read_doc', doc_id='D02', chunk_id='D02-C01'),
            finish(),
        ])
        agent = Agent(model, WrongIdentityTools(), max_steps=3)
        self.assertEqual(agent.run('报销期限多久？')['status'], 'incomplete')

    def test_malformed_successful_search_is_not_evidence_of_absence(self):
        for malformed in (
            {'ok': True},
            {'ok': True, 'results': None, 'truncated': False},
            {'ok': True, 'results': 'not-an-array', 'truncated': False},
            {'ok': True, 'results': [None], 'truncated': False},
            {'ok': True, 'results': [{'doc_id': []}], 'truncated': False},
        ):
            with self.subTest(response=malformed):
                class MalformedTools(CandidateTools):
                    def search_docs(self, query, top_k=5):
                        return copy.deepcopy(malformed)
                model = ScriptModel([
                    action('search_docs', query='停车位申请'),
                    action('finish', answer='资料不足。', citations=[], gaps=['缺少资料'],
                           status='insufficient_evidence', clarification_question=''),
                ])
                agent = Agent(model, MalformedTools(), max_steps=2)
                self.assertEqual(agent.run('停车位申请？')['status'], 'incomplete')
                self.assertFalse(agent.events[0]['observation']['ok'])

    def test_whitespace_decision_summary_rejected_before_tool(self):
        class CountingTools(CandidateTools):
            calls = 0
            def search_docs(self, query, top_k=5):
                self.calls += 1
                return super().search_docs(query, top_k)
        invalid = action('search_docs', query='报销期限')
        invalid['decision_summary'] = ' \t\n'
        tools = CountingTools()
        agent = Agent(ScriptModel([invalid]), tools, max_steps=1)
        self.assertEqual(agent.run('报销期限多久？')['status'], 'incomplete')
        self.assertEqual(tools.calls, 0)
        self.assertFalse(agent.events[0]['observation']['ok'])

    def test_unhashable_model_error_attributes_are_sanitized(self):
        for code, hint in (([], None), ('invalid_model_output', {})):
            with self.subTest(code=code, hint=hint):
                class BrokenModel:
                    mode = 'mock'
                    name = 'audit-broken-error'
                    def decide(self, messages):
                        exc = RuntimeError('sensitive-provider-details')
                        exc.code, exc.hint = code, hint
                        raise exc
                agent = Agent(BrokenModel(), CandidateTools(), max_steps=1)
                result = agent.run('报销期限多久？')
                self.assertEqual(result['status'], 'incomplete')
                self.assertNotIn('sensitive-provider-details', str(result) + str(agent.events))

    def test_malformed_finish_fields_fail_closed_without_crash(self):
        variants = [
            {'answer': []}, {'citations': [None]}, {'gaps': [{}]},
            {'status': []}, {'clarification_question': {}},
        ]
        for change in variants:
            with self.subTest(change=change):
                invalid = finish()
                invalid['arguments'].update(change)
                agent = Agent(ScriptModel([
                    action('search_docs', query='报销期限'),
                    action('read_doc', doc_id='D01', chunk_id='D01-C01'), invalid,
                ]), CandidateTools(), max_steps=3)
                self.assertEqual(agent.run('报销期限多久？')['status'], 'incomplete')

    def test_same_fragment_recovery_allows_answer_and_keeps_trace(self):
        class RecoveringTools(CandidateTools):
            reads = 0
            def read_doc(self, doc_id, chunk_id):
                self.reads += 1
                if self.reads == 1:
                    return {'ok': False, 'error': {'code': 'TOOL_UNAVAILABLE', 'message': '读取失败', 'retryable': True}}
                return copy.deepcopy(READ)
        actions = [
            action('search_docs', query='报销期限'),
            action('read_doc', doc_id='D01', chunk_id='D01-C01'),
            action('read_doc', doc_id='D01', chunk_id='D01-C01'),
            finish(),
        ]
        agent = Agent(ScriptModel(actions), RecoveringTools(), max_steps=4)
        result = agent.run('报销期限多久？')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['citations'], [CITATION])
        self.assertEqual(result['metadata']['steps'], 4)
        self.assertEqual([e['next_action'] for e in agent.events],
                         ['read_doc', 'read_doc', 'finish', 'stop:model_finished'])
        self.assertFalse(agent.events[1]['observation']['ok'])
        self.assertTrue(agent.events[2]['observation']['ok'])
        self.assertTrue(agent.events[3]['observation']['validated'])

    def test_unknown_id_failure_is_conservatively_retained(self):
        class UnknownIdTools(CandidateTools):
            def read_doc(self, doc_id, chunk_id):
                if doc_id == 'D404':
                    return {'ok': False, 'error': {'code': 'DOCUMENT_NOT_FOUND', 'message': 'ID不存在', 'retryable': False}}
                return copy.deepcopy(READ)
        agent = Agent(ScriptModel([
            action('search_docs', query='报销期限'),
            action('read_doc', doc_id='D404', chunk_id='D404-C01'),
            action('read_doc', doc_id='D01', chunk_id='D01-C01'),
            finish(),
        ]), UnknownIdTools(), max_steps=4)
        result = agent.run('报销期限多久？')
        # Deliberately conservative: an unrelated success must not silently
        # erase failure. A future recovery policy needs its own evidence.
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(agent.events[-1]['observation']['ok'])


if __name__ == '__main__':
    unittest.main()
