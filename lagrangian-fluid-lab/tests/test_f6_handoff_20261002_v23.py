from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v23.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v23", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_enriched_h5_and_labels_are_complete_hash_bound_and_review_only() -> None:
    audit = F6.V21_MODULE.read_json(F6.POST_ROOT / "h5_labels_audit_001.json")
    assert audit["status"] == "actual_cpu_postprocessing_review_only"
    assert audit["q_n_status"].startswith("pending")
    assert len(audit["cases"]) == 2
    for case in audit["cases"]:
        assert all(case["checks"].values())
        assert case["trajectory"]["frames"] == 241
        assert case["trajectory"]["lifecycle_mode"] == "native_sparse_cohort"
        assert case["labels"]["complete"] is True
        assert case["labels"]["model_invoked"] is False
        assert case["labels"]["source_hdf5_sha256_matches"] is True
        assert case["labels"]["initial_fluid_mass_kg"] == 5120.0


def test_simple_sparse_loss_is_exposed_without_relabeling_it_as_qn() -> None:
    audit = F6.V21_MODULE.read_json(F6.POST_ROOT / "h5_labels_audit_001.json")
    simple = next(row for row in audit["cases"] if row["mechanism_id"] == "simple_free_response")
    assert simple["trajectory"]["valid_false_fluid_rows"] == 232
    assert simple["labels"]["numerical_loss_mass_last_kg"] == 0.125
    assert simple["q_n_status"] == "pending_native_exclusion_reconciliation"

