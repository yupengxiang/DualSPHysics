#!/usr/bin/env python3
"""Prepare the ROOT150 F3 full-window native stream request.

This is a forward-only builder.  It reuses the immutable V2 full-stream
worker/request shape, but releases a new request only after joining the
*actual* ROOT147 request, terminal receipt, ten-frame report, and independent
verification proof.  The join is metadata-only: this file reads JSON/source
metadata and never opens a Part payload.  The full 836-frame worker remains a
parent-guarded CPU task and keeps QI/QN/QE UNKNOWN.

The consumed V2 builder and request are intentionally left untouched.  A
failed or incomplete ROOT147 gate raises before a request is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

import stage2_f3_s2_full_native_stream_request_v2 as base


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.full-native-stream-request.v3"
EXPECTED_STATUS = "READY_FOR_PARENT_GUARD"

FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
FRAMES = list(range(base.EXPECTED_FRAME_COUNT))
TEN_FRAMES = [0, 199, 200, 399, 400, 599, 600, 799, 800, 835]
FINAL_TIME_S = base.FINAL_TIME_S

ROOT147_REQUEST = base.MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f3-s2-coarse-ten-native-header-audit-v1-root-forward-147-001.json"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT147_RECEIPT = DATA_ROOT / (
    "families/F3/F3_S2_COARSE_TEN_NATIVE_HEADER_AUDIT_ROOT_147/"
    "f3-s2-coarse-ten-native-header-audit-root-147-001-root-forward-030-001/"
    "execution-receipt.json"
)
ROOT147_REPORT = ROOT147_RECEIPT.parent / "observer/f3_s2_coarse_native_header_root147.json"
ROOT147_PROOF = base.MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "F3_TEN_FRAME_NATIVE_HEADER_ACTUAL_LIMITED_ROOT_VERIFICATION_147.json"
)

ROOT147_REQUEST_SHA = "15a9908ea5de00f911533cbea6bb9c2d69a66bb20a0b15b4c5813be6cd45a511"
ROOT147_RECEIPT_SHA = "1f27f5352447ec22d17e9209a764bd67380e2189948b4d74832df309594c5ea4"
ROOT147_REPORT_SHA = "f958813c40ac4d067e52a529e30af2c347c0c422f50eda02e3b0210275b022b2"
ROOT147_PROOF_SHA = "3a1fa958831db3f17c1e50426d4c3403853a5ca4599fbe240ff1504e3c903a25"
ROOT147_NATIVE_MASS_FLUID = 0.003375000087544322
ROOT147_NATIVE_MASS_HEX = "00000060e3a56b3f"
ROOT147_NATIVE_SAMPLE_MASS = 14.580000378191471
ROOT147_NATIVE_PARTICLE_COUNT = 4320

DEFAULT_OUTPUT = base.REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f3-s2-full-native-stream-v3-root150-001.json"
)
OUTPUT_PATH = "{attempt_root}/observer/f3_s2_full_native_stream_v3_root150.json"


class GateError(ValueError):
    """ROOT147 did not provide the exact source-bound release evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise GateError(f"{label} is missing or symlinked: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} is not a JSON object: {path}")
    return value


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def _identity(value: dict[str, Any], label: str) -> None:
    for key, expected in (
        ("family_id", FAMILY_ID),
        ("sentinel_id", SENTINEL_ID),
        ("physical_case_id", PHYSICAL_CASE_ID),
    ):
        _expect(value.get(key) == expected, f"{label} {key} is not the F3-S2 identity")


def _finite_number(value: Any, label: str) -> None:
    _expect(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} is not numeric")
    _expect(math.isfinite(float(value)), f"{label} is not finite")


