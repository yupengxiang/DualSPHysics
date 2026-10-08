#!/usr/bin/env python3
"""Validate the already completed F2-S1 native source closure.

This is a metadata and small-output consumer for the historical
``RX056_RY014_FILL080_ROT090`` case.  The official PartVTKOut invocation was
already run by the guarded 118-case configuration-closure attempt.  The
consumer only reads JSON/XML/text/CSV evidence and the two decoder receipts;
it never opens HDF5, ``PartOut_000.obi4``, or any ``Part_*.bi4`` file and it
does not launch a decoder or solver.

The old F2-S1 reconciliation was deliberately retained.  The closure record
below proves that the fresh guarded decoder output has the same three rows as
the preserved old CSV while binding the output to CURRENT336, the exact
GenCase/solver/XML/Run.out/RunPARTs parent, DsphConfig.xml, and the official
binary.  Physical fate, legal flux, converter implementation, and dynamics
remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = WORKTREE_ROOT / "lagrangian-fluid-lab"
CURRENT = LAB_ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
CONFIG_MANIFEST = LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/native-runtime-config-closure-v1/"
    "native-runtime-config-closure-manifest.json"
)
CONFIG_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_NATIVE_RUNTIME_CONFIG_CLOSURE_118_V1/"
    "native-runtime-config-closure-118-v1-primary-001/"
    "native-runtime-config-closure.json"
)
CONFIG_RECEIPT = CONFIG_REPORT.with_name("execution-receipt.json")

PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
RUNTIME_CASE_ALIAS = "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
CASE_KEY = "F2/scan-F2-S1-001"
EXPECTED_CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_CONFIG_MANIFEST_SHA256 = "14aaabaa91fffcbdc4eec8ae788d2513ec4d63fd54f1383741fefbb337438566"
EXPECTED_CONFIG_REPORT_SHA256 = "8cafefd00553f299d4c7ac694aea9718b11c238a2a3946cbf31f55390549dea5"
EXPECTED_CONFIG_RECEIPT_SHA256 = "2505e28e8b220bc7db7ec67dae636dc5d92de042d75f194752092d366139d6af"

OLD_RECONCILIATION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_S1_EXCLUSIONS/join-F2-S1-001/native-reconciliation.json"
)
OLD_RECONCILIATION_RECEIPT = OLD_RECONCILIATION.with_name("execution-receipt.json")
OLD_SCAN = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_S1_SCIENCE/scan-F2-S1-001/scientific-scan.json"
)
OLD_SCAN_RECEIPT = OLD_SCAN.with_name("execution-receipt.json")
OLD_DECODER_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_S1_EXCLUSIONS/decode-F2-S1-002/execution-receipt.json"
)
OLD_CSV = OLD_DECODER_RECEIPT.with_name("PartOut.csv")

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OFFICIAL_TOOL = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
)
DSPH_CONFIG = OFFICIAL_TOOL.with_name("DsphConfig.xml")


class ClosureError(RuntimeError):
    """Raised when the immutable closure evidence does not bind exactly."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ClosureError(f"{label} is missing: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosureError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ClosureError(f"{label} is not an object: {path}")
    return value


