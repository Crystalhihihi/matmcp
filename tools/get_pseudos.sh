#!/usr/bin/env bash
# Plan B: per-element pslibrary 1.0.0 PBE (kjpaw) UPFs, resume-capable.
set -u
DIR="$HOME/qe-pseudo/pslibrary"
mkdir -p "$DIR"
BASE="https://pseudopotentials.quantum-espresso.org/upf_files"
FILES="Mo.pbe-spn-kjpaw_psl.1.0.0.UPF S.pbe-n-kjpaw_psl.1.0.0.UPF Si.pbe-n-kjpaw_psl.1.0.0.UPF Ga.pbe-dn-kjpaw_psl.1.0.0.UPF As.pbe-n-kjpaw_psl.1.0.0.UPF Ti.pbe-spn-kjpaw_psl.1.0.0.UPF O.pbe-n-kjpaw_psl.1.0.0.UPF Li.pbe-s-kjpaw_psl.1.0.0.UPF Co.pbe-spn-kjpaw_psl.1.0.0.UPF H.pbe-kjpaw_psl.1.0.0.UPF"
for f in $FILES; do
  if [ -s "$DIR/$f" ]; then echo "have $f"; continue; fi
  if wget -q -c --tries=5 --timeout=60 "$BASE/$f" -O "$DIR/$f"; then
    echo "OK $f"
  else
    echo "FAIL $f"
    rm -f "$DIR/$f"
  fi
done
echo "----"
ls -la "$DIR"
