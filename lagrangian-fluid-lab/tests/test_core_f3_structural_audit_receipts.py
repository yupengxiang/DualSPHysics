"""Tests for the immutable F3 structural receipt set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_DIR = ROOT / "campaigns/core-v1/evidence/f3-structural-audits-v1"
ADAPTER = ROOT / "campaigns/core-v1/evidence/f3-structural-audit-adapter-v1.json"
GENERATOR = ROOT / "scripts/core_f3_structural_audit_receipts.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_32_receipts_are_hash_bound_and_cover_structural_axes() -> None:
    adapter = json.loads(ADAPTER.read_text(encoding="utf-8"))
    assert adapter["schema"] == "core.f3.structural_audit_adapter.v1"
    assert adapter["case_count"] == 32
    assert adapter["structural_pass"] is True
    assert adapter["generator_sha256"] == _sha256(GENERATOR)
    assert len(list(RECEIPT_DIR.glob("*.json"))) == 32

    for reference in adapter["cases"]:
        receipt_path = ROOT / reference["path"]
        assert receipt_path.is_file()
        assert _sha256(receipt_path) == reference["sha256"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["schema"] == "core.f3.structural_audit_receipt.v1"
        assert receipt["manifest_binding"]["sha256"] == adapter["manifest_sha256"]
        assert receipt["structural_pass"] is True
        assert receipt["formal_release"] is False
        assert receipt["qualification_claim"].startswith("none;")
        assert set(receipt["checks"]) == {
            "particle_axis", "finite_values", "lifecycle", "units", "wall_opening",
        }
        assert all(check["structural_pass"] for check in receipt["checks"].values())
        assert receipt["checks"]["wall_opening"]["geometry_binding"]["open_faces"] == ["top"]


def test_receipts_preserve_source_audit_and_trajectory_hashes() -> None:
    adapter = json.loads(ADAPTER.read_text(encoding="utf-8"))
    for reference in adapter["cases"]:
        receipt = json.loads((ROOT / reference["path"]).read_text(encoding="utf-8"))
        evidence = receipt["source_evidence"]
        assert evidence["audit"]["sha256"] == _sha256(ROOT / evidence["audit"]["path"])
        assert evidence["prepared"]["sha256"] == _sha256(ROOT / evidence["prepared"]["path"])
        assert evidence["trajectory"]["opened_by_generator"] is False

