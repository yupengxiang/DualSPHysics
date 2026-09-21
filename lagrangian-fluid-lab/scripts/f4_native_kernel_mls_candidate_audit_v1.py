"""Read-only admission audit for the existing F4 native weighted MLS evidence."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "campaigns/core-v1/material/evidence"
DESIGN = EVIDENCE / "f4-native-kernel-mls-v1-design-v3-20260919.json"
SPEC = EVIDENCE / "f4-native-kernel-mls-v1-dense-short-canary-spec-20260919.json"
RESULT = EVIDENCE / "f4-native-kernel-mls-v1-dense-short-canary-result-20260919.json"
TRACE = EVIDENCE / "f4-native-kernel-mls-v1-rk4-budget-canary-s0p3.h5.summary.json"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def audit() -> dict:
    files = {"design": DESIGN, "spec": SPEC, "result": RESULT, "trace": TRACE}
    data = {k: json.loads(p.read_text()) for k, p in files.items()}
    by_source = data["trace"].get("by_source", [])
    unknown = max((float(x.get("unknown_fraction", 1.0)) for x in by_source), default=1.0)
    full_window = bool(data["trace"].get("event_window_complete", False))
    cdf = None  # no reference comparison exists in this candidate evidence
    gates = {
        "fixed_unknown_fraction_max": 0.01,
        "observed_unknown_fraction_max": unknown,
        "unknown_pass": unknown <= 0.01,
        "cdf_sup_abs_difference_max": 0.02,
        "observed_cdf_sup_abs_difference_max": cdf,
        "cdf_pass": False,
        "full_window_required": True,
        "full_window_observed": full_window,
        "full_window_pass": full_window,
        "residence_right_censored": any(float(x.get("right_censored_fraction", 1.0)) > 0 for x in by_source),
        "residence_gate_pass": False,
    }
    return {"schema": "core.material.f4.native_kernel_mls.candidate_audit.v1",
            "audit_role": "read_only_candidate_or_blocked_receipt", "backend": "f4_native_kernel_mls_wendland_mass_density_v1",
            "inputs": {k: {"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for k,p in files.items()},
            "gates": gates, "qualification_claim": "none", "credit": 0, "T2_macro": False,
            "status": "blocked", "block_reasons": ["CDF reference comparison is absent", "trace is not full-window", "residence remains right-censored"],
            "execution": {"read_only": True, "solver_started": False, "gpu_started": False, "long_h5_started": False,
                          "registry_mutation": 0, "ledger_mutation": 0, "ess32_rerun": False, "affine_bound_rerun": False}}

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("-o", "--output", type=Path, required=True); a = ap.parse_args()
    value = audit(); a.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps(value, sort_keys=True))

if __name__ == "__main__": main()
