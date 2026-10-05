#!/usr/bin/env python3
"""Validate fresh108 JSON/XML/Python handoff metadata without payload access.

This validator deliberately hashes only static metadata listed in disabled
requests.  H5/BI4/CSV/DAT/VTK/XMF paths are treated as opaque producer inputs
and are never opened or hashed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
MANIFEST = HERE / "F2_STAGE1_FRESH108_ACTUAL_TYPED_N3_XMF_RENDER_MANIFEST.json"
RAW = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC = {".json", ".xml", ".py", ".md", ".txt"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"metadata object required: {path}")
    return value


def digest(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in RAW:
        raise AssertionError(f"payload hash refused: {path}")
    if suffix not in STATIC:
        raise AssertionError(f"non-metadata input: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest64(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise AssertionError(f"{label} is not a 64-character digest")
    int(value, 16)


def completed_receipt(path: Path, label: str) -> dict[str, Any]:
    value = load(path)
    if value.get("status") != "completed" or value.get("returncode") != 0:
        raise AssertionError(f"{label} is not completed/0: {path}")
    return value


def check_static_closure(request: dict[str, Any], label: str) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(files, list) or not isinstance(hashes, dict):
        raise AssertionError(f"{label}: static input closure missing")
    if set(files) != set(hashes):
        raise AssertionError(f"{label}: input_files/input_sha256 mismatch")
    for raw in files:
        path = Path(raw)
        if path.suffix.lower() in RAW:
            raise AssertionError(f"{label}: payload in static closure {path}")
        if path.suffix.lower() not in STATIC:
            raise AssertionError(f"{label}: unsupported static suffix {path}")
        if not path.is_file():
            raise AssertionError(f"{label}: missing static input {path}")
        actual = digest(path)
        digest64(hashes[raw], f"{label} input {path}")
        if actual != hashes[raw]:
            raise AssertionError(f"{label}: static digest mismatch {path}")


def check_common(request: dict[str, Any], label: str) -> None:
    for key, expected in (("family_id", "F2"), ("scope_id", "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"),
                          ("schema", "ds02.runner-request.v3"), ("producer_scope_schema", "legacy-owner-scope.v0")):
        if request.get(key) != expected:
            raise AssertionError(f"{label}: {key} mismatch")
    for key in ("source_only", "disabled", "root_only", "root_review_required", "future_hashes_null",
                "no_arrays_read", "no_jobs_started", "no_science_payload_bound", "no_shared_registry_write"):
        if request.get(key) is not True:
            raise AssertionError(f"{label}: {key} must be true")
    for key in ("execution_allowed", "launch_allowed", "launch"):
        if request.get(key) is not False:
            raise AssertionError(f"{label}: {key} must be false")
    if request.get("canonical_grant") is not False or request.get("canonical_physical_binding_sha256") is not None:
        raise AssertionError(f"{label}: canonical binding was granted")
    if request.get("actual_converter_physical_condition_sha256") is not None:
        raise AssertionError(f"{label}: future converter scope is not null")
    if request.get("trajectory_h5_sha256") is not None:
        raise AssertionError(f"{label}: source hashed H5")
    if request.get("actual_typed_status") != "completed/0":
        raise AssertionError(f"{label}: typed status is not completed/0")
    if request.get("expected_dimension") != 3 or request.get("expected_native_frames") != 401 or request.get("expected_particles") != 418104:
        raise AssertionError(f"{label}: dimensions/counts mismatch")
    legacy = request.get("prospective_legacy_scope_sha256")
    source = request.get("source_plan_physical_condition_sha256")
    digest64(legacy, f"{label} legacy scope")
    digest64(source, f"{label} source plan")
    if legacy == source or request.get("physical_condition_sha256") != legacy:
        raise AssertionError(f"{label}: source/legacy scope separation invalid")
    check_static_closure(request, label)


def check_producer(request: dict[str, Any], label: str) -> None:
    h5 = request.get("trajectory_h5")
    producer = request.get("trajectory_h5_producer_sha256")
    if not isinstance(h5, str) or Path(h5).suffix.lower() not in {".h5", ".hdf5"}:
        raise AssertionError(f"{label}: H5 producer path missing")
    digest64(producer, f"{label} H5 producer")
    for key in ("producer_input_files", "future_input_files"):
        if h5 not in request.get(key, []):
            raise AssertionError(f"{label}: H5 omitted from {key}")
    for key in ("producer_input_sha256", "future_input_sha256"):
        mapping = request.get(key, {})
        if mapping.get(h5) != producer:
            raise AssertionError(f"{label}: producer H5 attestation mismatch in {key}")
    report_path = Path(request["conversion_report"])
    report = load(report_path)
    if report.get("conversion_status") != "completed" or report.get("frames") != 401 or report.get("particles") != 418104:
        raise AssertionError(f"{label}: conversion report dimensions/status mismatch")
    if report.get("output_sha256") != producer:
        raise AssertionError(f"{label}: producer digest differs from conversion report")
    receipt = completed_receipt(Path(request["typed_receipt"]), f"{label} typed receipt")
    if receipt.get("returncode") != 0:
        raise AssertionError(f"{label}: typed receipt return code")


def check_future(request: dict[str, Any], label: str) -> None:
    future = request.get("future_outputs")
    if not isinstance(future, dict) or any(value is not None for value in future.values()):
        raise AssertionError(f"{label}: future output is populated")
    for key, value in request.get("output_contract", {}).items():
        if key.endswith("sha256") or key.endswith("count") or key.endswith("counts"):
            if value is not None:
                raise AssertionError(f"{label}: output contract future value populated: {key}")


def main() -> int:
    manifest = load(MANIFEST)
    cases = manifest.get("cases", [])
    xmf_requests = sorted((HERE / "xmf/requests").glob("*-disabled.json"))
    render_requests = sorted((HERE / "render/requests").glob("*-disabled.json"))
    if len(cases) != len(xmf_requests) or len(cases) != len(render_requests):
        raise AssertionError("manifest/request count mismatch")
    if manifest.get("case_count") != len(cases) or manifest.get("deferred_typed_case_count") != 0:
        raise AssertionError("manifest count/deferred state mismatch")
    for path in xmf_requests + render_requests:
        request = load(path)
        label = path.name
        check_common(request, label)
        check_producer(request, label)
        check_future(request, label)
        if path.parent.name == "requests" and "render" in path.name:
            if request.get("xmf_case_sha256") is not None or request.get("xmf_manifest_sha256") is not None:
                raise AssertionError(f"{label}: future XMF hash populated")
        else:
            if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "audit":
                raise AssertionError(f"{label}: XMF task kind mismatch")
    selection = load(HERE / "evidence/typed-selection.json")
    if selection.get("completed_count") != len(cases) or selection.get("deferred_count") != 0:
        raise AssertionError("selection evidence mismatch")
    corrections = load(HERE / "evidence/upstream-digest-corrections.json")
    if corrections.get("correction_count") != 16:
        raise AssertionError("upstream digest correction count changed")
    result = {"schema": "ds02.f2.stage1.fresh108.source-contract-validation.v1", "cases": len(cases),
              "xmf_requests": len(xmf_requests), "render_requests": len(render_requests),
              "static_metadata_hashed": True, "scientific_payloads_opened": [],
              "h5_opened_or_hashed": False, "all_requests_disabled": True,
              "upstream_owner_digest_corrections_preserved": corrections["correction_count"], "status": "pass"}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
