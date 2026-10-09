#!/usr/bin/env python3
"""Prepare the F1-S2 medium half-CFL source request (ROOT265).

This module is preparation-only.  It reads small XML/JSON/receipt metadata and
the existing RunPARTs/Run.out control evidence, but never opens the CURRENT
BI4 payload.  The parent runner must copy the overlay XML and the immutable
CURRENT BI4 into a new attempt tree after reservation, then re-hash and
re-stat both inputs before and after the solver.

The half-CFL request is a single-variable comparison against the already
prepared medium same-CFL SaveDt request: both use the same CURRENT BI4,
geometry, controls, 4.000064410707409 s window, and .005 s output contract;
only the two XML CFL values change from .2 to .1.  The historical baseline
receipt used .01 s output and no SaveDt node, so it is retained as lineage and
control evidence rather than treated as the pair.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.medium-half-cfl-solver-source-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.medium-half-cfl-solver-source-manifest.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
REQUEST_DIR = STAGE2 / "requests/source-prepared265"
REQUEST_PATH = REQUEST_DIR / "f1_s2_medium_dp020_half_cfl_savedt_solver_root265_v1.json"
MANIFEST_PATH = REQUEST_DIR / "f1_s2_medium_dp020_half_cfl_savedt_manifest_root265_v1.json"

DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_CASE = DATA / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027"
SOURCE_XML = SOURCE_CASE / "prepared/F1_STAGE1_DUAL_H340_DP020.xml"
SOURCE_BI4 = SOURCE_CASE / "prepared/F1_STAGE1_DUAL_H340_DP020.bi4"
GENCASE_RECEIPT = SOURCE_CASE / "execution-receipt.json"
BASELINE_CASE = DATA / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-physical-endpoint-full-native-gpu-lease-retry-034"
BASELINE_RECEIPT = BASELINE_CASE / "execution-receipt.json"
BASELINE_RUNPARTS = BASELINE_CASE / "solver_output/RunPARTs.csv"
BASELINE_RUNOUT = BASELINE_CASE / "solver_output/Run.out"

PAIR_INPUT = REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F1_S2"
HALF_XML = PAIR_INPUT / "half_cfl/F1_STAGE1_DUAL_H340_DP020_half_cfl_savedt.xml"
HALF_MANIFEST = PAIR_INPUT / "half_cfl/overlay-manifest.json"
SAME_XML = PAIR_INPUT / "same_cfl/F1_STAGE1_DUAL_H340_DP020_same_cfl_savedt.xml"
SAME_MANIFEST = PAIR_INPUT / "same_cfl/overlay-manifest.json"
OLD_HALF_REQUEST = STAGE2 / "requests/stage2-savedt-cfl-pairs-v1/f1_s2_original_savedt_half_cfl.json"
OLD_SAME_REQUEST = STAGE2 / "requests/stage2-savedt-cfl-pairs-v1/f1_s2_original_savedt_same_cfl.json"
PAIR_BUILDER = REFERENCE / "stage2_savedt_cfl_pair_requests_v1.py"

DISPATCH = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"

ROOT260_PROOF = STAGE2 / "checkpoints/F1_CFL_ENTRYPOINT_V2_ACTUAL_ROOT_VERIFICATION_260.json"
ROOT227_PROOF = STAGE2 / "checkpoints/F1_S2_CONTINUOUS_OWNER_AUDIT_V2_ACTUAL_ROOT_VERIFICATION_227.json"
ROOT233_PROOF = STAGE2 / "checkpoints/F1_S2_INITIAL_SUPPORT_V2_ACTUAL_ROOT_VERIFICATION_233.json"
ROOT207_PROOF = STAGE2 / "checkpoints/F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json"
ROOT217_PROOF = STAGE2 / "checkpoints/OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json"
OWNER_CONTRACT = REFERENCE / "stage2_f1_s2_continuous_owner_audit_contract_v2.json"
REFERENCE_CONTRACT = REFERENCE / "stage2_f1_s2_reference_contract_v5.json"
CALIBRATION_CONTRACT = REFERENCE / "stage2_f1_s2_reference_calibration_v5.json"
CFL_CONTRACT = REFERENCE / "stage2_f1_s2_cfl_dt_control_index_contract_v1.json"
CFL_ENTRY_CONTRACT = REFERENCE / "stage2_f1_s2_cfl_entrypoint_audit_contract_v2.json"
UNIFIED_CONTRACT = REFERENCE / "stage2_f1_s2_three_grid_unified_diagnostic_contract_v1.json"

CURRENT_BI4_SHA = "8d020fb952c46d58a230e6f1b23d21c1efb12c63a2bfab296b75bd63a8e6e8df"
CURRENT_BI4_BYTES = 5_735_331
CURRENT_XML_SHA = "8c7f3c5de54c3dfa5dbc521e1536d0663f0075632f77733400869bfee8bbe18f"
CURRENT_XML_BYTES = 7_843
SAVEDT_INTERVAL = 0.005
WINDOW_END = 4.000064410707409
PLANNED_FRAMES = 802


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(f"refusing to overwrite differing file: {path}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def regular_record(path: Path, label: str, *, content_scope: str = "bounded_metadata") -> dict[str, Any]:
    path = require_file(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
        "stat": {
            "bytes": stat.st_size,
            "dev": stat.st_dev,
            "ino": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        },
        "stable_read": True,
        "content_scope": content_scope,
        "label": label,
        "payload_read_by_preparer": False,
    }


def deferred_record(path: Path, sha256: str, bytes_value: int | None, label: str) -> dict[str, Any]:
    path = require_file(path)
    return {
        "path": str(path),
        "bytes": bytes_value if bytes_value is not None else "UNKNOWN_UNTIL_PARENT_REHASH",
        "sha256": sha256,
        "content_scope": "deferred_parent_after_reservation_full_hash",
        "label": label,
        "stable_read": "PENDING_PARENT_PRE_POST",
        "payload_read_by_preparer": False,
        "parent_must_verify": ["bytes", "sha256", "dev", "ino", "mtime_ns", "ctime_ns"],
        "materialization": "byte_for_byte_copy_to_new_attempt_inode_for_BI4; no_hardlink",
    }


def validate_deferred_source_record(record: dict[str, Any], expected_sha256: str, expected_bytes: int | None = None) -> None:
    if record.get("sha256") != expected_sha256:
        raise ValueError("deferred source SHA does not match the bound source")
    if expected_bytes is not None and record.get("bytes") != expected_bytes:
        raise ValueError("deferred source byte count does not match the bound source")


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def cfl_values(text: str) -> list[str]:
    root = ET.fromstring(text)
    return [n.get("value", "") for n in root.iter() if local_tag(n.tag) == "cflnumber"]


def savedt_values(text: str) -> dict[str, str] | None:
    root = ET.fromstring(text)
    nodes = [n for n in root.iter() if local_tag(n.tag) == "savedt"]
    if not nodes:
        return None
    if len(nodes) != 1:
        raise ValueError(f"expected one savedt node, got {len(nodes)}")
    node = nodes[0]
    values = {local_tag(child.tag): child.get("value", "") for child in list(node)}
    values["active"] = node.get("active", "")
    return values


def canonical_xml(text: str, restore_cfl: list[str] | None = None) -> bytes:
    root = ET.fromstring(text)
    for parent in root.iter():
        for child in list(parent):
            if local_tag(child.tag) == "savedt":
                parent.remove(child)
    for parent in root.iter():
        for child in list(parent):
            if local_tag(child.tag) == "special" and len(child) == 0 and not (child.text or "").strip():
                parent.remove(child)
    if restore_cfl is not None:
        nodes = [n for n in root.iter() if local_tag(n.tag) == "cflnumber"]
        if len(nodes) != len(restore_cfl):
            raise ValueError("CFL node count changed")
        for node, value in zip(nodes, restore_cfl):
            node.set("value", value)
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(root, encoding="utf-8")


def xml_parameters(text: str) -> dict[str, str]:
    root = ET.fromstring(text)
    return {
        node.get("key", ""): node.get("value", "")
        for node in root.iter()
        if local_tag(node.tag) == "parameter" and node.get("key")
    }


def validate_xml_contract(source_text: str, overlay_text: str) -> dict[str, Any]:
    source_cfl = cfl_values(source_text)
    overlay_cfl = cfl_values(overlay_text)
    if source_cfl != ["0.2", "0.2"]:
        raise ValueError(f"unexpected CURRENT CFL values: {source_cfl}")
    if overlay_cfl != ["0.1", "0.1"]:
        raise ValueError(f"unexpected half-CFL overlay values: {overlay_cfl}")
    expected_savedt = {
        "start": "0", "finish": "0", "interval": "0.005",
        "fullinfo": "0", "alldt": "1", "active": "true",
    }
    if savedt_values(overlay_text) != expected_savedt:
        raise ValueError(f"unexpected SaveDt contract: {savedt_values(overlay_text)}")
    if savedt_values(source_text) is not None:
        raise ValueError("CURRENT source unexpectedly contains SaveDt")
    if canonical_xml(source_text) != canonical_xml(overlay_text, restore_cfl=source_cfl):
        raise ValueError("half overlay changed semantics outside CFL and SaveDt")
    source_root = ET.fromstring(source_text)
    overlay_root = ET.fromstring(overlay_text)
    source_params = xml_parameters(source_text)
    overlay_params = xml_parameters(overlay_text)
    if source_params != overlay_params:
        raise ValueError("execution parameters changed in half overlay")
    source_dps = [n.get("dp") for n in source_root.iter() if local_tag(n.tag) == "definition"]
    overlay_dps = [n.get("dp") for n in overlay_root.iter() if local_tag(n.tag) == "definition"]
    if source_dps != ["0.02"] or overlay_dps != source_dps:
        raise ValueError(f"unexpected source dp: {source_dps} {overlay_dps}")
    source_gravity = [
        {axis: n.get(axis) for axis in ("x", "y", "z")}
        for n in source_root.iter() if local_tag(n.tag) == "gravity"
    ]
    overlay_gravity = [
        {axis: n.get(axis) for axis in ("x", "y", "z")}
        for n in overlay_root.iter() if local_tag(n.tag) == "gravity"
    ]
    if source_gravity != overlay_gravity or source_gravity[-1] != {"x": "0", "y": "0", "z": "-9.81"}:
        raise ValueError("gravity/control source changed")
    return {
        "source_cfl_values": source_cfl,
        "overlay_cfl_values": overlay_cfl,
        "savedt": expected_savedt,
        "parameters": source_params,
        "gravity": source_gravity,
        "source_semantics_equal_after_restoring_cfl": True,
        "declared_diff": [
            {"field": "execution.special.savedt", "scope": "common_pair_output_contract", "value": ".005"},
            {"field": "cflnumber[0]", "from": ".2", "to": ".1", "scope": "half_CFL_only"},
            {"field": "cflnumber[1]", "from": ".2", "to": ".1", "scope": "half_CFL_only"},
        ],
    }


def xml_metadata() -> dict[str, Any]:
    return validate_xml_contract(
        SOURCE_XML.read_text(encoding="utf-8"),
        HALF_XML.read_text(encoding="utf-8"),
    )


def source_run_summary() -> dict[str, Any]:
    rows: list[list[str]] = []
    for line in BASELINE_RUNPARTS.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and line[0].isdigit():
            rows.append(line.split(";"))
    if not rows:
        raise ValueError("baseline RunPARTs has no numeric rows")
    return {
        "runparts": regular_record(BASELINE_RUNPARTS, "historical baseline RunPARTs", content_scope="bounded_run_control"),
        "runout": regular_record(BASELINE_RUNOUT, "historical baseline Run.out", content_scope="bounded_run_control"),
        "numeric_rows": len(rows),
        "first_part": int(rows[0][0]),
        "last_part": int(rows[-1][0]),
        "first_time_s": float(rows[0][1]),
        "last_time_s": float(rows[-1][1]),
        "sum_saved_window_steps": sum(int(row[2]) for row in rows),
        "dtallinfo_present": (BASELINE_CASE / "solver_output/DtAllInfo.csv").is_file(),
    }


def canonical_hash(value: dict[str, Any]) -> str:
    body = copy.deepcopy(value)
    body.pop("request_sha256", None)
    body.pop("sha256", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def add_path(paths: list[Path], path: Path) -> None:
    path = Path(path).resolve()
    if path not in paths:
        paths.append(path)


def proof_edges(proof_path: Path, label: str) -> tuple[dict[str, Any], list[Path]]:
    proof = load_json(proof_path)
    paths = [proof_path]
    for key in ("request", "receipt", "report", "child_report"):
        value = proof.get(key)
        if isinstance(value, str):
            paths.append(Path(value))
    return {"label": label, "proof": regular_record(proof_path, label), "status": proof.get("status"), "sha256": sha256_file(proof_path)}, paths


def build_without_bi4_hash() -> tuple[dict[str, Any], dict[str, Any]]:
    # This entry point is the actual source-only path.  SOURCE_BI4 is checked
    # for existence and bound to its known record; its payload is never read.
    for path in (SOURCE_XML, SOURCE_BI4, GENCASE_RECEIPT, BASELINE_RECEIPT, BASELINE_RUNPARTS, BASELINE_RUNOUT,
                 HALF_XML, HALF_MANIFEST, SAME_XML, SAME_MANIFEST, OLD_HALF_REQUEST, OLD_SAME_REQUEST,
                 DISPATCH, STRICT, RUNTIME, RUNTIME_V2, SOLVER, PYTHON, PYVENV, PAIR_BUILDER,
                 ROOT260_PROOF, ROOT227_PROOF, ROOT233_PROOF, ROOT207_PROOF, ROOT217_PROOF,
                 OWNER_CONTRACT, REFERENCE_CONTRACT, CALIBRATION_CONTRACT, CFL_CONTRACT, CFL_ENTRY_CONTRACT,
                 UNIFIED_CONTRACT):
        require_file(path)
    if SOURCE_XML.stat().st_size != CURRENT_XML_BYTES or sha256_file(SOURCE_XML) != CURRENT_XML_SHA:
        raise ValueError("CURRENT XML changed from the bound source")
    if SOURCE_BI4.stat().st_size != CURRENT_BI4_BYTES:
        raise ValueError("CURRENT BI4 size changed from the bound source")
    xml = xml_metadata()
    half_manifest = load_json(HALF_MANIFEST)
    same_manifest = load_json(SAME_MANIFEST)
    if half_manifest.get("mode") != "half_cfl" or same_manifest.get("mode") != "same_cfl":
        raise ValueError("wrong overlay modes")
    if half_manifest.get("source_bi4", {}).get("sha256") != CURRENT_BI4_SHA:
        raise ValueError("half overlay manifest is not bound to CURRENT BI4")
    if same_manifest.get("source_bi4", {}).get("sha256") != CURRENT_BI4_SHA:
        raise ValueError("same overlay manifest is not bound to CURRENT BI4")
    old_half = load_json(OLD_HALF_REQUEST)
    old_same = load_json(OLD_SAME_REQUEST)
    for old, mode in ((old_half, "half_cfl"), (old_same, "same_cfl")):
        if old.get("schema") != REQUEST_SCHEMA or old.get("cfl_mode", mode) not in (mode, None):
            # The historical pair request stores the mode under source binding;
            # this branch only rejects a known contradictory explicit field.
            if old.get("cfl_mode") not in (None, mode):
                raise ValueError(f"old {mode} request has contradictory mode")
        if old.get("expected_particles") != 130316 or old.get("expected_fluid_particles") != 42500:
            raise ValueError(f"old {mode} request particle binding changed")
        if old.get("physical_window_s") != [0.0, WINDOW_END] or old.get("save_interval_s") != SAVEDT_INTERVAL:
            raise ValueError(f"old {mode} request window/cadence changed")
        if old.get("cpu_threads") != 2 or old.get("omp_threads") != 2 or old.get("max_wall_seconds") != 900:
            raise ValueError(f"old {mode} resource budget changed")
    gencase = load_json(GENCASE_RECEIPT)
    baseline = load_json(BASELINE_RECEIPT)
    if gencase.get("status") != "completed" or gencase.get("returncode") != 0:
        raise ValueError("CURRENT GenCase receipt is not terminal-success")
    if baseline.get("status") != "completed" or baseline.get("returncode") != 0:
        raise ValueError("historical baseline solver receipt is not terminal-success")
    if not isinstance(baseline.get("command"), list):
        raise ValueError("historical baseline lacks command")

    p260 = load_json(ROOT260_PROOF)
    p227 = load_json(ROOT227_PROOF)
    p233 = load_json(ROOT233_PROOF)
    p207 = load_json(ROOT207_PROOF)
    p217 = load_json(ROOT217_PROOF)
    if p260.get("F1_S2_half_CFL_actual_pair") != "ABSENT_FROM_THIS_BOUND_EVIDENCE":
        raise ValueError("ROOT260 no longer states that the F1-S2 half-CFL pair is absent")
    if p233.get("status", "").startswith("VERIFIED_ACTUAL_F1_S2_THREE_GRID_FRAME0") is False:
        raise ValueError("ROOT233 frame-0 support proof is not the expected limited support proof")
    owner = p227.get("independent_owner_box_volume_density_mass", {})
    if owner.get("mass_kg") != 340.0 or owner.get("volume_m3") != 0.34:
        raise ValueError("continuous owner closure is not the bound 340 kg box")
    if p207.get("child_report_sha256") != "d588f17021c3b1418ac73e343d6c323f2d8850d2be1148d39bba7243ce101fb2":
        raise ValueError("ROOT207 child report join changed")
    if p217.get("status") and "VERIFIED_ACTUAL" not in p217.get("status", ""):
        raise ValueError("official writer calibration proof is not terminal actual")

    old_input_hashes = old_half.get("input_sha256", {})
    solver_sha = old_input_hashes.get(str(SOLVER))
    if not solver_sha:
        raise ValueError("historical pair request lacks official solver SHA")
    source_bi4_record = deferred_record(SOURCE_BI4, CURRENT_BI4_SHA, CURRENT_BI4_BYTES, "CURRENT BI4; parent rehash/copy after reservation")
    solver_record = deferred_record(SOLVER, solver_sha, None, "official v5.4 solver; parent rehash after reservation")

    static_paths: list[Path] = []
    for path in (DISPATCH, STRICT, RUNTIME, RUNTIME_V2, PYVENV, PAIR_BUILDER,
                 SOURCE_XML, GENCASE_RECEIPT, BASELINE_RECEIPT, BASELINE_RUNPARTS, BASELINE_RUNOUT,
                 HALF_XML, HALF_MANIFEST, SAME_XML, SAME_MANIFEST, OLD_HALF_REQUEST, OLD_SAME_REQUEST,
                 ROOT260_PROOF, ROOT227_PROOF, ROOT233_PROOF, ROOT207_PROOF, ROOT217_PROOF,
                 OWNER_CONTRACT, REFERENCE_CONTRACT, CALIBRATION_CONTRACT, CFL_CONTRACT, CFL_ENTRY_CONTRACT,
                 UNIFIED_CONTRACT):
        add_path(static_paths, path)
    for proof in (p260, p227, p233, p207, p217):
        for key in ("request", "receipt", "report", "child_report"):
            if isinstance(proof.get(key), str):
                add_path(static_paths, Path(proof[key]))
    static_records: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(static_paths):
        static_records[str(path)] = regular_record(path, f"ROOT265 static source {index}")
    # This builder itself is part of the parent source closure; it is small and
    # can be hashed after the file has been committed.  During --self-test it
    # is already present, so no provisional hash is needed.
    builder_record = regular_record(Path(__file__), "ROOT265 request builder")
    static_records[builder_record["path"]] = builder_record
    static_paths.append(Path(__file__).resolve())

    input_files = list(static_records)
    input_files.extend([str(SOURCE_BI4.resolve()), str(SOLVER.resolve())])
    input_sha256 = {path: record["sha256"] for path, record in static_records.items()}
    input_sha256[str(SOURCE_BI4.resolve())] = CURRENT_BI4_SHA
    input_sha256[str(SOLVER.resolve())] = solver_sha
    input_records = dict(static_records)
    input_records[str(SOURCE_BI4.resolve())] = source_bi4_record
    input_records[str(SOLVER.resolve())] = solver_record

    baseline_cmd = [str(item) for item in baseline.get("command", [])]
    if "-tout:0.01" not in baseline_cmd or "-tmax:4" not in baseline_cmd:
        raise ValueError(f"historical baseline command changed: {baseline_cmd}")
    cost = copy.deepcopy(old_half.get("cost", {}))
    storage = int(old_half.get("estimated_storage_bytes", cost.get("request_storage_reservation_bytes", 0)))
    owner_report = p227.get("report")
    support_report = p233.get("report")
    child_report = p207.get("child_report")
    proof_records = {
        "ROOT260_CFL_ENTRYPOINT": {
            "proof": regular_record(ROOT260_PROOF, "ROOT260 actual CFL entrypoint proof"),
            "request": regular_record(Path(p260["request"]), "ROOT260 source request"),
            "receipt": regular_record(Path(p260["receipt"]), "ROOT260 receipt"),
            "report": regular_record(Path(p260["report"]), "ROOT260 control report"),
            "finding": "F1-S2 half-CFL actual pair absent from this bound evidence",
        },
        "ROOT227_OWNER": {
            "proof": regular_record(ROOT227_PROOF, "ROOT227 owner closure proof"),
            "request": regular_record(Path(p227["request"]), "ROOT227 owner request"),
            "receipt": regular_record(Path(p227["receipt"]), "ROOT227 owner receipt"),
            "report": regular_record(Path(owner_report), "ROOT227 owner report"),
            "finding": "continuous owner 340 kg; native position support was pending in this earlier proof",
        },
        "ROOT233_FRAME0_SUPPORT": {
            "proof": regular_record(ROOT233_PROOF, "ROOT233 frame-0 support proof"),
            "request": regular_record(Path(p233["request"]), "ROOT233 support request"),
            "receipt": regular_record(Path(p233["receipt"]), "ROOT233 support receipt"),
            "report": regular_record(Path(support_report), "ROOT233 support report"),
            "finding": "limited frame-0 owner/support diagnostic; not QI/QN/QE",
        },
        "ROOT207_NATIVE_HEADER": {
            "proof": regular_record(ROOT207_PROOF, "ROOT207 native header proof"),
            "request": regular_record(Path(p207["request"]), "ROOT207 observer request"),
            "receipt": regular_record(Path(p207["receipt"]), "ROOT207 observer receipt"),
            "report": regular_record(Path(p207["report"]), "ROOT207 observer report"),
            "child_report": regular_record(Path(child_report), "ROOT207 child report"),
            "finding": "native weighted component observations; world orientation remains UNKNOWN",
        },
        "ROOT217_WRITER_CALIBRATION": {
            "proof": regular_record(ROOT217_PROOF, "ROOT217 manufactured writer calibration proof"),
            "finding": "decoder/storage calibration only; no production-world axis qualification",
        },
    }
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "SOURCE_PREPARED_LAUNCH_DISABLED_ROOT265",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "grid": "original_dp0p020000",
        "case_id": "F1_S2_MEDIUM_DP020_SAVEDT_HALF_CFL_ROOT265",
        "attempt_id": "f1-s2-medium-dp020-savedt-half-cfl-root265-001",
        "kind": "qualification",
        "qualification_stage": "stage2_f1_s2_medium_half_cfl_source_prepared_pending_parent_guard",
        "cpu_task_kind": "solver",
        "cpu_threads": int(old_half["cpu_threads"]),
        "omp_threads": int(old_half["omp_threads"]),
        "max_wall_seconds": int(old_half["max_wall_seconds"]),
        "estimated_storage_bytes": storage,
        "estimated_peak_gpu_mib": int(old_half["estimated_peak_gpu_mib"]),
        "worktree_root": str(REPO),
        "cwd": "{attempt_root}/solver-input",
        "command": [
            str(SOLVER),
            "{attempt_root}/solver-input/F1_STAGE1_DUAL_H340_DP020_half_cfl_savedt",
            "{attempt_root}/solver_output",
            "-tmax:4.000064410707409",
            "-tout:0.005",
        ],
        "gencase_receipt": str(GENCASE_RECEIPT.resolve()),
        "gencase_receipt_sha256": sha256_file(GENCASE_RECEIPT),
        "expected_particles": 130316,
        "expected_fluid_particles": 42500,
        "expected_native_frames": PLANNED_FRAMES,
        "expected_dimension": 3,
        "physical_window_s": [0.0, WINDOW_END],
        "save_interval_s": SAVEDT_INTERVAL,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_launch": False,
        "gpu_started": False,
        "source_only": True,
        "native_payload_read": False,
        "hdf5_read": False,
        "vtk_read": False,
        "gencase_launch": False,
        "primary_gpu_dispatch_required": True,
        "deferred_input_files": [str(SOURCE_BI4.resolve()), str(SOLVER.resolve())],
        "input_files": input_files,
        "input_sha256": input_sha256,
        "input_records": input_records,
        "source_binding": {
            "schema": "ds02.stage2.f1-s2.medium-half-cfl-source-binding.v1",
            "source_request_namespace": "ROOT265 source-prepared; parent must create a new actual root-forward request",
            "current_xml": regular_record(SOURCE_XML, "CURRENT DP020 XML"),
            "overlay_xml": regular_record(HALF_XML, "prepared half-CFL SaveDt XML"),
            "overlay_manifest": regular_record(HALF_MANIFEST, "half-CFL overlay manifest"),
            "current_bi4": source_bi4_record,
            "gencase_receipt": regular_record(GENCASE_RECEIPT, "CURRENT GenCase receipt"),
            "baseline_solver_receipt": regular_record(BASELINE_RECEIPT, "historical DP020 baseline solver receipt"),
            "baseline_run_control": source_run_summary(),
            "baseline_control": {
                "receipt_command": baseline_cmd,
                "actual_tmax_s": 4.0,
                "actual_tout_s": 0.01,
                "savedt_node": False,
                "role": "historical endpoint/control lineage; not the dense pair",
            },
            "pair_control": {
                "same_cfl_xml": regular_record(SAME_XML, "same-CFL SaveDt XML"),
                "same_cfl_manifest": regular_record(SAME_MANIFEST, "same-CFL overlay manifest"),
                "same_request": regular_record(OLD_SAME_REQUEST, "existing same-CFL source request"),
                "half_request": regular_record(OLD_HALF_REQUEST, "existing half-CFL source request template"),
                "common_requested_tmax_s": WINDOW_END,
                "common_requested_tout_s": SAVEDT_INTERVAL,
                "common_savedt_interval_s": SAVEDT_INTERVAL,
                "single_variable_difference": "half overlay changes exactly the two CFL values .2 -> .1; SaveDt/.005 and CLI tout/.005 are common pair instrumentation",
            },
            "xml_semantics": xml,
            "execution_authority": {
                "precedence": "actual receipt execution.launch_argv > receipt.command > request.command > XML declarations",
                "no_cfl_cli_override_in_prepared_command": True,
                "parent_must_join": ["actual request", "execution receipt", "RunPARTs.csv", "Run.out", "launched XML pre/post SHA"],
                "half_cfl_actual_pair": "not yet observed; ROOT260 explicitly records it absent",
            },
            "materialization": {
                "target_prefix": "{attempt_root}/solver-input/F1_STAGE1_DUAL_H340_DP020_half_cfl_savedt",
                "target_xml": "{attempt_root}/solver-input/F1_STAGE1_DUAL_H340_DP020_half_cfl_savedt.xml",
                "target_bi4": "{attempt_root}/solver-input/F1_STAGE1_DUAL_H340_DP020_half_cfl_savedt.bi4",
                "target_output": "{attempt_root}/solver_output",
                "copy_xml_from": str(HALF_XML.resolve()),
                "copy_bi4_from": str(SOURCE_BI4.resolve()),
                "copy_mode": "byte_for_byte_copy_to_new_inode_after_parent_reservation",
                "must_not_hardlink_current_bi4": True,
                "containment": "all prepared copies and output must remain below attempt_root; reject symlink escapes",
                "checks": ["target XML SHA", "target BI4 SHA", "source BI4 pre/post bytes and full stat", "target/output path containment"],
            },
            "owner_and_initial_state": {
                "continuous_owner_mass_kg": 340.0,
                "owner_box": {"low_m": [2.2, 0.0, 0.0], "size_m": [1.0, 1.0, 0.34], "density_kg_m3": 1000.0},
                "current_discrete_fluid_mass_kg": 340.00001614913344,
                "current_fluid_particles": 42500,
                "no_mass_rescale": True,
                "no_geometry_motion_control_edits": True,
                "support_and_owner_evidence": proof_records,
            },
            "source_records": proof_records,
        },
        "control_change_contract": {
            "baseline_to_pair": [
                "historical baseline had XML TimeOut=.01, CLI -tout:.01, no SaveDt",
                "both new pair members use SaveDt interval=.005 and CLI -tout:.005",
                "this output-contract change is common to same/half and is not attributed to CFL",
            ],
            "same_to_half": [
                "same source XML/BI4/Def/geometry/particle state",
                "same SaveDt values and TimeMax/TimeOut request",
                "only cflnumber value .2 -> .1 in both XML locations",
                "no -cfl runtime override is present in the prepared command",
            ],
            "runtime_join_required": True,
        },
        "owner_admission": {
            "source_owner_continuous_mass_closed": True,
            "frame0_support_limited_actual": True,
            "full_native_dynamic_support": "UNKNOWN_PENDING_PARENT_HALF_RUN",
            "initial_sample_is_not_continuum_truth": True,
            "mass_gate": {"preferred_relative_percent": 1.0, "hard_upper_percent": 2.0, "rescale": False, "widen": False},
            "admission_state": "SOURCE_READY_FOR_PARENT_GUARD; SCIENTIFIC_QUALIFICATION_PENDING",
            "minimal_parent_evidence": [
                "fresh after-reservation source copy and BI4 pre/post full SHA/stat closure",
                "terminal half-CFL receipt with actual launch argv and no hidden CFL override",
                "RunPARTs/Run.out/DtAllInfo join for the requested dense window",
                "native observer support and lifecycle remain separate from owner mass",
            ],
        },
        "output_plan": {
            "native_output": "retain every Part_*.bi4 over the complete requested window",
            "planned_frames": PLANNED_FRAMES,
            "queries_s": [0.0, 1.0, 2.0, 3.0, 4.0],
            "postrun_checks": [
                "RunPARTs final saved time against requested endpoint",
                "DtAllInfo row/time relation under documented terminal convention",
                "Run.out DTsMin aggregate and clamp semantics",
                "native MF/role/finite support in a separate guarded observer",
            ],
            "interpolation": "forbidden",
            "neighbor_grid_truth": "forbidden",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "cost": {
            "inherited_from_existing_half_request": str(OLD_HALF_REQUEST.resolve()),
            "inherited_request_sha256": sha256_file(OLD_HALF_REQUEST),
            "max_wall_seconds_unchanged": int(old_half["max_wall_seconds"]),
            "estimated_storage_bytes_unchanged": storage,
            "estimated_peak_gpu_mib_unchanged": int(old_half["estimated_peak_gpu_mib"]),
            "planned_frames": PLANNED_FRAMES,
            "raw_native_reserved_bytes": cost.get("raw_native_reserved_bytes", "INHERITED"),
            "storage_policy": "retain raw native; no delete/overwrite; actual terminal bytes pending parent guard",
            "cpu_gpu_time": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
            "no_deadline_extension_in_preparation": True,
        },
        "admission_blockers_and_minimum_repairs": [
            {
                "blocker": "No actual F1-S2 medium half-CFL terminal pair exists in ROOT260 evidence",
                "evidence": "ROOT260.F1_S2_half_CFL_actual_pair == ABSENT_FROM_THIS_BOUND_EVIDENCE",
                "minimum_repair": "run this exact source request under a fresh parent UUID/IO lease and retain actual receipt/RunPARTs/Run.out",
            },
            {
                "blocker": "Runtime CFL/dt authority cannot be inferred from XML alone",
                "evidence": "F1 CFL contract and ROOT260 authority precedence",
                "minimum_repair": "join launch argv, execution constants, RunPARTs, and XML pre/post from the actual half run",
            },
            {
                "blocker": "Scientific QI/QN/QE and integration/output error bounds remain unknown",
                "evidence": "owner/support proofs explicitly grant diagnostic scope only",
                "minimum_repair": "use actual saved rows/native fields with the frozen contracts; no interpolation or neighbor-grid truth",
            },
        ],
        "resource_guard": {
            "runner": "parent external solver v5/shared v4 runtime only",
            "launch_commit": "SOURCE_ROOT265; parent must replace with actual forward commit",
            "gpu_uuid_authorization": "parent only",
            "protected_gpu": {"uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec", "action": "do_not_touch"},
            "solver_started_by_preparation": False,
            "native_payload_read_by_preparation": False,
            "hdf5_read_by_preparation": False,
        },
        "request_sha256": "",
    }
    request["request_sha256"] = canonical_hash(request)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "SOURCE_PREPARED_LAUNCH_DISABLED_ROOT265",
        "request": {"path": str(REQUEST_PATH.resolve()), "sha256": request["request_sha256"], "content_scope": "source-prepared only"},
        "source_request_sha256": request["request_sha256"],
        "source_only": True,
        "solver_started": False,
        "gpu_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "builder": regular_record(Path(__file__), "ROOT265 builder"),
        "input_records": {key: {"path": key, "sha256": value["sha256"], "bytes": value["bytes"], "content_scope": value["content_scope"]} for key, value in input_records.items()},
        "deferred_inputs": [source_bi4_record, solver_record],
        "declared_change": "medium DP020 SaveDt pair; half member changes only XML CFL .2 -> .1 relative to same member",
        "science_status": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return request, manifest


def self_test() -> None:
    request, manifest = build_without_bi4_hash()
    assert request["schema"] == REQUEST_SCHEMA
    assert request["variant_schema"] == VARIANT_SCHEMA
    assert request["execution_allowed"] is False
    assert request["command"][-1] == "-tout:0.005"
    assert request["source_binding"]["xml_semantics"]["overlay_cfl_values"] == ["0.1", "0.1"]
    assert request["source_binding"]["xml_semantics"]["source_semantics_equal_after_restoring_cfl"] is True
    assert request["source_binding"]["materialization"]["must_not_hardlink_current_bi4"] is True
    assert request["source_binding"]["owner_and_initial_state"]["continuous_owner_mass_kg"] == 340.0
    assert manifest["science_status"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    original = HALF_XML.read_text(encoding="utf-8")
    bad_cfl = original.replace('value="0.1"', 'value="0.15"', 1)
    try:
        validate_xml_contract(SOURCE_XML.read_text(encoding="utf-8"), bad_cfl)
    except ValueError:
        pass
    else:
        raise AssertionError("mutated CFL fixture was accepted")
    bad_timeout = original.replace('key="TimeOut" value="0.01"', 'key="TimeOut" value="0.02"', 1)
    try:
        validate_xml_contract(SOURCE_XML.read_text(encoding="utf-8"), bad_timeout)
    except ValueError:
        pass
    else:
        raise AssertionError("mutated TimeOut fixture was accepted")
    good_bi4 = request["input_records"][str(SOURCE_BI4.resolve())]
    validate_deferred_source_record(good_bi4, CURRENT_BI4_SHA, CURRENT_BI4_BYTES)
    bad_record = dict(good_bi4)
    bad_record["sha256"] = "0" * 64
    try:
        validate_deferred_source_record(bad_record, CURRENT_BI4_SHA, CURRENT_BI4_BYTES)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong BI4 SHA fixture was accepted")
    print(json.dumps({"status": "SELF_TEST_PASS", "request_sha256": request["request_sha256"], "manifest_schema": manifest["schema"]}, indent=2))


def prepare() -> None:
    request, manifest = build_without_bi4_hash()
    atomic_json(REQUEST_PATH, request)
    manifest["request"]["path"] = str(REQUEST_PATH.resolve())
    atomic_json(MANIFEST_PATH, manifest)
    print(json.dumps({
        "status": "SOURCE_PREPARED_LAUNCH_DISABLED_ROOT265",
        "request": str(REQUEST_PATH.resolve()),
        "manifest": str(MANIFEST_PATH.resolve()),
        "request_sha256": request["request_sha256"],
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "solver_started": False,
        "native_payload_read": False,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.prepare:
        parser.error("choose exactly one of --self-test or --prepare")
    if args.self_test:
        self_test()
    else:
        prepare()


if __name__ == "__main__":
    main()
