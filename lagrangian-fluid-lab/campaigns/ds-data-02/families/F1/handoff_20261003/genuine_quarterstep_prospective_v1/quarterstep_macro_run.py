#!/usr/bin/env python3
"""Run macro comparison between genuine halfstep reference and quarterstep candidate.

Uses original unchanged compare_pair from ds_data02_f1_eccentric_three_dp_evidence.py.
Applies frozen 1% time allocation (macro_budget=0.01) across full window [0, 1.6] s.
Evaluates Center of Mass, Kinetic Energy, and Coordinate Quantiles ([0.05, 0.5, 0.95]).
Preserves negative finding that halfstep failed quantiles at 0.013760724309613467;
does not relax threshold or relabel temporal pass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Locate scripts directory
scripts_dir = Path(__file__).resolve().parents[6] / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from ds_data02_f1_eccentric_three_dp_evidence import compare_pair, sha256


def run_quarterstep_macro_comparison(binding_path: Path | str, output_path: Path | str) -> dict:
    binding_path = Path(binding_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    b = json.loads(binding_path.read_text())
    f = json.loads(Path(b["frozen"]).read_text())
    t = json.loads(Path(b["time_registration"]).read_text())

    assert f["H0_m"] == 0.3 and f["continuous_initial_mass_kg"] == 80.4
    assert t["time_macro_budget_fraction"] == 0.01
    assert t["integration_share"] == 0.2
    assert t["full_window_s"] == [0, 1.6]

    cases = {}
    bindings = {}
    for c in b["cases"]:
        obs_path = Path(c["observation"])
        rec_path = Path(c["receipt"])
        if not obs_path.exists() or not rec_path.exists():
            raise FileNotFoundError(
                f"Missing case files for {c['role']}: obs={obs_path}, rec={rec_path}"
            )
        r = json.loads(rec_path.read_text())
        assert r["status"] == "completed" and r["returncode"] == 0
        o = json.loads(obs_path.read_text())
        assert len(o["rows"]) == 1601 and o["rows"][0]["time_s"] == 0 and o["rows"][-1]["time_s"] >= 1.6
        assert o["physical_condition_sha256"] == b["physical_condition_sha256"]
        assert o["quantiles"] == [0.05, 0.5, 0.95]
        assert o["continuous_initial_mass_kg"] == 80.4
        assert abs(o["numerical_initial_mass_kg"] - 80.4) / 80.4 <= f["initial_mass_budget_fraction"]

        cases[c["role"]] = {
            "case_id": c["case_id"],
            "observation": o,
            "initial_mass_kg": o["numerical_initial_mass_kg"],
            "initial_mass_relative_error": o["initial_mass_relative_error"],
        }
        bindings[c["role"]] = {
            "observation_sha256": sha256(obs_path),
            "receipt_sha256": sha256(rec_path),
            "geometry_sha256": o["geometry_sha256"],
            "physical_condition_sha256": o["physical_condition_sha256"],
            "native_window_s": [o["rows"][0]["time_s"], o["rows"][-1]["time_s"]],
        }

    assert len({c["observation"]["coordinate_frame"] for c in cases.values()}) == 1

    pairs = {}
    # Candidate quarterstep vs reference halfstep
    for candidate, reference in [("quarterstep", "halfstep")]:
        z = compare_pair(
            cases[candidate],
            cases[reference],
            cadence=0.001,
            max_offset=f["max_time_offset_s"],
            H0=f["H0_m"],
            continuous_mass=f["continuous_initial_mass_kg"],
            macro_budget=t["time_macro_budget_fraction"],
        )
        assert z["time_alignment"]["common_frame_count"] == 1601
        assert abs(z["series"]["time_s"][-1] - 1.6) < 1e-12
        pairs[f"{candidate}_vs_{reference}"] = z

    out = {
        "schema": "ds02.f1.full-thick-dbc-quarterstep-frozen-macro-comparison.v1",
        "physical_window_s": [0.0, 1.6],
        "bindings": bindings,
        "pairs": pairs,
        "frozen_sha256": sha256(Path(b["frozen"])),
        "time_registration_sha256": sha256(Path(b["time_registration"])),
        "time_budget_fraction": t["time_macro_budget_fraction"],
        "prior_halfstep_failure_recorded": {
            "frozen_1pct_timeallocation_status": "FAILED",
            "halfstep_quantiles_max_over_H0": 0.013760724309613467,
            "center_of_mass_max_over_H0": 0.0011531225598928007,
            "kinetic_energy_max_over_continuous_MgH0": 0.000875883608976671,
            "policy": "Do not relax threshold/relabel temporal pass or assert exclusive causal attribution.",
        },
        "claim_boundary": b.get("claim_boundary", {
            "q_n": "not_granted",
            "production_approval": "none",
            "mass_normalization": "none",
            "operator": "unchanged compare_pair; frozen COM/coordinate-quantiles/KE with preregistered integration allocation 1%",
            "geometry_identity": "byte-identical discrete initial BI4, same continuum mother condition",
            "temporal_or_event_convergence": "full-window integration macro comparison only; transport event convergence and spatial Q-N remain ungranted",
        }),
    }
    output_path.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, help="Path to quarterstep_macro_binding.json")
    parser.add_argument("--output", required=True, help="Output path for macro-comparison.json")
    args = parser.parse_args()

    run_quarterstep_macro_comparison(args.binding, args.output)
