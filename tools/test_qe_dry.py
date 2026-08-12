"""QE engine dry-run tests — NO DFT execution.

Verifies, without running pw.x:
- get_engine() constructs both engines; unknown names are rejected
- GpawEngine / QeEngine expose identical Engine signatures
- QE input rendering (ASE write_espresso_in via calculator.write_inputfiles):
  ecutwfc/ecutrho conversion, fd smearing + degauss in Ry, Gamma-centered
  K_POINTS automatic shifts, pseudopotential mapping, crystal_b band path
- shared post-processing: gap_analysis / dos_arrays / klabel on synthetic data

Run inside WSL matmcp env:  python tools/test_qe_dry.py
"""
import inspect
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.build import mx2

from matmcp.engines import (QE_PSEUDO_DIR, QE_PSEUDOS, RY_PER_EV, ScfResult,
                            dos_arrays, gap_analysis, get_engine, klabel)

FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def render_pwi(eng, atoms, ecut_ev, calculation, kpts, tmp, tag):
    calc = eng._espresso(atoms, ecut_ev, calculation, tmp, tag, kpts)
    calc.write_inputfiles(atoms, ["energy"])  # renders espresso.pwi, no exec
    return (Path(tmp) / f"qe_{tag}" / "espresso.pwi").read_text()


