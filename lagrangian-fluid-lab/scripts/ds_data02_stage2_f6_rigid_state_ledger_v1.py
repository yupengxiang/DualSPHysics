#!/usr/bin/env python3
"""Independently validate F6 static/Kabsch output and write rigid-state sidecars.

The producer's Kabsch matrix is consumed as a diagnostic fit of the type=2
support sample.  This ledger keeps the 128 kg XML physical-body mass separate
from the 256 kg sampled SPH support mass, labels FloatingInfo ``center`` as
producer-observer data rather than COM, and writes one record per native frame.
It performs no H5 reads.  It validates the manifest/output/receipt contracts
and re-reads only the bound small FloatingInfo CSV and JSON source files.

SO(3) checks are algebraic diagnostics (finite proper rotation, orthogonality,
fit residual and rank).  They do not prove physical rigid-body orientation or
dynamics.  No Euler order or frame is inferred from the observer columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OUTPUT_SCHEMA = "ds02.stage2.f6-rigid-state-ledger.v1"
PRODUCER_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v5"
VALIDATION_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-validation.v5"
EXPECTED_CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
}
BODY_MASS_KG = 128.0
SUPPORT_SAMPLE_MASS_KG = 256.0
SUPPORT_PARTICLE_COUNT = 16384
SO3_RMSE_DEG = 2.0
SO3_MAX_DEG = 5.0
TIME_TOL_S = 1.0e-6
OBS_TOL = 2.0e-6
ORTH_TOL = 2.0e-5
DET_TOL = 2.0e-5


class RigidLedgerError(RuntimeError):
    """Raised when the F6 rigid observation contract is not closed."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str, *, allow_h5: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RigidLedgerError(f"{label} is missing: {path}")
    if not allow_h5 and (path.suffix.lower() in {".h5", ".hdf5", ".obi4"} or (path.name.startswith("Part_") and path.name.endswith(".bi4"))):
        raise RigidLedgerError(f"H5/raw PartOut input is forbidden: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RigidLedgerError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(result, dict):
        raise RigidLedgerError(f"{label} is not an object: {path}")
    return path, result


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RigidLedgerError(f"refuse to overwrite existing output: {path}")
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
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


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RigidLedgerError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise RigidLedgerError(f"{label} is not finite")
    return result


def close(left: Any, right: Any, *, abs_tol: float = OBS_TOL, rel_tol: float = 2.0e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=abs_tol, rel_tol=rel_tol)
    except (TypeError, ValueError):
        return False


def source_binding(value: Path | str, label: str, expected_sha: str | None = None) -> dict[str, Any]:
    path = require_file(value, label)
    digest = sha256(path)
    if expected_sha is not None and digest != expected_sha:
        raise RigidLedgerError(f"{label} digest differs: {path}")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def matrix(value: Any, label: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in value):
        raise RigidLedgerError(f"{label} is not a 3x3 matrix")
    result = [[finite(item, f"{label}[{i}][{j}]") for j, item in enumerate(row)] for i, row in enumerate(value)]
    return result


def mat_transpose(value: list[list[float]]) -> list[list[float]]:
    return [[value[j][i] for j in range(3)] for i in range(3)]


def mat_mul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def determinant(value: list[list[float]]) -> float:
    return (value[0][0] * (value[1][1] * value[2][2] - value[1][2] * value[2][1])
            - value[0][1] * (value[1][0] * value[2][2] - value[1][2] * value[2][0])
            + value[0][2] * (value[1][0] * value[2][1] - value[1][1] * value[2][0]))


def so3_diagnostics(rotation: Any, *, label: str = "rotation") -> dict[str, Any]:
    """Validate a proper rotation matrix without imposing Euler conventions."""
    value = matrix(rotation, label)
    product = mat_mul(value, mat_transpose(value))
    orth_error = math.sqrt(sum((product[i][j] - (1.0 if i == j else 0.0)) ** 2 for i in range(3) for j in range(3)))
    det = determinant(value)
    if abs(det - 1.0) > DET_TOL:
        raise RigidLedgerError(f"{label} is not a proper rotation: determinant={det}")
    if orth_error > ORTH_TOL:
        raise RigidLedgerError(f"{label} is not orthogonal: error={orth_error}")
    cosine = max(-1.0, min(1.0, (value[0][0] + value[1][1] + value[2][2] - 1.0) / 2.0))
    angle = math.acos(cosine)
    return {
        "matrix": value,
        "determinant": det,
        "orthogonality_error_frobenius": orth_error,
        "rotation_angle_rad": angle,
        "rotation_angle_deg": math.degrees(angle),
        "near_pi_axis_ambiguity": abs(math.pi - angle) <= 1.0e-6,
        "axis_semantics": "not reported; direct matrix/angle only, axis sign is ambiguous near pi",
        "fit_status": "KABSCH_PROPER_ROTATION_DIAGNOSTIC",
        "physical_orientation_claim": "UNKNOWN",
    }


def parse_observer_csv(path: Path, expected_sha: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = source_binding(path, "F6 FloatingInfo CSV", expected_sha)
    required = {"part", "time [s]", "center.x [m]", "center.y [m]", "center.z [m]",
                "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]"}
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = {str(item).strip() for item in (reader.fieldnames or [])}
        if not required <= fields:
            raise RigidLedgerError(f"FloatingInfo lacks fields {sorted(required - fields)}")
        for ordinal, raw in enumerate(reader):
            item = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None}
            try:
                part = int(item["part"])
                time_s = finite(item["time [s]"], "FloatingInfo time")
                center = [finite(item[f"center.{axis} [m]"], f"FloatingInfo center {axis}") for axis in "xyz"]
                omega = [finite(item[f"fomega.{axis} [rad/s]"], f"FloatingInfo omega {axis}") for axis in "xyz"]
            except (KeyError, TypeError, ValueError) as exc:
                raise RigidLedgerError(f"FloatingInfo row {ordinal} is invalid") from exc
            if part != ordinal:
                raise RigidLedgerError(f"FloatingInfo part sequence is not native-order at row {ordinal}")
            rows.append({"part": part, "time_s": time_s, "observer_center_m": center, "observer_omega_rad_s": omega})
    if not rows:
        raise RigidLedgerError("FloatingInfo CSV is empty")
    return source, rows


def validate_mass_semantics(static: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    if not close(static.get("floating_support_mass_kg"), SUPPORT_SAMPLE_MASS_KG, abs_tol=1.0e-6):
        raise RigidLedgerError("Kabsch support mass is not the frozen 256 kg sample mass")
    if int(static.get("floating_support_particle_count", -1)) != SUPPORT_PARTICLE_COUNT:
        raise RigidLedgerError("Kabsch support particle count differs from frozen 16384")
    if not close(frozen.get("body_mass_kg"), BODY_MASS_KG, abs_tol=1.0e-9):
        raise RigidLedgerError("frozen physical body mass is not 128 kg")
    if not close(frozen.get("support_sample_mass_kg"), SUPPORT_SAMPLE_MASS_KG, abs_tol=1.0e-6):
        raise RigidLedgerError("frozen support sample mass is not 256 kg")
    return {
        "physical_body_mass_kg": BODY_MASS_KG,
        "sampled_support_mass_kg": SUPPORT_SAMPLE_MASS_KG,
        "sampled_support_particle_count": SUPPORT_PARTICLE_COUNT,
        "body_vs_sample_mass_claim": "separate quantities; sampled SPH mass is not rigid body mass",
        "physical_COM": "UNKNOWN_NOT_IDENTIFIED_BY_SUPPORT_SAMPLE_CENTROID",
    }


def validate_case(manifest_row: dict[str, Any], output_row: dict[str, Any]) -> dict[str, Any]:
    physical_id = str(manifest_row.get("physical_case_id"))
    if physical_id not in EXPECTED_CASES or output_row.get("physical_case_id") != physical_id:
        raise RigidLedgerError(f"F6 case identity differs: {physical_id}")
    static = output_row.get("static", {})
    kabsch = output_row.get("kabsch", {})
    if output_row.get("h5_read_ledger", {}).get("opened_once") is not True:
        raise RigidLedgerError(f"{physical_id} lacks one-open H5 ledger")
    if output_row.get("h5_read_ledger", {}).get("closed_after_static_and_kabsch") is not True:
        raise RigidLedgerError(f"{physical_id} H5 handle scope is not closed after both analyses")
    if kabsch.get("status") != "completed":
        raise RigidLedgerError(f"{physical_id} Kabsch output is not completed")
    declared_contract = manifest_row.get("conversion_contract")
    output_contract = output_row.get("conversion_contract")
    if not isinstance(declared_contract, dict) or output_contract != declared_contract:
        raise RigidLedgerError(f"{physical_id} conversion contract is not copied exactly from the bound manifest")
    frozen = kabsch.get("frozen_contract", {})
    if frozen.get("so3_error_tolerances_deg") != {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG}:
        raise RigidLedgerError(f"{physical_id} SO3 tolerance contract differs")
    if frozen.get("rotation_convention") != "active column-vector world-from-initial; row positions transformed by R.T":
        raise RigidLedgerError(f"{physical_id} rotation convention is not the frozen direct-Kabsch convention")
    mass_semantics = validate_mass_semantics(static, frozen)
    small_sources = manifest_row.get("small_sources", {})
    conversion_decl = manifest_row.get("conversion_report", {})
    conversion_source = source_binding(conversion_decl.get("path", ""), f"{physical_id} conversion report", conversion_decl.get("sha256"))
    floating_decl = small_sources.get("floating_csv_path", {})
    floating_path = Path(str(floating_decl.get("path", ""))).expanduser().resolve()
    floating_source, observer_rows = parse_observer_csv(floating_path, str(floating_decl.get("sha256")))
    frames = kabsch.get("frames")
    if not isinstance(frames, list) or len(frames) != len(observer_rows):
        raise RigidLedgerError(f"{physical_id} frame count differs from bound FloatingInfo")
    native_frames: list[dict[str, Any]] = []
    previous_time = -math.inf
    for ordinal, (frame, observer) in enumerate(zip(frames, observer_rows)):
        if int(frame.get("part", -1)) != ordinal or int(frame.get("part", -1)) != observer["part"]:
            raise RigidLedgerError(f"{physical_id} native frame part differs at {ordinal}")
        time_s = finite(frame.get("time_s"), f"{physical_id} Kabsch time")
        if time_s <= previous_time or not close(time_s, observer["time_s"], abs_tol=TIME_TOL_S):
            raise RigidLedgerError(f"{physical_id} native frame time differs at {ordinal}")
        previous_time = time_s
        fit = so3_diagnostics(frame.get("rotation_world_from_initial"), label=f"{physical_id} frame {ordinal} rotation")
        residual_rmse = finite(frame.get("residual_rmse_m"), f"{physical_id} residual RMSE")
        residual_max = finite(frame.get("residual_max_m"), f"{physical_id} residual max")
        if residual_rmse < 0 or residual_max < 0:
            raise RigidLedgerError(f"{physical_id} residual is negative at {ordinal}")
        singular = frame.get("singular_values")
        if not isinstance(singular, list) or len(singular) != 3 or any(finite(value, "singular value") <= 0 for value in singular):
            raise RigidLedgerError(f"{physical_id} Kabsch singular values are invalid at {ordinal}")
        rank_relative = finite(frame.get("rank_relative"), f"{physical_id} Kabsch rank")
        if rank_relative <= 0:
            raise RigidLedgerError(f"{physical_id} Kabsch rank is invalid at {ordinal}")
        centroid = frame.get("sample_centroid_current_m")
        if not isinstance(centroid, list) or len(centroid) != 3 or any(not math.isfinite(float(value)) for value in centroid):
            raise RigidLedgerError(f"{physical_id} sample centroid is invalid at {ordinal}")
        reported_center = frame.get("observer_center_m")
        reported_omega = frame.get("observer_omega_rad_s")
        if (not isinstance(reported_center, list) or len(reported_center) != 3
                or not isinstance(reported_omega, list) or len(reported_omega) != 3
                or any(not math.isfinite(float(value)) for value in (*reported_center, *reported_omega))):
            raise RigidLedgerError(f"{physical_id} observer fields are invalid at {ordinal}")
        if reported_center != observer["observer_center_m"] or reported_omega != observer["observer_omega_rad_s"]:
            # Allow only the producer's decimal round trip, never a semantic substitution.
            if any(not close(a, b) for a, b in zip(reported_center, observer["observer_center_m"])) or any(not close(a, b) for a, b in zip(reported_omega, observer["observer_omega_rad_s"])):
                raise RigidLedgerError(f"{physical_id} observer fields differ at {ordinal}")
        native_frames.append({
            "part": ordinal,
            "time_s": time_s,
            "rotation_world_from_initial": fit["matrix"],
            "so3_fit": fit,
            "residual_rmse_m": residual_rmse,
            "residual_max_m": residual_max,
            "rank_relative": rank_relative,
            "sample_centroid_current_m": [float(value) for value in centroid],
            "observer_center_m": observer["observer_center_m"],
            "observer_center_semantics": "FloatingInfo producer center; frame and physical-COM meaning UNKNOWN",
            "observer_omega_rad_s": observer["observer_omega_rad_s"],
            "observer_omega_semantics": "FloatingInfo producer omega; frame/convention meaning UNKNOWN",
            "physical_COM_m": "UNKNOWN",
            "physical_orientation": "UNKNOWN; Kabsch fit is a support-sample diagnostic",
        })
    return {
        "physical_case_id": physical_id,
        "sentinel_id": manifest_row.get("sentinel_id"),
        "source_bindings": {
            "manifest_small_sources": {name: source_binding(item["path"], f"{physical_id} {name}", item.get("sha256")) for name, item in small_sources.items()},
            "conversion_report": conversion_source,
            "floating_csv": floating_source,
        },
        "mass_semantics": mass_semantics,
        "frame_count": len(native_frames),
        "frames": native_frames,
        "so3_contract": {
            "declared_tolerances_deg": {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG},
            "application": "not applied as angular truth criterion; producer supplies no independent angular reference",
            "Euler_order": "UNKNOWN_NOT_USED",
            "physical_orientation_claim": "UNKNOWN",
        },
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def validate_execution(manifest_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "F6 v5 manifest")
    output_path, output = read_json(output_path, "F6 v5 output")
    receipt_path, receipt = read_json(receipt_path, "F6 v5 execution receipt")
    if manifest.get("schema") != "ds02.stage2.f6-static-kabsch-combined-bundle.v5" or output.get("schema") != PRODUCER_SCHEMA:
        raise RigidLedgerError("F6 v5 manifest/output schema differs")
    if output.get("status") != "completed":
        raise RigidLedgerError("F6 v5 output is not completed")
    result_bundle = output.get("bundle", {})
    if str(Path(result_bundle.get("path", "")).resolve()) != str(manifest_path.resolve()) or result_bundle.get("sha256") != sha256(manifest_path):
        raise RigidLedgerError("F6 v5 output is not bound to exact manifest")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise RigidLedgerError("F6 v5 execution receipt is not completed code 0")
    request = receipt.get("request", {})
    if request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V5" or request.get("attempt_id") != "f6-static-kabsch-combined-v5-primary-001":
        raise RigidLedgerError("F6 v5 receipt request identity differs")
    if output.get("source_policy", {}).get("h5_opened") is not True or output.get("source_policy", {}).get("solver_started") is not False:
        raise RigidLedgerError("F6 v5 output source policy differs")
    manifest_rows = {row.get("physical_case_id"): row for row in manifest.get("source_cases", [])}
    output_rows = {row.get("physical_case_id"): row for row in output.get("cases", [])}
    if set(manifest_rows) != EXPECTED_CASES or set(output_rows) != EXPECTED_CASES:
        raise RigidLedgerError("F6 v5 case union differs")
    # Verify H5 hashes only as receipt metadata; no H5 path is opened or hashed.
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    for row in manifest.get("source_cases", []):
        h5 = row.get("trajectory_h5", {})
        key = str(Path(str(h5.get("path", ""))).expanduser().resolve())
        digest = h5.get("sha256")
        if not isinstance(digest, str) or declared.get(key) != digest or launch.get(key) != digest or finish.get(key) != digest:
            raise RigidLedgerError(f"F6 v5 H5 terminal metadata is not stable: {key}")
    cases = [validate_case(manifest_rows[key], output_rows[key]) for key in sorted(EXPECTED_CASES)]
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "completed",
        "producer": {"path": str(output_path), "sha256": sha256(output_path)},
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "execution_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "cases": cases,
        "claim_boundary": {
            "physical_body_mass": "128 kg",
            "sampled_support_mass": "256 kg",
            "physical_COM": "UNKNOWN",
            "SO3_truth": "UNKNOWN; algebraic Kabsch fit diagnostics only",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "read_policy": {"h5_opened_by_validator": False, "trajectory_content_opened_by_validator": False, "solver_started": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_execution(args.manifest, args.output, args.receipt)
        atomic_json(args.sidecar, result)
    except RigidLedgerError as exc:
        raise SystemExit(f"RigidLedgerError: {exc}")
    print(json.dumps({"status": result["status"], "sidecar": str(args.sidecar.resolve()), "case_count": len(result["cases"]), "h5_opened_by_validator": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
