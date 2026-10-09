#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Prepare ROOT173/ROOT174 source cards and parent-guard request skeletons.

The two studies share the ROOT161 middle BI4 source and current forcing
table.  ROOT173 changes the CFL coefficient from 0.05 to 0.025 while keeping
the output cadence at 0.01 s.  ROOT174 keeps CFL at 0.05 and changes only
the solver output cadence from 0.01 to 0.005 s.  ``--build-cards`` writes
planning cards without reading payloads.  ``--build-request`` additionally
checks a small generated-XML overlay and emits a parent-reviewable external
solver request; BI4 and forcing content are represented by supplied SHA
values and are never read by this builder.

Neither card grants scientific qualification.  Actual dt/clamp history,
saved times, terminal storage, and observer/output calibration remain
UNKNOWN until a parent guard runs a separately reserved attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
MATERIALIZER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_external_solver_v5_materialize.py"
BASE_XML = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/generated/F3_S2_P1200_AY0750_MATCHED.xml"
BASE_BI4 = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/generated/F3_S2_P1200_AY0750_MATCHED.bi4"
BASE_FORCING = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-v1-root-086-001-root-forward-030-001/generated/CaseSloshingAccData.csv"
# The actual ROOT086 path is used by the source card below; this alternate
# spelling is retained only as a fallback for worktrees where the generated
# forcing copy is in the source-preparation tree.
SOURCE_FORCING = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/CaseSloshingAccData.csv"
ROOT161_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_MIDDLE_BI4_SINGLE_STREAM_ACTUAL_SOURCE_SNAPSHOT_ROOT_VERIFICATION_161.json"
ROOT161_SHA = "3bd6d0a5e70dca477aad347b54057c2169de4fab8ca41cd5ac1af59e5142459a"
ROOT161_BYTES = 9_227_118
BASE_XML_SHA = "3ae2aae572b0fc8cb0687e0590b0fb1762af61212d037da603d4bc8326a8ae9d"
FORCING_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
TMAX_S = 8.350016881886734
BASE_CFL = 0.05
HALF_CFL = 0.025
BASE_TOUT_S = 0.01
HALF_TOUT_S = 0.005
COEF_DT_MIN = 0.005
SCHEMA = "ds02.stage2.f3-s2.middle-overlay-source-card.v1"
REQUEST_SCHEMA = "ds02.stage2.f3-s2.middle-overlay-study-request.v1"


def _path(path: Path) -> Path:
    return path.expanduser().resolve()


def _regular(path: Path, label: str) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_record(path: Path, label: str, expected_sha: str | None = None, *, max_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    path = _regular(path, label)
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise ValueError(f"{label} exceeds small input limit: {stat.st_size} bytes")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha or _sha256(path),
        "content_scope": "small_source_hashed_by_builder_and_parent",
    }


def _payload_record(path: Path, label: str, expected_sha: str, expected_bytes: int | None = None) -> dict[str, Any]:
    """Record only stat for a payload; do not open or hash it."""

    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if expected_bytes is not None and int(stat.st_size) != expected_bytes:
        raise ValueError(f"{label} byte count {stat.st_size} != expected {expected_bytes}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha,
        "sha256_computed_by_builder": False,
        "content_scope": "parent_after_reservation_pre_post_hash",
    }


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _card(study: str) -> dict[str, Any]:
    if study == "half_cfl":
        return {
            "study_id": "ROOT173",
            "case_id": "F3_S2_MATCHED_MIDDLE_HALF_CFL_ROOT173",
            "attempt_id": "f3-s2-matched-middle-half-cfl-root-173-001",
            "study_variable": "cflnumber",
            "base_cflnumber": BASE_CFL,
            "overlay_cflnumber": HALF_CFL,
            "base_tout_s": BASE_TOUT_S,
            "overlay_tout_s": BASE_TOUT_S,
            "output_change": False,
            "cfl_change": True,
            "output_label": "half CFL, same output cadence",
        }
    if study == "half_output":
        return {
            "study_id": "ROOT174",
            "case_id": "F3_S2_MATCHED_MIDDLE_HALF_OUTPUT_ROOT174",
            "attempt_id": "f3-s2-matched-middle-half-output-root-174-001",
            "study_variable": "TimeOut",
            "base_cflnumber": BASE_CFL,
            "overlay_cflnumber": BASE_CFL,
            "base_tout_s": BASE_TOUT_S,
            "overlay_tout_s": HALF_TOUT_S,
            "output_change": True,
            "cfl_change": False,
            "output_label": "same CFL, half output cadence",
        }
    raise ValueError(f"unknown study kind: {study}")


