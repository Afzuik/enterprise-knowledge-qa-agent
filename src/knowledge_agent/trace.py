"""Write inspectable artifacts, never silently overwrite a previous run."""
import json
from pathlib import Path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def save_run(directory, request, result, events):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=False)
    write_json(target / 'input.json', request)
    write_json(target / 'output.json', result)
    (target / 'trace.jsonl').write_text(''.join(json.dumps(dict(e, run_id=result['metadata']['run_id'], mode=result['metadata']['mode']), ensure_ascii=False) + '\n' for e in events), encoding='utf-8')
    write_json(target / 'process.json', {'exit_code': 2 if result['status'] == 'incomplete' else 0})
