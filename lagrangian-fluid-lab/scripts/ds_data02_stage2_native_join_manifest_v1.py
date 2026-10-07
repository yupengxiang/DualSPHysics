#!/usr/bin/env python3
"""Emit a source-bound manifest for completed Stage2 native omission joins.

This is a metadata-only inventory of already completed join attempts.  It does
not open trajectory H5 files, scan trajectories, or run a decoder.  Every row
is tied to its request, v4 batch receipt, join execution receipt, sidecar,
PartOut CSV, native decoder receipt, and RunPARTs CSV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ManifestError(RuntimeError):
    pass


FAMILIES = ("F4", "F6")
EXPECTED_CASES = {"F4": 19, "F6": 46}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ManifestError(f"{label} is missing: {path}")
    return path


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise ManifestError(f"{label} is invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{label} is not a JSON object: {path}")
    return path, value


def ref(path: str | Path, *, declared_sha: str | None = None,
        label: str = "evidence") -> dict[str, Any]:
    path = require_file(path, label)
    actual = sha256(path)
    if declared_sha is not None and actual != declared_sha:
        raise ManifestError(f"{label} hash mismatch: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.",
                                     dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_manifest(data_root: Path, request_root: Path,
                   batch_root: Path) -> dict[str, Any]:
    request_by_case: dict[str, tuple[Path, dict[str, Any]]] = {}
    for family in FAMILIES:
        pattern = request_root / f"omission-forensics-{family.lower()}-join-v3" / "reconcile-*.json"
        for request_path in sorted(pattern.parent.glob(pattern.name)):
            path, request = read_json(request_path, "native join request")
            case_id = str(request.get("case_id", ""))
            if not case_id.startswith(f"STAGE2_OMISSION_{family}_"):
                continue
            if case_id in request_by_case:
                raise ManifestError(f"duplicate request for {case_id}")
            if request.get("attempt_id") not in ("omission-forensics-f4-v3", "omission-forensics-f6-v3"):
                raise ManifestError(f"unexpected join attempt for {case_id}: {request.get('attempt_id')}")
            if any(str(item).lower().endswith(".h5") for item in request.get("input_files", [])):
                raise ManifestError(f"H5 declared by join request: {path}")
            request_by_case[case_id] = (path, request)

    batch_by_request: dict[str, tuple[Path, dict[str, Any]]] = {}
    batch_paths: dict[str, dict[str, Any]] = {}
    for batch_path in sorted(batch_root.glob("*/batch-receipt.json")):
        path, batch = read_json(batch_path, "batch receipt")
        if batch.get("status") != "completed":
            continue
        batch_paths[str(path)] = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        for item in batch.get("requests", []):
            request = item.get("request")
            if isinstance(request, str):
                if request in batch_by_request:
                    raise ManifestError(f"request appears in multiple completed batches: {request}")
                batch_by_request[request] = (path, batch)

    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        sidecar_paths = sorted(data_root.glob(
            f"families/{family}/STAGE2_OMISSION_*/omission-forensics-{family.lower()}-v3/omission-forensics.json"))
        if len(sidecar_paths) != EXPECTED_CASES[family]:
            raise ManifestError(
                f"expected {EXPECTED_CASES[family]} {family} v3 sidecars, got {len(sidecar_paths)}")
        for sidecar_path in sidecar_paths:
            side_path, sidecar = read_json(sidecar_path, "native join sidecar")
            case_id = str(sidecar.get("physical_case_id", ""))
            if not case_id.startswith(f"{family}_"):
                raise ManifestError(f"sidecar family mismatch: {side_path}")
            request_pair = request_by_case.get(f"STAGE2_OMISSION_{case_id.split('_', 1)[1]}")
            # physical_case_id is the long CURRENT case ID; map by the numeric
            # STAGE2 output directory because request IDs are exact output IDs.
            number = side_path.parent.parent.name.rsplit("_", 1)[-1]
            request_id = f"STAGE2_OMISSION_{family}_{number}"
            request_pair = request_by_case.get(request_id)
            if request_pair is None:
                raise ManifestError(f"no request for {request_id} / {case_id}")
            request_path, request = request_pair
            request_sha = sha256(request_path)
            batch_pair = batch_by_request.get(str(request_path))
            if batch_pair is None:
                raise ManifestError(f"request has no completed batch receipt: {request_path}")
            batch_path, batch = batch_pair
            batch_item = next((item for item in batch.get("requests", [])
                               if item.get("request") == str(request_path)), None)
            if batch_item is None or batch_item.get("request_sha256") != request_sha:
                raise ManifestError(f"batch request binding mismatch: {request_path}")
            join_receipt_path = sidecar_path.parent / "execution-receipt.json"
            _, join_receipt = read_json(join_receipt_path, "join execution receipt")
            if join_receipt.get("status") != "completed" or join_receipt.get("returncode") != 0:
                raise ManifestError(f"join receipt is not completed: {join_receipt_path}")
            if join_receipt.get("request_sha256") != request_sha:
                raise ManifestError(f"join receipt request binding mismatch: {join_receipt_path}")
            if sidecar.get("status") != "CAUSES_RECONCILED":
                raise ManifestError(f"sidecar status is not CAUSES_RECONCILED: {sidecar_path}")
            native = sidecar.get("native_decode", {})
            decoder_obj = native.get("receipt", {})
            decoder_path = decoder_obj.get("path") if isinstance(decoder_obj, dict) else decoder_obj
            decoder_ref = ref(decoder_path, declared_sha=(decoder_obj.get("sha256") if isinstance(decoder_obj, dict) else None), label="decoder receipt")
            partout_obj = native.get("partout", {})
            partout_ref = ref(partout_obj.get("path"), declared_sha=partout_obj.get("sha256"), label="PartOut CSV")
            runparts_obj = native.get("runparts", {})
            runparts_ref = ref(runparts_obj.get("path"), declared_sha=runparts_obj.get("sha256"), label="RunPARTs CSV")
            excluded = sidecar.get("excluded_particles", [])
            motive_counts: dict[str, int] = {}
            for item in excluded:
                motive = str(item.get("native_motive", "UNKNOWN"))
                motive_counts[motive] = motive_counts.get(motive, 0) + 1
            rows.append({
                "family_id": family,
                "request_case_id": request_id,
                "physical_case_id": case_id,
                "request": ref(request_path, label="native join request"),
                "batch_receipt": ref(batch_path, label="join batch receipt"),
                "join_receipt": ref(join_receipt_path, label="join execution receipt"),
                "sidecar_report": ref(sidecar_path, label="native join sidecar"),
                "decoder_receipt": decoder_ref,
                "partout_csv": partout_ref,
                "runparts_csv": runparts_ref,
                "missing_fluid_count": sidecar.get("typed_identity", {}).get("missing_fluid_count"),
                "missing_fluid_initial_mass_kg": sidecar.get("typed_identity", {}).get("missing_fluid_initial_mass_kg"),
                "first_missing_frame": min((int(item["first_missing_frame"]) for item in excluded), default=None),
                "native_motive_counts": motive_counts,
                "physical_fate": sidecar.get("physical_fate", "UNKNOWN"),
                "dynamical_impact": sidecar.get("dynamical_impact", "UNKNOWN"),
            })

    rows.sort(key=lambda row: (row["family_id"], row["request_case_id"]))
    counts = {family: sum(row["family_id"] == family for row in rows) for family in FAMILIES}
    if counts != EXPECTED_CASES:
        raise ManifestError(f"manifest counts differ: {counts}")
    return {
        "schema": "ds02.stage2.native-join-manifest.v1",
        "purpose": "Completed F4/F6 v3 native join receipt/path/hash manifest for the 65 newly reconciled historical cases.",
        "scope": {"families": FAMILIES, "case_counts": counts, "total_cases": len(rows)},
        "constraints": {
            "trajectory_h5_opened": False,
            "scientific_scan_reexecuted": False,
            "native_decoder_reexecuted": False,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "f6_missing_mass_semantics": "typed fluid mass only; XML rigid-body and floating sample masses are separate",
        },
        "batch_receipts": [
            batch_paths[key]
            for key in sorted({row["batch_receipt"]["path"] for row in rows})
        ],
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--request-root", required=True, type=Path)
    parser.add_argument("--batch-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_manifest(args.data_root.resolve(), args.request_root.resolve(), args.batch_root.resolve())
    write_atomic(args.output.resolve(), result)
    print(json.dumps({"status": "completed", "output": str(args.output), "scope": result["scope"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestError as exc:
        raise SystemExit(f"ManifestError: {exc}")