def build_cards(output: Path) -> dict[str, Any]:
    cards = []
    for study in ("half_cfl", "half_output"):
        item = _card(study)
        item.update({
            "schema": SCHEMA,
            "status": "SOURCE_CARD_ONLY_PARENT_REVIEW_REQUIRED",
            "family_id": "F3",
            "sentinel_id": "F3-S2",
            "physical_case_id": PHYSICAL_CASE_ID,
            "source_binding": {
                "middle_bi4": {
                    "sha256": ROOT161_SHA,
                    "bytes": ROOT161_BYTES,
                    "source_provenance": "ROOT161 single-fd after-reservation snapshot; no builder payload read",
                },
                "generated_xml_base": {"sha256": BASE_XML_SHA, "path": str(BASE_XML), "read_by_builder": False},
                "forcing": {"sha256": FORCING_SHA, "path": str(SOURCE_FORCING), "read_by_builder": False},
                "source_control": "same ROOT161/ROOT162 physical/control input; no historical forcing substitution",
            },
            "physical_window_s": [0.0, TMAX_S],
            "execution_parameters_held_fixed": {
                "CoefDtMin": COEF_DT_MIN,
                "DtMin": 0.0,
                "DtFixed": 0.0,
                "TimeMax": TMAX_S,
                "StepAlgorithm": 2,
                "DensityDT": 3,
                "forcing_sha256": FORCING_SHA,
                "generated_bi4_sha256": ROOT161_SHA,
            },
            "overlay_contract": {
                "only_one_semantic_variable_changes": True,
                "half_cfl": {
                    "changed_xml_semantics": ["casedef/constantsdef/cflnumber/@value", "execution/constants/cflnumber/@value"],
                    "expected_base_value": BASE_CFL,
                    "expected_overlay_value": HALF_CFL,
                },
                "half_output": {
                    "changed_xml_semantics": ["execution/parameters/parameter[key=TimeOut]/@value"],
                    "expected_base_value": BASE_TOUT_S,
                    "expected_overlay_value": HALF_TOUT_S,
                },
                "no_implicit_CoefDtMin_change": True,
                "no_geometry_motion_forcing_change": True,
                "overlay_xml_must_be_new_file": True,
                "base_source_and_consumed_XML_immutable": True,
            },
            "request_contract": {
                "schema": REQUEST_SCHEMA,
                "top_level_status": "READY_FOR_PARENT_GUARD",
                "materializer": str(MATERIALIZER),
                "solver": str(SOLVER),
                "tout_s": item["overlay_tout_s"],
                "tmax_s": TMAX_S,
                "mdbc_noslip": 1,
                "dynamic_sha_source": "parent after-reservation only",
                "GPU_UUID": "PARENT_FRESH_INVENTORY_REQUIRED",
                "reservation": "PARENT_ATOMIC_EXTERNAL_V5_REQUIRED",
                "terminal_evidence": ["RunPARTs.csv", "Run.out", "DtAllInfo", "DTsMin count semantics", "actual final saved time", "input pre/post SHA/stat", "storage and CPU/GPU charge"],
            },
            "resource_estimate": {
                "storage_bytes": "UNKNOWN_PENDING_TERMINAL",
                "wall_seconds": "UNKNOWN_PENDING_TERMINAL",
                "full_window_required": True,
                "no_frame0_or_short_window_substitution": True,
            },
            "qualification": {
                "QI": "UNKNOWN",
                "QN": "UNKNOWN",
                "QE": "UNKNOWN",
                "reason": "CFL/output-control separation card only; no solver, dt trace, field observer, or spatial truth credit",
            },
            "launch_policy": {"launch_disabled": True, "solver_started": False, "gencase_launch": False, "builder_payload_read": False},
        })
        item["sha256"] = _canonical(item)
        cards.append(item)
    value = {
        "schema": "ds02.stage2.f3-s2.middle-overlay-source-cards.v1",
        "status": "SOURCE_CARDS_READY_PARENT_REVIEW_REQUIRED",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "cards": cards,
        "only_one_change_per_study": True,
        "solver_started": False,
        "native_payload_read": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    value["sha256"] = _canonical(value)
    _write_once(output, value)
    return value


def _semantic_tree(root: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}

    def walk(element: ET.Element, path: str) -> None:
        for key, value in sorted(element.attrib.items()):
            # GenCase's generated XML date/app metadata is not a physical
            # condition.  Everything else must remain byte-semantic equal.
            if path == "case" and key in {"date", "app"}:
                continue
            values[f"{path}/@{key}"] = value
        child_counts: dict[str, int] = {}
        for child in list(element):
            index = child_counts.get(child.tag, 0)
            child_counts[child.tag] = index + 1
            walk(child, f"{path}/{child.tag}[{index}]")

    walk(root, root.tag)
    return values


def _audit_overlay(study: str, overlay_xml: Path) -> dict[str, Any]:
    base_path = _regular(BASE_XML, "ROOT086 base generated XML")
    overlay_path = _regular(overlay_xml, "new overlay generated XML")
    base = _semantic_tree(ET.parse(base_path).getroot())
    overlay = _semantic_tree(ET.parse(overlay_path).getroot())
    if set(base) != set(overlay):
        missing = sorted(set(base) - set(overlay))[:8]
        extra = sorted(set(overlay) - set(base))[:8]
        raise ValueError(f"overlay XML changed semantic tree keys: missing={missing} extra={extra}")
    changed = {key: {"base": base[key], "overlay": overlay[key]} for key in base if base[key] != overlay[key]}
    card = _card(study)
    allowed = (
        {
            "casedef/constantsdef/cflnumber/@value",
            "execution/constants/cflnumber/@value",
        }
        if study == "half_cfl"
        else {"execution/parameters/parameter[key=TimeOut]/@value"}
    )
    def numeric_equal(value: str, expected: float) -> bool:
        try:
            return abs(float(value) - expected) <= 1.0e-12
        except (TypeError, ValueError):
            return False

    # Path indices vary when a producer serializes XML differently.  Match
    # semantic suffixes rather than silently allowing arbitrary attributes.
    def allowed_change(key: str) -> bool:
        if study == "half_cfl":
            return key.endswith("/cflnumber[0]/@value") and ("/constantsdef[" in key or "/constants[" in key)
        # The parameter key is a sibling XML attribute, so the stable
        # generated path is the registered TimeOut index; no free-form
        # parameter value changes are accepted.
        return key.endswith("/parameter[21]/@value") and "/parameters[" in key
    if any(not allowed_change(key) for key in changed):
        raise ValueError(f"overlay contains changes outside the registered {study} variable: {sorted(changed)}")
    if study == "half_cfl":
        if len(changed) != 2 or any(not numeric_equal(item["base"], BASE_CFL) or not numeric_equal(item["overlay"], HALF_CFL) for item in changed.values()):
            raise ValueError("half-CFL overlay does not set both cflnumber values to 0.025")
    else:
        if len(changed) != 1 or not numeric_equal(next(iter(changed.values()))["base"], BASE_TOUT_S) or not numeric_equal(next(iter(changed.values()))["overlay"], HALF_TOUT_S):
            raise ValueError("half-output overlay must change only TimeOut to 0.005")
    return {"study": study, "base_xml_sha256": _sha256(base_path), "overlay_xml_sha256": _sha256(overlay_path), "changed": changed, "allowed_semantic_paths": sorted(allowed)}


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    card = _card(args.study)
    overlay = _audit_overlay(args.study, args.overlay_xml)
    if overlay["base_xml_sha256"] != BASE_XML_SHA:
        raise ValueError("ROOT086 base generated XML SHA is not the frozen ROOT161 source")
    if args.generated_bi4_sha256 != ROOT161_SHA:
        raise ValueError("generated BI4 SHA must be the ROOT161 fresh middle source SHA")
    if args.forcing_sha256 != FORCING_SHA:
        raise ValueError("forcing SHA must be the frozen current-control SHA")
    worker = _regular(MATERIALIZER, "external v5 materializer")
    python_record = _small_record(PYTHON, "literal venv interpreter", max_bytes=16 * 1024 * 1024)
    materializer_record = _small_record(worker, "external v5 materializer")
    overlay_record = _small_record(args.overlay_xml, "new XML overlay")
    input_records = {python_record["path"]: python_record, materializer_record["path"]: materializer_record, overlay_record["path"]: overlay_record}
    input_files = sorted(input_records)
    hashes = {path: input_records[path]["sha256"] for path in input_files}
    generated_bi4 = _path(args.generated_bi4)
    forcing = _path(args.forcing_csv)
    # Only stat payloads; contents are owned by the parent v5 guard.
    bi4_record = _payload_record(generated_bi4, "ROOT161 middle BI4", ROOT161_SHA, ROOT161_BYTES)
    forcing_record = _payload_record(forcing, "current forcing CSV", FORCING_SHA)
    input_files += [bi4_record["path"], forcing_record["path"]]
    hashes.update({bi4_record["path"]: ROOT161_SHA, forcing_record["path"]: FORCING_SHA})
    tout = card["overlay_tout_s"]
    command = [
        str(PYTHON), str(worker),
        "--solver", str(SOLVER), "--output-root", "{output_root}",
        "--generated-xml", str(overlay_record["path"]), "--generated-bi4", str(bi4_record["path"]),
        "--forcing-csv", str(forcing_record["path"]),
        "--expected-generated-xml-sha", overlay["overlay_xml_sha256"],
        "--expected-generated-bi4-sha", ROOT161_SHA, "--expected-forcing-sha", FORCING_SHA,
        "--tmax", repr(TMAX_S), "--tout", repr(tout), "--mdbc-noslip", "1",
    ]
    value: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "kind": "gpu",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": card["case_id"],
        "attempt_id": card["attempt_id"],
        "launch_commit": args.launch_commit,
        "study_variable": card["study_variable"],
        "source_card_status": "SOURCE_CARD_ONLY_PARENT_REVIEW_REQUIRED",
        "command": command,
        "input_files": sorted(input_files),
        "input_sha256": hashes,
        "input_records": {**input_records, bi4_record["path"]: bi4_record, forcing_record["path"]: forcing_record},
        "deferred_input_files": [bi4_record["path"], forcing_record["path"]],
        "deferred_input_policy": "parent V5 reserve then full pre/post content SHA/stat; builder did not read BI4 or forcing payload",
        "solver_started": False,
        "gencase_launch": False,
        "execution_allowed": True,
        "launch_disabled": False,
        "gpu_uuid": "PARENT_FRESH_INVENTORY_REQUIRED",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 8 * 1024**3,
        "external_reserve_bytes": "UNKNOWN_PENDING_PARENT_REVIEW",
        "home_receipt_reserve_bytes": "UNKNOWN_PENDING_PARENT_REVIEW",
        "estimated_storage_bytes": "UNKNOWN_PENDING_TERMINAL",
        "estimated_peak_memory_bytes": "UNKNOWN_PENDING_TERMINAL",
        "output_root": "{output_root}",
        "output": {"atomic": True, "refuse_overwrite": True},
        "source_binding": {
            "middle_bi4_sha256": ROOT161_SHA,
            "middle_bi4_bytes": ROOT161_BYTES,
            "forcing_sha256": FORCING_SHA,
            "base_generated_xml_sha256": BASE_XML_SHA,
            "overlay": overlay,
            "tmax_s": TMAX_S,
            "tout_s": tout,
            "CoefDtMin": COEF_DT_MIN,
            "only_one_semantic_change": True,
            "same_physical_geometry_motion_forcing": True,
            "actual_dt_and_clamp": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS_AND_OFFICIAL_LOG",
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-external-v5", "fresh_uuid_lease": True, "solver_launch": "parent_only"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "single-variable CFL/output overlay canary; no time/field/spatial qualification"},
    }
    value["sha256"] = _canonical(value)
    return value


def self_test() -> dict[str, Any]:
    if ROOT161_BYTES <= 0 or len(ROOT161_SHA) != 64 or len(FORCING_SHA) != 64:
        raise AssertionError("frozen source binding incomplete")
    if _card("half_cfl")["study_variable"] == _card("half_output")["study_variable"]:
        raise AssertionError("two overlays must have distinct one-variable studies")
    return {"status": "PASS", "schema": SCHEMA, "cards": ["ROOT173_half_cfl", "ROOT174_half_output"], "only_one_change_per_study": True, "payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-cards", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--study", choices=("half_cfl", "half_output"))
    parser.add_argument("--overlay-xml", type=Path)
    parser.add_argument("--generated-bi4", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--forcing-csv", type=Path)
    parser.add_argument("--forcing-sha256")
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-overlay-source-cards-root173-174.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.build_cards:
        try:
            value = build_cards(args.output)
        except Exception as exc:
            print(json.dumps({"status": "FAILED_MIDDLE_OVERLAY_CARD_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 1
        print(json.dumps({"status": value["status"], "output": str(args.output.expanduser().resolve()), "solver_started": False}, ensure_ascii=False, indent=2)); return 0
    required = (args.study, args.overlay_xml, args.generated_bi4, args.generated_bi4_sha256, args.forcing_csv, args.forcing_sha256, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires --study, new overlay XML, BI4/forcing paths+SHA, and --launch-commit")
    try:
        value = build_request(args)
        _write_once(args.output, value)
    except Exception as exc:
        print(json.dumps({"status": "FAILED_MIDDLE_OVERLAY_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 1
    print(json.dumps({"status": value["status"], "output": str(args.output.expanduser().resolve()), "study": args.study, "solver_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
