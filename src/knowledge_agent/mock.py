"""Explicit rule-based OFFLINE fixture, NOT evidence of LLM reasoning.

This deliberately limited simulator consumes tool observations. It is not used
in live mode, and its behavior must never be reported as real model quality.
"""
import json
import re


class MockModel:
    mode = 'mock'
    name = 'offline-rule-mock'

    def decide(self, messages):
        request = json.loads(messages[1]['content'])
        query = request['question']
        if '报销' not in query and '期限' in query:
            for h in reversed(request.get('history', [])):
                if h['role'] == 'user' and '报销' in h['content']:
                    query = '报销期限'
                    break
        observations = []
        for m in messages[2:]:
            if m['role'] == 'user':
                item = json.loads(m['content'])
                if 'observation' in item:
                    observations.append(item)

        def action(name, args, why):
            return {'action': name, 'arguments': args, 'decision_summary': '[离线规则模拟] ' + why}

        def finish(status, answer, citations=None, gaps=None, question=''):
            return action('finish', {'status': status, 'answer': answer, 'citations': citations or [],
                                     'gaps': gaps or [], 'clarification_question': question}, '依据当前模拟规则和工具返回结束。')

        if not observations:
            return action('search_docs', {'query': query, 'top_k': 5}, '先检索与问题相关的资料。')
        last = observations[-1]
        if not last['observation'].get('ok'):
            fails = [o for o in observations if not o['observation'].get('ok')]
            if len(fails) < 2 and last.get('action') in ('search_docs', 'read_doc'):
                return action(last['action'], last['arguments'], '工具报告失败，尝试一次恢复。')
            return finish('incomplete', '工具持续失败，本次无法完成可靠回答。', gaps=['工具未恢复，未能取得可靠资料'])

        searches = [o for o in observations if o.get('action') == 'search_docs' and o['observation'].get('ok')]
        reads = [o['observation'] for o in observations if o.get('action') == 'read_doc' and o['observation'].get('ok')]
        if not searches:
            return action('search_docs', {'query': query, 'top_k': 5}, '取得检索结果。')
        # Use first search to avoid treating scope search hits as new authority.
        candidates = searches[0]['observation'].get('results', [])
        if not candidates:
            if len(searches) < 2:
                return action('search_docs', {'query': query.replace('如何', '').replace('公司', ''), 'top_k': 10}, '初次无结果，调整查询再检索。')
            return finish('insufficient_evidence', '现有资料未提供该问题的依据，无法确认答案。', gaps=['缺少相关制度或产品资料'])
        read_ids = {(r['doc_id'], r['chunk_id']) for r in reads}
        for c in candidates:
            if (c['doc_id'], c['chunk_id']) not in read_ids:
                return action('read_doc', {'doc_id': c['doc_id'], 'chunk_id': c['chunk_id']}, '读取候选原文，不能把摘要当作最终依据。')
        citations = [{'doc_id': r['doc_id'], 'chunk_id': r['chunk_id'], 'version_date': r['version_date'], 'quote': r['text']} for r in reads]
        values = {match for r in reads for match in re.findall(r'报销期限为\s*(\d+)\s*天', r['text'])}
        if len(values) > 1:
            if len(searches) < 2:
                return action('search_docs', {'query': '报销期限 适用范围 优先级 替代关系', 'top_k': 10}, '原文期限不同，补充查证适用依据。')
            return finish('needs_clarification', '资料存在冲突：' + '；'.join(r['doc_id'] + '：' + r['text'] for r in reads) + ' 无法确认适用制度。', citations,
                          ['缺少适用范围与优先级；离线Mock不具备通用冲突消歧能力'], '请确认适用制度或提供制度优先级、适用范围的依据。')
        return finish('answered', '依据本轮读取资料：' + '；'.join(r['doc_id'] + '：' + r['text'] for r in reads), citations)
