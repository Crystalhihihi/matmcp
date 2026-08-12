"""FastMCP server exposing the matmcp workflows. Thin wrappers over workflows.py.

Run (stdio):  python -m matmcp.server
All file outputs stay on disk; tools return paths + short summaries only.
"""
from __future__ import annotations

import traceback

from fastmcp import FastMCP

from . import workflows
from .config import RUNS, load_secrets

mcp = FastMCP("matmcp")


def _wrap(fn, **kwargs) -> dict:
    try:
        return {"ok": True, **fn(**kwargs)}
    except Exception as e:  # surface root cause to the agent, keep stdout clean
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "traceback_tail": traceback.format_exc().splitlines()[-5:]}


@mcp.tool
def fetch_structure(query: str, use_builtin: bool = False) -> dict:
    """Fetch a crystal structure by formula (e.g. 'MoS2') or Materials Project id
    ('mp-1434'), or use the built-in MoS2 monolayer builder. Saves structure.cif
    into a new run dir and returns run_id + reference data (incl. MP band gap)."""
    load_secrets()
    return _wrap(workflows.fetch_structure, query=query, use_builtin=use_builtin)


@mcp.tool
def relax_structure(run_id: str, ecut: int = 400, kpts_density: float = 25.0,
                    fmax: float = 0.05, max_steps: int = 100,
                    engine: str = "gpaw") -> dict:
    """Relax the structure of an existing run (plane-wave, PBE; engine='gpaw'
    or 'qe'). Returns total energy, final max force, step count and relaxed.cif path."""
    return _wrap(workflows.relax_structure, run_id=run_id, ecut=ecut,
                 kpts_density=kpts_density, fmax=fmax, max_steps=max_steps,
                 engine=engine)


@mcp.tool
def calc_band_dos(run_id: str, ecut: int = 400, kpts_density: float = 30.0,
                  npoints: int = 60, window_ev: float = 8.0,
                  engine: str = "gpaw") -> dict:
    """SCF + band structure + DOS for a run (uses relaxed.cif if present;
    engine='gpaw' or 'qe'). Writes bands.png / dos.png / summary.json;
    returns band gap and paths."""
    return _wrap(workflows.calc_band_dos, run_id=run_id, ecut=ecut,
                 kpts_density=kpts_density, npoints=npoints, window_ev=window_ev,
                 engine=engine)


@mcp.tool
def check_convergence(run_id: str, tol_mev_per_atom: float = 5.0,
                      engine: str = "gpaw") -> dict:
    """Automated convergence test: sweeps plane-wave cutoff and k-point grid,
    reports per-step energy change and recommended converged parameters
    (engine='gpaw' or 'qe').
    A run's final results are only trustworthy at or above these parameters."""
    from . import verify
    return _wrap(verify.check_convergence, run_id=run_id,
                 tol_mev_per_atom=tol_mev_per_atom, engine=engine)


@mcp.tool
def verify_run(run_id: str, gap_tol_ev: float = 0.3) -> dict:
    """Physics sanity verification of a finished run: relax convergence,
    structure drift, band gap vs Materials Project reference, gap character
    (direct/indirect, machine-derived). Returns pass/warn/fail per check."""
    from . import verify
    return _wrap(verify.verify_run, run_id=run_id, gap_tol_ev=gap_tol_ev)


@mcp.tool
def run_verified_workflow(query: str, use_builtin: bool = False, ecut: int = 400,
                          kpts_density: float = 25.0, max_retries: int = 2,
                          engine: str = "gpaw") -> dict:
    """Full verified pipeline in one call: fetch -> relax -> convergence gate
    -> automatic reparametrize & retry (<=max_retries, param failures only)
    -> band structure + DOS -> physics verification. Final results are only
    produced from converged parameters. engine='gpaw' (default) or 'qe'.
    Use this as the default entry point."""
    from . import verify
    return _wrap(verify.run_verified_workflow, query=query,
                 use_builtin=use_builtin, ecut=ecut, kpts_density=kpts_density,
                 max_retries=max_retries, engine=engine)


@mcp.tool
def get_run_artifacts(run_id: str) -> dict:
    """List all artifact files of a run with sizes (paths are repo-relative)."""
    def _list(run_id: str) -> dict:
        from .config import verify_run_id
        d = RUNS / verify_run_id(run_id)
        if not d.is_dir():
            raise ValueError(f"no such run: {run_id}")
        files = sorted(p for p in d.iterdir() if p.is_file())
        return {"run_id": run_id,
                "artifacts": [{"path": str(p.relative_to(RUNS.parent)),
                               "bytes": p.stat().st_size} for p in files]}
    return _wrap(_list, run_id=run_id)


if __name__ == "__main__":
    mcp.run()  # stdio