def _snapshot_records() -> dict[int, dict[str, Any]]:
    """Read the ROOT139 wrapper's ten small source records, never BI4 bytes."""

    snapshot = _json(base.TEN_MANIFEST, "ROOT139 snapshot wrapper")
    records = snapshot.get("immutable_source_sha_list")
    _expect(isinstance(records, list) and len(records) == len(TEN_FRAMES), "ROOT139 source list is not ten frames")
    result: dict[int, dict[str, Any]] = {}
    for item in records:
        _expect(isinstance(item, dict), "ROOT139 source record is not an object")
        frame = item.get("frame")
        _expect(frame in TEN_FRAMES, f"ROOT139 source record has unexpected frame {frame!r}")
        result[int(frame)] = {
            "path": item.get("path"),
            "bytes": item.get("bytes"),
            "sha256": item.get("sha256"),
        }
    _expect(sorted(result) == TEN_FRAMES, "ROOT139 source list does not close the ten-frame axis")
    return result


def _validate_source_records(report: dict[str, Any]) -> None:
    expected = _snapshot_records()
    integrity = report.get("source_integrity")
    _expect(isinstance(integrity, dict), "ROOT147 report has no source_integrity")
    _expect(integrity.get("status") == "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT", "ROOT147 source guard did not pass")
    _expect(integrity.get("pre_post_sha_and_stat_equal") is True, "ROOT147 pre/post SHA/stat closure is absent")
    _expect(integrity.get("cross_decode_stat_boundaries_equal") is True, "ROOT147 cross-decode stat closure is absent")
    pre = integrity.get("pre_decode_records")
    post = integrity.get("post_decode_records")
    _expect(isinstance(pre, list) and len(pre) == len(TEN_FRAMES), "ROOT147 pre-decode records are incomplete")
    _expect(isinstance(post, list) and len(post) == len(TEN_FRAMES), "ROOT147 post-decode records are incomplete")
    for label, records in (("pre", pre), ("post", post)):
        seen: set[int] = set()
        for item in records:
            _expect(isinstance(item, dict), f"ROOT147 {label} record is not an object")
            frame = item.get("frame")
            _expect(frame in expected and frame not in seen, f"ROOT147 {label} frame axis is invalid: {frame!r}")
            seen.add(frame)
            source = expected[frame]
            _expect(item.get("path") == source["path"], f"ROOT147 {label} frame {frame} path differs from ROOT139")
            _expect(item.get("bytes") == source["bytes"], f"ROOT147 {label} frame {frame} bytes differ from ROOT139")
            _expect(item.get("sha256") == source["sha256"], f"ROOT147 {label} frame {frame} SHA differs from ROOT139")
            stat_before = item.get("stat_before")
            stat_after = item.get("stat_after")
            _expect(isinstance(stat_before, dict) and isinstance(stat_after, dict), f"ROOT147 {label} frame {frame} lacks stat closure")
            _expect(stat_before == stat_after, f"ROOT147 {label} frame {frame} stat changed during hash")
        _expect(seen == set(expected), f"ROOT147 {label} records do not close the ten-frame axis")


