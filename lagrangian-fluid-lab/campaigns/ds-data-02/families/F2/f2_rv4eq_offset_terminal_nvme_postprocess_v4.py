#!/usr/bin/env python3
"""Run source-bound OFFSET pose and v6 labels stages from private NVMe copies.

The terminal conversion H5 is about six GiB and must not be placed in the
shared runner's ordinary ``input_files`` list.  This additive producer keeps
the registered terminal report, receipt, and configuration in the strict
runner hash map, then streams the H5 to a private NVMe temporary file while
checking its complete SHA256 and stable source identity.  The unchanged F2
pose fitter and moving local-z-top operator read that private path.  Reports
are rebound to the canonical source/output paths before they are published;
the private path is never presented as a durable scientific source.

``build`` creates the first, pose-stage request.  ``build-labels`` can only be
run after the pose request has a completed receipt and a real pose H5/report;
it creates a second independent labels-stage request bound to those actual
hashes.  Neither stage launches GenCase, a solver, a converter, GPU work, or
a qualification decision.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable


FAMILY_ROOT = Path(__file__).resolve().parent
LAB_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families" / "F2"
CASE_ID = "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"
CASE_ROOT = F2_DATA / CASE_ID
PHYSICAL_CASE_ID = "F2_RV4EQ_DP005_OFFSET_V1"
PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
NUMERICAL_HASH = "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7"

NATIVE_INPUT_ROOT = F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002" / CASE_ID
SOURCE_H5 = CASE_ROOT / (
    "conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/"
    "trajectory.h5"
)
CONVERSION_REPORT = CASE_ROOT / (
    "conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/"
    "conversion-report.json"
)
CONVERSION_RECEIPT = CASE_ROOT / (
    "conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/"
    "execution-receipt.json"
)
OWNER = FAMILY_ROOT / (
    "handoff_20261003/offset_baseline_terminal_v1/owner_metadata/"
    f"{CASE_ID}.owner.v2-terminal-bound.json"
)
IDENTITY = FAMILY_ROOT / (
    "handoff_20261003/offset_baseline_terminal_v1/typed_identity/"
    f"{CASE_ID}.identity-correction-sidecar.v1.json"
)
XML = NATIVE_INPUT_ROOT / f"{CASE_ID}.xml"
MOTION = NATIVE_INPUT_ROOT / f"{CASE_ID}_motion.dat"
GENCASE_RECEIPT = F2_DATA / PHYSICAL_CASE_ID / (
    "gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json"
)
NATIVE_ROOT = CASE_ROOT / (
    "qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1"
)
SOLVER_OUTPUT = NATIVE_ROOT / "solver_output"
RUN_RECEIPT = NATIVE_ROOT / "execution-receipt.json"
RUN_OUT = SOLVER_OUTPUT / "Run.out"
RUN_CSV = SOLVER_OUTPUT / "Run.csv"
RUNPARTS = SOLVER_OUTPUT / "RunPARTs.csv"
DATA_DIR = SOLVER_OUTPUT / "data"
PARTINFO = DATA_DIR / "PartInfo.ibi4"
PART_MOTION_REF = DATA_DIR / "PartMotionRef.ibi4"
PARTOUT = DATA_DIR / "PartOut_000.obi4"
EXCLUSION_CSV = F2_DATA / (
    "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/"
    "rv4-native-partvtkout-baseline-002/artifacts/artifacts/partvtkout/"
    f"{CASE_ID}/excluded_particles.csv"
)

V6_LABELS = FAMILY_ROOT / "f2_handoff_20261002_v6_labels.py"
EVENT_OPERATOR = FAMILY_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
EVENT_MANIFEST = FAMILY_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
POSE_HELPER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
)
RUNTIME = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
STRICT_DISPATCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
)
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"
PYTHON = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/offset_terminal_nvme_v2"
DEFAULT_POSE_CONFIG = HANDOFF_ROOT / "offset_pose_nvme_config_v2.json"
DEFAULT_POSE_REQUEST = HANDOFF_ROOT / "offset_pose_nvme_request_v2.json"
DEFAULT_LABEL_CONFIG = HANDOFF_ROOT / "offset_labels_nvme_config_v3.json"
DEFAULT_LABEL_REQUEST = HANDOFF_ROOT / "offset_labels_nvme_request_v3.json"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-offset-terminal-nvme-v2")

SCHEMA = "ds-data-02.f2.offset-terminal-nvme-postprocess.v2"
EXPECTED_H5_SHA = "e76eb883c22c06d2eeb498e7cd6aa3b254e4755488f0ef651caa35b2c8b07c96"
EXPECTED_H5_BYTES = 6063678335
EXPECTED_REPORT_SHA = "4533df13c520bcd4868b2b9f6ea76896475fde095fc70ed8e3adeb34242d2389"
EXPECTED_RECEIPT_SHA = "77cd462910b053f31687cfa5f02ce9e43920d8f84a2bf845b75d89d833957883"


class PostprocessError(RuntimeError):
    """Raised when a source-bound stage cannot be proven safe to run."""


def require_file(path: Path, label: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise PostprocessError(f"{label} is missing: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with require_file(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PostprocessError(f"refusing to overwrite additive output: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PostprocessError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise PostprocessError(f"{label} must be a JSON object: {path}")
    return value


def binding(path: Path, role: str, *, known_sha: str | None = None) -> dict[str, Any]:
    path = require_file(path, role)
    return {
        "path": str(path),
        "sha256": known_sha or sha256(path),
        "bytes": int(path.stat().st_size),
        "role": role,
        "hash_source": "terminal_report" if known_sha else "local_sha256",
    }


def _source_static_paths() -> list[Path]:
    return [
        Path(__file__), V6_LABELS, EVENT_OPERATOR, EVENT_MANIFEST, POSE_HELPER,
        RUNTIME, STRICT_DISPATCH, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY,
        REFERENCE_MATRIX, GOAL, OWNER, IDENTITY, CONVERSION_REPORT, CONVERSION_RECEIPT,
        XML, MOTION, GENCASE_RECEIPT, RUN_RECEIPT, RUN_OUT, RUN_CSV, RUNPARTS,
        PARTINFO, PART_MOTION_REF, PARTOUT, EXCLUSION_CSV,
    ]


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if str(resolved) not in seen:
            seen.add(str(resolved))
            result.append(resolved)
    return result


def _hash_map(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256(path) for path in _unique_paths(paths)}


def _terminal_bindings() -> dict[str, dict[str, Any]]:
    report = load_json(CONVERSION_REPORT, "terminal conversion report")
    receipt = load_json(CONVERSION_RECEIPT, "terminal conversion receipt")
    if report.get("conversion_status") != "completed" or report.get("q_n_status") != "not_assessed":
        raise PostprocessError("terminal conversion report is not the expected evidence-only completed report")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PostprocessError("terminal conversion receipt is not completed/code0")
    if str(report.get("output_hdf5")) != str(SOURCE_H5):
        raise PostprocessError("terminal report points at a different H5")
    if str(report.get("output_sha256")) != EXPECTED_H5_SHA:
        raise PostprocessError("terminal report H5 SHA differs from frozen source binding")
    if int(report.get("frames", -1)) != 401 or int(report.get("particles", -1)) != 1667249:
        raise PostprocessError("terminal report dimensions differ from the completed OFFSET conversion")
    if report.get("solver_dimension", {}).get("solver_dimension") != 3:
        raise PostprocessError("terminal report is not actual 3D")
    if int(SOURCE_H5.stat().st_size) != EXPECTED_H5_BYTES:
        raise PostprocessError("terminal H5 byte size differs from report-bound source")
    if sha256(CONVERSION_REPORT) != EXPECTED_REPORT_SHA or sha256(CONVERSION_RECEIPT) != EXPECTED_RECEIPT_SHA:
        raise PostprocessError("terminal report or receipt changed from the completed source handoff")
    return {
        "terminal_source_h5": binding(SOURCE_H5, "completed OFFSET fullstate H5", known_sha=EXPECTED_H5_SHA),
        "terminal_conversion_report": binding(CONVERSION_REPORT, "completed OFFSET conversion report"),
        "terminal_conversion_receipt": binding(CONVERSION_RECEIPT, "completed OFFSET conversion receipt"),
    }


def _stable_stat(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (int(stat.st_dev), int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns))


def verified_copy(source: Path, target: Path, expected_sha: str, expected_bytes: int | None = None) -> dict[str, Any]:
    """Copy one immutable source while hashing the bytes actually read."""
    source = require_file(source, "NVMe source H5")
    if target.exists():
        raise PostprocessError(f"refusing to overwrite private NVMe copy: {target}")
    before = _stable_stat(source)
    if expected_bytes is not None and before[2] != int(expected_bytes):
        raise PostprocessError(f"source byte size differs from registered value: {before[2]} != {expected_bytes}")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    actual = digest.hexdigest()
    after = _stable_stat(source)
    if before != after:
        raise PostprocessError("source H5 changed during verified NVMe copy")
    if actual != expected_sha:
        raise PostprocessError(f"private NVMe copy SHA differs from expected source: {actual} != {expected_sha}")
    if expected_bytes is not None and target.stat().st_size != int(expected_bytes):
        raise PostprocessError("private NVMe copy byte size differs from source binding")
    target.chmod(0o400)
    return {
        "canonical_source_path": str(source),
        "canonical_source_sha256": expected_sha,
        "canonical_source_bytes": int(before[2]),
        "private_reader_path": str(target),
        "private_reader_sha256": actual,
        "private_reader_bytes": int(target.stat().st_size),
        "source_stat_before": list(before),
        "source_stat_after": list(after),
        "copy_verified_during_stream": True,
        "private_reader_deleted_before_publish": True,
    }


def _verify_static_inputs(config: dict[str, Any]) -> None:
    expected = config.get("static_input_sha256")
    if not isinstance(expected, dict) or not expected:
        raise PostprocessError("config has no full static input SHA map")
    for raw_path, expected_sha in expected.items():
        path = require_file(Path(raw_path), "registered stage input")
        actual = sha256(path)
        if actual != str(expected_sha):
            raise PostprocessError(f"registered stage input changed: {path}")


def _verify_terminal(config: dict[str, Any]) -> dict[str, Any]:
    terminal = config.get("terminal_bindings")
    if not isinstance(terminal, dict):
        raise PostprocessError("config has no terminal bindings")
    report_binding = terminal.get("terminal_conversion_report")
    receipt_binding = terminal.get("terminal_conversion_receipt")
    source_binding = terminal.get("terminal_source_h5")
    for name, row in (("terminal conversion report", report_binding), ("terminal conversion receipt", receipt_binding), ("terminal source H5", source_binding)):
        if not isinstance(row, dict) or not row.get("path") or len(str(row.get("sha256", ""))) != 64:
            raise PostprocessError(f"{name} binding is incomplete")
    report = load_json(Path(report_binding["path"]), "terminal conversion report")
    receipt = load_json(Path(receipt_binding["path"]), "terminal conversion receipt")
    if sha256(Path(report_binding["path"])) != report_binding["sha256"]:
        raise PostprocessError("terminal conversion report SHA changed")
    if sha256(Path(receipt_binding["path"])) != receipt_binding["sha256"]:
        raise PostprocessError("terminal conversion receipt SHA changed")
    if report.get("conversion_status") != "completed" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PostprocessError("terminal report/receipt no longer describe a completed conversion")
    if report.get("output_sha256") != source_binding["sha256"]:
        raise PostprocessError("terminal report output SHA does not equal configured H5 source SHA")
    if report.get("output_hdf5") != source_binding["path"]:
        raise PostprocessError("terminal report output path does not equal configured canonical H5 path")
    return {"report": report, "receipt": receipt, "source": source_binding}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, require_file(path, name))
    if spec is None or spec.loader is None:
        raise PostprocessError(f"cannot import stage implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rebind_report(report_path: Path, *, canonical_source: dict[str, Any], copy_evidence: dict[str, Any], stage: str) -> dict[str, Any]:
    payload = load_json(report_path, f"{stage} report")
    if stage == "pose":
        row = payload.get("source_trajectory")
        if not isinstance(row, dict) or row.get("sha256") != canonical_source["sha256"]:
            raise PostprocessError("pose report source H5 SHA is not the verified canonical SHA")
        payload["source_trajectory"] = {
            "path": canonical_source["path"],
            "sha256": canonical_source["sha256"],
            "bytes": canonical_source["bytes"],
            "path_rebound_from_private_reader": True,
        }
    elif stage == "labels":
        row = payload.get("trajectory")
        if not isinstance(row, dict) or row.get("sha256") != canonical_source["sha256"]:
            raise PostprocessError("labels report pose H5 SHA is not the verified canonical SHA")
        payload["trajectory"] = {
            "path": canonical_source["path"],
            "sha256": canonical_source["sha256"],
            "bytes": canonical_source["bytes"],
            "path_rebound_from_private_reader": True,
        }
    payload["nvme_source_copy"] = copy_evidence
    payload["reader_path_policy"] = {
        "private_reader_used_for_exact_stage": True,
        "canonical_path_published_after_verified_copy": canonical_source["path"],
        "private_path_is_ephemeral": True,
    }
    payload["postprocess_stage"] = stage
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def run_pose(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "pose NVMe config")
    if config.get("stage") != "pose":
        raise PostprocessError("pose runner received a non-pose config")
    _verify_static_inputs(config)
    terminal = _verify_terminal(config)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    augmented = output_dir / "trajectory-with-actual-pose.h5"
    pose_report = output_dir / "rigid-body-state.json"
    if augmented.exists() or pose_report.exists():
        raise PostprocessError("pose output already exists; request attempts are immutable")
    source = terminal["source"]
    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f2-offset-pose-", dir=scratch_parent) as private:
        private_source = Path(private) / "terminal-trajectory.h5"
        copy_evidence = verified_copy(Path(source["path"]), private_source, str(source["sha256"]), int(source["bytes"]))
        labels = _load_module(V6_LABELS, "f2_v6_pose_impl")
        pose = labels.augment_pose(
            source=private_source,
            augmented=augmented,
            generated_xml=require_file(XML, "generated XML"),
            motion=require_file(MOTION, "motion control"),
            run_out=require_file(RUN_OUT, "Run.out"),
            pose_report=pose_report,
            conversion_report=require_file(CONVERSION_REPORT, "conversion report"),
            solver_receipt=require_file(RUN_RECEIPT, "solver receipt"),
            gencase_receipt=require_file(GENCASE_RECEIPT, "GenCase receipt"),
            owner_metadata=require_file(OWNER, "owner metadata"),
        )
        if pose.get("status") != "actual_saved_moving_node_pose_complete":
            raise PostprocessError("pose fitter did not report a complete actual-node fit")
        canonical = {
            "path": str(SOURCE_H5.resolve()),
            "sha256": str(source["sha256"]),
            "bytes": int(source["bytes"]),
        }
        pose_payload = _rebind_report(pose_report, canonical_source=canonical, copy_evidence=copy_evidence, stage="pose")
    output_binding = binding(augmented, "actual pose-enriched trajectory")
    if output_binding["sha256"] != pose_payload["augmented_trajectory"]["sha256"]:
        raise PostprocessError("pose report output SHA does not match the published H5")
    manifest = {
        "schema": "ds-data-02.f2.offset-terminal-nvme-pose-result.v2",
        "status": "completed_evidence_only",
        "stage": "pose",
        "case_id": CASE_ID,
        "physical_condition_hash": PHYSICAL_HASH,
        "terminal_bindings": config["terminal_bindings"],
        "pose_report": binding(pose_report, "actual moving-node pose report"),
        "pose_h5": output_binding,
        "nvme_policy": config["nvme_policy"],
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return {"status": "completed", "stage": "pose", "pose_h5": output_binding, "pose_report": binding(pose_report, "pose report"), "manifest": binding(manifest_path, "pose manifest")}


def run_labels(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "labels NVMe config")
    if config.get("stage") != "labels":
        raise PostprocessError("labels runner received a non-labels config")
    _verify_static_inputs(config)
    terminal = _verify_terminal(config)
    pose = config.get("pose_bindings")
    if not isinstance(pose, dict):
        raise PostprocessError("labels config has no completed pose bindings")
    for name in ("pose_h5", "pose_report", "pose_receipt"):
        if not isinstance(pose.get(name), dict) or len(str(pose[name].get("sha256", ""))) != 64:
            raise PostprocessError(f"labels config lacks full SHA for {name}")
    pose_report = load_json(Path(pose["pose_report"]["path"]), "completed pose report")
    pose_receipt = load_json(Path(pose["pose_receipt"]["path"]), "completed pose receipt")
    if sha256(Path(pose["pose_report"]["path"])) != pose["pose_report"]["sha256"]:
        raise PostprocessError("pose report changed after request registration")
    if sha256(Path(pose["pose_receipt"]["path"])) != pose["pose_receipt"]["sha256"]:
        raise PostprocessError("pose receipt changed after request registration")
    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise PostprocessError("pose stage receipt is not completed/code0")
    pose_row = pose_report.get("augmented_trajectory")
    if not isinstance(pose_row, dict) or pose_row.get("sha256") != pose["pose_h5"]["sha256"]:
        raise PostprocessError("pose report and registered pose H5 SHA disagree")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_output = output_dir / "f2-v6-labels.h5"
    observations = output_dir / "f2-v6-observations.json"
    if labels_output.exists() or observations.exists():
        raise PostprocessError("labels output already exists; request attempts are immutable")
    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f2-offset-labels-", dir=scratch_parent) as private:
        private_pose = Path(private) / "trajectory-with-actual-pose.h5"
        copy_evidence = verified_copy(Path(pose["pose_h5"]["path"]), private_pose, str(pose["pose_h5"]["sha256"]), int(pose["pose_h5"]["bytes"]))
        event = _load_module(EVENT_OPERATOR, "f2_v6_event_operator")
        observed = event.observe(
            trajectory=private_pose,
            owner_metadata=require_file(OWNER, "owner metadata"),
            exclusion_csv=require_file(EXCLUSION_CSV, "corrected native exclusion CSV"),
            output=labels_output,
            report=observations,
            definition_override=require_file(XML, "generated XML"),
            numerical_recipe_hash_override=NUMERICAL_HASH,
            case_id_override=CASE_ID,
        )
        observed_status = (
            observed.get("qi_evidence", {}).get("status")
            if isinstance(observed.get("qi_evidence"), dict)
            else observed.get("status")
        )
        if observed_status != "v6-observation-evidence-ready; Q-N and production eligibility not assessed":
            raise PostprocessError("v6 operator returned an unexpected status")
        canonical = {
            "path": str(pose["pose_h5"]["path"]),
            "sha256": str(pose["pose_h5"]["sha256"]),
            "bytes": int(pose["pose_h5"]["bytes"]),
        }
        report_payload = _rebind_report(observations, canonical_source=canonical, copy_evidence=copy_evidence, stage="labels")
    labels_binding = binding(labels_output, "actual v6 labels H5")
    if labels_binding["sha256"] != report_payload["output"]["sha256"]:
        raise PostprocessError("labels report output SHA does not match the published labels H5")
    manifest = {
        "schema": "ds-data-02.f2.offset-terminal-nvme-labels-result.v2",
        "status": "completed_evidence_only",
        "stage": "labels",
        "case_id": CASE_ID,
        "physical_condition_hash": PHYSICAL_HASH,
        "terminal_bindings": config["terminal_bindings"],
        "pose_bindings": pose,
        "labels": labels_binding,
        "observations": binding(observations, "actual v6 observations"),
        "nvme_policy": config["nvme_policy"],
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return {"status": "completed", "stage": "labels", "labels": labels_binding, "observations": binding(observations, "observations"), "manifest": binding(manifest_path, "labels manifest")}


def _base_config(stage: str) -> dict[str, Any]:
    terminal = _terminal_bindings()
    static = _unique_paths(_source_static_paths())
    static_hashes = _hash_map(static)
    return {
        "schema": SCHEMA + ".config",
        "stage": stage,
        "family_id": "F2",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_condition_hash": PHYSICAL_HASH,
        "numerical_recipe_hash": NUMERICAL_HASH,
        "terminal_bindings": terminal,
        "static_input_sha256": static_hashes,
        "static_input_files": list(static_hashes),
        "reader_contract": {
            "source_h5_excluded_from_runtime_input_files": True,
            "full_sha256_stream_verified_before_exact_reader": True,
            "stable_source_stat_checked_before_and_after_copy": True,
            "private_reader_path_rebound_to_canonical_path_before_publish": True,
            "source_is_read_only": True,
        },
        "nvme_policy": {
            "scratch_parent": str(DEFAULT_SCRATCH),
            "private_copy_deleted_after_stage": True,
            "same_unchanged_pose_and_v6_operator": True,
            "no_home_source_rehash_in_exact_reader": True,
        },
        "claim_boundary": {
            "q_i": "not_granted",
            "q_n": "not_assessed",
            "production": "not_evaluated",
            "native_exclusions": "numerical_unknown; never physical spill by this stage",
        },
    }


def _request(*, stage: str, config_path: Path, config: dict[str, Any], attempt_id: str,
             output_root: Path, max_wall: int, storage: int, pose_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    config_path = require_file(config_path, "stage config")
    static = [Path(path) for path in config["static_input_files"]]
    extra = []
    if pose_bindings:
        extra.extend(Path(pose_bindings[key]["path"]) for key in ("pose_report", "pose_receipt"))
    input_paths = _unique_paths([config_path, *static, *extra])
    input_hashes = _hash_map(input_paths)
    command = [
        str(PYTHON), str(Path(__file__).resolve()), "run", stage,
        "--config", str(config_path), "--output-dir", "{attempt_root}",
        "--scratch-parent", str(config["nvme_policy"]["scratch_parent"]),
    ]
    expected = {"pose": ["trajectory-with-actual-pose.h5", "rigid-body-state.json", "postprocess-manifest.json"],
                "labels": ["f2-v6-labels.h5", "f2-v6-observations.json", "postprocess-manifest.json"]}[stage]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "stage_schema": SCHEMA + ".request",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 2,
        "max_wall_seconds": int(max_wall),
        "estimated_storage_bytes": int(storage),
        "command": command,
        "cwd": str(FAMILY_ROOT.resolve()),
        "raw_output_root": str(output_root.resolve()),
        "worktree_root": str(LAB_ROOT.resolve()),
        "input_files": [str(path) for path in input_paths],
        "input_sha256": input_hashes,
        "source_bindings": {
            "config": binding(config_path, f"immutable {stage} NVMe config"),
            "terminal_bindings": config["terminal_bindings"],
            "stage": stage,
            "source_h5_excluded_from_input_files": config["reader_contract"]["source_h5_excluded_from_runtime_input_files"],
        },
        "expected_outputs": {name: str(output_root / name) for name in expected},
        "reader_contract": config["reader_contract"],
        "nvme_policy": config["nvme_policy"],
        "physical_condition_hash": PHYSICAL_HASH,
        "numerical_recipe_hash": NUMERICAL_HASH,
        "solver_launch_forbidden": True,
        "conversion_launch_forbidden": True,
        "gencase_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "root_only": True,
        "launch_allowed": True,
        "runnable": True,
        "authorization": "root-authorized bounded CPU postprocessing; no Q-I/Q-N/production grant",
        "claim_boundary": config["claim_boundary"],
    }
    return request


def build_pose(config_path: Path, request_path: Path) -> dict[str, Any]:
    config = _base_config("pose")
    dump_json(config_path, config)
    request = _request(
        stage="pose", config_path=config_path, config=config,
        attempt_id="offset-terminal-nvme-pose-v2-001",
        output_root=CASE_ROOT / "offset-terminal-nvme-pose-v2-001",
        max_wall=3600, storage=12 * 1024**3,
    )
    dump_json(request_path, request)
    return {"config": binding(config_path, "pose config"), "request": binding(request_path, "pose request"), "request_value": request}


def build_labels(config_path: Path, request_path: Path, pose_attempt_root: Path) -> dict[str, Any]:
    pose_attempt_root = Path(pose_attempt_root).expanduser().resolve()
    pose_receipt_path = require_file(pose_attempt_root / "execution-receipt.json", "completed pose receipt")
    pose_report_path = require_file(pose_attempt_root / "rigid-body-state.json", "completed pose report")
    pose_h5_path = require_file(pose_attempt_root / "trajectory-with-actual-pose.h5", "completed pose H5")
    pose_receipt = load_json(pose_receipt_path, "completed pose receipt")
    pose_report = load_json(pose_report_path, "completed pose report")
    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise PostprocessError("cannot build labels request before pose request is completed/code0")
    pose_binding = pose_report.get("augmented_trajectory")
    if not isinstance(pose_binding, dict) or len(str(pose_binding.get("sha256", ""))) != 64:
        raise PostprocessError("completed pose report has no full H5 SHA")
    if pose_binding.get("path") != str(pose_h5_path):
        raise PostprocessError("completed pose report does not point to its actual output")
    # The consumed v2 pose report predates the additive byte-count field.  Its
    # full SHA is the authoritative output binding; derive the byte count from
    # the immutable completed file for the new labels config rather than
    # rewriting that consumed report.
    registered_pose_bytes = int(pose_binding.get("bytes", pose_h5_path.stat().st_size))
    if registered_pose_bytes != int(pose_h5_path.stat().st_size):
        raise PostprocessError("completed pose report byte count differs from actual H5")
    config = _base_config("labels")
    config["pose_bindings"] = {
        "pose_h5": binding(pose_h5_path, "completed pose-enriched H5", known_sha=str(pose_binding["sha256"])),
        "pose_report": binding(pose_report_path, "completed pose report"),
        "pose_receipt": binding(pose_receipt_path, "completed pose execution receipt"),
    }
    dump_json(config_path, config)
    request = _request(
        stage="labels", config_path=config_path, config=config,
        attempt_id="offset-terminal-nvme-labels-v2-002",
        output_root=CASE_ROOT / "offset-terminal-nvme-labels-v2-002",
        max_wall=10800, storage=20 * 1024**3, pose_bindings=config["pose_bindings"],
    )
    dump_json(request_path, request)
    return {"config": binding(config_path, "labels config"), "request": binding(request_path, "labels request"), "request_value": request}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--config", type=Path, default=DEFAULT_POSE_CONFIG)
    build.add_argument("--request", type=Path, default=DEFAULT_POSE_REQUEST)
    labels = sub.add_parser("build-labels")
    labels.add_argument("--config", type=Path, default=DEFAULT_LABEL_CONFIG)
    labels.add_argument("--request", type=Path, default=DEFAULT_LABEL_REQUEST)
    labels.add_argument("--pose-attempt-root", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("stage", choices=("pose", "labels"))
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--scratch-parent", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_pose(args.config, args.request)
        elif args.command == "build-labels":
            result = build_labels(args.config, args.request, args.pose_attempt_root)
        elif args.stage == "pose":
            result = run_pose(args.config, args.output_dir, args.scratch_parent)
        else:
            result = run_labels(args.config, args.output_dir, args.scratch_parent)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, PostprocessError, ImportError) as error:
        print(f"f2_rv4eq_offset_terminal_nvme_postprocess_v4: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