def checked_hash(path: Path, expected: str, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    observed = sha256(path)
    if observed != expected:
        raise ClosureError(f"{label} digest differs: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": observed}


def declared(path: Path, expected: str, expected_bytes: int, label: str) -> dict[str, Any]:
    """Bind a guarded input without reading it in this consumer.

    ``PartOut_000.obi4`` and the official binary/config are already covered by
    the completed v4 receipt.  This function deliberately uses stat plus the
    receipt-attested digest so this forward validator cannot accidentally
    reopen a BI4 input.
    """
    path = require_file(path, label)
    size = path.stat().st_size
    if size != expected_bytes:
        raise ClosureError(f"{label} byte count differs: {path}: {size} != {expected_bytes}")
    return {"path": str(path), "bytes": size, "sha256": expected, "digest_source": "completed_guard_receipt"}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise ClosureError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def case_from_current(current: dict[str, Any]) -> dict[str, Any]:
    cases = current.get("cases")
    if not isinstance(cases, list):
        raise ClosureError("CURRENT336 cases is not a list")
    matches = [case for case in cases if isinstance(case, dict) and case.get("physical_case_id") == PHYSICAL_CASE_ID]
    if len(matches) != 1:
        raise ClosureError(f"CURRENT336 has {len(matches)} matches for {PHYSICAL_CASE_ID}")
    case = matches[0]
    if case.get("runtime_case_alias") != RUNTIME_CASE_ALIAS or case.get("family_id") != "F2":
        raise ClosureError("CURRENT336 identity alias/family mismatch")
    if case.get("frames") != 401 or case.get("particles") != 418104:
        raise ClosureError("CURRENT336 frame/particle identity mismatch")
    return case


def rows(path: Path, label: str) -> list[dict[str, str]]:
    path = require_file(path, label)
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def validate_csv(path: Path, label: str) -> dict[str, Any]:
    parsed = rows(path, label)
    if len(parsed) != 3:
        raise ClosureError(f"{label} row count is not three")
    expected = [("403829", "154", "1"), ("397194", "207", "1"), ("404024", "207", "1")]
    observed = [(str(row.get("Idp", "")).strip(), str(row.get("PartOut", "")).strip(), str(row.get("Motive", "")).strip()) for row in parsed]
    if observed != expected:
        raise ClosureError(f"{label} identity rows differ: {observed}")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path), "row_count": len(parsed), "ids": [int(item[0]) for item in observed]}


