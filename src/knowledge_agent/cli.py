import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agent import Agent
from .config import ROOT, load_env
from .mock import MockModel
from .model import LiveModel, ModelError
from .tools import KnowledgeTools, FAULTS
from .trace import save_run


def make_model(mode, timeout=30):
    if mode == 'mock':
        return MockModel()
    load_env()
    return LiveModel.from_env(timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description='企业知识问答 Agent；Mock仅验证流程，真实模式需配置.env。')
    sub = parser.add_subparsers(dest='command', required=True)
    ask = sub.add_parser('ask', help='运行单个问题并保存输入、输出与Trace')
    ask.add_argument('--question', required=True)
    ask.add_argument('--corpus', type=Path, default=ROOT / 'data/corpus_normal.json')
    ask.add_argument('--history', type=Path)
    ask.add_argument('--fault', choices=sorted(FAULTS), default='none')
    ask.add_argument('--max-steps', type=int, default=10)
    evaluate = sub.add_parser('evaluate', help='运行十项验收用例，保留失败结果')
    evaluate.add_argument('--cases', type=Path, default=ROOT / 'data/cases.json')
    for p in (ask, evaluate):
        p.add_argument('--mode', choices=['mock', 'live'], default='mock')
        p.add_argument('--timeout', type=float, default=30)
        p.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    output = args.output or ROOT / 'examples/local' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + args.mode)
    try:
        if output.exists():
            raise ValueError('输出目录已存在，请指定新目录，避免覆盖既有证据')
        if args.command == 'evaluate':
            from .evaluate import evaluate_cases
            return evaluate_cases(args.cases, args.mode, output, args.timeout)
        model = make_model(args.mode, args.timeout)
        history = json.loads(args.history.read_text(encoding='utf-8')) if args.history else []
        tools = KnowledgeTools(args.corpus, args.fault)
        agent = Agent(model, tools, args.max_steps)
        result = agent.run(args.question, history)
        request = {'question': args.question, 'history': history, 'corpus': str(args.corpus), 'fault': args.fault, 'mode': args.mode, 'max_steps': args.max_steps}
        save_run(output, request, result, agent.events)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print('Artifacts: ' + str(output.resolve()), file=sys.stderr)
        return 2 if result['status'] == 'incomplete' else 0
    except ModelError as exc:
        print(json.dumps({'status': 'incomplete', 'reason': exc.code, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError) as exc:
        # No raw input or environment values in operational diagnostics.
        print(json.dumps({'status': 'incomplete', 'reason': 'input_or_filesystem_error', 'error_type': type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
