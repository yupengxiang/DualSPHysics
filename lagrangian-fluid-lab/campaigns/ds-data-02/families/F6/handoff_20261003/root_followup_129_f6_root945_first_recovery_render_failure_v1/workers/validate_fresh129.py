#!/usr/bin/env python3
"""Validate fresh129 failure evidence without opening scientific payloads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
CASE = "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_record(item: dict) -> None:
    path = Path(item["path"])
    assert path.is_file(), path
    assert path.suffix.lower() not in FORBIDDEN, path
    assert digest(path) == item["sha256"], path


def walk_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)
    elif isinstance(value, str):
        yield value


def assert_no_payload_paths(value) -> None:
    for text in walk_strings(value):
        assert not any(text.lower().endswith(suffix) for suffix in FORBIDDEN), text


def main() -> None:
    index = load(META / "review-index.json")
    closure = load(META / "failure-closure.json")
    evidence = load(META / "evidence-files.json")

    assert index["schema"] == "ds02.f6.delegated-render-failure-review.v1"
    assert index["fresh_id"] == "fresh129"
    assert index["source_only"]
    assert not index["scientific_payload_read_or_hashed_by_review"]
    assert not index["global_credit_updated"]
    assert index["case_credit"] == 0
    assert not index["visual_review_started"]
    assert index["visual_decision"] == "render-failed-before-visual-review"
    assert len(index["cases"]) == 1
    row = index["cases"][0]
    assert row["case_id"] == CASE
    assert row["status"] == "render-failed-before-visual-review"
    assert row["decision"] == "needs-root-escalation"
    assert row["root945_controller_status"] == "failed"
    assert row["root945_controller_returncode"] == 1
    assert row["root945_receipt_status"] == "failed"
    assert row["root945_receipt_returncode"] == 1
    assert row["actual_png_count"] == 0
    assert row["actual_full_animation_report"] is False
    assert row["view_image_called"] is False

    assert closure["schema"] == "ds02.f6.fresh129.render-failure-closure.v1"
    assert closure["case_id"] == CASE
    assert closure["source_only"]
    assert not closure["scientific_payload_read_or_hashed_by_review"]
    assert closure["case_credit"] == 0
    visual = closure["visual_review"]
    assert visual["status"] == "render-failed-before-visual-review"
    assert visual["contact_sheets_viewed"] == 0
    assert visual["key_frames_viewed"] == 0
    assert not visual["png_hashes_recorded"]

    execution = closure["root945_execution"]
    receipt = execution["receipt"]
    assert receipt["status"] == "failed"
    assert receipt["returncode"] == 1
    assert receipt["published_output_root"] is None
    assert receipt["stage_removed_after_rejection"]
    assert execution["controller"]["requested"] == 37
    assert execution["controller"]["completed"] == 0
    assert execution["controller"]["held"] == 36

    cause = closure["root_cause"]
    assert cause["failure_class"] == "manifest_JSON_object_string_passed_as_CLI_path"
    assert cause["actual_argv_manifest_argument_index"] == 4
    assert cause["actual_argv_manifest_argument_length"] == 49002
    assert cause["worker"]["metadata_parser_line"] == 450
    assert cause["worker"]["execute_request_line"] == 833
    assert cause["root023"]["cli_manifest_type_line"] == 902
    assert cause["root023"]["manifest_read_line"] == 219
    assert cause["stat_only_reproduction"]["errno"] == 36
    assert not cause["stat_only_reproduction"]["science_payload_io"]

    scopes = closure["scope_separation"]
    assert scopes["must_not_equate_scopes"]
    assert scopes["physical_mass_kg"] == 128.0
    assert scopes["native_support_mass_kg"] == 256.0
    assert scopes["mass_rescaling"] is False
    assert scopes["floating_state0_is_required_for_angular_corroboration"]

    for obj in (index, closure, evidence):
        assert_no_payload_paths(obj)
    assert evidence["schema"] == "ds02.f6.fresh129.metadata-evidence-files.v1"
    for item in evidence["files"]:
        file_record(item)

    attempt_root = Path(execution["receipt"]["path"]).parent
    assert attempt_root.is_dir()
    output_files = [path for path in attempt_root.rglob("*") if path.is_file()]
    assert all(path.suffix.lower() not in {".png", ".gif", ".pvsm"} for path in output_files)
    assert not any(path.name == "paraview-full-animation-report.json" for path in output_files)

    print("fresh129 validation PASS: Root945 failed before visual output; no PNG review or case credit recorded")


if __name__ == "__main__":
    main()
