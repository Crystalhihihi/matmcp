"""Engine-parity acceptance: same MoS2 monolayer through GPAW and QE.

Gate: both workflows pass; same gap_type; |gap_gpaw - gap_qe| <= 0.05 eV.
Also serves as post-refactor regression for the GPAW path.

Run inside WSL matmcp env:  python tools/test_qe_parity.py
"""
from matmcp import verify

g = verify.run_verified_workflow("MoS2", use_builtin=True, engine="gpaw")
print("GPAW:", round(g["band_gap_ev"], 4), g["gap_type"], g["status"], g["run_id"])

q = verify.run_verified_workflow("MoS2", use_builtin=True, engine="qe")
print("QE  :", round(q["band_gap_ev"], 4), q["gap_type"], q["status"], q["run_id"])

dgap = abs(g["band_gap_ev"] - q["band_gap_ev"])
print(f"dgap = {dgap:.4f} eV")
assert g["status"] == "pass", g.get("root_cause") or g.get("blocking_failures")
assert q["status"] == "pass", q.get("root_cause") or q.get("blocking_failures")
assert g["gap_type"] == q["gap_type"], f"gap character mismatch: {g['gap_type']} vs {q['gap_type']}"
assert dgap <= 0.05, f"engine gap mismatch: {dgap}"
print("PARITY_OK")
