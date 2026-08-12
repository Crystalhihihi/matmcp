"""P2 acceptance gate: feed garbage params (ecut=200 eV, k-grid 1x1x1 via density=3).

System MUST NOT emit a plausible-looking garbage result. Required behavior:
intercept via convergence gate -> auto reparametrize (<=2 retries) ->
final results from converged params -> physics verification passes.

Run inside WSL matmcp env:  python tools/test_p2_verifier.py
"""
from matmcp import verify

out = verify.run_verified_workflow("MoS2", use_builtin=True, ecut=200, kpts_density=3)

print("attempts:", out["n_attempts"])
for a in out["attempts"]:
    print(f"  attempt {a['attempt']}: ecut={a['ecut_ev']} kd={a['kpts_density']} "
          f"relax_ok={a['relax_converged']} params_ok={a['params_converged']} "
          f"-> recommended {a['recommended']}")
print("final params:", out["final_params"])
print("gap:", round(out["band_gap_ev"], 3), "eV |", out["gap_type"])
print("verdict:", out["verdict"], "| blocking:", out["blocking_failures"])

assert out["n_attempts"] >= 2, "garbage params were NOT intercepted"
assert out["status"] == "pass", f"status: {out['status']}"
assert out["final_params"]["ecut_ev"] >= 300, "ecut was not escalated"
assert out["final_params"]["kpts_density"] >= 15, "k-grid was not escalated"
assert out["verdict"] == "pass", f"verdict: {out['verdict']} {out['blocking_failures']}"
assert out["gap_type"] == "direct", f"gap character wrong: {out['gap_type']}"
assert 1.5 < out["band_gap_ev"] < 1.9, f"final gap off: {out['band_gap_ev']}"
print("RUN_DIR: runs/" + out["run_id"])
print("P2_ACCEPT_DONE")
