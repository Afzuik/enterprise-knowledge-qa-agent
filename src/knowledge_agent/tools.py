"""Deterministic local retrieval tools. Corpus text is data, never instructions."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path


FAULTS = {'none', 'search_once', 'search_always', 'read_once', 'read_always'}
_SYNONYMS = (
    ('报账', '报销'), ('报帐', '报销'), ('能报销', '报销'), ('能报', '报销'),
    ('最迟', '期限'), ('最晚', '期限'), ('多少天', '期限'),
    ('多长时间', '期限'), ('多久', '期限'),
    ('忘记密码', '重置密码'), ('找回密码', '重置密码'),
)
_STOPWORDS = ('请问', '请告诉我', '企业', '公司', '制度', '政策', '规则', '什么', '怎么', '如何', '是否', '可以', '需要', '申请')


def _normalize(text):
    text = text.lower()
    for old, new in _SYNONYMS:
        text = text.replace(old, new)
    for word in _STOPWORDS:
        text = text.replace(word, ' ')
    return text


def _tokens(text):
    """Chinese bigrams plus complete Latin words/numbers, no third-party tokenizer."""
    parts = re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+', _normalize(text))
    result = set()
    for part in parts:
        if re.fullmatch(r'[\u4e00-\u9fff]+', part):
            result.update(part[i:i + 2] for i in range(len(part) - 1))
        else:
            result.add(part)
    return result


def _error(code, message, retryable=False):
    return {'ok': False, 'error': {'code': code, 'message': message, 'retryable': retryable}}


class KnowledgeTools:
    """Read-only tools backed by a validated synthetic corpus.

    Fault injection is explicit, local and run-scoped. A failed call never
    mutates the corpus; a ``*_once`` fault affects the first valid call only.
    """

    def __init__(self, corpus_path, fault='none'):
        if fault not in FAULTS:
            raise ValueError('Unsupported fault mode: %s' % fault)
        self.corpus_path = str(corpus_path)
        raw = Path(corpus_path).read_bytes()
        self.corpus_hash = hashlib.sha256(raw).hexdigest()
        parsed = json.loads(raw.decode('utf-8'))
        documents = parsed.get('documents') if isinstance(parsed, dict) else parsed
        if not isinstance(documents, list) or not documents:
            raise ValueError('Corpus must contain a nonempty documents list')
        self.documents = {}
        self._chunks = {}
        self._fault = fault
        self._calls = {'search': 0, 'read': 0}
        for doc in documents:
            if not isinstance(doc, dict):
                raise ValueError('Every document must be an object')
            for key in ('doc_id', 'title', 'version_date'):
                if not isinstance(doc.get(key), str) or not doc[key].strip():
                    raise ValueError('Missing or invalid document field: %s' % key)
            date.fromisoformat(doc['version_date'])
            if doc['doc_id'] in self.documents:
                raise ValueError('Duplicate doc_id: %s' % doc['doc_id'])
            if not isinstance(doc.get('keywords'), list) or not all(isinstance(x, str) for x in doc['keywords']):
                raise ValueError('keywords must be a list of strings')
            if not isinstance(doc.get('chunks'), list) or not doc['chunks']:
                raise ValueError('Every document needs at least one chunk')
            for key in ('scope', 'priority'):
                if key not in doc or doc[key] is not None and not isinstance(doc[key], str):
                    raise ValueError('%s must be a string or null' % key)
            for chunk in doc['chunks']:
                if not isinstance(chunk, dict) or not all(isinstance(chunk.get(k), str) and chunk[k].strip() for k in ('chunk_id', 'text')):
                    raise ValueError('Invalid chunk')
                if chunk['chunk_id'] in self._chunks:
                    raise ValueError('Duplicate chunk_id: %s' % chunk['chunk_id'])
                self._chunks[chunk['chunk_id']] = (doc, chunk)
            self.documents[doc['doc_id']] = doc

    def _injected_error(self, name):
        self._calls[name] += 1
        if self._fault == name + '_always' or self._fault == name + '_once' and self._calls[name] == 1:
            return _error('TOOL_UNAVAILABLE', 'Injected %s tool failure for verification.' % name, True)
        return None

    def search_docs(self, query, top_k=5):
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            return _error('INVALID_ARGUMENT', 'query must be 1–500 non-blank characters.')
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
            return _error('INVALID_ARGUMENT', 'top_k must be an integer between 1 and 10.')
        failure = self._injected_error('search')
        if failure:
            return failure
        query_tokens = _tokens(query)
        if not query_tokens:
            return {'ok': True, 'results': [], 'truncated': False}
        ranked = []
        for doc, chunk in self._chunks.values():
            title_hits = query_tokens & _tokens(doc['title'])
            keyword_hits = query_tokens & _tokens(' '.join(doc['keywords']))
            body_hits = query_tokens & _tokens(chunk['text'])
            matched = title_hits | keyword_hits | body_hits
            if not matched:
                continue
            # Require meaningful coverage; a lone common match in a long query
            # is not sufficient evidence. Ranking scores are not authority.
            coverage = len(matched) / len(query_tokens)
            if coverage < 0.12:
                continue
            score = (4 * len(title_hits) + 3 * len(keyword_hits) + len(body_hits)) / len(query_tokens)
            ranked.append({
                'doc_id': doc['doc_id'], 'title': doc['title'],
                'version_date': doc['version_date'], 'chunk_id': chunk['chunk_id'],
                'snippet': chunk['text'][:120], 'score': round(score, 4),
            })
        ranked.sort(key=lambda x: (-x['score'], x['doc_id'], x['chunk_id']))
        return {'ok': True, 'results': ranked[:top_k], 'truncated': len(ranked) > top_k}

    def read_doc(self, doc_id, chunk_id):
        if not isinstance(doc_id, str) or not isinstance(chunk_id, str):
            return _error('INVALID_ARGUMENT', 'doc_id and chunk_id must be strings.')
        if doc_id not in self.documents:
            return _error('DOCUMENT_NOT_FOUND', 'Document does not exist.')
        found = self._chunks.get(chunk_id)
        if not found or found[0]['doc_id'] != doc_id:
            return _error('CHUNK_NOT_FOUND', 'Chunk does not belong to the requested document.')
        failure = self._injected_error('read')
        if failure:
            return failure
        doc, chunk = found
        return {
            'ok': True, 'doc_id': doc_id, 'chunk_id': chunk_id,
            'version_date': doc['version_date'], 'title': doc['title'],
            'text': chunk['text'], 'scope': doc['scope'], 'priority': doc['priority'],
        }
