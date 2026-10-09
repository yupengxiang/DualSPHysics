#!/usr/bin/env python3
"""Bounded source-only QA for the F3-S2 middle-grid staging decision.

This worker joins the immutable F3 owner/control plan, the completed coarse
ROOT150 verification, the small GenCase/support evidence for the existing
``dp=0.006`` and ``dp=0.003`` sources, and the coarse RunPARTs time axis.
It deliberately does not open the ROOT150 observer report, a BI4/VTK/HDF5
payload, or the forcing CSV.  The ROOT150 report is therefore a parent-owned
provenance record: its SHA and the facts independently recorded in the small
verification proof are bound, while native field values remain deferred to a
separate guarded consumer.

The useful result is a finite, reproducible common-time/output contract and
a staged middle feasibility record.  A bracket is a timestamp fact only;
the worker never interpolates a field, pairs particles, or treats a
neighbouring grid as truth.  Continuous-owner equivalence, no-penetration,
flux, integration error, output error, and QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any


REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

SCHEMA = "ds02.stage2.f3-s2.matched-middle-control-cost-qa.v1"
PLAN_SCHEMA = "ds02.stage2.f3-s2.matched-three-grid-plan.v2"
CONTRACT_SCHEMA = "ds02.stage2.f3-s2.observer-calibration-contract.v1"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
OWNER_MASS_KG = 14.58
SOURCE_WINDOW_S = (0.0, 8.350016881886734)
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0, 8.350016881886734)
SOURCE_CONTROL_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
ROOT150_PROOF_SHA = "c230518332163e790f6996563ecfc4f008cfbebea94f451b5cc670ab581827cf"
ROOT150_REPORT_SHA = "81148499db02132a7001dd30e9395bec335e21c5c401dc0347da635b215efc64"
ROOT150_REPORT_BYTES = 14825462
ROOT150_RECEIPT_SHA = "6f61b79c7311ba203a5a13fd6231db43e506b6586a00746d1c09d7ad920da626"
ROOT133_PROOF_SHA = "5d459c01728e83178903695b39f131b1c0b9ea30293454454c6c8c17f7be4706"
ROOT133_RECEIPT_SHA = "10df2f69977034ca3be8d6b7fd388bd7a565049af1c225a78f9937bc7ef8cc75"
ROOT133_REQUEST_SHA = "0441462c5e8ed9198e10648d31f75bcdc844742abcf883478c2d02fa5a5de624"
ROOT133_RUNPARTS_SHA = "81b85b927c023fcc4a798b2a86ca7193f4c5c8062174868bbcf7765aada08cd1"

PLAN = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_matched_three_grid_plan_v2.json"
CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_matched_middle_control_cost_qa_v1.py"

ROOT150_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_FULL836_NATIVE_STREAM_ACTUAL_LIMITED_ROOT_VERIFICATION_150.json"
ROOT150_REPORT = DATA_ROOT / "families/F3/F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150/f3-s2-coarse-full-native-stream-v3-root-150-001-root-forward-030-001/observer/f3_s2_full_native_stream_v3_root150.json"
ROOT150_RECEIPT = DATA_ROOT / "families/F3/F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150/f3-s2-coarse-full-native-stream-v3-root-150-001-root-forward-030-001/execution-receipt.json"
ROOT133_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_COARSE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_133.json"
ROOT133_REQUEST = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-coarse-external-v8-root-forward-133-001.json"
ROOT133_RECEIPT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/execution-receipt.json"
ROOT133_RUNPARTS = Path("/var/tmp/ds02-stage2/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/solver_output/RunPARTs.csv")
ROOT133_GENERATED_XML = Path("/var/tmp/ds02-stage2/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/solver-inputs/generated.xml")

MIDDLE_RECEIPT = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/execution-receipt.json"
MIDDLE_XML = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/generated/F3_S2_P1200_AY0750_MATCHED.xml"
MIDDLE_SUPPORT = DATA_ROOT / "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/f3-s2-root086-vtk-support-qa-v2.json"
FINE_RECEIPT = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/execution-receipt.json"
FINE_XML = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED.xml"
FINE_SUPPORT = DATA_ROOT / "families/F3/F3_S2_DP003_ACTUAL_INITIAL_SUPPORT_QA_ROOT_104/f3-s2-dp003-initial-support-qa-v1-root-104-001-root-forward-030-001/f3-s2-dp003-initial-support-qa-v1.json"
COARSE_SUPPORT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_SUPPORT_V6_ACTUAL_ROOT_VERIFICATION_128.json"
SOURCE_XML = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"


class InputChangedError(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "dev": int(value.st_dev),
        "ino": int(value.st_ino),
    }


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_stable(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> tuple[bytes, dict[str, Any]]:
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise ValueError(f"bounded metadata input exceeds {max_bytes} bytes: {path}")
    data = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise InputChangedError(f"input changed during read: {path}")
    record = dict(after)
    record["sha256"] = _sha_bytes(data)
    return data, record


def _read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data, record = _read_stable(path)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON input is not an object: {path}")
    return value, record


def _read_text(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> tuple[str, dict[str, Any]]:
    data, record = _read_stable(path, max_bytes=max_bytes)
    return data.decode("utf-8", errors="replace"), record


def _finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def _atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _contains(value: Any, target: str) -> bool:
    if isinstance(value, str):
        return value == target
    if isinstance(value, dict):
        return any(_contains(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, target) for item in value)
    return False


def _bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        return {"query_time_s": query, "status": "REJECT_NONFINITE_QUERY"}
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {
            "query_time_s": query,
            "status": "OUTSIDE_SAVED_WINDOW",
            "window_s": [rows[0]["time_s"], rows[-1]["time_s"]],
            "field_interpolation": "FORBIDDEN",
        }
    for row in rows:
        if abs(row["time_s"] - query) <= 1.0e-12:
            return {
                "query_time_s": query,
                "status": "EXACT",
                "lower_frame": row["frame"],
                "upper_frame": row["frame"],
                "lower_time_s": row["time_s"],
                "upper_time_s": row["time_s"],
                "field_interpolation": "FORBIDDEN",
            }
    for left, right in zip(rows, rows[1:]):
        if left["time_s"] < query < right["time_s"]:
            fraction = (query - left["time_s"]) / (right["time_s"] - left["time_s"])
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": left["frame"],
                "upper_frame": right["frame"],
                "lower_time_s": left["time_s"],
                "upper_time_s": right["time_s"],
                "bracket_fraction_for_diagnostic_only": fraction,
                "field_interpolation": "FORBIDDEN",
            }
    raise AssertionError(f"could not bracket finite query {query}")


def _read_runparts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text, record = _read_text(path)
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(lines, delimiter=";"):
        part_raw = str(raw.get("Part", "")).strip()
        time_raw = str(raw.get("TimeStep [s]", "")).strip()
        part_match = re.match(r"^(\d+)", part_raw)
        time_match = re.match(r"^([^#\s]+)", time_raw)
        if not part_match or not time_match:
            continue
        part = int(part_match.group(1))
        rows.append({"frame": part, "time_s": _finite(time_match.group(1), f"RunPARTs frame {part} time")})
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    rows.sort(key=lambda item: item["frame"])
    if [item["frame"] for item in rows] != list(range(len(rows))):
        raise ValueError("coarse RunPARTs frame IDs are not contiguous from zero")
    if any(b["time_s"] <= a["time_s"] for a, b in zip(rows, rows[1:])):
        raise ValueError("coarse RunPARTs times are not strictly increasing")
    return rows, record


def _validate_identity(plan: dict[str, Any], contract: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("matched-three-grid plan schema drift")
    if plan.get("family_id") != FAMILY_ID or plan.get("sentinel_id") != SENTINEL_ID:
        raise ValueError("plan family/sentinel identity drift")
    if plan.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("plan physical case identity drift")
    owner = plan.get("owner_contract", {})
    if owner.get("continuous_owner_mass_kg") != OWNER_MASS_KG:
        raise ValueError("owner mass is not the frozen 14.58 kg contract")
    window = plan.get("future_solver_shape", {}).get("window_s")
    if window != list(SOURCE_WINDOW_S):
        raise ValueError(f"solver window drift: {window!r}")
    source = plan.get("source_binding", {})
    if SOURCE_CONTROL_SHA not in str(source.get("current_forcing", {}).get("sha256")):
        raise ValueError("plan current forcing SHA is not the registered current control")
    # The plan intentionally mentions the historical 6f426... record as an
    # excluded diagnostic.  Presence of that prose is not a control join;
    # the structured current_forcing SHA above is the authority.
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("observer calibration contract schema drift")
    if contract.get("family_id") != FAMILY_ID or contract.get("sentinel_id") != SENTINEL_ID:
        raise ValueError("observer calibration identity drift")
    if contract.get("source_particles", {}).get("fluid_sample_mass_kg") != OWNER_MASS_KG:
        raise ValueError("observer contract owner mass drift")
    if contract.get("event_time", {}).get("characteristic_time_s") not in (None, "UNKNOWN", "UNKNOWN_NO_SOURCE_EVENT_DEFINITION"):
        raise ValueError("event time was silently assigned from a non-source window")


def _validate_proof(proof: dict[str, Any], proof_record: dict[str, Any]) -> None:
    if proof_record.get("sha256") != ROOT150_PROOF_SHA:
        raise ValueError("ROOT150 proof file SHA drift")
    if proof.get("schema") != ROOT_PROOF_SCHEMA:
        raise ValueError("ROOT150 proof schema drift")
    if proof.get("status") != "VERIFIED_ACTUAL_F3_ALL836_NATIVE_FIELDS_IDENTITIES_AND_HEADER_DIAGNOSTICS":
        raise ValueError("ROOT150 proof is not the completed full836 verification")
    if proof.get("request_sha256") != "482a4a5b045bcb1225c4f604a47289734db04f6788d3aa3615c04b84f6d3f4ec":
        raise ValueError("ROOT150 request SHA drift")
    if proof.get("report_sha256") != ROOT150_REPORT_SHA or proof.get("report_bytes") != ROOT150_REPORT_BYTES:
        raise ValueError("ROOT150 report binding drift")
    if proof.get("frame_count") != 836 or proof.get("all836_active_PosVelRhop_finite") is not True:
        raise ValueError("ROOT150 full836 finite/frame proof missing")
    if proof.get("all24264_IDs_observed_all836_frames") is not True:
        raise ValueError("ROOT150 identity coverage proof missing")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("root_array_content_read") is not False:
        raise ValueError("ROOT150 scope no-array/no-H5 contract drift")
    qual = proof.get("scientific_qualification", {})
    if any(qual.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        raise ValueError("ROOT150 unexpectedly grants scientific qualification")


def _validate_receipt(receipt: dict[str, Any], physical_case: str, label: str) -> None:
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{label} receipt is not a completed successful GenCase receipt")
    request = receipt.get("request", {})
    if isinstance(request, dict) and request.get("physical_case_id") not in (None, physical_case):
        raise ValueError(f"{label} receipt physical identity drift")
    if receipt.get("cfd_invoked") is True or receipt.get("model_invoked") is True:
        raise ValueError(f"{label} evidence unexpectedly invokes CFD/model")


def build_report(*, plan_path: Path, contract_path: Path, proof_path: Path, root133_proof_path: Path, root133_request_path: Path, root133_receipt_path: Path, runparts_path: Path) -> dict[str, Any]:
    plan, plan_record = _read_json(plan_path)
    contract, contract_record = _read_json(contract_path)
    proof, proof_record = _read_json(proof_path)
    root133_proof, root133_proof_record = _read_json(root133_proof_path)
    root133_request, root133_request_record = _read_json(root133_request_path)
    root133_receipt, root133_receipt_record = _read_json(root133_receipt_path)
    _validate_identity(plan, contract)
    _validate_proof(proof, proof_record)
    if root133_proof_record.get("sha256") != ROOT133_PROOF_SHA:
        raise ValueError("ROOT133 proof file SHA drift")
    if root133_proof.get("schema") != "ds02.stage2.root-actual-external-solver-verification.v1" or root133_proof.get("status") != "VERIFIED_ACTUAL_F3_DP015_NATIVE_WINDOW_CONTROL_MATERIALIZATION_NO_SCIENTIFIC_Q":
        raise ValueError("ROOT133 coarse actual proof schema/status drift")
    if root133_request.get("physical_case_id") != PHYSICAL_CASE_ID or root133_request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("ROOT133 source request identity/status drift")
    if not _contains(root133_request, SOURCE_CONTROL_SHA):
        raise ValueError("ROOT133 source request does not bind the current forcing SHA")
    if root133_receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN" or root133_receipt.get("request", {}).get("sha256") != ROOT133_REQUEST_SHA:
        raise ValueError("ROOT133 actual solver receipt identity/status drift")
    if root133_receipt.get("cfd_invoked") is not True or root133_receipt.get("model_invoked") is True:
        raise ValueError("ROOT133 receipt does not prove the expected external solver scope")
    rows, runparts_record = _read_runparts(runparts_path)
    if len(rows) != proof.get("frame_count"):
        raise ValueError("ROOT150 frame count and ROOT133 RunPARTs row count differ")
    expected_final = float(proof["time_window"]["last_saved_time_s"])
    if abs(rows[-1]["time_s"] - expected_final) > 1.0e-12:
        raise ValueError("ROOT133 RunPARTs endpoint differs from ROOT150 verified endpoint")
    brackets = [_bracket(rows, value) for value in QUERY_TIMES_S]

    grids = plan["grid_ladder"]
    middle = grids["current_source_middle_dp0.006"]
    fine = grids["actual_owner_fine_dp0.003"]
    for path, label in ((Path(middle["source_gencase"]["receipt"]), "middle"), (Path(fine["source_gencase"]["receipt"]), "fine")):
        value, _ = _read_json(path)
        _validate_receipt(value, PHYSICAL_CASE_ID, label)
    middle_support, middle_support_record = _read_json(Path(middle["support_evidence"]["report"]))
    fine_support, fine_support_record = _read_json(Path(fine["support_evidence"]["report"]))
    for value, label in ((middle_support, "middle support"), (fine_support, "fine support")):
        if value.get("physical_case_id") != PHYSICAL_CASE_ID:
            raise ValueError(f"{label} physical identity drift")
        source_control = value.get("source", {}).get("control", {}).get("sha256")
        if source_control != SOURCE_CONTROL_SHA:
            raise ValueError(f"{label} does not bind current forcing SHA")

    def mass_audit(sample: float) -> dict[str, Any]:
        relative = (sample - OWNER_MASS_KG) / OWNER_MASS_KG
        return {
            "sample_mass_kg": sample,
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "relative_error": relative,
            "preferred_gate_le_1_percent": abs(relative) <= 0.01,
            "hard_fail_gt_2_percent": abs(relative) > 0.02,
            "mass_rescale": False,
            "semantics": "discrete_generated_sample_diagnostic; not a proof of continuum equivalence",
        }

    coarse_mass = float(proof["native_fluid_sample_mass_kg"])
    middle_mass = float(middle["actual_mass"]["sample_mass_kg"])
    fine_mass = float(fine["actual_mass"]["sample_mass_kg"])
    proof_time = proof["time_window"]
    root133_charge = root133_proof.get("parent_charge")

    return {
        "schema": SCHEMA,
        "status": "PASS_SOURCE_BOUND_METADATA_MIDDLE_STAGING_QA_NO_SOLVER",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "scope": {
            "purpose": "Use the completed F3 dp015 coarse provenance to close common timestamps and decide whether the dp006 middle source is the next parent-reviewed canary before dp003.",
            "worker_reads": ["small JSON plans/proofs/receipts/support reports", "coarse RunPARTs.csv time axis"],
            "worker_does_not_read": ["ROOT150 observer report payload", "BI4", "VTK", "HDF5", "forcing CSV", "solver task or native particle arrays"],
            "native_field_values": "DEFERRED_TO_PARENT_NATIVE_OBSERVER; ROOT150 proof facts are not re-read as arrays",
            "old_products_modified": False,
            "solver_started": False,
            "gpu_started": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_records": {
            "plan": plan_record,
            "observer_contract": contract_record,
            "root150_proof": {"path": str(proof_path.resolve()), "sha256": ROOT150_PROOF_SHA, "content_scope": "small parent verification; no native field payload read"},
            "root150_report": {"path": str(ROOT150_REPORT), "bytes": ROOT150_REPORT_BYTES, "sha256": ROOT150_REPORT_SHA, "read_by_worker": False, "hash_authority": "ROOT150 proof"},
            "root150_receipt": {"path": str(ROOT150_RECEIPT), "sha256": ROOT150_RECEIPT_SHA, "read_by_worker": False},
            "root133_request": root133_request_record,
            "root133_receipt": root133_receipt_record,
            "root133_proof": {"path": str(root133_proof_path.resolve()), "sha256": ROOT133_PROOF_SHA, "content_scope": "small parent solver verification"},
            "root133_runparts": {**runparts_record, "sha256": ROOT133_RUNPARTS_SHA, "content_scope": "actual coarse timestamp axis only"},
            "current_forcing": {"path": str(plan["source_binding"]["current_forcing"]["path"]), "bytes": plan["source_binding"]["current_forcing"]["bytes"], "sha256": SOURCE_CONTROL_SHA, "read_by_worker": False, "full_hash_by_worker": False, "hash_authority": "existing source plan and ROOT133 source request"},
        },
        "owner_and_control": {
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "continuous_owner_geometry": plan["owner_contract"],
            "current_control_sha256": SOURCE_CONTROL_SHA,
            "current_source_xml_sha256": plan["source_binding"]["current_xml"]["sha256"],
            "historical_control_excluded": "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3",
            "continuous_owner_equivalence": "UNKNOWN_FOR_ALL_THREE; particle support and sample mass do not prove continuum/contact/flux equivalence",
        },
        "initial_grid_audit": {
            "coarse_dp0.015": {
                "role": "ACTUAL_ROOT133/ROOT150_COARSE",
                "dp_m": 0.015,
                "counts": {"fluid": 4320, "fixed": 19944, "total": 24264},
                "mass": mass_audit(coarse_mass),
                "support": "ROOT128_DISCRETE_OWNER_ENVELOPE_ONLY",
                "control_identity": "PASS_SOURCE_REQUEST_AND_ROOT133_PROOF",
                "solver_observables": "ROOT150_FULL836_FIELDS_VERIFIED_BY_PARENT_PROOF; this worker does not read them",
                "continuous_equivalence": "UNKNOWN",
            },
            "middle_dp0.006": {
                "role": "EXISTING_OWNER_CENTERED_INITIAL_SOURCE",
                "dp_m": 0.006,
                "counts": middle["actual_counts"],
                "mass": mass_audit(middle_mass),
                "support": "LIMITED_DISCRETE_SUPPORT_CURRENT_CONTROL_REPORT; NO_NO_PENETRATION_OR_FLUX_CREDIT",
                "control_identity": "PASS_METADATA_CURRENT_SHA",
                "solver_observables": "NOT_AVAILABLE",
                "continuous_equivalence": "UNKNOWN",
                "solver_release": "BLOCKED_UNTIL_PARENT_CURRENT_CONTROL_SUPPORT_JOIN_AND_RESOURCE_REVIEW",
            },
            "fine_dp0.003": {
                "role": "EXISTING_OWNER_CENTERED_INITIAL_SOURCE",
                "dp_m": 0.003,
                "counts": fine["actual_counts"],
                "mass": mass_audit(fine_mass),
                "support": "LIMITED_DISCRETE_OWNER_ENVELOPE_SUPPORT; NO_NO_PENETRATION_OR_FLUX_CREDIT",
                "control_identity": "PASS_METADATA_CURRENT_SHA",
                "solver_observables": "NOT_AVAILABLE",
                "continuous_equivalence": "UNKNOWN",
                "solver_release": "DEFER_UNTIL_MIDDLE_TERMINAL_AND_COST_RECEIPT",
            },
        },
        "actual_coarse_time_and_output": {
            "source": "ROOT133 RunPARTs.csv, stable bounded read; ROOT150 proof/report remain parent authority for decoded fields",
            "frame_count": len(rows),
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "registered_source_window_s": list(SOURCE_WINDOW_S),
            "root150_verified_window": [proof_time["first_saved_time_s"], proof_time["last_saved_time_s"]],
            "query_brackets": brackets,
            "field_interpolation": "FORBIDDEN",
            "endpoint_policy": "source endpoint is bracketed/exact only according to actual rows; no terminal extrapolation",
            "common_observables": ["mass_by_mk", "weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j", "region_assignment", "finite_Pos_Vel_Rhop"],
            "field_value_status": "UNKNOWN_TO_THIS_WORKER; no native payload read",
        },
        "cost_and_staging": {
            "actual_root133_solver": {
                "gpu_seconds": None if root133_charge is None else root133_charge.get("gpu_seconds"),
                "cpu_core_seconds": None if root133_charge is None else root133_charge.get("cpu_core_seconds"),
                "new_storage_bytes": None if root133_charge is None else root133_charge.get("new_storage_bytes"),
                "basis": "ROOT133 parent proof; full coarse source-bound solver actual",
            },
            "actual_root150_observer": {
                "cpu_core_seconds": proof.get("full_systemd_cpu_seconds"),
                "new_storage_bytes": proof.get("actual_tree_bytes"),
                "native_input_bytes": proof.get("actual_native_total_bytes"),
                "basis": "bounded selected/full836 observer, not a new solver-output estimate",
            },
            "middle_dp0.006_full_window_proxy": {
                "receipt_charge_bytes_proxy": 6604181245,
                "storage_gib_proxy": 6.1506230803,
                "basis": "historical same-forcing ROOT706 baseline formula from plan; not a middle solver result",
                "status": "PLANNING_PROXY_ONLY",
            },
            "fine_dp0.003_full_window_proxy": {
                "receipt_charge_bytes_proxy": 35971428340,
                "storage_gib_proxy": 33.5010032543,
                "basis": "same historical baseline particle-count proxy from plan; not a fine solver result",
                "status": "PLANNING_PROXY_ONLY",
            },
            "staged_next": {
                "step_1": "Use this metadata closure and parent review to select one dp0.006 same-CFL full-window canary; preserve [0,8.350016881886734], actual RunPARTs/Run.out/DtAllInfo/DTsMin and output receipt are mandatory.",
                "step_2": "Only after the middle terminal receipt and common-time field/output audit, review dp0.003; no simultaneous fine launch.",
                "half_cfl": "Separate source-bound overlay, not implied by this QA; actual dt/clamp/terminal time remain UNKNOWN.",
                "dense_output": "-tout:0.005 is a separate parent-reviewed output request; no 2x storage or error credit is granted here.",
            },
        },
        "frozen_calibration": {
            "position_L_m": 0.894,
            "velocity_scale_m_s": 0.9077664897978995,
            "kinetic_energy_scale_j": 6.0072516,
            "position_tolerance_fraction_L": 0.02,
            "velocity_and_ke_tolerance_fraction_scale": 0.05,
            "event_time_T": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "time_and_output_budget_each_fraction": 0.25,
            "time_output_semantics": "task budget share, not an automatic per-bracket error bound",
            "no_neighbor_grid_truth": True,
            "no_particle_interpolation": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--calibration-contract", type=Path, default=CONTRACT)
    parser.add_argument("--root150-proof", type=Path, default=ROOT150_PROOF)
    parser.add_argument("--root133-proof", type=Path, default=ROOT133_PROOF)
    parser.add_argument("--root133-request", type=Path, default=ROOT133_REQUEST)
    parser.add_argument("--root133-receipt", type=Path, default=ROOT133_RECEIPT)
    parser.add_argument("--runparts", type=Path, default=ROOT133_RUNPARTS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    report = build_report(
        plan_path=args.plan.expanduser().resolve(),
        contract_path=args.calibration_contract.expanduser().resolve(),
        proof_path=args.root150_proof.expanduser().resolve(),
        root133_proof_path=args.root133_proof.expanduser().resolve(),
        root133_request_path=args.root133_request.expanduser().resolve(),
        root133_receipt_path=args.root133_receipt.expanduser().resolve(),
        runparts_path=args.runparts.expanduser().resolve(),
    )
    if args.self_test:
        assert report["status"] == "PASS_SOURCE_BOUND_METADATA_MIDDLE_STAGING_QA_NO_SOLVER"
        assert report["scope"]["solver_started"] is False
        assert report["scope"]["gpu_started"] is False
        assert report["scope"]["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
        assert report["actual_coarse_time_and_output"]["frame_count"] == 836
        assert report["owner_and_control"]["current_control_sha256"] == SOURCE_CONTROL_SHA
        print(json.dumps({"status": "PASS", "schema": SCHEMA, "frame_count": 836, "native_payload_read": False, "forcing_read": False}, indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    _atomic_json(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
