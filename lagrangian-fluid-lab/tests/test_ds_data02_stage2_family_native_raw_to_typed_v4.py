"""Metadata/attestation tests for the additive generic v4 worker.

The tests use the real F1 v3 request only for its JSON/stat closure.  They do
not hash or open its HDF5/BI4 payloads and never invoke the raw converter.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_native_raw_to_typed_v4.py"
V3_REQUEST = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "generic-v3/f1-s1-native-raw-to-typed-compare-request-v3-001.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("ds02_v4_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(module, value: dict) -> str:
    return hashlib.sha256(
        json.dumps({key: item for key, item in value.items() if key != "sha256"},
                   sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   default=str).encode()
    ).hexdigest()


def _attestation(module, request: dict, *, post_sha: str | None = None) -> dict:
    reference = Path(request["reference_hdf5"]["path"])
    stat = reference.stat()
    expected = request["reference_hdf5"]["sha256"]
    value = {
        "schema": module.ATTESTATION_SCHEMA,
        "status": "PASS_PARENT_CONTENT_ATTESTATION",
        "scope": "exact CURRENT trajectory_h5",
        "content_verified": True,
        "source_path": str(reference.resolve()),
        "pre_content_sha256": expected,
        "post_content_sha256": expected if post_sha is None else post_sha,
        "pre_stat": {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                     "inode": stat.st_ino, "device": stat.st_dev},
        "post_stat": {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                      "inode": stat.st_ino, "device": stat.st_dev},
        "parent_attempt_id": "manufactured-v4-parent-attestation-001",
    }
    value["sha256"] = _canonical(module, value)
    return value


def test_build_attach_and_prepare_keep_fast_path_parent_attested(tmp_path: Path) -> None:
    module = _module()
    request_path = tmp_path / "request-v4.json"
    base = module.build_request(V3_REQUEST, request_path)
    assert base["schema"] == module.SCHEMA
    assert base["reference_parent_attestation"] is None
    assert module._comparison_mode(output_sha256=base["reference_hdf5"]["sha256"], attestation=None) == "FULL_FIELD_FALLBACK_REQUIRED"

    att_path = tmp_path / "reference-attestation.json"
    att = _attestation(module, base)
    att_path.write_text(json.dumps(att, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    forward_path = tmp_path / "request-v4-attested.json"
    forward = module.attach_parent_attestation(request_path, att_path, forward_path)
    assert forward["status"] == "READY_FOR_PARENT_GUARD_WITH_REFERENCE_ATTESTATION"
    bound = module.validate_request(forward_path)
    assert bound["parent_attestation"]["expected_sha256"] == base["reference_hdf5"]["sha256"]
    assert module._comparison_mode(
        output_sha256=base["reference_hdf5"]["sha256"],
        attestation=bound["parent_attestation"],
    ) == "WHOLE_FILE_SHA_EQUAL_PARENT_ATTESTED"
    preflight_path = tmp_path / "preflight.json"
    report = module.prepare_report(forward_path, preflight_path)
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["execution_boundary"]["hdf5_opened"] is False


def test_reference_sha_difference_requires_full_field_fallback() -> None:
    module = _module()
    assert module._comparison_mode(output_sha256="0" * 64, attestation={"expected_sha256": "1" * 64}) == "FULL_FIELD_FALLBACK_REQUIRED"
    assert module._comparison_mode(output_sha256="0" * 64, attestation=None) == "FULL_FIELD_FALLBACK_REQUIRED"


def test_wrong_parent_content_or_scope_is_rejected(tmp_path: Path) -> None:
    module = _module()
    request_path = tmp_path / "request-v4.json"
    base = module.build_request(V3_REQUEST, request_path)
    bad = _attestation(module, base, post_sha="0" * 64)
    bad["sha256"] = _canonical(module, bad)
    bad_path = tmp_path / "bad-attestation.json"
    bad_path.write_text(json.dumps(bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.FamilyNativeV4Error, match="pre/post content SHA"):
        module.attach_parent_attestation(request_path, bad_path, tmp_path / "rejected.json")

    wrong_scope = _attestation(module, base)
    wrong_scope["scope"] = "stat-only"
    wrong_scope["sha256"] = _canonical(module, wrong_scope)
    wrong_scope_path = tmp_path / "wrong-scope.json"
    wrong_scope_path.write_text(json.dumps(wrong_scope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.FamilyNativeV4Error, match="scope"):
        module.attach_parent_attestation(request_path, wrong_scope_path, tmp_path / "rejected-scope.json")
