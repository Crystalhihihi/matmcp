#!/usr/bin/env bash
# Canonical wrapper: run a command inside the WSL matmcp env from Git Bash.
# Usage (Git Bash):  MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/d/材料mcp大串烧/tools/wsl_run.sh <cmd...>
# Every command gets: conda env activation + MP_API_KEY injection + repo cwd.
set -e
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate matmcp
set -a
[ -f "$HOME/.config/matmcp/env" ] && source "$HOME/.config/matmcp/env"
set +a
cd /mnt/d/材料mcp大串烧
exec "$@"
