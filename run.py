#!/usr/bin/env python3
"""Run without package installation, on Python 3.9+."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from knowledge_agent.cli import main
if __name__ == '__main__':
    sys.exit(main())
