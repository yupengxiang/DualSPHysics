#!/usr/bin/env python3
"""Run the bounded F4-S1 macro/event/calibration stream audit.

The request produced by this module is deliberately forward-only.  It binds
the five already-produced F4-S1 DROP conversions to their exact metadata,
conversion reports, and declared trajectory HDF5 digests.  The worker does
not generate a case, run a solver, decode BI4, or invoke PartVTKOut.  When a
guarded CPU attempt is launched, it calls the existing typed science operator
on each HDF5 and writes new JSON/CSV sidecars below the attempt directory.

The output is reference/Q-I evidence.  Numerical contact, finite-aperture
crossings, residence, and macro comparisons are reported as observations;
physical fate, Q-N/QE/QI, and a position/velocity/energy decomposition remain
unresolved unless an independently bound source proves them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from ds_data02_f4_science import _calibration, compute_curve_and_events
except ModuleNotFoundError:  # pragma: no cover - import path used by package tests
    from scripts.ds_data02_f4_science import _calibration, compute_curve_and_events


SCHEMA = "ds02.stage2.f4-s1-stream.v1"
OPERATORS_SCHEMA = "ds02.f4.science-operators.v2"
MANIFEST_SCHEMA = "ds02.stage2.f4-s1-stream-manifest.v1"
EXPECTED_FAMILY = "F4"
EXPECTED_CASE = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
EXPECTED_ARTIFACT_PREFIX = "f4_drop_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
EXPECTED_ARTIFACT_SUFFIXES = (
    "coarse-native",
    "medium-native",
    "fine-native",
    "fine-half_dt",
    "fine-half_save",
)
EXPECTED_VARIANT = {
    "coarse-native": ("coarse", "native"),
    "medium-native": ("medium", "native"),
    "fine-native": ("fine", "native"),
    "fine-half_dt": ("fine", "half_dt"),
    "fine-half_save": ("fine", "half_save"),
}


class StreamContractError(RuntimeError):
    """Raised when a request is not source-bound or is otherwise malformed."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise StreamContractError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StreamContractError(f"invalid JSON input: {path}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise StreamContractError(f"expected JSON object: {path}")
    return value


