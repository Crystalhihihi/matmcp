#!/usr/bin/env bash
# P0 setup: miniforge + GPAW/ASE/pymatgen env, TUNA mirrors with upstream fallback
set -euxo pipefail

# --- miniforge ---
if [ ! -d "$HOME/miniforge3" ]; then
  if ! wget -q --timeout=60 https://mirrors.tuna.tsinghua.edu.cn/github-release/conda-forge/miniforge/LatestRelease/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh; then
    wget -q --timeout=120 https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh
  fi
  bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
fi
source "$HOME/miniforge3/etc/profile.d/conda.sh"

# --- TUNA conda mirror ---
cat > "$HOME/.condarc" <<'EOF'
channels:
  - conda-forge
show_channel_urls: true
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
  defaults: https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
EOF

# --- env ---
conda create -n matmcp -y python=3.11 gpaw ase pymatgen matplotlib
conda activate matmcp
python -c "import gpaw, ase, pymatgen; print('gpaw', gpaw.__version__, '| ase', ase.__version__)"

# --- PAW datasets ---
if [ -z "${GPAW_SETUP_PATH:-}" ] || ! ls "${GPAW_SETUP_PATH:-/nonexistent}" >/dev/null 2>&1; then
  gpaw install-data "$HOME/gpaw-data" || true
fi
SETUPDIR=$(ls -d "$HOME"/gpaw-data/gpaw-setups-* 2>/dev/null | head -1 || true)
if [ -n "$SETUPDIR" ]; then
  grep -q GPAW_SETUP_PATH "$HOME/.bashrc" || echo "export GPAW_SETUP_PATH=$SETUPDIR" >> "$HOME/.bashrc"
  export GPAW_SETUP_PATH=$SETUPDIR
fi
gpaw info
echo "P0_SETUP_DONE"
