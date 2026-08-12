"""Verification layer: convergence gates + physics sanity checks + verified orchestration.

Design rule: every claim a report makes must come from machine-derived numbers,
never from an agent eyeballing a plot.
"""
from __future__ import annotations

import numpy as np
from ase.io import read as ase_read

from .config import RUNS, write_json
from .engines import gap_analysis, get_engine
from .workflows import auto_kpts, calc_band_dos, fetch_structure, relax_structure

# ------------------------------------------------------------- convergence

def _scf_eval(atoms, ecut: int, kpts, txt, eng) -> tuple[float, float | None]:
    """One scf; returns (total_energy_eV, band_gap_eV or None if metallic)."""
    from pathlib import Path
    txt = Path(txt)
    scf = eng.scf(atoms, ecut_ev=ecut, kpts=kpts, out_dir=txt.parent,
                  tag=txt.stem)
    return scf.energy_ev, gap_analysis(scf)["gap"]


def check_convergence(run_id: str, ecuts=(300, 400, 500, 600, 800),
                      kdensities=(10, 15, 20, 25, 35, 45),
                      tol_mev_per_atom: float = 5.0,
                      tol_gap_ev: float = 0.02,
                      ecut_energy_tol_mev_per_atom: float = 100.0,
                      engine: str = "gpaw") -> dict:
    """Sweep ecut (fixed moderate k-grid) and k-grid (fixed ecut=400).
    Convergence policy (per axis, first point satisfying the rule wins):
    - ecut: band gap stable (successive |Δgap| < tol_gap_ev) is the primary
      criterion — absolute PW total energies converge asymptotically (Ti PAW:
      67 meV/atom even at 600->800 eV) and absolute energies across different
      ecut are physically meaningless anyway; energy delta kept only as a
      loose pathology backstop (< ecut_energy_tol_mev_per_atom).
    - k-grid: BOTH |ΔE| < tol_mev_per_atom AND |Δgap| < tol_gap_ev — k-point
      sampling error is a real physical error in both channels.
    Metallic systems (no gap) fall back to the energy criterion alone.
    Duplicate k-grids (after symmetry-aware rounding) are evaluated once."""
    from .config import verify_run_id
    run_dir = RUNS / verify_run_id(run_id)
    src = run_dir / "relaxed.cif"
    if not src.exists():
        src = run_dir / "structure.cif"
    atoms = ase_read(src)
    nat = len(atoms)
    eng = get_engine(engine)

    def sweep(values, kind):
        rows = []
        seen = set()
        for v in values:
            if kind == "ecut":
                kpts = eng.realize_kpts(auto_kpts(atoms, 15))
                key = ("e", int(v), kpts)
                label = {"ecut_ev": int(v)}
            else:
                # realize before dedupe: QE rounds grids up (odd/Gamma-centering),
                # so distinct densities can collapse to one executed grid
                kpts = eng.realize_kpts(auto_kpts(atoms, float(v)))
                key = ("k", kpts)
                label = {"kpts_density": float(v), "kpts": kpts}
            if key in seen:
                continue
            seen.add(key)
            e, gap = _scf_eval(atoms,
                               int(v) if kind == "ecut" else 400,
                               kpts,
                               run_dir / f"conv_{kind}{v}.txt",
                               eng)
            rows.append({**label, "energy_ev": e, "gap_ev": gap})
        for i in range(len(rows) - 1):
            rows[i]["delta_mev_per_atom"] = abs(
                rows[i + 1]["energy_ev"] - rows[i]["energy_ev"]) / nat * 1000
            g0, g1 = rows[i]["gap_ev"], rows[i + 1]["gap_ev"]
            rows[i]["delta_gap_ev"] = (abs(g1 - g0)
                                       if g0 is not None and g1 is not None else None)
        rows[-1]["delta_mev_per_atom"] = None
        rows[-1]["delta_gap_ev"] = None
        return rows

    ek = sweep(ecuts, "ecut")
    kk = sweep(kdensities, "kpts")

    def recommend(rows, key, energy_tol):
        for r in rows:
            dE = r["delta_mev_per_atom"]
            dg = r["delta_gap_ev"]
            if dg is not None:
                ok = dg < tol_gap_ev and (dE is None or dE < energy_tol)
            else:  # metallic: energy criterion alone
                ok = dE is not None and dE < energy_tol
            if ok:
                return r[key], True
        return rows[-1][key], False  # hit sweep ceiling -> flag not converged

    rec_ecut, ok_e = recommend(ek, "ecut_ev", ecut_energy_tol_mev_per_atom)
    rec_kd, ok_k = recommend(kk, "kpts_density", tol_mev_per_atom)
    result = {
        "run_id": run_id, "engine": eng.name, "tol_mev_per_atom": tol_mev_per_atom,
        "tol_gap_ev": tol_gap_ev,
        "ecut_sweep": ek, "kpts_sweep": kk,
        "ecut_converged": ok_e, "kpts_converged": ok_k,
        "recommended_ecut_ev": int(rec_ecut),
        "recommended_kpts_density": float(rec_kd),
        "converged": bool(ok_e and ok_k),
    }
    write_json(run_dir / "convergence.json", result)
    return result