def build(output: Path) -> dict[str, Any]:
    current_path = require_file(CURRENT, "CURRENT336")
    current_sha = sha256(current_path)
    if current_sha != EXPECTED_CURRENT_SHA256:
        raise ClosureError("CURRENT336 digest differs from the exact audited CURRENT")
    current = read_json(current_path, "CURRENT336")
    current_case = case_from_current(current)

    config_manifest_path = require_file(CONFIG_MANIFEST, "config-closure manifest")
    config_manifest_sha = sha256(config_manifest_path)
    if config_manifest_sha != EXPECTED_CONFIG_MANIFEST_SHA256:
        raise ClosureError("config-closure manifest digest differs")
    config_manifest = read_json(config_manifest_path, "config-closure manifest")
    if config_manifest.get("schema") != "ds02.stage2.native-runtime-config-closure-manifest.v1":
        raise ClosureError("unexpected config-closure manifest schema")
    case_entries = [case for case in config_manifest.get("cases", []) if case.get("physical_case_id") == PHYSICAL_CASE_ID]
    if len(case_entries) != 1 or case_entries[0].get("source_mode") != "legacy_f2_s1_explicit_current_binding":
        raise ClosureError("config-closure manifest does not contain the exact F2-S1 binding")
    manifest_case = case_entries[0]

    config_report_path = require_file(CONFIG_REPORT, "config-closure report")
    config_report_sha = sha256(config_report_path)
    if config_report_sha != EXPECTED_CONFIG_REPORT_SHA256:
        raise ClosureError("config-closure report digest differs")
    config_report = read_json(config_report_path, "config-closure report")
    if config_report.get("schema") != "ds02.stage2.native-runtime-config-closure.v1" or config_report.get("status") != "completed":
        raise ClosureError("config-closure report is not completed")
    report_cases = [case for case in config_report.get("cases", []) if case.get("physical_case_id") == PHYSICAL_CASE_ID]
    if len(report_cases) != 1:
        raise ClosureError("config-closure report does not contain exact F2-S1 case")
    report_case = report_cases[0]
    comparison = report_case.get("comparison", {})
    if report_case.get("status") != "EXACT_SEMANTIC_MATCH" or comparison.get("row_count") != 3 or comparison.get("status") != "EXACT_SEMANTIC_MATCH":
        raise ClosureError("fresh decoder does not exactly match preserved native CSV")
    if any(float(value) != 0.0 for value in comparison.get("max_abs_difference", {}).values()):
        raise ClosureError("fresh decoder has nonzero semantic difference")
    if report_case.get("physical_fate") != "UNKNOWN" or report_case.get("dynamical_impact") != "UNKNOWN":
        raise ClosureError("physical claim boundary was changed")

    config_receipt_path = require_file(CONFIG_RECEIPT, "config-closure receipt")
    config_receipt_sha = sha256(config_receipt_path)
    if config_receipt_sha != EXPECTED_CONFIG_RECEIPT_SHA256:
        raise ClosureError("config-closure receipt digest differs")
    config_receipt = read_json(config_receipt_path, "config-closure receipt")
    if config_receipt.get("status") != "completed" or config_receipt.get("returncode") != 0:
        raise ClosureError("config-closure execution receipt is not successful")

    source = manifest_case.get("sources", {})
    required_source_names = ("gencase_receipt", "generated_xml", "solver_receipt", "runout", "runparts", "raw_partout")
    if any(name not in source for name in required_source_names):
        raise ClosureError("config-closure manifest lacks a required exact source binding")
    source_bindings: dict[str, Any] = {}
    for name in required_source_names:
        item = source[name]
        path = Path(item["path"])
        if name == "raw_partout":
            source_bindings[name] = declared(path, item["sha256"], int(item["bytes"]), f"raw {name}")
        else:
            source_bindings[name] = checked_hash(path, item["sha256"], f"source {name}")

    official = config_manifest.get("official_runtime", {})
    for name in ("partvtkout", "dsph_config"):
        item = official.get(name)
        if not isinstance(item, dict):
            raise ClosureError(f"missing official runtime binding: {name}")
        expected_path = OFFICIAL_TOOL if name == "partvtkout" else DSPH_CONFIG
        source_bindings[name] = declared(expected_path, item["sha256"], int(item["bytes"]), f"official {name}")

    old_receipt = read_json(OLD_DECODER_RECEIPT, "old PartVTKOut receipt")
    if old_receipt.get("status") != "completed" or old_receipt.get("returncode") != 0:
        raise ClosureError("old PartVTKOut receipt is not completed")
    old_command = old_receipt.get("command", [])
    if "-threads:1" in old_command:
        raise ClosureError("old PartVTKOut receipt contains rejected -threads:1")
    old_raw = next((str(value) for value in old_command if str(value).endswith("/solver_output/data")), None)
    if old_raw != str(Path(source["raw_partout"]["path"]).parent):
        raise ClosureError("old decoder raw parent differs from exact solver output parent")
    old_csv = validate_csv(OLD_CSV, "preserved old PartOut.csv")
    fresh_csv = validate_csv(Path(report_case["fresh_decoder"]["partout_csv"]["path"]), "fresh guarded PartOut.csv")
    if old_csv["sha256"] != fresh_csv["sha256"] or old_csv["sha256"] != report_case["preserved_decoder"]["partout_csv"]["sha256"]:
        raise ClosureError("fresh and preserved PartVTKOut CSV hashes differ")

    old_recon = read_json(OLD_RECONCILIATION, "old native reconciliation")
    if old_recon.get("schema") != "ds02.stage2.native-exclusion-reconciliation.v1" or old_recon.get("joined_count") != 3:
        raise ClosureError("old three-ID reconciliation is not the expected schema/count")
    if old_recon.get("native_motive_counts") != {"position": 3, "density": 0, "movement": 0}:
        raise ClosureError("old native motive counts differ")
    if not str(old_recon.get("physical_fate", "")).startswith("UNKNOWN") or not str(old_recon.get("dynamical_impact", "")).startswith("NOT_ASSESSED"):
        raise ClosureError("old reconciliation physical claim boundary changed")
    old_recon_receipt = read_json(OLD_RECONCILIATION_RECEIPT, "old native reconciliation receipt")
    old_scan = read_json(OLD_SCAN, "old scientific scan")
    old_scan_receipt = read_json(OLD_SCAN_RECEIPT, "old scientific scan receipt")

    # Bind the exact CURRENT review manifest and conversion metadata without
    # reopening trajectory.h5.  These files are small JSON/XML metadata.
    current_manifest_path = Path(current_case["manifest"]["path"])
    current_manifest_binding = checked_hash(current_manifest_path, current_case["manifest"]["recomputed_sha256"], "CURRENT case manifest")
    conversion_path = Path(current_case["conversion_report"]["path"])
    conversion_binding = checked_hash(conversion_path, current_case["conversion_report"]["recomputed_sha256"], "CURRENT conversion report")
    xmf_binding = checked_hash(Path(current_case["xmf"]["path"]), current_case["xmf"]["recomputed_sha256"], "CURRENT XMF")

    payload = {
        "schema": "ds02.stage2.f2-s1-native-source-closure.v1",
        "status": "EXACT_NATIVE_SOURCE_CLOSED_WITH_PHYSICAL_FATE_UNKNOWN",
        "case_key": CASE_KEY,
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "runtime_case_alias": RUNTIME_CASE_ALIAS,
        "closure_scope": {
            "identity": "CURRENT336 exact physical/runtime identity, 401 frames, 418104 particles",
            "source": "GenCase receipt, generated XML, solver receipt, Run.out, RunPARTs, raw PartOut parent, official PartVTKOut and DsphConfig are source-bound by completed config-closure receipt",
            "decoder": "fresh official PartVTKOut output exactly matches preserved old three-row CSV",
            "old_partial_reconciliation": "retained immutable; this record adds closure evidence and does not rewrite it",
        },
        "current": {"path": str(current_path), "bytes": current_path.stat().st_size, "sha256": current_sha, "case": {"frames": current_case["frames"], "particles": current_case["particles"], "actual_time_window_s": current_case["actual_time_window_s"]}},
        "source_bindings": {
            **source_bindings,
            "current_review_manifest": current_manifest_binding,
            "current_conversion_report": conversion_binding,
            "current_xmf": xmf_binding,
            "old_native_reconciliation": checked_hash(OLD_RECONCILIATION, "d8b4fcf0bd2f3e45a252b58db9a442f0095b94e8a512c6c77aab25cd8b8a2cc9", "old native reconciliation"),
            "old_native_reconciliation_receipt": checked_hash(OLD_RECONCILIATION_RECEIPT, "73aebbbe73aee676eaba573b91a181aae1ee74e4d8a7c771524c4519fac66a7b", "old native reconciliation receipt"),
            "old_scientific_scan": checked_hash(OLD_SCAN, "0b4a66a0ea457137b4d324dc5a8710e2a43b59cea5678fb1b425e2d3bc80be59", "old scientific scan"),
            "old_scientific_scan_receipt": checked_hash(OLD_SCAN_RECEIPT, "57fec628031cdd7fb821e2d4248ef7f7a9519e4c3769246e43283e3d263a2e06", "old scientific scan receipt"),
            "old_partvtkout_receipt": checked_hash(OLD_DECODER_RECEIPT, "65c2bb24c98d79215cf1a104750af86671da2723a5b6a110461b7ed6e791585f", "old PartVTKOut receipt"),
            "old_partvtkout_csv": old_csv,
            "fresh_partvtkout_csv": fresh_csv,
            "config_closure_manifest": {"path": str(config_manifest_path), "bytes": config_manifest_path.stat().st_size, "sha256": config_manifest_sha},
            "config_closure_report": {"path": str(config_report_path), "bytes": config_report_path.stat().st_size, "sha256": config_report_sha},
            "config_closure_receipt": {"path": str(config_receipt_path), "bytes": config_receipt_path.stat().st_size, "sha256": config_receipt_sha},
        },
        "native_result": {
            "status": report_case["status"],
            "joined_count": comparison["row_count"],
            "idp": [403829, 397194, 404024],
            "motive_counts": {"position": 3, "density": 0, "movement": 0},
            "identity_fields": comparison["identity_fields"],
            "numeric_abs_tolerance": comparison["numeric_abs_tolerance"],
            "max_abs_difference": comparison["max_abs_difference"],
            "old_receipt_returncode": old_receipt["returncode"],
            "fresh_decoder_command": report_case["fresh_decoder"]["command"],
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_part_content_opened": False,
            "raw_partout_opened_by_this_consumer": False,
            "official_decoder_started_by_this_consumer": False,
            "solver_started": False,
            "cfd_or_model_run": False,
            "completed_guard_decoder_raw_partout_only": True,
        },
        "claim_boundary": {
            "native_cause": "NUMERICAL_POSITION_EXCLUSION from official native PartVTKOut/RunPARTs; no additional endpoint predicate credit",
            "mass": "existing source-visible lower bound only",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
            "converter_implementation": "UNKNOWN_NOT_BOUND_BY_CONVERTER_SOURCE_EXECUTION",
        },
        "old_evidence_preservation": {
            "old_native_reconciliation_modified": False,
            "old_decoder_receipt_modified": False,
            "old_partout_csv_modified": False,
            "fresh_output_is_additive": True,
        },
    }
    atomic_json(output, payload)
    return {"status": payload["status"], "output": str(output.resolve()), "joined_count": 3, "raw_partout_opened": False, "h5_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.output)
    except ClosureError as exc:
        raise SystemExit(f"ClosureError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
