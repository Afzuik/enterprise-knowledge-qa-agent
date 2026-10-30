#!/usr/bin/env python3
"""Reproducible offline verification with raw stdout/stderr and actual exit status."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    commands = [
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        [sys.executable, str(ROOT / 'run.py'), 'evaluate', '--mode', 'mock', '--output', str(output / 'mock')],
        [sys.executable, '-m', 'compileall', '-q', 'src', 'run.py'],
    ]
    records = []
    for i, command in enumerate(commands, 1):
        started = datetime.now(timezone.utc).isoformat()
        proc = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True)
        (output / ('%02d-stdout.txt' % i)).write_text(proc.stdout, encoding='utf-8')
        (output / ('%02d-stderr.txt' % i)).write_text(proc.stderr, encoding='utf-8')
        records.append({'command': command, 'cwd': str(ROOT), 'env_overrides': {'PYTHONPATH': str(ROOT/'src')},
                        'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                        'exit_code': proc.returncode, 'stdout': '%02d-stdout.txt' % i, 'stderr': '%02d-stderr.txt' % i})
        print('command', i, 'exit', proc.returncode, flush=True)
    original = json.loads((ROOT/'docs/source-sha256.json').read_text(encoding='utf-8'))
    originals_unchanged = all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name, digest in original.items())
    report = {'commands': records, 'original_requirements_unchanged': originals_unchanged,
              'passed': originals_unchanged and all(r['exit_code'] == 0 for r in records)}
    (output/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
