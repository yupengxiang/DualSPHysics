"""Fail-closed tests for the residual seed29 authority projection gap."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_residual_hidden16_seed29_authority_projection_gap_v1 as projection
from scripts import f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 as admission


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _receipt_path(tmp_path: Path) -> Path:
    namespace = tmp_path / "f3-residual-seed29-namespace"
    namespace.mkdir(mode=0o700)
    namespace.chmod(0o700)
    return namespace / admission.RECEIPT_NAME


def _receipt(tmp_path: Path, *, complete: bool = False) -> tuple[Path, dict[str, object]]:
    path = _receipt_path(tmp_path)
    namespace = path.parent
    identity: dict[str, object] = {
        "model_kind": admission.MODEL,
        "hidden": admission.HIDDEN,
        "updates": admission.UPDATES,
        "seed": admission.SEED,
        "case_id": admission.CASE_ID,
        "split": admission.SPLIT,
        "transitions": admission.TRANSITIONS,
        "frames": admission.FRAMES,
    }
    if complete:
        source_files = {
            name: {
                "path": str(admission.LAB_ROOT / relative),
                "sha256": f"{index + 1:064x}",
            }
            for index, (name, relative) in enumerate(admission.SOURCE_RELATIVE_PATHS.items())
        }
        identity.update(
            {
                "root": str(admission.LAB_ROOT),
                "run_id": admission.RUN_ID,
                "manifest": {"path": str(admission.DEFAULT_MANIFEST), "binding": {}, "file": {}},
                "training_receipt": {"path": "/tmp/residual29-training.json", "binding": {}, "file": {}},
                "checkpoint": {"path": "/tmp/residual29-checkpoint.pt", "sha256": "a" * 64, "bytes": 1},
                "source_files": source_files,
                "executable": {"path": sys.executable, "sha256": "b" * 64, "bytes": 1},
                "command": {
                    "argv": [sys.executable],
                    "cwd": str(admission.LAB_ROOT),
                    "env_overrides": {},
                },
                "outputs": {"positions": str(namespace / "positions.h5")},
                "environment": {},
                "resource_admission": {},
                "gpu": {},
                "gpu_identity_sha256": "c" * 64,
                "namespace": str(namespace),
                "namespace_descriptor": {
                    "path": str(namespace),
                    "dev": 1,
                    "ino": 1,
                    "mode": 0o700,
                    "uid": 0,
                    "gid": 0,
                    "nlink": 2,
                    "parent_dev": 1,
                    "parent_ino": 1,
                },
                "nonce": "d" * 32,
                "external_authority": {
                    "path": str(tmp_path / "scheduler" / "authority" / ("d" * 32 + ".json"))
                },
                "formal_state_touched": False,
            }
        )
        # The plan helper only consumes the bound shape; no file is opened.
        identity["plan_sha256"] = admission._plan_binding_digest(
            admission._identity_plan_binding(identity)
        )

    receipt: dict[str, object] = {
        "schema": admission.SCHEMA,
        "report_id": admission.REPORT_ID,
        "status": "admission_issued",
        "receipt_path": str(path),
        "namespace": str(namespace),
        "namespace_nonce": "d" * 32,
        "identity": identity,
        "identity_sha256": projection.canonical_digest(identity),
        "consumption": {
            "one_shot": True,
            "lock_path": str(namespace / admission.CONSUMPTION_LOCK),
            "consumed_marker": str(namespace / admission.CONSUMED_MARKER),
            "consumed": False,
        },
        "diagnostic_execute_only": True,
        "terminal_receipt_minting": False,
        **projection.ZERO_CREDIT,
    }
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    _write_json(path, receipt)
    return path, receipt


def test_missing_source_receipt_is_a_zero_credit_gap(tmp_path: Path) -> None:
    report = projection.build_report(tmp_path / "missing-receipt.json")

    assert report["status"] == "blocked_projection_gap"
    assert report["source_observed"] is False
    assert report["external_authority"]["verified"] is False
    assert report["runner_consumable"] is False
    assert report["popen_allowed"] is False
    assert report["credit"] == 0
    assert projection.validate_report(report) == []


def test_legacy_receipt_reports_non_projectable_fields_without_repair(tmp_path: Path) -> None:
    path, original = _receipt(tmp_path, complete=False)
    report = projection.build_report(path)

    assert report["status"] == "blocked_projection_gap"
    assert "identity.root" in report["non_projectable_missing_fields"]
    assert "authority" in report["projectable_missing_fields"]
    assert report["historical_receipt_rewritten"] is False
    assert report["durable_receipt_written"] is False
    assert report["credit"] == 0
    assert projection.validate_report(report) == []
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_complete_shape_still_requires_real_external_authority(tmp_path: Path) -> None:
    path, receipt = _receipt(tmp_path, complete=True)

    with pytest.raises(projection.ProjectionGap, match="external scheduler authority"):
        projection.project_authority(
            receipt,
            external_authority=None,
            resource_admission=None,
        )
    assert json.loads(path.read_text(encoding="utf-8"))["receipt_sha256"] == receipt["receipt_sha256"]


def test_supplied_authority_path_must_match_producer_binding(tmp_path: Path) -> None:
    _path, receipt = _receipt(tmp_path, complete=True)

    with pytest.raises(projection.ProjectionGap, match="authority path"):
        projection.project_authority(
            receipt,
            external_authority=tmp_path / "other-authority.json",
            resource_admission={},
        )


def test_forged_adapter_authority_is_not_accepted_as_a_source_receipt(tmp_path: Path) -> None:
    path, receipt = _receipt(tmp_path, complete=False)
    forged = copy.deepcopy(receipt)
    forged["authority"] = projection._authority_envelope()
    forged.pop("receipt_sha256", None)
    forged["receipt_sha256"] = projection.canonical_digest(forged)

    with pytest.raises(projection.ProjectionError, match="source receipt shell"):
        projection.project_authority(
            forged,
            external_authority=None,
            resource_admission=None,
        )
    assert json.loads(path.read_text(encoding="utf-8"))["receipt_sha256"] == receipt["receipt_sha256"]


def test_report_validator_rejects_promotion_or_side_effect_mutation(tmp_path: Path) -> None:
    report = projection.build_report(tmp_path / "missing.json")

    forged_credit = copy.deepcopy(report)
    forged_credit["credit"] = 1
    assert projection.validate_report(forged_credit)

    forged_effect = copy.deepcopy(report)
    forged_effect["side_effects"]["popen_attempted"] = True
    assert projection.validate_report(forged_effect)


def test_report_writer_is_seed29_scoped(tmp_path: Path) -> None:
    report = projection.build_report(tmp_path / "missing.json")
    json_path = tmp_path / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-GAP.json"
    md_path = tmp_path / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-GAP.md"
    projection.write_reports(report, report_path=json_path, markdown_path=md_path)

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["schema"] == projection.REPORT_SCHEMA
    assert parsed["scope"]["seed"] == 29
    assert parsed["credit"] == 0
    assert "seed29" in md_path.read_text(encoding="utf-8")


def test_cli_contract_has_no_execution_alias() -> None:
    parsed = projection._parse_args(["--receipt", "/tmp/receipt.json"])
    assert parsed.receipt == Path("/tmp/receipt.json")
    assert not hasattr(parsed, "execute")
