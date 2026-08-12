"""P1 acceptance: fetch(builtin MoS2) -> relax -> band+DOS, direct workflow calls.

Run inside WSL matmcp env:  python tools/test_p1_mos2.py
"""
from matmcp import workflows

info = workflows.fetch_structure("MoS2", use_builtin=True)
print("FETCH:", info["run_id"], info["formula"], "ref_gap =", info["band_gap_ref"])

r = workflows.relax_structure(info["run_id"])
print("RELAX:", r["converged"], "steps =", r["n_steps"],
      "fmax =", round(r["max_force_ev_per_a"], 4), "E =", round(r["total_energy_ev"], 3))
assert r["converged"], "relax did not converge"

s = workflows.calc_band_dos(info["run_id"])
print("BANDS: gap =", round(s["band_gap_ev"], 3), "eV, Ef =", round(s["fermi_ev"], 3))
assert 1.0 < s["band_gap_ev"] < 2.5, f"MoS2 monolayer PBE gap off: {s['band_gap_ev']}"
print("RUN_DIR: runs/" + info["run_id"])
print("P1_ACCEPT_DONE")
