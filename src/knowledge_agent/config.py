"""Minimal .env reader. Never executes shell syntax or prints values."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {'LLM_API_KEY', 'LLM_MODEL', 'LLM_BASE_URL', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL'}


def load_env(path=None):
    path = Path(path) if path else ROOT / '.env'
    if not path.exists():
        return
    if path.stat().st_size > 16384:
        raise ValueError('.env 文件过大')
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or key not in ALLOWED:
            raise ValueError('.env 仅允许示例中的模型配置键')
        if value[:1] in ('"', "'"):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError('.env 引号不匹配')
            value = value[1:-1]
        if value and not os.environ.get(key):
            os.environ[key] = value
