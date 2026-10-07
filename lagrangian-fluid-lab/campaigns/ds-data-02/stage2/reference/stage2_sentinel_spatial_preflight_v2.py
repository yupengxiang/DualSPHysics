#!/usr/bin/env python3
"""Audit exact solver controls and correct F3 source-bound GenCase inputs.

The v1 spatial preflight is already consumed and remains immutable.  This v2
sidecar reads the exact CURRENT solver receipts and their argv/XML controls,
records missing values as UNKNOWN, and repairs the F3 acceleration dependency
for a new six-run GenCase-only preflight.  It never launches a solver or reads
the native/typed full-time trajectory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


SCHEMA = "ds02.stage2.sentinel-spatial-preflight.v2"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
V1_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/manifest.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
INPUT_ROOT = Path(__file__).with_name("stage2_sentinel_spatial_preflight_inputs_v2")
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-sentinel-spatial-preflight-v2"
AUDIT_REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-sentinel-spatial-audit-v2"
TARGET_SENTINELS = ("F1-S1", "F1-S2", "F2-S2", "F3-S1", "F3-S2")
CORRECTED_SENTINELS = ("F3-S1", "F3-S2")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def load_catalog() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')}")
    reviews = {row["sentinel_id"]: row for row in review.get("sentinels", [])}
    if any(sid not in reviews for sid in TARGET_SENTINELS):
        raise ValueError("explicit target sentinel is missing from review matrix")
    return current, reviews


def current_row(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    matches = [row for row in current["cases"] if row.get("physical_case_id") == physical_case_id]
    if len(matches) != 1:
        raise ValueError(f"expected one exact CURRENT row for {physical_case_id}, found {len(matches)}")
    return matches[0]


def parse_xml(path: Path) -> ET.Element:
    return ET.fromstring(path.read_bytes())


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1].lower()


def values(root: ET.Element, element_tag: str, attr: str) -> list[str]:
    return [e.attrib[attr] for e in root.iter() if tag(e) == element_tag and attr in e.attrib]


def one_or_unknown(items: list[str]) -> str:
    unique = list(dict.fromkeys(items))
    return unique[0] if len(unique) == 1 else ("UNKNOWN" if not unique else "UNKNOWN_CONFLICT")


def parameter_values(root: ET.Element, key: str) -> list[str]:
    return [e.attrib["value"] for e in root.iter() if tag(e) == "parameter" and e.attrib.get("key") == key and "value" in e.attrib]


def fluid_mass_summary(root: ET.Element) -> dict[str, Any]:
    blocks = []
    for element in root.iter():
        if tag(element) != "fluid" or "count" not in element.attrib:
            continue
        try:
            blocks.append({"count": int(element.attrib["count"]), "mkfluid": element.attrib.get("mkfluid", "UNKNOWN")})
        except ValueError:
            blocks.append({"count": "UNKNOWN", "mkfluid": element.attrib.get("mkfluid", "UNKNOWN")})
    mass_values = values(root, "massfluid", "value")
    result: dict[str, Any] = {"fluid_blocks": blocks, "massfluid_values": mass_values}
    if not blocks or not mass_values or len(set(mass_values)) != 1:
        result["sample_mass_kg"] = "UNKNOWN"
        result["reason"] = "fluid block count or common massfluid value is unavailable/conflicting"
        return result
    try:
        mass = float(mass_values[0])
        count = sum(int(block["count"]) for block in blocks)
    except (TypeError, ValueError):
        result["sample_mass_kg"] = "UNKNOWN"
        result["reason"] = "fluid count or massfluid is nonnumeric"
        return result
    result["total_fluid_particles"] = count
    result["sample_mass_kg"] = count * mass
    return result


def cli_flag(command: list[str], prefix: str) -> str:
    found = [arg.split(":", 1)[1] for arg in command if arg.startswith(prefix + ":")]
    return one_or_unknown(found)


def exact_solver_audit(sid: str, row: dict[str, Any], review: dict[str, Any], v1_sentinel: dict[str, Any]) -> dict[str, Any]:
    solver_path = Path(row["source_bindings"]["solver_receipt"]["path"])
    solver = json.loads(solver_path.read_text(encoding="utf-8"))
    request = solver.get("request", {})
    generated_path = Path(row["source_bindings"]["generated_xml"]["path"])
    generated_root = parse_xml(generated_path)
    command = request.get("command", [])
    actual_xml = {
        "cflnumber": one_or_unknown(values(generated_root, "cflnumber", "value")),
        "DtMin": one_or_unknown(parameter_values(generated_root, "DtMin")),
        "DtFixed": one_or_unknown(parameter_values(generated_root, "DtFixed")),
        "DtIni": one_or_unknown(parameter_values(generated_root, "DtIni")),
        "CoefDtMin": one_or_unknown(parameter_values(generated_root, "CoefDtMin")),
        "TimeMax": one_or_unknown(parameter_values(generated_root, "TimeMax")),
        "TimeOut": one_or_unknown(parameter_values(generated_root, "TimeOut")),
        "dp_m": one_or_unknown(values(generated_root, "definition", "dp")),
        "h_m": one_or_unknown(values(generated_root, "h", "value")),
    }
    xml_refs = []
    for element in generated_root.iter():
        for key, value in element.attrib.items():
            if key.lower() in {"file", "name", "value"} and any(suffix in value for suffix in (".csv", ".dat", ".stl")):
                xml_refs.append(value)
    solver_inputs = []
    for input_name in request.get("input_files", []):
        path = Path(input_name)
        if path.is_file() and path.suffix.lower() in {".csv", ".dat", ".stl"}:
            solver_inputs.append({"basename": path.name, "record": file_record(path), "referenced_by_xml": path.name in xml_refs})
    source_deps = v1_sentinel.get("source_binding", {}).get("relative_dependencies", [])
    source_dep_hashes = {item.get("sha256") for item in source_deps}
    solver_dep_hashes = {item["record"]["sha256"] for item in solver_inputs}
    if not source_deps and not solver_inputs:
        dependency_status = "NO_EXTERNAL_FILE_DECLARED"
    elif source_dep_hashes == solver_dep_hashes and source_dep_hashes:
        dependency_status = "MATCH"
    elif source_dep_hashes & solver_dep_hashes:
        dependency_status = "PARTIAL_HASH_MATCH"
    else:
        dependency_status = "MISMATCH"
    effective = {
        "solver_cli_tmax": cli_flag(command, "-tmax"),
        "solver_cli_tout": cli_flag(command, "-tout"),
        "xml": actual_xml,
        "solver_request_flags": [arg for arg in command if arg.startswith("-")],
        "values_are_from_exact_generated_xml_or_solver_argv": True,
    }
    return {
        "sentinel_id": sid,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "current_identity": {
            "runtime_case_alias": row["runtime_case_alias"],
            "generated_xml": file_record(generated_path),
            "solver_receipt": file_record(solver_path),
            "solver_status": solver.get("status"),
            "solver_returncode": solver.get("returncode"),
        },
        "exact_solver_effective_controls": effective,
        "xml_external_references": xml_refs,
        "solver_external_inputs": solver_inputs,
        "source_genCase_dependencies": source_deps,
        "dependency_comparison": {
            "status": dependency_status,
            "source_hashes": sorted(x for x in source_dep_hashes if x),
            "solver_hashes": sorted(solver_dep_hashes),
            "F3_interpretation": "GenCase shared bytes do not establish solver forcing equivalence" if sid.startswith("F3-") else "NOT_APPLICABLE",
        },
        "generated_xml_fluid_mass": fluid_mass_summary(generated_root),
        "review_proposed_controls": {
            "baseline_cfl": review.get("baseline_cfl", "UNKNOWN"),
            "proposed_half_cfl": review.get("proposed_half_cfl", "UNKNOWN"),
            "proposed_dense_cadence_s": review.get("proposed_dense_cadence_s", "UNKNOWN"),
            "status": "proposal_only; not substituted for exact solver control",
        },
        "physical_binding_path": request.get("physical_binding", request.get("actual_continuum_binding", "UNKNOWN")),
        "status": "PASS_SOURCE_BINDING" if dependency_status in {"MATCH", "NO_EXTERNAL_FILE_DECLARED"} else "FAIL_SOURCE_DEPENDENCY_MISMATCH",
    }


def source_definition_for(row: dict[str, Any], peer_row: dict[str, Any] | None = None) -> Path:
    generated = Path(row["source_bindings"]["generated_xml"]["path"])
    candidate = generated.with_name(generated.stem + "_Def.xml")
    if candidate.is_file():
        return candidate
    if peer_row is not None:
        peer_generated = Path(peer_row["source_bindings"]["generated_xml"]["path"])
        candidate = peer_generated.with_name(peer_generated.stem + "_Def.xml")
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"exact source Def not found for {row['physical_case_id']}")


def normalized_hash(data: bytes) -> str:
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError("expected one definition@dp")
    return hashlib.sha256(normalized).hexdigest()


def derive_f3_inputs(current: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    records = []
    for sid in CORRECTED_SENTINELS:
        review = reviews[sid]
        row = current_row(current, review["source_physical_case_id"])
        solver = json.loads(Path(row["source_bindings"]["solver_receipt"]["path"]).read_text(encoding="utf-8"))
        forcing = [Path(name) for name in solver["request"].get("input_files", []) if Path(name).name == "CaseSloshingAccData.csv" and Path(name).is_file()]
        if len(forcing) != 1:
            raise ValueError(f"expected one exact solver forcing file for {sid}, found {len(forcing)}")
        definition = source_definition_for(row, current_row(current, reviews["F3-S1"]["source_physical_case_id"]) if sid == "F3-S2" else None)
        source_bytes = definition.read_bytes()
        generated_root = parse_xml(Path(row["source_bindings"]["generated_xml"]["path"]))
        source_dp = float(values(generated_root, "definition", "dp")[0])
        source_part = Path(row["raw_root"]["path"]) / "Part_0000.bi4"
        candidates = []
        for label, dp in zip(("coarse", "original", "fine"), (float(x) for x in review["proposed_spacing_m"])):
            case = f"{sid.replace('-', '_')}_SPATIAL_V2_{label.upper()}_DP{dp:.6f}".replace(".", "p")
            case_dir = INPUT_ROOT / sid.replace("-", "_") / label
            case_dir.mkdir(parents=True, exist_ok=False)
            updated, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', lambda m: m.group(1) + f"{dp:g}".encode() + m.group(2), source_bytes, count=1)
            if count != 1:
                raise ValueError(f"source Def has no unique dp for {sid}")
            def_path = case_dir / f"{case}_Def.xml"
            forcing_path = case_dir / forcing[0].name
            atomic_write(def_path, updated)
            shutil.copyfile(forcing[0], forcing_path)
            ratio = source_dp / dp
            candidates.append({
                "case_id": case,
                "sentinel_id": sid,
                "family_id": row["family_id"],
                "physical_case_id": row["physical_case_id"],
                "label": label,
                "dp_m": dp,
                "source_dp_m": source_dp,
                "source_definition": file_record(definition),
                "derived_definition": file_record(def_path),
                "solver_receipt": file_record(Path(row["source_bindings"]["solver_receipt"]["path"])),
                "gencase_receipt": file_record(Path(row["source_bindings"]["gencase_receipt"]["path"])),
                "solver_forcing": file_record(forcing[0]),
                "derived_forcing": file_record(forcing_path),
                "forcing_byte_identical": sha256_file(forcing[0]) == sha256_file(forcing_path),
                "continuous_geometry_normalized_hash": normalized_hash(source_bytes),
                "derived_geometry_normalized_hash": normalized_hash(updated),
                "intentional_resolution": {"dp_m": dp, "h_m": "UNKNOWN_UNTIL_GENCASE", "massfluid_kg": "UNKNOWN_UNTIL_GENCASE", "particle_count": "UNKNOWN_UNTIL_GENCASE", "lattice_phase": "UNKNOWN_UNTIL_GENCASE"},
                "estimated_storage_bytes": max(16 * 1024 * 1024, int(math.ceil(source_part.stat().st_size * ratio**3 * 2.0))),
            })
        records.append({
            "sentinel_id": sid,
            "physical_case_id": row["physical_case_id"],
            "solver_forcing_sha256": file_record(forcing[0])["sha256"],
            "solver_forcing_path": str(forcing[0]),
            "source_definition": file_record(definition),
            "candidates": candidates,
        })
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_F3_CORRECTED_INPUTS_NOT_RUN",
        "v1_preserved": str(V1_MANIFEST),
        "current_catalog": file_record(CURRENT_PATH),
        "review_matrix": file_record(REVIEW_PATH),
        "quality_label_split": file_record(QUALITY_PATH),
        "correction_rule": "use the exact solver receipt CaseSloshingAccData.csv per F3 sentinel; vary only Def dp; preserve geometry and forcing bytes",
        "sentinels": records,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "QI": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }
    atomic_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(candidate: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    definition = Path(candidate["derived_definition"]["path"]).resolve()
    source_paths = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(), GENCASE.resolve(), CURRENT_PATH, REVIEW_PATH, QUALITY_PATH,
        V1_MANIFEST, manifest_path, Path(candidate["source_definition"]["path"]),
        Path(candidate["solver_receipt"]["path"]), Path(candidate["gencase_receipt"]["path"]),
        Path(candidate["solver_forcing"]["path"]), definition, Path(candidate["derived_forcing"]["path"]),
    ]
    paths = []
    seen = set()
    for path in source_paths:
        path = path.resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise FileNotFoundError(path)
            paths.append(path)
            seen.add(str(path))
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": candidate["family_id"], "case_id": candidate["case_id"],
        "attempt_id": candidate["case_id"].lower() + "-001", "kind": "cpu", "cpu_task_kind": "gencase",
        "cpu_threads": 2, "max_wall_seconds": 300, "estimated_storage_bytes": candidate["estimated_storage_bytes"],
        "worktree_root": str(REPO), "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in paths], "input_hashes": {str(path): sha256_file(path) for path in paths},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "ds_data02_stage2_dispatch.py", "strict_guard": "ds_data02_strict_dispatch_v1.py", "runtime": "ds_data02_runtime_v2.py", "launch_commit": git_commit(), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "estimated_cpu_core_hours": 2 * 300 / 3600, "estimated_new_storage_bytes": candidate["estimated_storage_bytes"]},
        "scope": {"sentinel_id": candidate["sentinel_id"], "physical_case_id": candidate["physical_case_id"], "corrected_solver_forcing_sha256": candidate["solver_forcing"]["sha256"], "dp_m": candidate["dp_m"], "gencase_only": True, "solver_started": False, "full_time_hdf5_read": False, "gpu_uuid_lease": "none", "scientific_qualification": "UNKNOWN"},
    }


def emit_requests(manifest: dict[str, Any], outdir: Path) -> list[dict[str, Any]]:
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = (INPUT_ROOT / "manifest.json").resolve()
    requests = []
    for sentinel in manifest["sentinels"]:
        for candidate in sentinel["candidates"]:
            request = request_for(candidate, manifest_path)
            atomic_json(outdir / f"{candidate['case_id'].lower()}.json", request)
            requests.append(request)
    return requests


def audit_request(output_path: Path, manifest: dict[str, Any], current: dict[str, Any], reviews: dict[str, dict[str, Any]], include_candidates: bool) -> dict[str, Any]:
    v1 = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    by_sid = {item["sentinel_id"]: item for item in v1["sentinels"]}
    audits = [exact_solver_audit(sid, current_row(current, reviews[sid]["source_physical_case_id"]), reviews[sid], by_sid[sid]) for sid in TARGET_SENTINELS]
    result: dict[str, Any] = {"schema": "ds02.stage2.sentinel-source-audit.v2", "status": "AUDITED", "source_v2": str(Path(__file__).resolve()), "current_catalog": file_record(CURRENT_PATH), "sentinels": audits, "solver_launch": False, "full_time_hdf5_read": False, "scientific_qualification": "UNKNOWN"}
    if include_candidates:
        candidates = []
        for sentinel in json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))["sentinels"]:
            for candidate in sentinel["candidates"]:
                receipt_path = DATA_ROOT / "families" / candidate["family_id"] / candidate["case_id"] / (candidate["case_id"].lower() + "-001") / "execution-receipt.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                generated_path = Path(receipt["output_root"]) / "generated" / "generated.xml"
                generated_root = parse_xml(generated_path)
                candidates.append({"sentinel_id": candidate["sentinel_id"], "case_id": candidate["case_id"], "receipt": file_record(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "total_particles": receipt.get("total_particles"), "fluid_particles": receipt.get("fluid_particles"), "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"), "generated_xml": file_record(generated_path), "fluid_mass": fluid_mass_summary(generated_root), "dp_m": one_or_unknown(values(generated_root, "definition", "dp")), "h_m": one_or_unknown(values(generated_root, "h", "value")), "massfluid_kg": one_or_unknown(values(generated_root, "massfluid", "value"))})
        result["corrected_f3_candidates"] = candidates
    atomic_json(output_path, result)
    print(json.dumps({"status": "PASS", "output": str(output_path), "sentinels": len(audits), "include_candidates": include_candidates}, ensure_ascii=False))
    return result


def build_audit_request(outdir: Path, include_candidates: bool) -> dict[str, Any]:
    current, reviews = load_catalog()
    v1 = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    paths = [REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py", REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py", REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py", Path(__file__).resolve(), CURRENT_PATH, REVIEW_PATH, QUALITY_PATH, V1_MANIFEST]
    for sid in TARGET_SENTINELS:
        row = current_row(current, reviews[sid]["source_physical_case_id"])
        paths.extend([Path(row["source_bindings"]["generated_xml"]["path"]), Path(row["source_bindings"]["gencase_receipt"]["path"]), Path(row["source_bindings"]["solver_receipt"]["path"])])
    if include_candidates:
        manifest = json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
        for sentinel in manifest["sentinels"]:
            for candidate in sentinel["candidates"]:
                receipt = DATA_ROOT / "families" / candidate["family_id"] / candidate["case_id"] / (candidate["case_id"].lower() + "-001") / "execution-receipt.json"
                generated = receipt.parent / "generated" / "generated.xml"
                paths.extend([receipt, generated])
    unique = []
    seen = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise FileNotFoundError(path)
            unique.append(path); seen.add(str(path))
    request = {"schema": REQUEST_SCHEMA, "family_id": "infra", "case_id": "STAGE2_SENTINEL_SOURCE_AUDIT_V2", "attempt_id": "stage2-sentinel-source-audit-v2-001", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "max_wall_seconds": 300, "estimated_storage_bytes": 8 * 1024 * 1024, "worktree_root": str(REPO), "cwd": str(REPO), "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(Path(__file__).resolve()), "--audit", "--include-candidates" if include_candidates else "--no-candidates", "--output", "{attempt_root}/source-audit-v2.json"], "input_files": [str(path) for path in unique], "input_hashes": {str(path): sha256_file(path) for path in unique}, "resource_guard": {"owner": "stage2-reference-preparation", "runner": "ds_data02_stage2_dispatch.py", "strict_guard": "ds_data02_strict_dispatch_v1.py", "runtime": "ds_data02_runtime_v2.py", "launch_commit": git_commit(), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden"}, "scope": {"exact_solver_receipts": True, "include_corrected_f3_candidates": include_candidates, "solver_started": False, "full_time_hdf5_read": False, "gpu_uuid_lease": "none"}}
    outdir.mkdir(parents=True, exist_ok=True)
    atomic_json(outdir / ("stage2-sentinel-source-audit-v2-with-candidates.json" if include_candidates else "stage2-sentinel-source-audit-v2.json"), request)
    print(json.dumps({"status": "PASS", "request": str(outdir), "inputs": len(unique), "include_candidates": include_candidates}, ensure_ascii=False))
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests-dir", type=Path)
    parser.add_argument("--build-audit-request-dir", type=Path)
    parser.add_argument("--include-candidates", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-candidates", action="store_true")
    args = parser.parse_args()
    if args.audit:
        if args.output is None:
            raise SystemExit("--audit requires --output")
        current, reviews = load_catalog()
        audit_request(args.output, json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8")), current, reviews, args.include_candidates)
        return 0
    if args.prepare:
        manifest = derive_f3_inputs(*load_catalog())
    else:
        manifest = json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if args.emit_requests_dir is not None:
        requests = emit_requests(manifest, args.emit_requests_dir)
        print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False))
    if args.build_audit_request_dir is not None:
        build_audit_request(args.build_audit_request_dir, args.include_candidates)
    if not args.emit_requests_dir and not args.build_audit_request_dir:
        print(json.dumps({"status": "PASS", "manifest": str(INPUT_ROOT / "manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