# --------------------------------------------------------------- physics QA

def verify_run(run_id: str, gap_tol_ev: float = 0.3, fmax_tol: float = 0.05,
               drift_tol_a: float = 0.5) -> dict:
    """Physics sanity checks over an existing run's artifacts."""
    import json
    from .config import verify_run_id
    run_dir = RUNS / verify_run_id(run_id)
    checks: list[dict] = []

    def add(name, status, detail, fix=""):
        checks.append({"check": name, "status": status, "detail": detail, "fix": fix})

    def load(name):
        p = run_dir / name
        return json.loads(p.read_text()) if p.exists() else None

    fetch, relax, summary = load("fetch.json"), load("relax.json"), load("summary.json")
    conv = load("convergence.json")

    if conv:
        add("convergence_gate", "pass" if conv.get("converged") else "warn",
            f"ecut_converged={conv.get('ecut_converged')}, "
            f"kpts_converged={conv.get('kpts_converged')}, recommended "
            f"ecut={conv.get('recommended_ecut_ev')} kd={conv.get('recommended_kpts_density')}",
            "sweep hit ceiling: extend range; treat results as lower accuracy")

    if relax:
        if relax.get("converged") and relax.get("max_force_ev_per_a", 9) <= fmax_tol:
            add("relax_convergence", "pass",
                f"fmax={relax['max_force_ev_per_a']:.3f} eV/A in {relax['n_steps']} steps")
        else:
            add("relax_convergence", "fail",
                f"converged={relax.get('converged')}, fmax={relax.get('max_force_ev_per_a')}",
                "increase max_steps; if still failing, inspect structure for clashes")
        s0, s1 = run_dir / "structure.cif", run_dir / "relaxed.cif"
        if s0.exists() and s1.exists():
            a0, a1 = ase_read(s0), ase_read(s1)
            drift = float(np.linalg.norm(a1.positions - a0.positions, axis=1).max())
            add("structure_drift", "pass" if drift <= drift_tol_a else "warn",
                f"max displacement {drift:.3f} A (tol {drift_tol_a})",
                "large drift: double-check the initial structure is sane")
    else:
        add("relax_convergence", "fail", "no relax.json — relax step never ran",
            "run relax_structure first")

    if summary and fetch:
        gap, ref = summary.get("band_gap_ev"), fetch.get("band_gap_ref")
        if gap is not None and ref is not None:
            diff = abs(gap - ref)
            status = "pass" if diff <= gap_tol_ev else ("warn" if diff <= 1.5 * gap_tol_ev else "fail")
            add("band_gap_vs_mp", status,
                f"calc {gap:.3f} eV vs MP ref {ref:.3f} eV (|Δ|={diff:.3f})",
                "persistent mismatch: check k-grid/ecut convergence, structure phase, "
                "or whether the MP reference is the same polymorph")
        elif ref is None:
            add("band_gap_vs_mp", "skip", "no MP reference for this structure")
        gt = summary.get("gap_type")
        if gt:
            v = summary.get("vbm") or {}
            c = summary.get("cbm") or {}
            if gt == "metallic" or not v or not c:
                add("gap_character", "info",
                    "metallic/gapless: no VBM/CBM analysis applicable")
            else:
                add("gap_character", "info",
                    f"{gt} gap: VBM@{v.get('label')}={v.get('energy_ev')} eV, "
                    f"CBM@{c.get('label')}={c.get('energy_ev')} eV")
    elif not summary:
        add("band_gap_vs_mp", "fail", "no summary.json — band/DOS step never ran",
            "run calc_band_dos first")

    if fetch:
        stab = fetch.get("is_stable")
        if stab is not None:
            add("mp_stability", "pass" if stab else "warn",
                f"MP is_stable={stab}",
                "metastable phase per MP hull: result may not describe the "
                "ground-state polymorph — check phase before citing")

    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    verdict = "fail" if fails else ("pass_with_warnings" if warns else "pass")
    out = {"run_id": run_id, "verdict": verdict, "checks": checks,
           "blocking_failures": [c["check"] for c in fails]}
    write_json(run_dir / "verify.json", out)
    return out


