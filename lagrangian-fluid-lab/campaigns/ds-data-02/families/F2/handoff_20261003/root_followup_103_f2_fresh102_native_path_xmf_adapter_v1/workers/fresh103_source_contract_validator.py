#!/usr/bin/env python3
"""Validate fresh103 without reading scientific payloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


RAW = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC = {".json", ".xml", ".py", ".md", ".txt"}
LOGICAL_GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
COUNT_KEYS = ("fixed", "moving", "floating", "fluid")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def sha(path: Path) -> str:
    assert path.suffix.lower() in STATIC, f"scientific/non-static hash refused: {path}"
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def closure(doc: dict[str, Any], label: str, recorded_raw: dict[str, str]) -> int:
    files = doc.get("input_files", [])
    hashes = doc.get("input_sha256", {})
    assert set(files) == set(hashes), f"{label}: input closure mismatch"
    checked = 0
    for raw_path, expected in hashes.items():
        path = Path(raw_path)
        if path.suffix.lower() in RAW or path.suffix.lower() not in STATIC:
            assert recorded_raw.get(str(path.resolve())) == expected, f"{label}: unverified raw/binary digest {path}"
            continue
        assert path.is_file() and sha(path) == expected, f"{label}: changed metadata {path}"
        checked += 1
    assert all(value is None for value in (doc.get("future_input_sha256") or {}).values()), f"{label}: future hash filled"
    return checked


def guard_check(doc: dict[str, Any], label: str) -> None:
    assert doc.get("strict_guard_digest") == LOGICAL_GUARD, label
    assert doc.get("strict_dispatch_file_sha256") == STRICT_SHA, label
    guard = doc.get("strict_guard") or {}
    assert guard.get("strict_dispatch", {}).get("sha256") == STRICT_SHA, label
    assert guard.get("strict_guard_digest") == LOGICAL_GUARD, label
    assert doc.get("disabled") is True and doc.get("execution_allowed") is False and doc.get("launch_allowed") is False, label
    assert doc.get("future_hashes_null") is True and doc.get("source_only") is True, label
    assert doc.get("expected_dimension") == 3, label
    if label.endswith(":qa"):
        assert doc.get("expected_native_frames") is None and doc.get("expected_particles") == 418104, label
    else:
        assert doc.get("expected_native_frames") == 401 and doc.get("expected_particles") is None, label


def binding_check(path: Path, label: str) -> int:
    value = load(path)
    assert value.get("canonical_physical_binding_sha256") is None, label
    assert value.get("canonical_grant") is False, label
    assert value.get("producer_scope_schema") == "legacy-owner-scope.v0", label
    assert value.get("expected_dimension") == 3 and value.get("expected_native_frames") == 401, label
    assert value.get("expected_particles") is None, label
    assert value.get("xmf_shape_contract", {"dynamic_vector_dimensions": "{actual_particles} 3"}).get("dynamic_vector_dimensions", "{actual_particles} 3") == "{actual_particles} 3" if "xmf_shape_contract" in value else True
    assert all(item is None for item in (value.get("future_outputs") or {}).values()), label
    checked = 0
    for raw_path, expected in (value.get("bound_metadata_sha256") or {}).items():
        source = Path(raw_path)
        assert source.suffix.lower() not in RAW and source.is_file() and sha(source) == expected, f"{label}: changed bound metadata {source}"
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = load(args.manifest)
    assert manifest.get("schema") == "ds02.f2.stage1.fresh103.native-path-xmf-adapter-manifest.v1"
    assert manifest.get("fresh_id") == "fresh103" and manifest.get("family_id") == "F2" and manifest.get("case_count") == 16
    assert manifest.get("all_requests_disabled") and manifest.get("future_hashes_null")
    assert manifest.get("prepared_gencase_particle_total") == 418104
    assert manifest.get("prepared_gencase_counts", manifest.get("prepared_gencase_particle_counts")) == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114}
    assert manifest.get("logical_strict_guard_digest") == LOGICAL_GUARD and manifest.get("actual_strict_dispatch_file_sha256") == STRICT_SHA
    root = args.manifest.resolve().parent
    for path in root.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in RAW, f"raw payload in fresh103 package: {path}"
    checked = 0
    requests = 0
    qa_failed_or_pending = 0
    for case in manifest["cases"]:
        assert case["prepared_gencase_particle_count"] == 418104
        assert case["prepared_gencase_particle_counts"] == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114}
        evidence = load(Path(case["gencase_evidence"]["path"]))
        assert evidence["source_only"] and evidence["execution_allowed"] is False
        assert evidence["contract_checks"]["root353_solver_dimension_three"] is True
        assert evidence["raw_gencase_receipt"]["raw_receipt_immutable"] is True
        assert evidence["prepared_input_report"]["actual_total_particles"] == 418104
        assert evidence["prepared_input_report"]["bi4_read_or_rehashed_here"] is False
        raw_recorded: dict[str, str] = {}
        for request_key in ("initial_qa_adapter_request", "native_request", "xmf_request", "render_request"):
            template = load(Path(case[request_key]["path"]))
            for p, h in template.get("input_sha256", {}).items():
                if Path(p).suffix.lower() in RAW or Path(p).suffix.lower() not in STATIC:
                    raw_recorded[str(Path(p).resolve())] = h
        for key, label in [("initial_qa_adapter_request", "qa"), ("native_request", "native"), ("xmf_request", "xmf"), ("render_request", "render")]:
            request = load(Path(case[key]["path"]))
            guard_check(request, f"{case['case_id']}:{label}")
            checked += closure(request, f"{case['case_id']}:{label}", raw_recorded)
            requests += 1
        qa = load(Path(case["initial_qa_adapter_request"]["path"]))
        assert qa["gencase_receipt_semantics"].startswith("raw immutable")
        assert qa["semantic_receipt"]["path"] is None and qa["semantic_receipt"]["sha256"] is None
        assert qa["prepared_report_observed_counts"]["fluid"] == 21114
        native = load(Path(case["native_request"]["path"]))
        assert native["depends_on_attempts"][1] == qa["attempt_id"]
        assert native["gencase_semantic_dimension_source"].startswith("fresh102")
        for key in ("actual_native_receipt", "actual_typed_receipt", "actual_h5_sha256", "actual_xmf_sha256", "actual_render_sha256"):
            assert case[key] is None
        checked += binding_check(Path(case["xmf_binding"]["path"]), f"{case['case_id']}:xmf")
        checked += binding_check(Path(case["render_binding"]["path"]), f"{case['case_id']}:render")
        render = load(Path(case["render_binding"]["path"]))
        assert render["camera_policy"]["fixed_camera_override"] is False
        assert render["camera_policy"]["camera_bounds_in_manifest"] is False
        if case.get("observed_prior_qa") is not None:
            qa_failed_or_pending += 1
            assert case["observed_prior_qa"].get("returncode_semantics") == "historical fresh102 QA output; not reused as pass"
    print(json.dumps({"status": "pass", "cases": 16, "requests": requests, "metadata_hashes_checked": checked, "historical_qa_reports": qa_failed_or_pending, "prepared_total": 418104, "dimension": 3, "strict_dispatch_file_sha256": STRICT_SHA, "scientific_payloads_read": []}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
