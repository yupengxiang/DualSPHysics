#!/usr/bin/env python3
"""Validate fresh189 personal PNG review metadata without hashing PNGs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
DECISION = PACKAGE / "metadata" / "actual1159-personal-visual-decision.json"
EVIDENCE = PACKAGE / "metadata" / "png-evidence" / "actual1159.json"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
HASHABLE = {".json", ".xml", ".xmf", ".py", ".md"}


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if p.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"scientific payload read attempted: {p}")
    if p.suffix.lower() != ".json":
        raise AssertionError(f"expected JSON: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def metadata_sha(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() not in HASHABLE:
        raise AssertionError(f"non-metadata hash attempted: {p}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_receipt(ref: dict, label: str) -> dict:
    p = Path(ref["path"])
    data = read_json(p)
    assert data.get("status") == "completed", f"{label} not completed"
    assert data.get("returncode") == 0, f"{label} returncode"
    assert metadata_sha(p) == ref["sha256"], f"{label} SHA mismatch"
    return data


def check_image(item: dict, role: str) -> None:
    p = Path(item["path"])
    assert p.suffix.lower() == ".png"
    assert p.exists(), f"{role} missing"
    assert p.stat().st_size == item["bytes"], f"{role} stat changed"
    assert item["stat_checked"] is True
    assert item["personally_viewed_with_view_image"] is True
    assert item["reviewer_hashed_or_read_bytes_directly"] is False
    assert len(item["producer_declared_sha256"]) == 64
    assert item["sha256_source"] == "immutable render-publish-receipt.json"


def main() -> int:
    decision = read_json(DECISION)
    evidence = read_json(EVIDENCE)
    assert decision["fresh_id"] == "fresh189"
    assert decision["assigned_worktree_family"] == "F3"
    assert decision["actual_case_family"] == "F5"
    assert decision["configured_model"] == "gpt-5.6-luna/max"
    assert decision["model_substitution"] is False
    assert decision["visual_status"] == "visual-approved-by-delegated-agent"
    assert decision["case_credit"] == 0
    assert decision["q_n"] == 0 and decision["q_e"] == 0
    review = decision["personal_review"]
    assert review["method"] == "view_image"
    assert review["review_completed_at_utc"] == "2026-10-07T10:33:47.174510175+00:00"
    assert review["contact_sheets_viewed"] == 34
    assert review["key_frames_viewed"] == 9
    assert review["all_required_published_pngs_viewed"] is True
    assert review["png_bytes_hashed_by_reviewer"] is False

    assert len(evidence["contacts"]) == 34
    assert len(evidence["keys"]) == 9
    assert evidence["all_paths_stat_checked"] is True
    assert evidence["all_required_images_personally_viewed"] is True
    assert evidence["reviewer_did_not_hash_pngs"] is True
    for item in evidence["contacts"]:
        check_image(item, item["role"])
    for item in evidence["keys"]:
        check_image(item, item["role"])

    actual = decision["actual_provenance"]
    render = actual["render_receipt"]
    report = actual["render_report"]
    publish = actual["publish_receipt"]
    render_data = check_receipt(render, "render receipt")
    report_data = read_json(report["path"])
    assert metadata_sha(report["path"]) == report["sha256"]
    assert report_data["frames"] == 801
    assert report_data["all_frames_rendered"] is True
    assert report_data["actual_times_preserved_exactly"] is True
    assert len(report_data["outputs"]["contact_sheets"]) == 34
    publish_data = read_json(publish["path"])
    assert metadata_sha(publish["path"]) == publish["sha256"]
    assert publish_data["status"] == "published_after_atomic_rename"
    assert len(publish_data["files_excluding_receipt"]) == 838
    assert publish_data["published_bytes_excluding_receipt"] == 79190210
    assert render_data["status"] == "completed"

    qi = actual["qi_proof"]
    qi_path = Path(qi["path"])
    assert qi_path.exists()
    assert metadata_sha(qi_path) == qi["sha256"]
    roles = decision["scope_roles"]
    assert roles["roles_are_distinct"] is True
    assert roles["native_canonical_physical_condition_sha256"] == "873b4e8ab9cc1fe351876d13063f1eb42fb722302f2f77b7684a6bd44ee1fbee"
    assert roles["typed_legacy_owner_scope_sha256"] == "06e5dafcbb4dd8f471b6071dbff6a51e97111a2c13fe3108f5a5169ed5c8b034"
    assert roles["bed_source_definition_sha256"] == "426b2eb0d07213735d4754efa99fb02c8a5d94a2bc66b4bfbb45767f1c933047"
    assert decision["read_boundary"]["scientific_payload_read_or_hashed"] is False
    assert decision["read_boundary"]["fresh188_modified"] is False

    for path in PACKAGE.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in FORBIDDEN, f"payload in package: {path}"
    print("fresh189 personal visual review metadata PASS")
    print("viewed=34 contact sheets + 9 key frames")
    print("visual_status=visual-approved-by-delegated-agent")
    print("case_credit=0; q_n=0; q_e=0; scientific_payload_io=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