# ------------------------------------------------------- verified orchestration

def run_verified_workflow(query: str, use_builtin: bool = False, ecut: int = 400,
                          kpts_density: float = 25.0, max_retries: int = 2,
                          engine: str = "gpaw") -> dict:
    """fetch -> relax -> convergence gate -> (auto reparametrize & retry) ->
    band+DOS -> physics verification. Final results only from converged params."""
    info = fetch_structure(query, use_builtin=use_builtin)
    run_id = info["run_id"]
    attempts: list[dict] = []
    cur_ecut, cur_kd = int(ecut), float(kpts_density)
    gate_open = False
    fatal: str | None = None

    for attempt in range(max_retries + 1):
        try:
            relax = relax_structure(run_id, ecut=cur_ecut, kpts_density=cur_kd,
                                    engine=engine)
            conv = check_convergence(run_id, engine=engine)
        except Exception as e:  # SCF crash etc.: not a param failure -> stop with root cause
            fatal = f"{type(e).__name__}: {e}"
            attempts.append({"attempt": attempt, "ecut_ev": cur_ecut,
                             "kpts_density": cur_kd, "error": fatal})
            write_json(RUNS / run_id / "attempts.json", {"attempts": attempts})
            break
        rec = {"attempt": attempt, "ecut_ev": cur_ecut, "kpts_density": cur_kd,
               "relax_converged": relax["converged"],
               "params_converged": (conv["converged"]
                                    and cur_ecut >= conv["recommended_ecut_ev"]
                                    and cur_kd >= conv["recommended_kpts_density"]),
               "recommended": {"ecut_ev": conv["recommended_ecut_ev"],
                               "kpts_density": conv["recommended_kpts_density"]}}
        attempts.append(rec)
        if relax["converged"] and rec["params_converged"]:
            gate_open = True
            write_json(RUNS / run_id / "attempts.json", {"attempts": attempts})
            break
        new_ecut = max(cur_ecut, conv["recommended_ecut_ev"])
        new_kd = max(cur_kd, conv["recommended_kpts_density"])
        if (new_ecut, new_kd) == (cur_ecut, cur_kd):
            # params already at/above recommendation but sweep hit its ceiling:
            # retrying identical params is pointless — record root cause and stop.
            rec["note"] = "sweep ceiling: energy/gap not settled within tested range"
            write_json(RUNS / run_id / "attempts.json", {"attempts": attempts})
            break
        if attempt < max_retries:
            cur_ecut, cur_kd = new_ecut, new_kd
        write_json(RUNS / run_id / "attempts.json", {"attempts": attempts})

    if not gate_open:
        # The gate is real: no band gap, no figures, no "final results".
        # Intermediate artifacts stay on disk for forensics only.
        result = {
            "run_id": run_id, "query": query,
            "status": "error" if fatal else "rejected_unconverged",
            "root_cause": fatal or "convergence gate never opened "
                                   "(sweep ceiling or relax not converged)",
            "n_attempts": len(attempts), "attempts": attempts,
            "final_params": {"ecut_ev": cur_ecut, "kpts_density": cur_kd},
            "message": "收敛门未开启：未产出能带/DOS/带隙等最终结果；"
                       "run 目录内中间产物仅供取证，禁止作为结果引用。",
        }
        write_json(RUNS / run_id / "workflow_result.json", result)
        return result

    summary = calc_band_dos(run_id, ecut=cur_ecut, kpts_density=cur_kd,
                            engine=engine)
    verdict = verify_run(run_id)
    rejected = verdict["verdict"] == "fail"
    result = {
        "run_id": run_id,
        "query": query,
        "status": "rejected_by_verifier" if rejected else "pass",
        "final_params": {"ecut_ev": cur_ecut, "kpts_density": cur_kd},
        "n_attempts": len(attempts),
        "attempts": attempts,
        "band_gap_ev": summary["band_gap_ev"],
        "gap_type": summary.get("gap_type"),
        "verdict": verdict["verdict"],
        "blocking_failures": verdict["blocking_failures"],
        "bands_png": summary["bands_png"],
        "dos_png": summary["dos_png"],
    }
    if rejected:
        result["rejected_notice"] = ("物理校验未通过：以上数值与图片仅供取证，"
                                     "禁止作为结果引用。修复方向见 verify.json 各 check 的 fix 字段。")
    write_json(RUNS / run_id / "workflow_result.json", result)
    return result
