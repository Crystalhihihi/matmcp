"""Core DFT workflows: structure fetch, relax, band+DOS. Plain functions (MCP-agnostic).

All heavy output goes to files under runs/<run_id>/; functions return small dicts.
Actual DFT execution is delegated to the engine layer (engines.py): 'gpaw'
(default) or 'qe'; post-processing is shared, so results are comparable.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase.build import mx2
from ase.io import read as ase_read

from .config import new_run, repo_rel, write_json
from .engines import gap_analysis, get_engine, plot_bands, plot_dos

# ---------------------------------------------------------------- structures

BUILTIN_BUILDERS = {"mos2-monolayer", "mos2_monolayer", "mos2"}


def _build_mos2_monolayer():
    """2H-MoS2 monolayer, a=3.18 A (MP mp-1023924 ref gap ~1.66 eV)."""
    return mx2(formula="MoS2", kind="2H", a=3.18, thickness=3.17, vacuum=10.0)


def fetch_structure(query: str, use_builtin: bool = False) -> dict:
    """Fetch structure from Materials Project (or built-in builder), save CIF, open a run dir."""
    from mp_api.client import MPRester  # lazy: not needed for built-ins

    from .config import load_secrets
    load_secrets()  # MP_API_KEY; safe to call repeatedly, never overrides env

    run_id, run_dir = new_run(query)
    info: dict = {"run_id": run_id, "query": query}

    if use_builtin or query.lower() in BUILTIN_BUILDERS:
        atoms = _build_mos2_monolayer()
        atoms.write(run_dir / "structure.cif")
        info.update(source="ase-mx2-builtin", formula="MoS2 (monolayer 2H)",
                    n_atoms=len(atoms), mp_id=None, band_gap_ref=1.66,
                    note="built-in builder; ref gap from MP mp-1023924")
    else:
        with MPRester() as mpr:
            fields = ["material_id", "band_gap", "formula_pretty", "nsites", "is_stable"]
            if query.startswith("mp-"):
                docs = mpr.materials.summary.search(material_ids=[query], fields=fields)
            else:
                docs = mpr.materials.summary.search(formula=query, fields=fields)
            if not docs:
                raise ValueError(f"no MP entry for query={query!r}")
            docs.sort(key=lambda d: (not d.is_stable, d.nsites))
            doc = docs[0]
            struct = mpr.get_structure_by_material_id(doc.material_id)
            struct.to(filename=str(run_dir / "structure.cif"))
            info.update(source="materials-project", formula=doc.formula_pretty,
                        n_atoms=doc.nsites, mp_id=str(doc.material_id),
                        band_gap_ref=doc.band_gap, is_stable=doc.is_stable,
                        candidates=len(docs))

    write_json(run_dir / "fetch.json", info)
    info["cif"] = repo_rel(run_dir / "structure.cif")
    return info


# ------------------------------------------------------------------ helpers

def _vacuum_axes(atoms, min_gap_a: float = 8.0) -> tuple[bool, bool, bool]:
    """Detect slab vacuum per axis from the *atom span*, not the cell length.
    (Cell-length rules misfire on layered bulk like LiCoO2: c=14 A is a real
    periodic direction, not vacuum — found via regression E6.)"""
    frac = atoms.get_scaled_positions() % 1.0
    out = []
    for i in range(3):
        L = atoms.cell.lengths()[i]
        s = np.sort(frac[:, i])
        gap = float(np.diff(np.concatenate([s, [s[0] + 1.0]])).max()) * L
        out.append(bool(gap > min_gap_a))
    return tuple(out)


def auto_kpts(atoms, density: float = 25.0) -> tuple[int, int, int]:
    """k-grid from lattice lengths; vacuum axes (atom-span detected) -> 1.

    Hexagonal 2D cells force n to a multiple of 3 on in-plane axes:
    only then does the Gamma-centered grid contain K=(1/3,1/3,0),
    without which band gap / gap character come out wrong."""
    lengths = atoms.cell.lengths()
    angles = atoms.cell.angles()
    vacuum = _vacuum_axes(atoms)
    hex2d = (vacuum[2] and abs(lengths[0] - lengths[1]) / lengths[0] < 0.05
             and abs(angles[2] - 120.0) < 2.0)
    kpts = []
    for i, length in enumerate(lengths):
        if vacuum[i]:
            kpts.append(1)
            continue
        n = max(1, int(round(density / length)))
        if hex2d and i < 2:
            n = max(3, ((n + 2) // 3) * 3)
        kpts.append(n)
    return tuple(kpts)


def _is_2d(atoms) -> bool:
    return bool(_vacuum_axes(atoms)[2])  # vacuum along c -> slab


def _params_verified(run_dir: Path, ecut: int, kpts_density: float) -> bool:
    """True only if a convergence gate has passed at >= these params for this run.
    Standalone calls bypassing run_verified_workflow get False — loud and honest."""
    import json as _json
    cj_path = run_dir / "convergence.json"
    if not cj_path.exists():
        return False
    try:
        cj = _json.loads(cj_path.read_text())
    except Exception:
        return False
    return bool(cj.get("converged")
                and ecut >= cj.get("recommended_ecut_ev", 10**9)
                and kpts_density >= cj.get("recommended_kpts_density", 10**9))


# --------------------------------------------------------------------- relax

def relax_structure(run_id: str, ecut: int = 400, kpts_density: float = 25.0,
                    fmax: float = 0.05, max_steps: int = 100,
                    engine: str = "gpaw") -> dict:
    from .config import RUNS, verify_run_id
    run_dir = RUNS / verify_run_id(run_id)
    atoms = ase_read(run_dir / "structure.cif")
    eng = get_engine(engine)
    kpts = eng.realize_kpts(auto_kpts(atoms, kpts_density))

    res = eng.relax(atoms, ecut_ev=ecut, kpts=kpts, out_dir=run_dir,
                    tag="relax", fmax=fmax, max_steps=max_steps)

    relaxed = res["atoms"]
    relaxed.write(run_dir / "relaxed.cif")
    result = {
        "run_id": run_id,
        "engine": eng.name,
        "converged": res["converged"],
        "n_steps": res["n_steps"],
        "total_energy_ev": res["energy_ev"],
        "max_force_ev_per_a": res["max_force_ev_per_a"],
        "kpts": kpts, "ecut_ev": ecut,
        "relaxed_cif": repo_rel(run_dir / "relaxed.cif"),
    }
    write_json(run_dir / "relax.json", result)
    return result


# ---------------------------------------------------------------- band + DOS

def calc_band_dos(run_id: str, ecut: int = 400, kpts_density: float = 30.0,
                  npoints: int = 60, window_ev: float = 8.0,
                  engine: str = "gpaw") -> dict:
    from .config import RUNS, verify_run_id
    run_dir = RUNS / verify_run_id(run_id)
    src = run_dir / "relaxed.cif"
    if not src.exists():
        src = run_dir / "structure.cif"
    atoms = ase_read(src)
    eng = get_engine(engine)
    kpts = eng.realize_kpts(auto_kpts(atoms, kpts_density))

    # scf on the uniform grid (engine persists its own restart data)
    scf = eng.scf(atoms, ecut_ev=ecut, kpts=kpts, out_dir=run_dir,
                  tag="bands_scf")

    # band gap + VBM/CBM positions from ibz eigenvalues (machine-derived, no eyeballing)
    g = gap_analysis(scf)
    gap = g["gap"] if g["gap"] is not None else 0.0

    # band structure along a high-symmetry path
    path_str = "GMKG" if _is_2d(atoms) else None
    path = (atoms.cell.bandpath(path_str, npoints=npoints) if path_str
            else atoms.cell.bandpath(npoints=npoints))
    band = eng.band_eigs(atoms, ecut_ev=ecut, kpts_scf=kpts, path=path,
                         out_dir=run_dir, tag="bands")
    plot_bands(band, path, scf.fermi_ev, run_dir / "bands.png", window_ev)

    # DOS from the scf grid
    plot_dos(scf, run_dir / "dos.png", window_ev)

    summary = {
        "run_id": run_id,
        "engine": eng.name,
        "params_verified": _params_verified(run_dir, ecut, kpts_density),
        "total_energy_ev": scf.energy_ev,
        "fermi_ev": scf.fermi_ev,
        "band_gap_ev": gap,
        "gap_type": g["gap_type"],
        "vbm": g["vbm"],
        "cbm": g["cbm"],
        "kpts_scf": kpts,
        "ecut_ev": ecut,
        "band_path": path_str or "auto-3d",
        "bands_png": repo_rel(run_dir / "bands.png"),
        "dos_png": repo_rel(run_dir / "dos.png"),
    }
    write_json(run_dir / "summary.json", summary)
    if not summary["params_verified"]:
        summary["verification_note"] = ("no convergence gate passed at these "
                                        "parameters — treat results as unverified")
    return summary