def _path_hash_entry(item: Mapping[str, Any], key: str) -> tuple[Path, str]:
    value = item.get(key)
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise StreamContractError(f"{key} must contain path and sha256")
    digest = str(value["sha256"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise StreamContractError(f"{key}.sha256 is not a lowercase hexadecimal SHA-256 digest")
    return Path(str(value["path"])), digest


def _verify_file(entry: Mapping[str, Any], key: str, *, require_exists: bool) -> tuple[Path, str]:
    path, expected = _path_hash_entry(entry, key)
    if not require_exists:
        return path, expected
    if not path.is_file():
        raise StreamContractError(f"{key} path is not a file: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise StreamContractError(f"{key} SHA mismatch: {path}: expected {expected}, got {actual}")
    return path, actual


def _validate_metadata(path: Path, *, expected_case: str, expected_binding: str, require_exists: bool) -> dict[str, Any]:
    if not require_exists:
        return {}
    metadata = _load_object(path)
    if metadata.get("schema") != "ds02.f4.direct-binding.v1":
        raise StreamContractError(f"unexpected F4 metadata schema: {path}")
    if metadata.get("family_id") != EXPECTED_FAMILY or metadata.get("physical_case_id") != expected_case:
        raise StreamContractError(f"metadata physical identity mismatch: {path}")
    if metadata.get("mechanism_id") != "finite_drop_pool":
        raise StreamContractError(f"unexpected F4 mechanism: {path}")
    if metadata.get("physical_binding_sha256") != expected_binding:
        raise StreamContractError(f"metadata physical binding mismatch: {path}")
    physical = metadata.get("physical_binding")
    if not isinstance(physical, Mapping) or physical.get("family_id") != EXPECTED_FAMILY:
        raise StreamContractError(f"metadata physical binding is not F4: {path}")
    event_window = physical.get("event_window")
    if not isinstance(event_window, Mapping) or event_window.get("time_start_s") != 0.0 or event_window.get("time_end_s") != 1.2:
        raise StreamContractError(f"metadata event window is not the frozen [0,1.2] window: {path}")
    typed = metadata.get("typed_identity_binding")
    if not isinstance(typed, Mapping) or typed.get("fluid_mkfluid_to_native_mk") != {"0": 1, "1": 2}:
        raise StreamContractError(f"metadata typed identity mapping is not the F4-S1 mapping: {path}")
    return metadata


def _variant_from_artifact(artifact_id: str) -> str:
    prefix = EXPECTED_ARTIFACT_PREFIX + "-"
    if not artifact_id.startswith(prefix):
        raise StreamContractError(f"unexpected F4-S1 artifact id: {artifact_id}")
    suffix = artifact_id[len(prefix):]
    if suffix not in EXPECTED_ARTIFACT_SUFFIXES:
        raise StreamContractError(f"unsupported F4-S1 artifact variant: {artifact_id}")
    return suffix


def validate_manifest_dict(
    manifest: Mapping[str, Any],
    *,
    operators: Mapping[str, Any] | None = None,
    require_files: bool = False,
) -> list[dict[str, Any]]:
    """Validate structure and identity without opening trajectory HDF5 files.

    ``require_files=False`` is used by JSON-only tests and request preparation;
    it still validates every declared path/hash shape and all non-HDF5
    identity fields.  A guarded worker uses ``require_files=True`` and hashes
    the small JSON source files.  The HDF5 digests remain the values declared
    by the immutable evidence manifest and are checked by the shared runner's
    source closure rather than by this JSON preflight.
    """

    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise StreamContractError(f"unexpected F4-S1 manifest schema: {manifest.get('schema')!r}")
    if manifest.get("family_id") != EXPECTED_FAMILY or manifest.get("case_id") != EXPECTED_CASE:
        raise StreamContractError("F4-S1 manifest physical identity mismatch")
    if manifest.get("trajectory_read_policy") != "guarded_h5_read_only_no_bi4_no_solver":
        raise StreamContractError("manifest trajectory read policy is not the guarded HDF5-only policy")
    claim_boundary = manifest.get("claim_boundary")
    if not isinstance(claim_boundary, Mapping) or claim_boundary.get("q_n") != "not_assessed" or claim_boundary.get("physical_fate") != "unknown":
        raise StreamContractError("manifest must preserve the Q-N and physical-fate boundary")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(EXPECTED_ARTIFACT_SUFFIXES):
        raise StreamContractError("F4-S1 manifest must contain exactly five artifacts")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise StreamContractError("F4-S1 artifact entry must be an object")
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in seen:
            raise StreamContractError(f"duplicate or invalid artifact id: {artifact_id!r}")
        seen.add(artifact_id)
        variant = _variant_from_artifact(artifact_id)
        resolution, time_variant = EXPECTED_VARIANT[variant]
        if item.get("case_id") != EXPECTED_CASE or item.get("resolution") != resolution or item.get("time_variant") != time_variant:
            raise StreamContractError(f"F4-S1 variant identity mismatch: {artifact_id}")
        if item.get("physical_binding_sha256") != manifest.get("physical_binding_sha256"):
            raise StreamContractError(f"physical binding mismatch: {artifact_id}")
        for key in ("trajectory_hdf5", "metadata", "conversion_report", "conversion_receipt", "source_regions"):
            _path_hash_entry(item, key)
        # The guarded runner owns the HDF5 input hash.  Rehashing these large
        # files in preflight would add another unregistered read.  The
        # existing science operator itself registers a second pass when it
        # writes its source label digest; that pass is declared in the request
        # source-cost contract rather than hidden by this preflight.
        h5_path, h5_digest = _path_hash_entry(item, "trajectory_hdf5")
        if require_files and not h5_path.is_file():
            raise StreamContractError(f"trajectory_hdf5 path is not a file: {h5_path}")
        metadata_path, metadata_digest = _verify_file(item, "metadata", require_exists=require_files)
        conversion_path, conversion_digest = _verify_file(item, "conversion_report", require_exists=require_files)
        receipt_path, receipt_digest = _verify_file(item, "conversion_receipt", require_exists=require_files)
        regions_path, regions_digest = _verify_file(item, "source_regions", require_exists=require_files)
        metadata = _validate_metadata(metadata_path, expected_case=EXPECTED_CASE, expected_binding=str(manifest["physical_binding_sha256"]), require_exists=require_files)
        if metadata and metadata.get("physical_binding_sha256") != item.get("physical_binding_sha256"):
            raise StreamContractError(f"metadata/artifact binding mismatch: {artifact_id}")
        # Conversion/source-region JSON is part of the source closure.  We
        # deliberately do not infer scientific values from these files here.
        if require_files:
            conversion = _load_object(conversion_path)
            receipt = _load_object(receipt_path)
            regions = _load_object(regions_path)
            if conversion.get("schema") and not str(conversion["schema"]).startswith("ds-data-02.bi4-direct-conversion"):
                raise StreamContractError(f"unexpected conversion report schema: {conversion_path}")
            if receipt.get("status") not in {"completed", "completed_actual", "success"}:
                raise StreamContractError(f"conversion receipt is not completed: {receipt_path}")
            if not isinstance(regions, Mapping):
                raise StreamContractError(f"source regions is not an object: {regions_path}")
        validated.append({
            **item,
            "variant": variant,
            "trajectory_hdf5_path": str(h5_path),
            "trajectory_hdf5_sha256": h5_digest,
            "metadata_path": str(metadata_path),
            "metadata_sha256": metadata_digest,
            "conversion_report_path": str(conversion_path),
            "conversion_report_sha256": conversion_digest,
            "conversion_receipt_path": str(receipt_path),
            "conversion_receipt_sha256": receipt_digest,
            "source_regions_path": str(regions_path),
            "source_regions_sha256": regions_digest,
        })
    if set(_variant_from_artifact(item["artifact_id"]) for item in validated) != set(EXPECTED_ARTIFACT_SUFFIXES):
        raise StreamContractError("F4-S1 manifest does not cover all required variants")
    if operators is not None:
        if operators.get("schema") != OPERATORS_SCHEMA:
            raise StreamContractError(f"unexpected F4 science operator schema: {operators.get('schema')!r}")
        physical_support = operators.get("physical_support")
        transport = operators.get("transport")
        if not isinstance(physical_support, Mapping) or physical_support.get("support_radius_m") != 0.02:
            raise StreamContractError("F4 support radius is not the frozen 0.02 m value")
        if not isinstance(transport, Mapping) or transport.get("missing_identity_policy") != "unknown state; missing particles are excluded from active aperture sums and never counted as physical exit":
            raise StreamContractError("F4 missing-identity policy is not preserved")
    return validated


def validate_manifest(manifest_path: Path, operators_path: Path, *, require_files: bool = True) -> list[dict[str, Any]]:
    manifest = _load_object(manifest_path)
    operators = _load_object(operators_path)
    return validate_manifest_dict(manifest, operators=operators, require_files=require_files)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run(*, manifest_path: Path, operators_path: Path, output_dir: Path) -> dict[str, Any]:
    """Run all five streams into a fresh output directory."""

    if output_dir.exists():
        runner_owned = {"stdout.log", "execution-receipt.json"}
        leftovers = [path for path in output_dir.iterdir() if path.name not in runner_owned]
        if leftovers:
            raise StreamContractError(f"refusing to overwrite output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_object(manifest_path)
    operators = _load_object(operators_path)
    entries = validate_manifest_dict(manifest, operators=operators, require_files=True)
    started = time.monotonic()
    calibration = _calibration()
    reports: list[dict[str, Any]] = []
    for item in sorted(entries, key=lambda value: EXPECTED_ARTIFACT_SUFFIXES.index(value["variant"])):
        artifact_id = str(item["artifact_id"])
        h5_path, h5_declared_sha = _path_hash_entry(item, "trajectory_hdf5")
        metadata_path = Path(item["metadata_path"])
        metadata = _load_object(metadata_path)
        artifact_dir = output_dir / "artifacts" / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        curve_path = artifact_dir / "typed-science-timeseries.csv"
        science = compute_curve_and_events(h5_path=h5_path, metadata=metadata, operators=operators, output_csv=curve_path)
        labels_path = artifact_dir / "typed-science-labels.json"
        _write_json(labels_path, science["labels"])
        report = {
            "schema": "ds02.stage2.f4-s1-stream-artifact.v1",
            "artifact_id": artifact_id,
            "case_id": item["case_id"],
            "resolution": item["resolution"],
            "time_variant": item["time_variant"],
            "trajectory_hdf5": {
                "path": str(h5_path),
                "declared_sha256": h5_declared_sha,
                "source_hash_binding": "shared_guard_input_sha256",
            },
            "metadata": {"path": str(metadata_path), "sha256": sha256_file(metadata_path)},
            "conversion_report": {"path": item["conversion_report_path"], "sha256": item["conversion_report_sha256"]},
            "conversion_receipt": {"path": item["conversion_receipt_path"], "sha256": item["conversion_receipt_sha256"]},
            "source_regions": {"path": item["source_regions_path"], "sha256": item["source_regions_sha256"]},
            "physical_binding_sha256": item["physical_binding_sha256"],
            "curve": {"path": str(curve_path), "sha256": sha256_file(curve_path), "rows": len(science["rows"])},
            "labels": {"path": str(labels_path), "sha256": sha256_file(labels_path)},
            "contact_first": science["contact_first"],
            "recontact": science["recontact"],
            "transport": science["source_event_data"],
            "unknowns": [
                "physical fate of missing/uncertain identities",
                "position/velocity/kinetic-energy error decomposition",
                "Q-N/QE/QI and production eligibility",
                "continuous event time between saved trajectory frames",
            ],
            "status": "actual_source_bound_reference_observation; no_qualification_claim",
        }
        _write_json(artifact_dir / "f4-s1-stream-artifact.json", report)
        reports.append(report)
    output_report = {
        "schema": SCHEMA,
        "attempt_status": "completed_actual_source_bound_stream" ,
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "operators": {"path": str(operators_path), "sha256": sha256_file(operators_path)},
        "calibration": calibration,
        "artifact_count": len(reports),
        "artifacts": reports,
        "claim_boundary": manifest["claim_boundary"],
        "trajectory_read_policy": manifest["trajectory_read_policy"],
        "resource": {"wall_seconds": time.monotonic() - started},
    }
    report_path = output_dir / "f4-s1-stream-report.json"
    _write_json(report_path, output_report)
    output_report["report"] = {"path": str(report_path), "sha256": sha256_file(report_path)}
    return output_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", choices=("run",), default="run")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = run(manifest_path=args.manifest, operators_path=args.operators, output_dir=args.output)
    print(json.dumps({"report": report["report"], "artifacts": report["artifact_count"], "status": report["attempt_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
