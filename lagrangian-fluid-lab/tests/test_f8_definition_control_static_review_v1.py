from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_definition_control_static_review_v1 as review_module
from scripts.f8_definition_control_static_review_v1 import (
    CONTROL_TARGET,
    DEFINITION_TARGET,
    DOCUMENTS,
    OFFICIAL_PRECEDENTS,
    OUTPUT,
    build_review,
    evaluate_static_constraints,
    load_documents,
    write_review,
)


ROOT = Path(__file__).resolve().parents[1]


def test_static_review_binds_all_required_inputs_and_authorizes_only_one_write_pair() -> None:
    review = build_review()
    assert review["status"] == (
        "static_constraints_satisfied_one_time_definition_control_materialization_authorized")
    assert review["static_constraint_gaps"] == []
    assert review["qualification_claim"] == "none"
    assert review["qualification_credit"] == 0
    authorization = review["static_materialization_authorization"]
    assert authorization["granted"] is True
    assert authorization["definition_target"] == str(DEFINITION_TARGET)
    assert authorization["control_target"] == str(CONTROL_TARGET)
    assert authorization["maximum_fresh_definition_files"] == 1
    assert authorization["maximum_fresh_control_files"] == 1
    assert authorization["reuse_or_overwrite_allowed"] is False
    assert "solver" in authorization["explicitly_not_authorized"]
    assert len(review["bindings"]) == len(DOCUMENTS) + len(OFFICIAL_PRECEDENTS) + 2
    bound_paths = {item["path"] for item in review["bindings"]}
    assert {str(path) for path in DOCUMENTS.values()}.issubset(bound_paths)
    assert {str(path) for path in OFFICIAL_PRECEDENTS.values()}.issubset(bound_paths)


def test_static_review_never_grants_runtime_or_credit() -> None:
    review = build_review()
    controls = review["execution_controls"]
    assert all(value is False for value in controls.values() if isinstance(value, bool))
    assert all(value == 0 for key, value in controls.items() if key.endswith("_mutation"))
    assert review["qualification_credit"] == 0
    assert any("separate CPU-preflight authorization receipt" in gate
               for gate in review["cpu_preflight_hard_gates"])


def test_constraint_failure_precisely_closes_write_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    documents, gaps = load_documents()
    assert gaps == []
    broken = copy.deepcopy(documents)
    broken["parameter_contract"]["parameterization"]["zero_mean_control"] = False
    observed = evaluate_static_constraints(broken)
    assert {gap["code"] for gap in observed} == {"FORCING_SEMANTICS"}
    monkeypatch.setattr(review_module, "load_documents", lambda: (broken, []))
    review = review_module.build_review()
    assert review["status"] == "static_constraints_unsatisfied_write_not_authorized"
    assert review["static_materialization_authorization"]["granted"] is False
    assert review["static_constraint_gaps"] == observed


def test_committed_review_is_hash_closed_and_historical_inputs_unchanged(tmp_path: Path) -> None:
    review = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert review["static_constraint_gaps"] == []
    for item in review["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    target = tmp_path / "review.json"
    write_review(target)
    with pytest.raises(FileExistsError):
        write_review(target)
