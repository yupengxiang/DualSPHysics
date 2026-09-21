from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from scripts import core_f4_tallwall120_production_collector as collector
from scripts.core_f4_tallwall120_production_refresh import refresh_product_index


LAB = Path(__file__).resolve().parents[1]
DESIGN = LAB / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/production-design.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def _archive(root: Path, *, case_id: str, job_id: str, qualification: bool = False) -> None:
    archive_dir = root / job_id
    product = archive_dir / "product"
    product.mkdir(parents=True)
    audit = {
        "schema": "core.cfd.v1",
        "case_id": case_id,
        "structural": {
            "full_scan": True,
            "attrs": {"physical_case_id": case_id, "lineage_group_id": case_id},
        },
        "requested_horizon_reached": True,
        "hard_integrity_pass": True,
        "source_mass_gate_pass": True,
        "event_window_complete": True,
        "qualification_only": qualification,
        "qualification_claim": "none" if not qualification else "canary",
    }
    result = {"schema": "core.cfd.v1", "case_id": case_id,
              "hard_integrity_pass": True, "source_mass_gate_pass": True,
              "event_window_complete": True,
              "qualification_only": qualification,
              "qualification_claim": "none" if not qualification else "canary"}
    observations = {"schema": "core.observations.v1", "case_id": case_id}
    _json(product / "audit.json", audit)
    _json(product / "result.json", result)
    _json(product / "observations.json", observations)
    (product / "trajectory.h5").write_bytes(b"synthetic-trajectory")
    outputs = []
    for name in ("audit.json", "result.json", "observations.json", "trajectory.h5"):
        path = product / name
        outputs.append({"path": f"product/{name}", "bytes": path.stat().st_size,
                        "sha256": _sha(path)})
    execution = {"schema": "core.execution_receipt.v1", "job_id": job_id,
                 "execution_status": "succeeded", "outputs": outputs}
    _json(archive_dir / "execution-receipt.json", execution)
    _json(archive_dir / "archive.json", {
        "schema": "core.verified_archive.v1", "job_id": job_id,
        "execution_status": "succeeded", "outputs": outputs,
        "receipt_sha256": collector.canonical_sha256(execution),
        "qualification_claim": "canary" if qualification else "none",
    })


def test_refresh_indexes_production_and_excludes_qualification(tmp_path):
    design = json.loads(DESIGN.read_text())
    design_path = tmp_path / "production-design.json"
    _json(design_path, design)
    archive_root = tmp_path / "archives"
    case_id = design["cases"][0]["case_id"]
    _archive(archive_root, case_id=case_id, job_id="production-00")
    _archive(archive_root, case_id="qualification-cell-00",
             job_id="qualification-cell-00", qualification=True)

    report = refresh_product_index(design_path, [archive_root], tmp_path)

    assert report["registered_denominator"] == 32
    assert report["indexed_case_count"] == 1
    assert report["indexed_case_indices"] == [0]
    assert report["qualification_excluded_archive_count"] == 1
    assert report["read_only"] is True
    assert report["formal_release"] is False


def test_refresh_deduplicates_identical_archives_across_roots(tmp_path):
    design = json.loads(DESIGN.read_text())
    design_path = tmp_path / "production-design.json"
    _json(design_path, design)
    first = tmp_path / "archives-v1"
    second = tmp_path / "archives-v2"
    _archive(first, case_id=design["cases"][0]["case_id"], job_id="production-00")
    shutil.copytree(first, second)

    report = refresh_product_index(design_path, [first, second], tmp_path)

    assert report["indexed_case_count"] == 1
    assert report["duplicate_archive_count"] == 1
    assert report["duplicate_archives"][0]["artifact_hashes_equal"] is True