def _validate_observations(report: dict[str, Any]) -> dict[str, Any]:
    observations = report.get("observations")
    _expect(isinstance(observations, list) and len(observations) == len(TEN_FRAMES), "ROOT147 observations are not ten frames")
    seen: set[int] = set()
    masses: list[float] = []
    sample_masses: list[float] = []
    for item in observations:
        _expect(isinstance(item, dict), "ROOT147 observation is not an object")
        frame = item.get("frame")
        _expect(frame in TEN_FRAMES and frame not in seen, f"ROOT147 observation frame is invalid: {frame!r}")
        seen.add(frame)
        finite = item.get("finite_fields")
        _expect(isinstance(finite, dict) and finite.get("status") == "PASS_FINITE", f"ROOT147 frame {frame} finite check failed")
        _expect(all(finite.get(key) is True for key in ("Idp", "Pos_or_Posd", "Vel", "Rhop")), f"ROOT147 frame {frame} has nonfinite fields")
        identity = item.get("identity")
        _expect(isinstance(identity, dict) and identity.get("status") == "PASS_XML_TYPED_RANGE_COVERAGE", f"ROOT147 frame {frame} identity check failed")
        _expect(identity.get("id_unique") is True, f"ROOT147 frame {frame} Idp uniqueness failed")
        header = item.get("native_header")
        _expect(isinstance(header, dict), f"ROOT147 frame {frame} has no native header")
        for field in ("MassFluid", "MassBound"):
            scalar = header.get(field)
            _expect(isinstance(scalar, dict), f"ROOT147 frame {frame} has no {field} scalar")
            _expect(scalar.get("field") == field, f"ROOT147 frame {frame} {field} field label differs")
            _expect(scalar.get("decoder_section") == "metadata", f"ROOT147 frame {frame} {field} is not decoder metadata")
            _finite_number(scalar.get("value"), f"ROOT147 frame {frame} {field}")
            _expect(float(scalar["value"]) == ROOT147_NATIVE_MASS_FLUID, f"ROOT147 frame {frame} {field} differs from the actual gate scalar")
            _expect(scalar.get("value_binary64_little_endian_hex") == ROOT147_NATIVE_MASS_HEX, f"ROOT147 frame {frame} {field} binary view differs")
            masses.append(float(scalar["value"])) if field == "MassFluid" else None
        observable = item.get("fluid_observable_using_native_header_mass")
        _expect(isinstance(observable, dict), f"ROOT147 frame {frame} has no mass-weighted observable")
        _expect(observable.get("fluid_count") == ROOT147_NATIVE_PARTICLE_COUNT, f"ROOT147 frame {frame} fluid count differs")
        _finite_number(observable.get("sample_mass_kg"), f"ROOT147 frame {frame} sample mass")
        _expect(float(observable["sample_mass_kg"]) == ROOT147_NATIVE_SAMPLE_MASS, f"ROOT147 frame {frame} sample mass differs")
        sample_masses.append(float(observable["sample_mass_kg"]))
    _expect(seen == set(TEN_FRAMES), "ROOT147 observations do not close the ten-frame axis")
    _expect(len(set(masses)) == 1 and len(set(sample_masses)) == 1, "ROOT147 native mass is not exact across selected frames")
    return {
        "selected_massfluid_kg": ROOT147_NATIVE_MASS_FLUID,
        "selected_sample_mass_kg": ROOT147_NATIVE_SAMPLE_MASS,
        "fluid_count": ROOT147_NATIVE_PARTICLE_COUNT,
        "selected_frame_ids": list(TEN_FRAMES),
    }


