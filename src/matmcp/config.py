"""Shared config: paths, secrets, run-directory management."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Repo root as seen from inside WSL. Override with MATMCP_REPO if moved.
REPO = Path(os.environ.get("MATMCP_REPO", "/mnt/d/材料mcp大串烧"))
RUNS = Path(os.environ.get("MATMCP_RUNS", str(REPO / "runs")))
ENV_FILE = Path.home() / ".config" / "matmcp" / "env"


def load_secrets() -> None:
    """Load KEY=VALUE lines from ~/.config/matmcp/env into os.environ (no override)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def new_run(label: str) -> tuple[str, Path]:
    """Create runs/<ts>_<label>_<uuid4hex>/ and return (run_id, path).
    The uuid suffix prevents silent directory sharing on same-second calls."""
    import uuid
    run_id = (time.strftime("%Y%m%d-%H%M%S") + "_"
              + "".join(c if c.isalnum() else "-" for c in label.lower())[:36]
              + "_" + uuid.uuid4().hex[:4])
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=False)
    return run_id, d


def verify_run_id(run_id: str) -> str:
    """Reject path traversal: run_id must be a plain directory name."""
    import re
    if not re.fullmatch(r"[0-9A-Za-z_-]+", run_id or ""):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return run_id


def repo_rel(p: Path) -> str:
    """Path relative to repo root for display in chat."""
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
