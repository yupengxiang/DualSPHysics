from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_request_builder_v3.py"
SPEC = importlib.util.spec_from_file_location("f2_fresh_v16_request_builder_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _producer_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    target = tmp_path / "relocated" / "target"
    output = tmp_path / "relocated" / "output"
    target.mkdir(parents=True)
    output.mkdir(parents=True)
    result = output / "typed-label-result-v16.json"
    result.write_text('{"schema":"ds02.stage2.f2-s1-replay-result.v16"}\n', encoding="utf-8")
    report = tmp_path / "typed-label-only-report-v1.json"
    report_body = {
        "schema": builder.REPORT_SCHEMA,
        "status": "COMPLETE_TYPED_ONLY_LABELS_DEVELOPMENT_UNKNOWN",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(builder.UNKNOWN),
        "labels": {"v16": {"path": str(result), "sha256": _sha_text("producer-result")}},
    }
    report_body["sha256"] = builder.canonical_sha(report_body)
    _write(report, report_body)
    original = tmp_path / "original"
    original.mkdir()
    contract = {
        "schema": builder.SOURCE_SCHEMA,
        "role": "DEVELOPMENT",
        "quality": dict(builder.UNKNOWN),
        "original_roots": [str(original)],
        "expected": {
            "source_binding": {
                "binding_status": "FROZEN_SOURCE_METADATA",
                "current_catalog_sha256": _sha_text("current"),
                "trajectory_h5_producer_sha256": _sha_text("h5"),
                "source_files": {"current_catalog": _sha_text("current")},
            },
            "case_identity": {"family_id": "F2", "physical_case_id": "F2-S1"},
            "cohort": {"selected_count": 1, "identity_key": "(Zone,Idp)", "identity_sha256": _sha_text("id")},
            "initial_mass_denominator": {
                "denominator_kg": 1.0, "initial_missing_mass_kg": 0.0,
                "later_missing_unique_count": 0, "later_missing_mass_kg": 0.0,
            },
            "time": {"frame_count": 1, "first_s": 0.0, "last_s": 0.0,
                     "tolerance_s": 0.0, "observer_profile_sha256": _sha_text("profile")},
            "observer_fields": ["mass_weighted_com_m"],
            "events": {"status_vocabulary": sorted(builder.V8.FIRST_PASSAGE_STATUSES),
                        "require_unknown_recross": True, "require_total_net_interval": True,
                        "require_receiver_labels": True, "require_residence_semantics": True},
        },
    }
    contract["sha256"] = builder.canonical_sha(contract)
    contract_path = tmp_path / "source-contract.json"
    _write(contract_path, contract)
    return report, result, contract_path, target, output


def test_report_adapter_uses_declared_sha_and_stat_without_result_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, result, contract, target, output = _producer_fixture(tmp_path)
    report_path, _, binding, _ = builder._load_producer_report(report)
    assert report_path == report
    assert binding["sha256"] == _sha_text("producer-result")
    assert binding["bytes"] == result.stat().st_size
    assert binding["content_sha_verified"] is False

    original_hash = builder.sha256_file
    seen: list[Path] = []

    def track(path: Path | str) -> str:
        seen.append(Path(path))
        if Path(path).resolve() == result.resolve():
            raise AssertionError("metadata builder hashed the large result before parent reservation")
        return original_hash(path)

    monkeypatch.setattr(builder, "sha256_file", track)
    value = builder._build_v8_request(
        source_contract=contract, producer_report=report_path, result_binding=binding,
        target=target, output_root=output, output=tmp_path / "request.json",
        parent_guard_record=None, trace_audit_request=None, python_executable=None,
        max_wall_seconds=900.0, max_result_bytes=100_000_000,
    )
    assert value["result_sha256"] == _sha_text("producer-result")
    request = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert request["result"]["content_verification_phase"] == "PARENT_AFTER_RESERVATION"
    assert result.resolve() not in [item.resolve() for item in seen]


def test_report_adapter_rejects_mutated_small_report(tmp_path: Path) -> None:
    report, _, _, _, _ = _producer_fixture(tmp_path)
    value = json.loads(report.read_text(encoding="utf-8"))
    value["labels"]["v16"]["sha256"] = _sha_text("changed")
    report.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(builder.V16ForwardRequestError, match="canonical SHA"):
        builder._load_producer_report(report)
