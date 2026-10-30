import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from knowledge_agent import cli, config
from knowledge_agent.model import ModelError
from knowledge_agent.trace import save_run


class ConfigTests(unittest.TestCase):
    def test_empty_config_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / '.env'
            config.load_env(path)
            path.write_text('LLM_API_KEY=\nLLM_MODEL=\n# no credentials\n', encoding='utf-8')
            config.load_env(path)
            self.assertNotIn('LLM_API_KEY', os.environ)
            with patch.object(cli, 'load_env'):
                with self.assertRaises(ModelError) as raised:
                    cli.make_model('live')
            self.assertEqual(raised.exception.code, 'config_missing')

    def test_environment_precedence_quotes_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LLM_MODEL': 'shell-model'}, clear=True):
            path = Path(tmp) / '.env'
            path.write_text('\ufeff# config\nexport LLM_MODEL="file-model"\nLLM_API_KEY=\'fake-key\'\nLLM_BASE_URL=https://example.invalid/v1\n', encoding='utf-8')
            config.load_env(path)
            self.assertEqual(os.environ['LLM_MODEL'], 'shell-model')
            self.assertEqual(os.environ['LLM_API_KEY'], 'fake-key')

    def test_never_executes_shell_syntax(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / '.env'
            marker = Path(tmp) / 'must-not-exist'
            value = '$(touch {})'.format(marker)
            path.write_text('LLM_API_KEY=' + value, encoding='utf-8')
            config.load_env(path)
            self.assertFalse(marker.exists())
            self.assertEqual(os.environ['LLM_API_KEY'], value)

    def test_bad_config_errors_do_not_contain_values(self):
        fixtures = ['UNEXPECTED=private-marker', 'LLM_API_KEY="private-marker',
                    'private-marker', 'LLM_API_KEY=' + 'private-marker' * 2000]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / '.env'
            for content in fixtures:
                path.write_text(content, encoding='utf-8')
                with self.subTest(content_length=len(content)), self.assertRaises(ValueError) as raised:
                    config.load_env(path)
                self.assertNotIn('private-marker', str(raised.exception))


class CLITests(unittest.TestCase):
    def run_mock_cli(self, tmp, *args):
        # Mock mode must not inspect any .env file or make any external request.
        environment = {key: value for key, value in os.environ.items() if key not in config.ALLOWED}
        return subprocess.run([sys.executable, str(config.ROOT / 'run.py'), *args],
                              cwd=tmp, env=environment, text=True, capture_output=True, timeout=15)

    def test_mock_does_not_load_environment_or_construct_live_model(self):
        with patch.object(cli, 'load_env', side_effect=AssertionError('must not load .env')), \
                patch.object(cli.LiveModel, 'from_env', side_effect=AssertionError('must not call live')):
            self.assertEqual(cli.make_model('mock').mode, 'mock')

    def test_live_configuration_failure_has_no_mock_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch.object(cli, 'load_env'), patch.object(cli, 'MockModel') as mock_model, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            output = Path(tmp) / 'run'
            code = cli.main(['ask', '--mode', 'live', '--question', '报销期限？', '--output', str(output)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(err.getvalue())['reason'], 'config_missing')
            self.assertFalse(output.exists())
            mock_model.assert_not_called()

    def test_cli_reproducible_from_other_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'run'
            proc = self.run_mock_cli(tmp, 'ask', '--mode', 'mock', '--question', '报销期限多久？', '--output', str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result['status'], 'answered')
            self.assertEqual(result['metadata']['mode'], 'mock')
            self.assertIn('Mock', result['metadata']['mock_disclaimer'])
            self.assertEqual(json.loads((target / 'output.json').read_text()), result)
            events = [json.loads(line) for line in (target / 'trace.jsonl').read_text().splitlines()]
            self.assertTrue(events)
            self.assertTrue(all(e['run_id'] == result['metadata']['run_id'] for e in events))
            self.assertTrue(all(e['mode'] == 'mock' for e in events))
            self.assertEqual(json.loads((target / 'process.json').read_text())['exit_code'], 0)

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'existing'
            target.mkdir()
            marker = target / 'output.json'
            marker.write_text('preserve existing evidence', encoding='utf-8')
            proc = self.run_mock_cli(tmp, 'ask', '--mode', 'mock', '--question', '报销期限多久？', '--output', str(target))
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(marker.read_text(), 'preserve existing evidence')
            self.assertEqual(sorted(p.name for p in target.iterdir()), ['output.json'])
            self.assertNotIn('Traceback', proc.stderr)

    def test_limit_returns_two_and_saved_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'limited'
            proc = self.run_mock_cli(tmp, 'ask', '--mode', 'mock', '--question', '报销期限多久？',
                                     '--max-steps', '1', '--output', str(target))
            self.assertEqual(proc.returncode, 2)
            result = json.loads(proc.stdout)
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(result['reason'], 'step_limit')
            self.assertEqual(json.loads((target / 'process.json').read_text())['exit_code'], 2)

    def test_invalid_history_logs_no_raw_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / 'history.json'
            history.write_text('private-marker not-json', encoding='utf-8')
            proc = self.run_mock_cli(tmp, 'ask', '--question', '报销期限？', '--history', str(history),
                                     '--output', str(Path(tmp) / 'run'))
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn('private-marker', proc.stderr + proc.stdout)
            self.assertNotIn('Traceback', proc.stderr)

    def test_unknown_mode_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_mock_cli(tmp, 'ask', '--mode', 'typo', '--question', '报销期限？')
            self.assertEqual(proc.returncode, 2)

    def test_trace_writer_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                save_run(tmp, {}, {}, [])


if __name__ == '__main__':
    unittest.main()
