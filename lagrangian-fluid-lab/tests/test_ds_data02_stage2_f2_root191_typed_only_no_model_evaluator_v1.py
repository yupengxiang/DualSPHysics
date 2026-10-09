"""Metadata-only contract tests for the ROOT191 evaluator bridge.

The fixture deliberately points at nonexistent typed-HDF5/V16 payload paths.
ROOT191 must be able to build a request from producer-attested metadata while
deferring all payload existence/content checks to the later parent guard.  The
tests exercise the real ROOT194/V12 binding logic and reject failed, stale, or
mis-bound terminal evidence without reading any scientific payload.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("root191_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module()


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: dict) -> str:
    return S.canonical_sha(value)


def fixture(tmp_path: Path, *, failed_terminal: bool = False,
            stale_terminal_path: bool = False,
            wrong_typed_sha: bool = False):
    current = tmp_path / "CURRENT336.json"
    current.write_text("{}\n", encoding="utf-8")
    sidecar = tmp_path / "root194-semantic-sidecar.json"
    write_json(sidecar, {
        "schema": S.V12_SIDECAR_SCHEMA,
        "missing_scope": "initial_fluid_source_cohort_global; identity fate unknown",
        "denominator_semantics": "initial denominator remains the frozen fluid mass",
    })
    frozen = tmp_path / "frozen-observer-profile.json"
    write_json(frozen, {"schema": "fixture.frozen.observer.v1", "profile": "source-bound"})

    # These are producer metadata paths only.  They intentionally do not
    # exist: ROOT191 must not open a 1.19 GB H5 or a 62 MB result at build time.
    typed_path = "/var/tmp/root194-fixture/typed-reconstructed.h5"
    result_path = "/var/tmp/root194-fixture/v16-result.json"
    typed_sha = "0" * 64 if wrong_typed_sha else S.TYPED_H5_SHA
    v8 = {
        "schema": S.ROOT194_V8_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "case_id": "STAGE2_F2_ROOT194_FIXTURE",
        "attempt_id": "f2-s1-root194-fixture-001",
        "model_invoked": False,
        "cfd_invoked": False,
        "quality": dict(S.UNKNOWN),
        "qualification": dict(S.UNKNOWN),
        "fresh_cold_credit": False,
        "current_manifest_binding": {"path": str(current), "sha256": S.CURRENT_SHA},
        "expected": {
            "source_binding": {"current_catalog_sha256": S.CURRENT_SHA},
            "cohort": {"selected_count": S.COHORT_COUNT, "identity_sha256": S.COHORT_IDENTITY_SHA},
            "initial_mass_denominator": {
                "denominator_kg": S.DENOMINATOR_KG,
                "later_missing_mass_kg": S.LATER_MISSING_KG,
            },
        },
        "result": {
            "path": result_path,
            "sha256": "1" * 64,
            "bytes": 62_365_973,
            "stat": {"bytes": 62_365_973, "mtime_ns": 10, "mode_bits": 0o644},
            "typed_output": {
                "path": typed_path,
                "sha256": typed_sha,
                "bytes": S.TYPED_H5_BYTES,
                "stat": {"bytes": S.TYPED_H5_BYTES, "mtime_ns": 11, "mode_bits": 0o644},
            },
        },
        "fresh_proof_namespace": {"root": str(tmp_path / "ROOT194_FRESH_PROOF_NAMESPACE")},
        "v12_forward": {
            "schema": S.V12_FORWARD_SCHEMA,
            "consumer": {
                "path": str(S.V12_SCRIPT),
                "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v12",
                "sha256": sha(S.V12_SCRIPT),
            },
            "semantic_sidecar": {
                "path": str(sidecar), "schema": S.V12_SIDECAR_SCHEMA, "sha256": sha(sidecar),
            },
        },
    }
    v8["sha256"] = canonical(v8)
    v8_path = write_json(tmp_path / "root194-proof-request.json", v8)
    outer = {
        "schema": S.ROOT194_WRAPPER_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "case_id": v8["case_id"],
        "attempt_id": v8["attempt_id"],
        "fresh_cold_credit": False,
        "no_old_ROOT060_reuse": True,
        "consumer_request_binding": {
            "path": str(v8_path), "sha256": sha(v8_path), "canonical_sha256": v8["sha256"],
        },
    }
    outer_path = write_json(tmp_path / "root194-wrapper.json", outer)
    outer_sha = sha(outer_path)

    terminal_dir = tmp_path / ("ROOT194-root190-terminal" if stale_terminal_path else "ROOT194-terminal")
    terminal_dir.mkdir()
    terminal_status = "FAILED_PARENT_EXECUTOR" if failed_terminal else "COMPLETED_PARENT_EXECUTOR"
    parent = write_json(terminal_dir / "parent-report.json", {
        "schema": "ds02.stage2.root194.parent-report.v1", "status": terminal_status,
        "request_sha256": outer_sha,
    })
    receipt = write_json(terminal_dir / "execution-receipt.json", {
        "schema": "ds02.stage2.root194.receipt.v1", "status": terminal_status,
        "request_sha256": outer_sha, "accounting_status": "completed",
    })
    root_proof = write_json(terminal_dir / "root-proof.json", {
        "schema": "ds02.stage2.root194.root-proof.v1", "status": terminal_status,
        "request_sha256": outer_sha, "ledger_mutated": not failed_terminal,
        "charge": {"status": "completed"},
    })

    # This is the actual V12/V8 proof shape consumed by ROOT191.  It is a
    # tiny semantic proof fixture; no result file is created or read.
    v12_proof = {
        "schema": S.V8_PROOF_SCHEMA,
        "status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
        "quality": dict(S.UNKNOWN), "qualification": dict(S.UNKNOWN),
        "execution": {"hdf5_or_bi4_content_read": False, "raw_opened": False},
        "v12_semantic_scope_adapter": {
            "schema": S.V12_FORWARD_SCHEMA,
            "sidecar_path": str(sidecar), "sidecar_sha256": sha(sidecar),
            "normalized_for_v8_only": True, "original_result_bytes_unchanged": True,
        },
        "request": {"path": str(v8_path), "sha256": v8["sha256"]},
        "source_result": {"sha256": "1" * 64, "bytes": 62_365_973, "content_sha_verified": True},
        "source_binding": {"current_catalog_sha256": S.CURRENT_SHA},
    }
    v12_proof["sha256"] = canonical(v12_proof)
    v12_path = write_json(tmp_path / "root194-v12-proof.json", v12_proof)
    return {
        "outer": outer_path, "v8": v8_path, "parent": parent, "receipt": receipt,
        "root_proof": root_proof, "v12_proof": v12_path, "frozen": frozen,
        "sidecar": sidecar, "typed_sha": typed_sha,
    }


def build(fixture_paths: dict, output: Path):
    return S._build_request(
        root194_request=fixture_paths["outer"], parent_report=fixture_paths["parent"],
        receipt=fixture_paths["receipt"], root_proof=fixture_paths["root_proof"],
        v12_proof=fixture_paths["v12_proof"], frozen_request=fixture_paths["frozen"],
        output=output, case_id="STAGE2_F2_ROOT191_FIXTURE",
        attempt_id="f2-s1-root191-fixture-001", fresh_output_root=output.parent / "ROOT191_FRESH",
    )


def test_build_and_validate_are_payload_free(tmp_path: Path):
    paths = fixture(tmp_path)
    result = build(paths, tmp_path / "root191-request.json")
    assert result["payload_read"] is False
    assert result["hdf5_or_bi4_read"] is False
    validated = S.validate_request(result["request"])
    assert validated["status"] == "ROOT191_METADATA_VALIDATED_READY_FOR_PARENT"
    assert not (tmp_path / "ROOT191_FRESH").exists()


def test_existing_v66_template_and_v12_consume_the_same_v8_contract():
    spec = importlib.util.spec_from_file_location("root191_v66_template", S.V66_TEMPLATE_SCRIPT)
    assert spec and spec.loader
    v66 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v66)
    v12_spec = importlib.util.spec_from_file_location("root191_v12_consumer", S.V12_SCRIPT)
    assert v12_spec and v12_spec.loader
    v12 = importlib.util.module_from_spec(v12_spec)
    v12_spec.loader.exec_module(v12)
    assert v66.V8_REQUEST_SCHEMA == S.ROOT194_V8_SCHEMA
    assert v12.REQUEST_SCHEMA == S.ROOT194_V8_SCHEMA
    assert v12.FORWARD_SCHEMA == S.V12_FORWARD_SCHEMA


def test_missing_typed_and_v16_payloads_do_not_get_opened_by_builder(tmp_path: Path):
    paths = fixture(tmp_path)
    # The paths above are intentionally absent.  Reaching a successful build
    # proves the new bridge is metadata-only; a later parent must verify them.
    assert not Path("/var/tmp/root194-fixture/typed-reconstructed.h5").exists()
    assert not Path("/var/tmp/root194-fixture/v16-result.json").exists()
    build(paths, tmp_path / "root191-request.json")


@pytest.mark.parametrize("kwargs", [
    {"failed_terminal": True},
    {"stale_terminal_path": True},
    {"wrong_typed_sha": True},
])
def test_root194_failed_stale_or_wrong_product_is_rejected(tmp_path: Path, kwargs: dict):
    paths = fixture(tmp_path, **kwargs)
    with pytest.raises(S.Root191Error):
        build(paths, tmp_path / "root191-request.json")


def test_existing_root191_destination_is_never_overwritten(tmp_path: Path):
    paths = fixture(tmp_path)
    output = tmp_path / "root191-request.json"
    output.write_text("existing\n", encoding="utf-8")
    with pytest.raises(S.Root191Error, match="existing ROOT191 output"):
        build(paths, output)


def test_real_cli_validate_path_uses_the_same_strict_bridge(tmp_path: Path):
    paths = fixture(tmp_path)
    output = tmp_path / "root191-request.json"
    build(paths, output)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--request", str(output)],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ROOT191_METADATA_VALIDATED_READY_FOR_PARENT" in completed.stdout