def validate_ten_probe(
    request: dict[str, Any],
    receipt: dict[str, Any],
    report: dict[str, Any],
    proof: dict[str, Any],
    *,
    request_sha: str,
    receipt_sha: str,
    report_sha: str,
    proof_sha: str,
    check_snapshot_records: bool = True,
) -> dict[str, Any]:
    """Validate the small ROOT147 evidence join without opening native data."""

    _expect(request.get("schema") == REQUEST_SCHEMA, "ROOT147 request schema differs")
    _expect(request.get("variant_schema") == "ds02.stage2.f3-s2.native-header-root147-request.v1", "ROOT147 request variant differs")
    _identity(request, "ROOT147 request")
    _expect(request.get("case_id") == "F3_S2_COARSE_TEN_NATIVE_HEADER_AUDIT_ROOT_147", "ROOT147 request case differs")
    _expect(request.get("attempt_id") == "f3-s2-coarse-ten-native-header-audit-root-147-001-root-forward-030-001", "ROOT147 request attempt differs")
    _expect(request.get("selected_native_frame_ids") == TEN_FRAMES, "ROOT147 request selected frame axis differs")
    _expect(request.get("execution_allowed") is True and request.get("launch_disabled") is False, "ROOT147 request was not the actual enabled request")
    source_binding = request.get("source_binding")
    _expect(isinstance(source_binding, dict), "ROOT147 request has no source binding")
    root139 = source_binding.get("root139_snapshot_wrapper")
    _expect(isinstance(root139, dict), "ROOT147 request has no ROOT139 wrapper binding")
    _expect(root139.get("path") == str(base.TEN_MANIFEST.resolve()), "ROOT147 request ROOT139 path differs")
    _expect(root139.get("sha256") == base.sha256_file(base.TEN_MANIFEST), "ROOT147 request ROOT139 SHA differs")
    _expect(root139.get("selected_frame_ids") == TEN_FRAMES, "ROOT147 request ROOT139 frame axis differs")
    _expect(root139.get("identity", {}).get("family_id") == FAMILY_ID, "ROOT147 request ROOT139 family differs")
    _expect(root139.get("identity", {}).get("sentinel_id") == SENTINEL_ID, "ROOT147 request ROOT139 sentinel differs")
    _expect(root139.get("identity", {}).get("physical_case_id") == PHYSICAL_CASE_ID, "ROOT147 request ROOT139 physical case differs")

    _expect(receipt.get("schema") == "ds02.execution-receipt.v1", "ROOT147 receipt schema differs")
    _expect(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "ROOT147 receipt is not a successful terminal receipt")
    _expect(receipt.get("request_sha256") == request_sha, "ROOT147 receipt request SHA differs")
    _expect(receipt.get("request") == request, "ROOT147 receipt request object differs from the actual request")

    _expect(report.get("schema") == "ds02.stage2.f3-s2.native-header-observer.v1", "ROOT147 report schema differs")
    _expect(report.get("status") == "PASS_DECODED_SELECTED_NATIVE_FIELDS", "ROOT147 report status is not a decode pass")
    scope = report.get("scope")
    _expect(isinstance(scope, dict), "ROOT147 report has no scope")
    _expect(scope.get("selected_frames_only") is True and scope.get("selected_frame_count") == 10, "ROOT147 report is not selected-ten scope")
    _expect(scope.get("runparts_frame_count") == base.EXPECTED_FRAME_COUNT, "ROOT147 report does not bind the complete 836-frame axis")
    _expect(scope.get("full_native_tree_scanned") is False and scope.get("hdf5_read") is False, "ROOT147 report exceeded bounded scope")
    _expect(scope.get("native_header_mass_audited") is True, "ROOT147 report did not audit native header mass")
    _expect(report.get("source", {}).get("selected_frames") == TEN_FRAMES, "ROOT147 report source frame axis differs")
    _validate_source_records(report) if check_snapshot_records else None
    summary = _validate_observations(report)
    _expect(report.get("scientific_qualification") == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "ROOT147 report granted scientific qualification")

    _expect(proof.get("schema") == "ds02.stage2.root-actual-verification.v1", "ROOT147 proof schema differs")
    _expect(proof.get("request_sha256") == request_sha, "ROOT147 proof request SHA differs")
    _expect(proof.get("receipt_sha256") == receipt_sha, "ROOT147 proof receipt SHA differs")
    _expect(proof.get("report_sha256") == report_sha, "ROOT147 proof report SHA differs")
    _expect(proof.get("selected_frames") == TEN_FRAMES, "ROOT147 proof frame axis differs")
    _expect(proof.get("all_ten_current_stat_prepost_source_SHA_join") is True, "ROOT147 proof lacks source pre/post closure")
    _expect(proof.get("all_selected_finite_and_unique") is True, "ROOT147 proof lacks finite/unique closure")
    _expect(proof.get("full836_native_fields_audited") is False, "ROOT147 proof incorrectly claims full836 audit")
    _expect(proof.get("root_array_content_read") is False, "ROOT147 proof claims root array reads")
    _expect(proof.get("scientific_qualification") == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "ROOT147 proof granted scientific qualification")
    _expect(proof.get("native_header_massfluid_kg") == ROOT147_NATIVE_MASS_FLUID, "ROOT147 proof native mass differs")
    _expect(proof.get("native_selected_sample_mass_kg") == ROOT147_NATIVE_SAMPLE_MASS, "ROOT147 proof sample mass differs")
    return {
        "status": "PASS_ROOT147_TEN_FRAME_GATE",
        "request_sha256": request_sha,
        "receipt_sha256": receipt_sha,
        "report_sha256": report_sha,
        "proof_sha256": proof_sha,
        **summary,
        "full836_native_fields_audited": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def validate_actual_root147() -> dict[str, Any]:
    """Validate the immutable actual ROOT147 metadata and its proof SHA joins."""

    for path, label in (
        (ROOT147_REQUEST, "ROOT147 request"),
        (ROOT147_RECEIPT, "ROOT147 receipt"),
        (ROOT147_REPORT, "ROOT147 report"),
        (ROOT147_PROOF, "ROOT147 verification proof"),
    ):
        _regular(path, label)
    observed = {
        "request_sha256": sha256_file(ROOT147_REQUEST),
        "receipt_sha256": sha256_file(ROOT147_RECEIPT),
        "report_sha256": sha256_file(ROOT147_REPORT),
        "proof_sha256": sha256_file(ROOT147_PROOF),
    }
    expected = {
        "request_sha256": ROOT147_REQUEST_SHA,
        "receipt_sha256": ROOT147_RECEIPT_SHA,
        "report_sha256": ROOT147_REPORT_SHA,
        "proof_sha256": ROOT147_PROOF_SHA,
    }
    _expect(observed == expected, f"ROOT147 artifact SHA mismatch: expected={expected}, observed={observed}")
    request = _json(ROOT147_REQUEST, "ROOT147 request")
    receipt = _json(ROOT147_RECEIPT, "ROOT147 receipt")
    report = _json(ROOT147_REPORT, "ROOT147 report")
    proof = _json(ROOT147_PROOF, "ROOT147 verification proof")
    _expect(proof.get("request") == str(ROOT147_REQUEST.resolve()), "ROOT147 proof request path differs")
    _expect(proof.get("receipt") == str(ROOT147_RECEIPT.resolve()), "ROOT147 proof receipt path differs")
    _expect(proof.get("report") == str(ROOT147_REPORT.resolve()), "ROOT147 proof report path differs")
    return validate_ten_probe(
        request, receipt, report, proof,
        request_sha=observed["request_sha256"],
        receipt_sha=observed["receipt_sha256"],
        report_sha=observed["report_sha256"],
        proof_sha=observed["proof_sha256"],
    )


def _record_small(path: Path, label: str) -> dict[str, Any]:
    return base.small_record(path, label)


def build(output: Path, *, case_id: str, attempt_id: str, launch_commit: str) -> dict[str, Any]:
    gate = validate_actual_root147()
    request = base.build(output, case_id=case_id, attempt_id=attempt_id, launch_commit=launch_commit)

    # Add the actual ROOT147 three-way evidence to the new request's charged
    # metadata closure.  These are JSON files only; Part payloads remain
    # deferred to the V2 worker after the parent reservation.
    gate_files = [
        (ROOT147_REQUEST, "ROOT147 actual request"),
        (ROOT147_RECEIPT, "ROOT147 terminal receipt"),
        (ROOT147_REPORT, "ROOT147 ten-frame report"),
        (ROOT147_PROOF, "ROOT147 independent verification proof"),
    ]
    records = {str(path.expanduser().resolve()): _record_small(path, label) for path, label in gate_files}
    builder_record = _record_small(Path(__file__), "ROOT150 full-stream request builder")
    records[builder_record["path"]] = builder_record
    input_files = sorted(set(request["input_files"]) | set(records))
    request["input_files"] = input_files
    request["input_sha256"] = {
        path: (records[path]["sha256"] if path in records else request["input_sha256"][path])
        for path in input_files
    }

    request["variant_schema"] = SCHEMA
    request["status"] = EXPECTED_STATUS
    request["execution_allowed"] = True
    request["launch_disabled"] = False
    request["solver_started"] = False
    request["output"] = {
        "atomic": True,
        "refuse_overwrite": True,
        "path": OUTPUT_PATH,
    }
    try:
        output_index = request["command"].index("--output")
        request["command"][output_index + 1] = OUTPUT_PATH
    except (ValueError, IndexError) as exc:
        raise GateError("V2 full-stream command has no replaceable --output operand") from exc

    request["root147_gate"] = gate
    request["encoding_go_no_go"] = {
        "status": "PASS_ROOT147_TEN_FRAME_GATE",
        "actual_request": {"path": str(ROOT147_REQUEST.resolve()), "sha256": ROOT147_REQUEST_SHA},
        "actual_receipt": {"path": str(ROOT147_RECEIPT.resolve()), "sha256": ROOT147_RECEIPT_SHA, "status": "completed", "returncode": 0},
        "actual_report": {"path": str(ROOT147_REPORT.resolve()), "sha256": ROOT147_REPORT_SHA, "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS"},
        "actual_proof": {"path": str(ROOT147_PROOF.resolve()), "sha256": ROOT147_PROOF_SHA},
        "selected_native_frame_ids": TEN_FRAMES,
        "selected_native_massfluid_kg": ROOT147_NATIVE_MASS_FLUID,
        "selected_native_sample_mass_kg": ROOT147_NATIVE_SAMPLE_MASS,
        "full836_native_fields_audited": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    binding = request.setdefault("source_binding", {})
    binding["root147_ten_frame_header_gate"] = {
        "request": {"path": str(ROOT147_REQUEST.resolve()), "sha256": ROOT147_REQUEST_SHA},
        "receipt": {"path": str(ROOT147_RECEIPT.resolve()), "sha256": ROOT147_RECEIPT_SHA},
        "report": {"path": str(ROOT147_REPORT.resolve()), "sha256": ROOT147_REPORT_SHA},
        "proof": {"path": str(ROOT147_PROOF.resolve()), "sha256": ROOT147_PROOF_SHA},
        "selected_frame_ids": TEN_FRAMES,
        "native_massfluid_kg": ROOT147_NATIVE_MASS_FLUID,
        "native_massfluid_binary64_little_endian_hex": ROOT147_NATIVE_MASS_HEX,
        "native_sample_mass_kg": ROOT147_NATIVE_SAMPLE_MASS,
        "native_particle_count": ROOT147_NATIVE_PARTICLE_COUNT,
        "all_selected_finite_and_unique": True,
        "source_pre_post_stat_sha_join": True,
        "full836_fields_audited": False,
        "payload_read_by_builder": False,
    }
    request["root_forward_scope_notes"] = {
        "release_gate": "actual ROOT147 request+receipt+ten-frame report+proof exact SHA/identity join",
        "full836_scope": "all Part_0000.bi4 through Part_0835.bi4; worker hashes/stat-checks each after parent reservation",
        "selected_probe_scope": "ROOT147 ten selected native headers/finite fields only",
        "native_mass": "official decoder MassFluid scalar; XML mass is never fallback",
        "continuum_owner_mass": "UNKNOWN; native sample mass does not establish continuum equivalence",
        "science": "QI/QN/QE UNKNOWN; no pointwise/interpolated truth or qualification",
    }
    request["resource_guard"]["root147_gate_required"] = True
    request["resource_guard"]["full_window_parent_reservation"] = True
    request["resource_guard"]["no_hdf5_or_solver"] = True
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request["sha256"] = base.canonical(request)
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manufactured_gate_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create a metadata-only fixture for contract and negative-path tests."""

    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": "ds02.stage2.f3-s2.native-header-root147-request.v1",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": "F3_S2_COARSE_TEN_NATIVE_HEADER_AUDIT_ROOT_147",
        "attempt_id": "f3-s2-coarse-ten-native-header-audit-root-147-001-root-forward-030-001",
        "selected_native_frame_ids": list(TEN_FRAMES),
        "execution_allowed": True,
        "launch_disabled": False,
        "source_binding": {
            "root139_snapshot_wrapper": {
                "path": str(base.TEN_MANIFEST.resolve()),
                "sha256": base.sha256_file(base.TEN_MANIFEST),
                "selected_frame_ids": list(TEN_FRAMES),
                "identity": {"family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID},
            },
        },
    }
    receipt = {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "request_sha256": "a" * 64,
        "request": request,
    }
    observations = []
    for frame in TEN_FRAMES:
        observations.append({
            "frame": frame,
            "finite_fields": {"Idp": True, "Pos_or_Posd": True, "Vel": True, "Rhop": True, "status": "PASS_FINITE"},
            "identity": {"status": "PASS_XML_TYPED_RANGE_COVERAGE", "id_unique": True},
            "native_header": {
                "MassFluid": {"field": "MassFluid", "decoder_section": "metadata", "value": ROOT147_NATIVE_MASS_FLUID, "value_binary64_little_endian_hex": ROOT147_NATIVE_MASS_HEX},
                "MassBound": {"field": "MassBound", "decoder_section": "metadata", "value": ROOT147_NATIVE_MASS_FLUID, "value_binary64_little_endian_hex": ROOT147_NATIVE_MASS_HEX},
            },
            "fluid_observable_using_native_header_mass": {"fluid_count": ROOT147_NATIVE_PARTICLE_COUNT, "sample_mass_kg": ROOT147_NATIVE_SAMPLE_MASS},
        })
    report = {
        "schema": "ds02.stage2.f3-s2.native-header-observer.v1",
        "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
        "scope": {"selected_frames_only": True, "selected_frame_count": 10, "runparts_frame_count": 836, "full_native_tree_scanned": False, "hdf5_read": False, "native_header_mass_audited": True},
        "source": {"selected_frames": list(TEN_FRAMES)},
        "source_integrity": {"status": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT", "pre_post_sha_and_stat_equal": True, "cross_decode_stat_boundaries_equal": True},
        "observations": observations,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    proof = {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "request_sha256": "a" * 64,
        "receipt_sha256": "b" * 64,
        "report_sha256": "c" * 64,
        "selected_frames": list(TEN_FRAMES),
        "all_ten_current_stat_prepost_source_SHA_join": True,
        "all_selected_finite_and_unique": True,
        "full836_native_fields_audited": False,
        "root_array_content_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "native_header_massfluid_kg": ROOT147_NATIVE_MASS_FLUID,
        "native_selected_sample_mass_kg": ROOT147_NATIVE_SAMPLE_MASS,
    }
    return request, receipt, report, proof


def self_test() -> dict[str, Any]:
    request, receipt, report, proof = _manufactured_gate_fixture()
    validate_ten_probe(
        request, receipt, report, proof,
        request_sha="a" * 64,
        receipt_sha="b" * 64,
        report_sha="c" * 64,
        proof_sha="d" * 64,
        check_snapshot_records=False,
    )
    bad_report = json.loads(json.dumps(report))
    bad_report["status"] = "UNKNOWN"
    try:
        validate_ten_probe(
            request, receipt, bad_report, proof,
            request_sha="a" * 64,
            receipt_sha="b" * 64,
            report_sha="c" * 64,
            proof_sha="d" * 64,
            check_snapshot_records=False,
        )
    except GateError:
        pass
    else:
        raise AssertionError("manufactured bad ROOT147 status was accepted")
    actual = validate_actual_root147()
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "manufactured_positive_and_negative_gate_tests": "PASS",
        "actual_root147_gate": actual,
        "native_payload_read_by_builder": False,
        "full836_request_ready": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT150")
    parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root150-001")
    parser.add_argument("--launch-commit", default=None)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.prepare:
        parser.error("use --prepare or --self-test")
    launch_commit = args.launch_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=base.REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    value = build(args.output, case_id=args.case_id, attempt_id=args.attempt_id, launch_commit=launch_commit)
    write_new(args.output, value)
    print(json.dumps({
        "status": value["status"],
        "request": str(args.output.expanduser().resolve()),
        "frame_count": base.EXPECTED_FRAME_COUNT,
        "root147_gate": value["root147_gate"],
        "native_payload_read_by_builder": False,
        "execution_allowed": value["execution_allowed"],
        "scientific_qualification": value["scientific_qualification"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
