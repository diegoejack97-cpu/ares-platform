"""Local artifacts only; no API or automatic prompt/policy/deployment modification."""

import argparse
import json
from pathlib import Path

from ares.agents.quality import release_gate

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", required=True, type=Path)
parser.add_argument("--candidate", required=True, type=Path)
arguments = parser.parse_args()
result = release_gate(
    json.loads(arguments.baseline.read_text(encoding="utf-8")),
    json.loads(arguments.candidate.read_text(encoding="utf-8")),
)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result["allowed"] else 1)
