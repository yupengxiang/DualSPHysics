#!/usr/bin/env python3
"""Bind the known F6 owner-authority gap without reading particle arrays.

The existing F6 XML audits establish body/control and grid-dependent generated
sample masses.  They do not bind a continuous fluid-owner shape, clipping,
transform, or material-region contract.  This sidecar makes that boundary
machine-readable.  In particular, a floating-particle sample mass is never
promoted to either the 128 kg rigid-body mass or an inferred continuum-fluid
owner mass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f6.owner-authority-gap-card.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6.owner-authority-gap-card.manifest.v1"
UNKNOWN_OWNER = "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT"
BODY_MASS_KG = 128.0


class GapError(ValueError):
    """Raised when the bound F6 source evidence is not internally consistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise GapError(f"missing JSON source: {path}")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev,
            "st_ino": stat.st_ino, "sha256": sha256_file(path)}


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GapError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GapError(f"{label} must be an object: {path}")
    return value


def expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise GapError(f"{label}: expected {wanted!r}, got {actual!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GapError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise GapError(f"{label} is not finite")
    return result


def load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise GapError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise GapError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise GapError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() != ".json":
            raise GapError(f"{key} is not a JSON source: {path}")
        actual = record(path)
        if ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(ref["sha256"]), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        records[key] = actual
        docs[key] = read_json(path, key)
    return paths, records, docs


def bound_report(proof: dict[str, Any], report_key: str, docs: dict[str, dict[str, Any]], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report_path = proof.get("report")
    report_sha = proof.get("report_sha256")
    if not isinstance(report_path, str) or not isinstance(report_sha, str):
        raise GapError(f"{report_key} proof lacks report path/SHA")
    report_record = records[report_key]
    expect(report_record["path"], str(Path(report_path).expanduser().resolve()), f"{report_key} report path")
    expect(report_record["sha256"], report_sha, f"{report_key} report SHA")
    return docs[report_key]


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("sentinel_id")), str(row.get("grid_id"))


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve(), "F6 gap manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    paths, records, docs = load_refs(manifest)
    for key in ("authority_proof", "authority_report", "body_proof", "body_report", "rigid_mass_proof"):
        if key not in docs:
            raise GapError(f"required source reference missing: {key}")
    authority_proof = docs["authority_proof"]
    body_proof = docs["body_proof"]
    authority = bound_report(authority_proof, "authority_report", docs, records)
    body = bound_report(body_proof, "body_report", docs, records)
    expect(authority.get("schema"), "ds02.stage2.f6.fluid-owner-authority-audit.v3", "authority report schema")
    expect(authority.get("status"), "COMPLETED_F6_FLUID_OWNER_AUTHORITY_XML_SOURCE_PROJECTION_AUDIT", "authority report status")
    expect(body.get("schema"), "ds02.stage2.f6.three-grid-initial-body-control.v1", "body report schema")
    expect(body.get("status"), "completed_source_xml_receipt_audit", "body report status")
    expect(authority.get("owner_authority", {}).get("continuous_fluid_owner"), UNKNOWN_OWNER, "authority owner status")
    expect(authority.get("owner_authority", {}).get("physical_body_mass_kg"), BODY_MASS_KG, "authority body mass")
    expect(body.get("mass_semantics", {}).get("physical_floating_body_mass_kg"), BODY_MASS_KG, "body physical mass")
    expect(body.get("mass_semantics", {}).get("body_and_sample_are_not_interchangeable"), True, "body/sample separation")
    rows_a = authority.get("rows")
    rows_b = body.get("rows")
    if not isinstance(rows_a, list) or len(rows_a) != 6 or not isinstance(rows_b, list) or len(rows_b) != 6:
        raise GapError("F6 reports must each expose six rows")
    map_a = {_row_key(row): row for row in rows_a if isinstance(row, dict)}
    map_b = {_row_key(row): row for row in rows_b if isinstance(row, dict)}
    if len(map_a) != 6 or len(map_b) != 6 or set(map_a) != set(map_b):
        raise GapError("F6 authority/body row identities differ")
    rows: list[dict[str, Any]] = []
    for key in sorted(map_a):
        ar, br = map_a[key], map_b[key]
        expect(ar.get("physical_case_id"), br.get("physical_case_id"), f"{key} case identity")
        body_contract = ar.get("body_contract")
        if not isinstance(body_contract, dict):
            raise GapError(f"{key} lacks body contract")
        expect(body_contract.get("massbody_kg"), BODY_MASS_KG, f"{key} body mass")
        generated = ar.get("generated_particle_summary")
        if not isinstance(generated, dict):
            raise GapError(f"{key} lacks generated particle summary")
        floating = br.get("sample_floating_mass_kg")
        sample_fluid = generated.get("fluid_sample_mass_kg")
        if floating is None or sample_fluid is None:
            raise GapError(f"{key} lacks sample mass values")
        rows.append({
            "sentinel_id": key[0],
            "grid_id": key[1],
            "physical_case_id": ar.get("physical_case_id"),
            "dp_m": finite(ar.get("dp_m"), f"{key} dp"),
            "physical_body_mass_kg": BODY_MASS_KG,
            "sample_floating_mass_kg": finite(floating, f"{key} sample floating mass"),
            "sample_fluid_mass_kg": finite(sample_fluid, f"{key} sample fluid mass"),
            "continuous_fluid_owner_mass_kg": None,
            "continuous_fluid_owner_authority": UNKNOWN_OWNER,
            "drawbox_volume_or_rho_mass_promoted": False,
            "source_control_and_generated_contract_scope": "XML/receipt source audit only; no continuous-owner equivalence",
        })
    sample_values = sorted({row["sample_floating_mass_kg"] for row in rows})
    expect(sample_values, [256.0, 257.87353515625], "sample floating masses")
    return {
        "schema": SCHEMA,
        "status": "F6_OWNER_AUTHORITY_GAP_BOUND_SOURCE_ONLY",
        "source_inputs": records,
        "evidence": {
            "authority_proof_status": authority_proof.get("status"),
            "body_proof_status": body_proof.get("status"),
            "authority_report_schema": authority.get("schema"),
            "body_report_schema": body.get("schema"),
            "six_row_identity_join": True,
            "all_rows_have_source_generated_receipt_closure": True,
        },
        "rows": rows,
        "mass_semantics": {
            "physical_rigid_body_mass_kg": BODY_MASS_KG,
            "sample_floating_mass_values_kg": sample_values,
            "sample_mass_definition": "generated floating-particle count multiplied by generated massfluid; grid-dependent",
            "sample_mass_is_not_rigid_body_mass": True,
            "sample_mass_is_not_continuum_fluid_owner_mass": True,
            "continuum_fluid_owner_mass_kg": None,
            "continuum_fluid_owner_mass_status": UNKNOWN_OWNER,
        },
        "owner_gap": {
            "status": UNKNOWN_OWNER,
            "known": [
                "The six source/generated XML rows and completed GenCase receipts are source-bound.",
                "The rigid body mass is independently declared as 128 kg.",
                "The floating SPH sample masses are grid-dependent and include 256.0 kg and 257.87353515625 kg.",
            ],
            "unresolved_inputs": [
                "An explicit continuous-fluid-owner shape and material/region contract.",
                "Source-to-generated clipping, transform, boundary-inclusion, and lattice-phase mapping for that owner.",
                "A linked owner declaration that distinguishes physical fluid volume from producer drawboxes.",
            ],
            "drawbox_or_particle_count_cannot_close_owner": True,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        "next_request_readiness": {
            "json_only_metadata_ready": True,
            "requires_arrays_or_native_payload": False,
            "minimal_future_source_inputs": ["explicit owner contract", "geometry clip/transform declaration", "material-region ownership mapping"],
            "no_owner_inference_from_particles": True,
        },
        "read_policy": {"json_only": True, "h5_opened": False, "bi4_opened": False, "obi4_opened": False, "vtk_opened": False, "solver_started": False, "gencase_started": False, "old_products_modified": False},
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise GapError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest))
    except GapError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