def main():
    # ------------------------------------------------ engine registry + API
    g, q = get_engine("gpaw"), get_engine("qe")
    check("registry: gpaw name", g.name == "gpaw-pw", g.name)
    check("registry: qe name", q.name == "qe-pw", q.name)
    try:
        get_engine("vasp")
        check("registry: unknown rejected", False)
    except ValueError:
        check("registry: unknown rejected", True)

    for meth in ("relax", "scf", "band_eigs"):
        sg = list(inspect.signature(getattr(g, meth)).parameters)
        sq = list(inspect.signature(getattr(q, meth)).parameters)
        check(f"signature parity: {meth}", sg == sq, f"{sg}")

    # ------------------------------------------------ pseudo map completeness
    missing = [s for s, fn in QE_PSEUDOS.items()
               if not (QE_PSEUDO_DIR / fn).exists()]
    check("pseudo files all present", not missing,
          f"missing={missing} dir={QE_PSEUDO_DIR}")

    # ------------------------------------------------ QE input: H2, Gamma only
    h2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)],
               cell=[10, 10, 10], pbc=True)
    ecut_ev = 20.0 / RY_PER_EV  # exactly 20 Ry
    with tempfile.TemporaryDirectory() as tmp:
        pwi = render_pwi(q, h2, ecut_ev, "scf", (1, 1, 1), tmp, "h2")

        m = re.search(r"ecutwfc\s*=\s*([\d.]+)", pwi)
        check("pwi: ecutwfc = 20 Ry", m and abs(float(m.group(1)) - 20.0) < 1e-6,
              m.group(1) if m else "not found")
        m = re.search(r"ecutrho\s*=\s*([\d.]+)", pwi)
        check("pwi: ecutrho = 80 Ry (4x PAW)", m and abs(float(m.group(1)) - 80.0) < 1e-6,
              m.group(1) if m else "not found")
        m = re.search(r"degauss\s*=\s*([\d.eEdD+-]+)", pwi)
        ok = m and abs(float(m.group(1).replace("D", "E").replace("d", "e"))
                       - 0.05 * RY_PER_EV) < 1e-6
        check("pwi: degauss = 0.05 eV in Ry", ok,
              f"{m.group(1)} vs {0.05 * RY_PER_EV:.6f}" if m else "not found")
        check("pwi: occupations=smearing", "occupations" in pwi
              and "'smearing'" in pwi)
        check("pwi: smearing='fd'", re.search(r"smearing\s*=\s*'fd'", pwi) is not None)
        check("pwi: H pseudo mapped",
              "H.pbe-kjpaw_psl.1.0.0.UPF" in pwi)
        check("pwi: verbosity high", "'high'" in pwi)
        check("pwi: outdir into run dir", "qe_wf" in pwi)
        m = re.search(r"K_POINTS automatic\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", pwi)
        check("pwi: K_POINTS 1 1 1 0 0 0",
              m and tuple(map(int, m.groups())) == (1, 1, 1, 0, 0, 0),
              m.groups() if m else "not found")

        # -------------------------------------- QE input: MoS2, even/odd grids
        # (dict form is exactly what QeEngine.scf/relax build internally)
        mos2 = mx2(formula="MoS2", kind="2H", a=3.18, thickness=3.17, vacuum=10.0)
        pwi_even = render_pwi(q, mos2, 400, "scf",
                              {"size": (6, 6, 1), "gamma": True}, tmp, "mos2even")
        m = re.search(r"K_POINTS automatic\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
                      pwi_even)
        # even n -> sk=1 on that axis keeps Gamma in the grid (QE MP convention),
        # matching GPAW {'size':..., 'gamma': True}; n3=1 odd -> sk=0
        check("pwi: even grid sk=1 (Gamma kept)",
              m and tuple(map(int, m.groups())) == (6, 6, 1, 1, 1, 0),
              m.groups() if m else "not found")
        check("pwi: Mo/S pseudos mapped",
              "Mo.pbe-spn-kjpaw_psl.1.0.0.UPF" in pwi_even
              and "S.pbe-n-kjpaw_psl.1.0.0.UPF" in pwi_even)

        pwi_odd = render_pwi(q, mos2, 400, "scf",
                             {"size": (9, 9, 1), "gamma": True}, tmp, "mos2odd")
        m = re.search(r"K_POINTS automatic\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
                      pwi_odd)
        check("pwi: odd grid sk=0",
              m and tuple(map(int, m.groups())) == (9, 9, 1, 0, 0, 0),
              m.groups() if m else "not found")

        # -------------------------------------- QE input: bands along a path
        path = mos2.cell.bandpath("GMKG", npoints=40)
        pwi_bands = render_pwi(q, mos2, 400, "bands", path, tmp, "mos2bands")
        check("pwi: calculation='bands'",
              re.search(r"calculation\s*=\s*'bands'", pwi_bands) is not None)
        m = re.search(r"K_POINTS crystal_b\n\s*(\d+)\n", pwi_bands)
        check("pwi: crystal_b path, 40 kpts",
              m and int(m.group(1)) == 40, m.group(1) if m else "not found")

        # missing element -> loud error, not a QE crash
        o2 = Atoms("Xe", positions=[(0, 0, 0)], cell=[10, 10, 10], pbc=True)
        try:
            render_pwi(q, o2, 400, "scf", (1, 1, 1), tmp, "xe")
            check("missing pseudo raises", False)
        except ValueError as e:
            check("missing pseudo raises", "Xe" in str(e), str(e)[:60])

    # ------------------------------------------------ shared post-processing
    ef = 0.0
    eigs = np.array([[-1.0, 1.0], [-0.5, 2.0]])  # k=Gamma, k=X(0.5,0,0)
    kf = np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])
    scf = ScfResult(-10.0, ef, eigs, kf, np.array([0.5, 0.5]))
    g = gap_analysis(scf)
    check("gap_analysis: value", abs(g["gap"] - 1.5) < 1e-12, g["gap"])
    check("gap_analysis: indirect", g["gap_type"] == "indirect")
    check("gap_analysis: VBM@M band0", g["vbm"]["band"] == 0
          and abs(g["vbm"]["energy_ev"] + 0.5) < 1e-12
          and g["vbm"]["label"] == "M", g["vbm"])
    check("gap_analysis: CBM@Gamma", g["cbm"]["label"] == "Γ"
          and g["cbm"]["band"] == 1, g["cbm"])

    met = gap_analysis(ScfResult(None, ef, np.array([[-2.0, -1.0]]),
                                 kf[:1], np.array([1.0])))
    check("gap_analysis: metallic -> gap None", met["gap"] is None
          and met["gap_type"] == "metallic")

    e, d = dos_arrays(ScfResult(None, 0.0, np.array([[0.0]]),
                                kf[:1], np.array([1.0])))
    integral = float(np.sum(d) * (e[1] - e[0]))  # uniform grid
    check("dos: peak at Ef", abs(e[np.argmax(d)]) < 0.02, e[np.argmax(d)])
    check("dos: integrates to 2 (spin)", abs(integral - 2.0) < 0.01,
          f"{integral:.4f}")

    check("klabel: named points", klabel([0, 0, 0]) == "Γ"
          and klabel([1/3, 1/3, 0]) == "K" and klabel([0.5, 0, 0]) == "M")

    print()
    if FAILS:
        print("QE_DRY_FAILED:", FAILS)
        sys.exit(1)
    print("QE_DRY_OK")


if __name__ == "__main__":
    main()
