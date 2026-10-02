#!/usr/bin/env python3
"""Create an additive provenance sidecar for the CENTER coarse hash mismatch.

The consumed CENTER coarse labels contain an old owner declaration
(``9e149...``) while the actual converted H5 and the generated RV4 source
bind to the GEM physical condition (``45c579...``).  This script reads both
lineages, records the old definition and the actual source definition, and
writes a sidecar.  It never edits the consumed H5, labels, report, owner
metadata, or solver inputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
CASE_ID = "F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001"
CASE_ROOT = F2_DATA_ROOT / CASE_ID
OBSERVATION = next(CASE_ROOT.glob("labels-*/f2-v6-observations.json"))
LABELS = next(CASE_ROOT.glob("labels-*/f2-v6-labels.h5"))
OWNER = F2_ROOT / "handoff_20261002/postsolver/owner_metadata/F2H10V2_CENTER_V1_COARSE.generator.v2.metadata.json"
CONVERSION_REPORT = next(CASE_ROOT.glob("conversion-*/conversion-report.json"))
MEDIUM_REPORT = F2_DATA_ROOT / "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001" / "conversion-f2h10v2_center_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json"
OUTPUT = F2_DATA_ROOT / "F2_RV4EQ_COARSE_MEDIUM_REVIEW_20261002/center-coarse-physical-binding-reconciliation.json"
SCHEMA = "ds-data-02.f2.center-coarse-physical-binding-reconciliation.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    path = require(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(output: Path = OUTPUT) -> dict[str, Any]:
    observation = load(OBSERVATION, "CENTER coarse v6 observation")
    owner = load(OWNER, "CENTER coarse consumed owner metadata")
    report = load(CONVERSION_REPORT, "CENTER coarse conversion report")
    medium = load(MEDIUM_REPORT, "CENTER medium conversion report")
    physical = report["hash_scopes"]["physical_condition"]
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    medium_hash = str(medium["hash_scopes"]["physical_condition_sha256"])
    old_source_def = require(Path(str(owner["source_definition"]["path"])), "old CENTER source definition")
    old_source_geometry = require(Path(str(owner["source_geometry_metadata"]["path"])), "old CENTER source geometry metadata")
    old_geometry = load(old_source_geometry, "old CENTER source geometry metadata")["geometry"]
    current_source = report["source_provenance"]["generated_xml"]
    current_xml = require(Path(str(current_source["path"])), "actual CENTER coarse generated XML")
    old_volume = float(old_geometry["fluid_volume_m3"])
    current_fluid = physical["geometry"]["fluid"]
    current_volume = float(current_fluid["size_m"][0]) * float(current_fluid["size_m"][1]) * float(current_fluid["size_m"][2])
    declared_hash = str(observation["physical_binding"]["physical_condition_hash_declared"])
    source_h5_hash = str(observation["physical_binding"]["source_h5_physical_condition_sha256"])
    checks = {
        "original_label_declared_hash_mismatch": declared_hash != source_h5_hash,
        "source_h5_hash_matches_conversion_report": source_h5_hash == physical_hash,
        "medium_hash_matches_coarse_authoritative_hash": medium_hash == physical_hash,
        "actual_generated_xml_matches_conversion_provenance": sha256(current_xml) == str(current_source["sha256"]),
        "old_source_definition_is_distinct_from_actual_generated_xml": sha256(old_source_def) != sha256(current_xml),
        "old_source_geometry_volume_differs_from_authoritative_fluid_volume": abs(old_volume - current_volume) > 1e-12,
        "authoritative_volume_matches_frozen_continuous_volume": abs(current_volume - 0.024576) <= 1e-15,
    }
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": CASE_ID,
        "scope_id": observation.get("quality_contract_binding", {}).get("scope_id", "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2"),
        "original_consumed_artifacts": {
            "observation_report": {"path": str(OBSERVATION), "sha256": sha256(OBSERVATION)},
            "labels_h5": {"path": str(LABELS), "sha256": sha256(LABELS)},
            "owner_metadata": {"path": str(OWNER), "sha256": sha256(OWNER)},
            "conversion_report": {"path": str(CONVERSION_REPORT), "sha256": sha256(CONVERSION_REPORT)},
        },
        "mismatch": {
            "label_report_declared_physical_condition_sha256": declared_hash,
            "label_h5_source_physical_condition_sha256": source_h5_hash,
            "authoritative_conversion_physical_condition_sha256": physical_hash,
            "meaning": "the v6 label report copied a stale owner declaration from the pre-GEM production definition; the actual H5/conversion source is the RV4 GEM mother",
        },
        "stale_declared_lineage": {
            "owner_source_definition": {"path": str(old_source_def), "sha256": sha256(old_source_def)},
            "owner_source_geometry_metadata": {"path": str(old_source_geometry), "sha256": sha256(old_source_geometry)},
            "old_fluid_volume_m3": old_volume,
            "old_fluid_height_m": old_geometry.get("fluid_height_m"),
            "old_physical_condition_hash_declared": str(owner.get("physical_condition_hash_declared")),
        },
        "authoritative_source_lineage": {
            "conversion_report_physical_condition": physical,
            "conversion_report_physical_condition_sha256": physical_hash,
            "generated_xml": {"path": str(current_xml), "sha256": sha256(current_xml)},
            "gencase_receipt": report["source_provenance"]["gencase_receipt"],
            "geometry_reference_sha256": report["source_provenance"]["geometry_reference_sha256"],
            "control_reference_sha256": report["source_provenance"]["control_reference_sha256"],
            "motion_control_sha256": observation["physical_binding"]["motion_control_sha256"],
            "fluid_volume_m3": current_volume,
            "continuous_mass_kg": 24.575999999999997,
            "mass_authority": "generated XML decimal MassFluid and native BI4 header; H5 float32/PartVTK display remains adapter evidence",
        },
        "cross_resolution_corrobation": {
            "center_medium_conversion_report": {"path": str(MEDIUM_REPORT), "sha256": sha256(MEDIUM_REPORT)},
            "center_medium_physical_condition_sha256": medium_hash,
            "same_authoritative_physical_condition": medium_hash == physical_hash,
        },
        "checks": checks,
        "resolution": {
            "status": "source_provenance_reconciled_in_additive_sidecar",
            "original_report_rewritten": False,
            "original_labels_rewritten": False,
            "original_owner_metadata_rewritten": False,
            "physical_pairing_rule": "use authoritative source_h5/conversion physical hash 45c579... only through this sidecar; the stale declared hash alone is ineligible for pairing",
            "qi_status": "pending independent review",
            "q_n_status": "pending; coarse/medium macro differences exceed budget",
            "production_status": "not_evaluated",
        },
    }
    result["all_reconciliation_checks_pass"] = all(bool(value) for value in checks.values())
    write(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
