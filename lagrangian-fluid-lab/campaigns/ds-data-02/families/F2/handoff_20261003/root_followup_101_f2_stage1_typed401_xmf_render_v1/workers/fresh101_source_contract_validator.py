#!/usr/bin/env python3
"""Validate fresh101 metadata closure without opening scientific payloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


RAW = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC = {".json", ".xml", ".py", ".md", ".txt"}
GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW or path.suffix.lower() not in STATIC:
        raise AssertionError(f"scientific/non-static path in metadata closure: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def closure(doc: dict, label: str) -> int:
    files = doc.get("input_files", [])
    hashes = doc.get("input_sha256", {})
    assert set(files) == set(hashes), f"{label}: input closure mismatch"
    checked = 0
    for raw_path, expected in hashes.items():
        path = Path(raw_path)
        assert path.suffix.lower() not in RAW, f"{label}: raw static input {path}"
        assert path.is_file(), f"{label}: missing {path}"
        assert sha(path) == expected, f"{label}: changed {path}"
        checked += 1
    future = doc.get("future_input_sha256", {})
    assert all(value is None for value in future.values()), f"{label}: future hash was filled"
    return checked


def binding_check(path: Path, label: str) -> int:
    binding = load(path)
    assert binding["producer_scope_schema"] == "legacy-owner-scope.v0", label
    assert binding["canonical_physical_binding_sha256"] is None, label
    assert binding["future_hashes_null"] and binding["source_only"], label
    assert binding["expected_native_frames"] == 401 and binding["expected_dimension"] == 3, label
    assert binding["expected_particles"] is None, label
    assert all(value is None for value in binding["future_outputs"].values()), label
    checked = 0
    for raw_path, expected in binding["bound_metadata_sha256"].items():
        source = Path(raw_path)
        assert source.suffix.lower() not in RAW, f"{label}: raw binding input {source}"
        assert source.is_file() and sha(source) == expected, f"{label}: changed {source}"
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = load(args.manifest)
    assert manifest["fresh_id"] == "fresh101"
    assert manifest["family_id"] == "F2" and manifest["case_count"] == 16
    assert manifest["all_requests_disabled"] and manifest["future_hashes_null"]
    root = args.manifest.resolve().parent
    for path in root.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in RAW, f"raw payload in source package: {path}"
    request_count = 0
    checked = 0
    for case in manifest["cases"]:
        for key in ("xmf_request", "render_request"):
            request = load(Path(case[key]["path"]))
            assert request["disabled"] and not request["execution_allowed"] and not request["launch_allowed"]
            assert request["future_hashes_null"] and request["strict_guard_digest"] == GUARD
            for required in ("runtime_v2", "strict_dispatch", "root142_inventory_policy", "resource_window"):
                assert required in request["strict_guard"], f"{case['case_id']}: missing guard {required}"
            checked += closure(request, f"{case['case_id']}:{key}")
            request_count += 1
        checked += binding_check(Path(case["xmf_binding"]["path"]), f"{case['case_id']}:xmf-binding")
        checked += binding_check(Path(case["render_binding"]["path"]), f"{case['case_id']}:render-binding")
        render = load(Path(case["render_binding"]["path"]))
        assert not render["camera_policy"]["fixed_camera_override"]
        assert not render["camera_policy"]["camera_bounds_in_manifest"]
    print(json.dumps({"status": "pass", "cases": 16, "requests": request_count,
                      "metadata_hashes_checked": checked, "scientific_payloads_read": []}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
