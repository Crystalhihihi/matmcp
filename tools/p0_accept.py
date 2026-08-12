#!/usr/bin/env python
"""P0 acceptance gate: H2 relax + Si scf + Si band structure (GPAW, PW mode).

Usage: python p0_accept.py [outdir]
Gate passes only if: H2 bond within [0.70, 0.80] A, Si scf converges,
band plot png written.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

from ase import Atoms
from ase.build import bulk
from ase.optimize import BFGS
from gpaw import GPAW, PW

out = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/p0")
out.mkdir(parents=True, exist_ok=True)

# --- 1. H2 relaxation ---
h2 = Atoms("H2", positions=[[0, 0, 0], [0, 0, 0.9]])
h2.center(vacuum=6.0)
h2.calc = GPAW(mode=PW(300), xc="PBE", txt=str(out / "h2.txt"))
BFGS(h2, trajectory=str(out / "h2.traj")).run(fmax=0.05)
d = h2.get_distance(0, 1)
print(f"[P0] H2 bond length: {d:.3f} A (exp 0.74)")
assert 0.70 < d < 0.80, f"H2 bond off: {d}"

# --- 2. Si scf at experimental lattice constant ---
si = bulk("Si", "diamond", a=5.43)
si.calc = GPAW(mode=PW(300), xc="PBE", kpts=(4, 4, 4), nbands=8,
               txt=str(out / "si_scf.txt"))
e = si.get_potential_energy()
print(f"[P0] Si total energy: {e:.3f} eV")

# --- 3. Si band structure along standard path (tutorial-robust route) ---
gpw = out / "si_gs.gpw"
si.calc.write(str(gpw))
path = si.cell.bandpath("GXWKL", npoints=80)
calc2 = GPAW(str(gpw)).fixed_density(kpts=path, symmetry="off")
bs = calc2.band_structure()
bs.plot(emax=10.0, filename=str(out / "si_bands.png"))
print(f"[P0] artifacts in {out.resolve()}")
print("P0_ACCEPT_DONE")
