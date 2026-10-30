"""Provider-independent, bounded decision -> tool -> observation loop."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone

from .prompts import SYSTEM_PROMPT

STATUSES = {'answered', 'needs_clarification', 'insufficient_evidence', 'incomplete'}


def validate_action(action):
    if not isinstance(action, dict):
        raise ValueError('动作必须为 JSON 对象')
    if set(action) != {'action', 'arguments', 'decision_summary'}:
        raise ValueError('动作字段必须为 action/arguments/decision_summary')
    name, args = action['action'], action['arguments']
    if not isinstance(name, str) or name not in ('search_docs', 'read_doc', 'finish'):
        raise ValueError('未知动作')
    if not isinstance(args, dict):
        raise ValueError('arguments 必须为对象')
    if not isinstance(action['decision_summary'], str) or not 1 <= len(action['decision_summary'].strip()) <= 500:
        raise ValueError('decision_summary 必须为 1～500 字的简短依据')
    if name == 'search_docs':
        if not {'query'} <= set(args) or set(args) - {'query', 'top_k'}:
            raise ValueError('search_docs 参数错误')
        if not isinstance(args['query'], str) or not 1 <= len(args['query'].strip()) <= 500:
            raise ValueError('query 必须为 1～500 字')
        k = args.get('top_k', 5)
        if type(k) is not int or not 1 <= k <= 10:
            raise ValueError('top_k 必须为 1～10 整数')
    elif name == 'read_doc':
        if set(args) != {'doc_id', 'chunk_id'} or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in args.values()):
            raise ValueError('read_doc 需要文档 ID 和片段 ID')
    return name, args


def validate_finish(args, evidence, successful_searches, unresolved_error):
    fields = {'answer', 'citations', 'gaps', 'status', 'clarification_question'}
    if set(args) != fields:
        raise ValueError('finish 字段必须为 answer/citations/gaps/status/clarification_question')
    if not isinstance(args['status'], str) or args['status'] not in STATUSES:
        raise ValueError('非法任务状态')
    if not isinstance(args['answer'], str) or not args['answer'].strip() or len(args['answer']) > 8000:
        raise ValueError('answer 必须是非空文本，最多8000字')
    if not isinstance(args['clarification_question'], str):
        raise ValueError('clarification_question 必须为文本，无需追问时为空串')
    if not isinstance(args['gaps'], list) or any(not isinstance(x, str) or not x.strip() for x in args['gaps']):
        raise ValueError('gaps 必须是非空字符串列表，可为空列表')
    if not isinstance(args['citations'], list):
        raise ValueError('citations 必须是列表')
    seen = set()
    for c in args['citations']:
        if not isinstance(c, dict) or set(c) != {'doc_id', 'chunk_id', 'version_date', 'quote'}:
            raise ValueError('引用字段错误')
        if any(not isinstance(v, str) or not v.strip() for v in c.values()):
            raise ValueError('引用字段必须为非空文本')
        key = (c['doc_id'], c['chunk_id'])
        source = evidence.get(key)
        if source is None:
            raise ValueError('引用必须来自本轮成功读取的原文')
        if c['version_date'] != source['version_date'] or c['quote'] not in source['text']:
            raise ValueError('引用版本或原文片段不匹配')
        if key in seen:
            raise ValueError('同一片段请合并引用')
        seen.add(key)
    status = args['status']
    if status in ('answered', 'insufficient_evidence') and not successful_searches:
        raise ValueError('尚无成功检索，不能报告已回答或资料不足')
    if status == 'answered' and not args['citations']:
        raise ValueError('事实回答必须提供本轮原文引用')
    if status in ('answered', 'insufficient_evidence') and unresolved_error:
        raise ValueError('存在未恢复工具故障，可能缺失关键或冲突证据；请恢复对应工具，或返回 incomplete，不能报告已回答/资料不足')
    if status != 'answered' and not args['gaps']:
        raise ValueError('非 answered 状态必须说明资料缺口或未完成原因')
    if status == 'needs_clarification' and not args['clarification_question'].strip():
        raise ValueError('需澄清时必须提供问题')


def validate_observation(name, args, value):
    """Fail closed on malformed or misrouted tool responses; never trust ok alone."""
    invalid = {'ok': False, 'error': {'code': 'invalid_tool_response',
               'message': '工具响应结构或请求身份不匹配；未获得可靠资料', 'retryable': True}}
    if not isinstance(value, dict) or type(value.get('ok')) is not bool:
        return invalid
    if not value['ok']:
        error = value.get('error')
        if not isinstance(error, dict) or not isinstance(error.get('code'), str) or not isinstance(error.get('message'), str):
            return invalid
        return value
    if name == 'search_docs':
        if not isinstance(value.get('results'), list) or type(value.get('truncated')) is not bool:
            return invalid
        for candidate in value['results']:
            if not isinstance(candidate, dict) or any(not isinstance(candidate.get(k), str) or not candidate[k].strip() for k in ('doc_id', 'chunk_id', 'snippet')):
                return invalid
    elif name == 'read_doc':
        if any(not isinstance(value.get(k), str) or not value[k].strip() for k in ('doc_id', 'chunk_id', 'version_date', 'text')):
            return invalid
        if value['doc_id'] != args['doc_id'] or value['chunk_id'] != args['chunk_id']:
            return invalid
    return value


class Agent:
    def __init__(self, model, tools, max_steps=10):
        if type(max_steps) is not int or not 1 <= max_steps <= 30:
            raise ValueError('max_steps 必须为 1～30 整数')
        self.model, self.tools, self.max_steps = model, tools, max_steps
        self.events = []

    def run(self, question, history=None):
        if not isinstance(question, str) or not question.strip() or len(question) > 8000:
            raise ValueError('question 必须是 1～8000 字的非空文本')
        history = [] if history is None else history
        if not isinstance(history, list) or len(history) > 20:
            raise ValueError('history 必须为最多20条消息的数组')
        for item in history:
            if not isinstance(item, dict) or set(item) != {'role', 'content'} or item['role'] not in ('user', 'assistant') or not isinstance(item['content'], str) or len(item['content']) > 8000:
                raise ValueError('历史仅允许 user/assistant role 和文本 content，每条最多8000字')
        self.events = []
        start = time.monotonic()
        source_hash = hashlib.sha256()
        for source in sorted(Path(__file__).resolve().parent.glob('*.py')):
            source_hash.update(source.name.encode())
            source_hash.update(source.read_bytes())
        metadata = {'source_sha256': source_hash.hexdigest(), 'run_id': str(uuid.uuid4()), 'started_at': datetime.now(timezone.utc).isoformat(),
                    'mode': self.model.mode, 'model': self.model.name, 'corpus_sha256': self.tools.corpus_hash,
                    'max_steps': self.max_steps, 'evidence_scope': '本轮已读取的资料，不保证知识库完整召回',
                    'mock_disclaimer': 'Mock仅验证流程，不证明真实模型决策效果' if self.model.mode != 'live' else ''}
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': json.dumps(
            {'question': question, 'history': history, 'max_steps': self.max_steps}, ensure_ascii=False)}]
        evidence, searches, unresolved = {}, 0, set()

        def complete(payload, reason):
            metadata['steps'] = len(self.events)
            metadata['duration_ms'] = round((time.monotonic() - start) * 1000, 2)
            for i, event in enumerate(self.events):
                event['next_action'] = self.events[i+1]['action'] if i+1 < len(self.events) else 'stop:' + reason
            return dict(payload, reason=reason, metadata=metadata)

        def incomplete(reason):
            return complete({'status': 'incomplete', 'answer': '本次任务未完成，不能据此给出可靠答案。',
                             'citations': [], 'gaps': [reason], 'clarification_question': ''}, reason)

        for step in range(1, self.max_steps + 1):
            step_start = time.monotonic()
            event = {'step': step, 'action': 'model_error', 'arguments': {}, 'decision_summary': '', 'observation': None}
            self.events.append(event)
            try:
                messages.append({'role': 'user', 'content': json.dumps({'budget': {'step': step, 'remaining_decisions_including_this': self.max_steps-step+1}, 'instruction': '仍须返回 action/arguments/decision_summary 完整JSON对象；如结束使用finish动作。'}, ensure_ascii=False)})
                action = self.model.decide(messages)
            except Exception as exc:
                code = getattr(exc, 'code', 'model_error')
                # Exception details can contain HTTP headers or secrets: never persist them.
                code = code if isinstance(code, str) and code in {'config_missing', 'invalid_model_output', 'invalid_request', 'network_error', 'http_error', 'response_too_large', 'config_invalid', 'model_timeout'} else 'model_error'
                hint = getattr(exc, 'hint', None)
                hint = hint if isinstance(hint, str) and hint in {'invalid_json', 'missing_action_fields', 'invalid_envelope', 'non_text_content', 'response_too_large'} else None
                event['observation'] = {'ok': False, 'error': {'code': code, 'hint': hint, 'message': '模型调用失败（敏感响应已省略）'}}
                event['elapsed_ms'] = round((time.monotonic()-step_start)*1000, 2)
                if code != 'invalid_model_output':
                    return incomplete(code)
                messages.append({'role': 'user', 'content': json.dumps({'observation': event['observation'], 'instruction': '请修复格式。必须包含action、arguments、decision_summary，不要直接输出答案对象。结束示例：', 'format_example': {'action': 'finish', 'arguments': {'status': 'insufficient_evidence', 'answer': '现有资料不足以回答。', 'citations': [], 'gaps': ['缺少相关资料'], 'clarification_question': ''}, 'decision_summary': '工具成功返回但未找到相关依据。'}}, ensure_ascii=False)})
                continue
            try:
                name, args = validate_action(action)
                event.update(action=name, arguments=args, decision_summary=action['decision_summary'])
                messages.append({'role': 'assistant', 'content': json.dumps(action, ensure_ascii=False)})
                if name == 'finish':
                    validate_finish(args, evidence, searches, unresolved)
                    event['observation'] = {'ok': True, 'validated': True}
                    event['elapsed_ms'] = round((time.monotonic()-step_start)*1000, 2)
                    return complete(args, 'model_finished')
                try:
                    observation = getattr(self.tools, name)(**args)
                    observation = validate_observation(name, args, observation)
                except Exception:
                    observation = {'ok': False, 'error': {'code': 'tool_exception', 'message': '工具异常，未返回可靠资料', 'retryable': True}}
                error_key = ('search_docs',) if name == 'search_docs' else ('read_doc', args['doc_id'], args['chunk_id'])
                if observation['ok']:
                    unresolved.discard(error_key)
                    if name == 'search_docs':
                        searches += 1
                    else:
                        if all(isinstance(observation.get(k), str) for k in ('doc_id', 'chunk_id', 'version_date', 'text')):
                            evidence[(observation['doc_id'], observation['chunk_id'])] = dict(observation)
                        else:
                            observation = {'ok': False, 'error': {'code': 'invalid_tool_response', 'message': '读取结果缺字段', 'retryable': False}}
                            unresolved.add(error_key)
                else:
                    unresolved.add(error_key)
            except (ValueError, TypeError) as exc:
                if event['action'] == 'model_error':
                    event['action'] = 'invalid_action'
                observation = {'ok': False, 'error': {'code': 'validation_error', 'message': str(exc), 'retryable': True}}
            event['observation'] = observation
            event['elapsed_ms'] = round((time.monotonic()-step_start)*1000, 2)
            messages.append({'role': 'user', 'content': json.dumps({'action': event['action'], 'arguments': event['arguments'], 'observation': observation}, ensure_ascii=False)})
        return incomplete('step_limit')
