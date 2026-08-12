"""Regression runner: one material through the full verified workflow.

Usage (WSL matmcp env):  python tools/regression_one.py mp-149
Prints the final JSON verdict block; all artifacts land in runs/<run_id>/.
"""
import json
import sys

from matmcp import verify

query = sys.argv[1] if len(sys.argv) > 1 else "mp-149"
out = verify.run_verified_workflow(query)
print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
print("REGRESSION_DONE", query, out["verdict"])
