#!/usr/bin/env python3
"""Additive F3 source-XML binding for the ROOT710 support audit.

ROOT710 consumed the nine actual GenCase products and completed six rows, but
the three F3 rows failed before product inspection because the independent
product map deliberately had ``source_xml: null``.  This version requires an
explicit F3 owner-source manifest and binds its exact source XML and source
Def bytes to each F3 grid.  It does not alias a generated XML, candidate Def,
or a label into the source role.

The builder reads only small JSON/XML metadata.  The worker delegates product
reads to the frozen V2/V1 worker inside the parent guard; native mass remains
whatever the ROOT709 decoder sidecar actually exposed (currently UNKNOWN),
and all scientific qualifications stay UNKNOWN.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v2.py"
V5_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v5.py"
V3_PATH = HERE / Path(__file__).name
JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
V2_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v2"
V3_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v3-f3-source-bound"
V1_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
SOURCE_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v3"
SOURCE_STATUS = "PREPARED_SOURCE_OWNER_GRID_AUDIT_V3"
TARGET = "F3-S1"
GRIDS = ("original", "coarse", "fine")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class SourceBoundFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SourceBoundFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_PATH, "owner_grid_initial_support_v1_for_f3_source_bound")
V2 = _load(V2_PATH, "owner_grid_initial_support_v2_for_f3_source_bound")


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _read_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise SourceBoundFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise SourceBoundFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise SourceBoundFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBoundFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceBoundFailure(f"{label} must be an object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat": after, "payload_read_by_builder": True,
                   "scope": "bounded_small_metadata"}


def _record(path: Path | str, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise SourceBoundFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise SourceBoundFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise SourceBoundFailure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": after,
            "payload_read_by_builder": True, "scope": "bounded_small_metadata"}


def _record_exact(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise SourceBoundFailure(f"{label} lacks an explicit path record")
    record = _record(value["path"], label)
    declared = value.get("sha256")
    if not _valid_sha(declared) or declared.lower() != record["sha256"].lower():
        raise SourceBoundFailure(f"{label} declared SHA does not match current bytes")
    return record


def _write_json(path: Path, value: dict[str, Any], label: str) -> dict[str, Any]:
    path = _abs(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > JSON_CAP:
        raise SourceBoundFailure(f"{label} exceeds the 10 MiB metadata cap")
    if path.exists() or path.is_symlink():
        raise SourceBoundFailure(f"refusing to overwrite {label}: {path}")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": _stat(path),
            "payload_read_by_builder": False, "scope": "builder_output_metadata"}


def _source_rows(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if source.get("schema") != SOURCE_SCHEMA or source.get("status") != SOURCE_STATUS:
        raise SourceBoundFailure("F3 owner source manifest schema/status is not the frozen V3 source")
    rows = source.get("cases")
    if not isinstance(rows, list):
        raise SourceBoundFailure("F3 owner source manifest has no cases")
    selected = [row for row in rows if isinstance(row, dict) and row.get("sentinel_id") == TARGET]
    # The source manifest has one row per sentinel and its ``grids`` list is
    # the authority for the three candidate Def paths.
    if len(selected) != 1:
        raise SourceBoundFailure("F3 owner source manifest must contain exactly one F3-S1 row")
    row = selected[0]
    grids = row.get("grids")
    if not isinstance(grids, list) or {g.get("label") for g in grids if isinstance(g, dict)} != set(GRIDS):
        raise SourceBoundFailure("F3 owner source manifest does not cover original/coarse/fine")
    source_xml = _record_exact(row.get("source_xml"), "F3 owner source XML")
    source_def = _record_exact(row.get("source_def"), "F3 owner source Def")
    if _abs(source_xml["path"]) == _abs(source_def["path"]):
        raise SourceBoundFailure("F3 source XML and source Def unexpectedly alias")
    result: dict[str, dict[str, Any]] = {}
    for grid in grids:
        if not isinstance(grid, dict) or grid.get("label") not in GRIDS:
            raise SourceBoundFailure("F3 owner grid row is malformed")
        candidate = _record_exact(grid.get("candidate_def"), f"F3 owner {grid['label']} candidate Def")
        result[str(grid["label"])] = {"source_xml": source_xml, "source_def": source_def,
                                         "candidate_def": candidate,
                                         "candidate_declared": grid["candidate_def"]}
    return result


def _bind_f3_rows(base: dict[str, Any], source: dict[str, Any], source_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    owner = _source_rows(source)
    cases = copy.deepcopy(base.get("cases"))
    if not isinstance(cases, list):
        raise SourceBoundFailure("base support manifest has no cases")
    found: set[str] = set()
    binding_rows: list[dict[str, Any]] = []
    for row in cases:
        if not isinstance(row, dict) or row.get("sentinel_id") != TARGET:
            continue
        grid = str(row.get("grid_label"))
        if grid not in owner:
            raise SourceBoundFailure(f"F3 source manifest lacks grid {grid}")
        candidate = row.get("candidate_def")
        expected = owner[grid]["candidate_def"]
        if not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str):
            raise SourceBoundFailure(f"F3 {grid} candidate Def record is missing")
        # The actual GenCase producer may have staged the same candidate Def
        # under a fresh attempt path.  Path identity therefore comes from the
        # producer row, while content identity must equal the owner-source
        # candidate record exactly.  This is a copy/rebind check, never a
        # label-based alias.
        if candidate.get("sha256", "").lower() != expected["sha256"].lower():
            raise SourceBoundFailure(f"F3 {grid} staged candidate Def bytes differ from owner-source record")
        # This is an exact source binding, not a generated XML fallback.
        if isinstance(row.get("generated_xml"), dict) and _abs(row["generated_xml"].get("path", "")) == _abs(owner[grid]["source_xml"]["path"]):
            raise SourceBoundFailure(f"F3 {grid} generated XML aliases owner source XML")
        row["source_xml"] = owner[grid]["source_xml"]
        row["source_def"] = owner[grid]["source_def"]
        row["source_xml_binding"] = {
            "kind": "EXACT_OWNER_SOURCE_MANIFEST_RECORD",
            "owner_source_manifest": {"path": str(_abs(source_path)),
                                       "sha256": _sha(Path(source_path).read_bytes())},
            "source_xml": owner[grid]["source_xml"],
            "source_def": owner[grid]["source_def"],
            "candidate_def": expected,
            "actual_candidate_def": candidate,
            "generated_xml_is_not_source_xml": True,
            "alias_or_label_fallback": False,
        }
        found.add(grid)
        binding_rows.append({"row_key": f"{TARGET}:{grid}",
                             "source_xml": owner[grid]["source_xml"],
                             "source_def": owner[grid]["source_def"],
                             "candidate_def": expected,
                             "actual_candidate_def": candidate})
    if found != set(GRIDS):
        raise SourceBoundFailure(f"F3 source binding incomplete: {sorted(found)}")
    binding = {"sentinel_id": TARGET, "source_manifest": _record(source_path, "F3 owner source manifest"),
               "rows": binding_rows, "semantic_authority": "F3_V3_OWNER_SOURCE_MANIFEST",
               "generated_xml_fallback": False, "candidate_label_fallback": False}
    return cases, binding


def _manifest_paths(manifest: dict[str, Any]) -> tuple[Path, Path]:
    binding = manifest.get("header_binding")
    if not isinstance(binding, dict):
        raise SourceBoundFailure("base manifest lacks ROOT709 header binding")
    for key in ("proof", "report"):
        if not isinstance(binding.get(key), dict) or not isinstance(binding[key].get("path"), str):
            raise SourceBoundFailure(f"base header binding lacks {key}")
    return _abs(binding["proof"]["path"]), _abs(binding["report"]["path"])


def build(base_manifest_path: Path, source_manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    base, base_record = _read_json(base_manifest_path, "ROOT710 source-bound V2 manifest")
    if base.get("schema") != V2_SCHEMA or base.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2":
        raise SourceBoundFailure("base manifest is not the consumed ROOT710 V2 manifest")
    source, source_record = _read_json(source_manifest_path, "F3 owner source manifest")
    cases, binding = _bind_f3_rows(base, source, _abs(source_manifest_path))
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SourceBoundFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = copy.deepcopy(base)
    manifest["schema"] = V3_SCHEMA
    manifest["status"] = "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V3_F3_SOURCE_BOUND"
    manifest["cases"] = cases
    manifest["f3_source_binding"] = binding
    manifest["scientific_scope"] = {**manifest.get("scientific_scope", {}), **NO_CREDIT,
                                     "xml_mass_fallback": False, "continuous_owner": "UNKNOWN",
                                     "F3_source_xml_binding": "EXACT_OWNER_SOURCE_MANIFEST_RECORD"}
    manifest["payload_read_by_builder"] = False
    manifest_path = output_dir / "initial-support-manifest-v3-f3-source-bound.json"
    manifest_record = _write_json(manifest_path, manifest, "V3 support manifest")

    proof_path, report_path = _manifest_paths(base)
    proof, _ = _read_json(proof_path, "ROOT709 proof")
    sidecars: list[dict[str, Any]] = []
    for row in base.get("cases", []):
        if isinstance(row, dict) and isinstance(row.get("native_header_probe"), dict):
            sidecars.append(_record_exact(row["native_header_probe"], f"{row.get('row_key')} native sidecar"))
    static = V2._static_source_records(base, _abs(base_manifest_path), proof_path, report_path, proof, sidecars)
    for path, label in ((source_manifest_path, "F3 owner source manifest"),
                        (V3_PATH, "V3 F3 source-bound worker"),
                        (V2_PATH, "V2 support worker"),
                        (V1_PATH, "V1 support worker"),
                        (V5_PATH, "V5 support verifier")):
        rec = _record(path, label)
        static[rec["path"]] = rec
    static[base_record["path"]] = base_record
    for row in cases:
        if isinstance(row, dict) and row.get("sentinel_id") == TARGET:
            for role in ("source_xml", "source_def"):
                rec = _record_exact(row[role], f"{row['row_key']} bound {role}")
                static[rec["path"]] = rec
    static[manifest_record["path"]] = manifest_record
    deferred: list[dict[str, Any]] = []
    for row in cases:
        deferred.extend(V2._products(row))
    command = [str(PYTHON), str(V3_PATH), "--run", "--manifest", str(manifest_path),
               "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/initial-support-v3.json"]
    request = {
        "schema": "ds02.request.v1", "variant_schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v3-f3-source-bound",
        "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V3_F3_SOURCE_BOUND",
        "request_variant": "owner_grid_initial_support_audit_v3_f3_source_bound_root709",
        "family_id": "infra", "physical_case_id": "THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V3_F3_SOURCE_BOUND",
        "case_id": "THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_AUDIT_V3_F3_SOURCE_BOUND",
        "attempt_id": "PARENT_AFTER_RESERVATION_REQUIRED", "kind": "cpu", "cpu_task_kind": "audit",
        "cpu_threads": 1, "execution_allowed": False, "launch_disabled": True,
        "solver_launch": False, "gencase_launch": False, "source_only": True,
        "native_payload_read": False, "command": command,
        "command_scope": "parent_after_reservation_template_only", "manifest": manifest_record,
        "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "deferred_input_records": deferred, "source_closure_missing": [],
        "resource_scope": {"cpu_seconds": 900, "memory_bytes": 4 * 1024 * 1024 * 1024,
                           "scratch_bytes": 512 * 1024 * 1024, "static_metadata_cap_bytes": JSON_CAP,
                           "payload_reads": "parent_after_reservation_only"},
        "header_binding": manifest["header_binding"], "f3_source_binding": binding,
        "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0,
    }
    request_path = output_dir / "initial-support-request-v3-f3-source-bound.json"
    request_record = _write_json(request_path, request, "V3 support request")
    package = {"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-package.v3-f3-source-bound",
               "status": request["status"], "manifest": manifest_record, "request": request_record,
               "f3_source_binding": binding, "input_records": static, "deferred_input_records": deferred,
               "payload_read_by_builder": False, "solver_launch": False, "gencase_launch": False,
               "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0}
    package_path = output_dir / "initial-support-package-v3-f3-source-bound.json"
    package_record = _write_json(package_path, package, "V3 support package")
    return {"status": request["status"], "manifest": str(manifest_path), "request": str(request_path),
            "package": str(package_path), "manifest_record": manifest_record, "request_record": request_record,
            "package_record": package_record, "f3_rows": len(binding["rows"]), "scientific_credit": 0}


def _validate_runtime(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != V3_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V3_F3_SOURCE_BOUND":
        raise SourceBoundFailure("V3 F3 source-bound manifest schema/status mismatch")
    if manifest.get("solver_launch") is not False or manifest.get("gencase_launch") is not False:
        raise SourceBoundFailure("V3 manifest permits solver/GenCase launch")
    if manifest.get("scientific_scope", {}).get("scientific_credit") != 0:
        raise SourceBoundFailure("V3 manifest carries scientific credit")
    binding = manifest.get("f3_source_binding")
    if not isinstance(binding, dict) or binding.get("generated_xml_fallback") is not False or binding.get("candidate_label_fallback") is not False:
        raise SourceBoundFailure("V3 manifest lacks strict F3 source binding")
    rows = {f"{r.get('sentinel_id')}:{r.get('grid_label')}": r for r in manifest.get("cases", []) if isinstance(r, dict)}
    for grid in GRIDS:
        row = rows.get(f"{TARGET}:{grid}")
        if row is None or not isinstance(row.get("source_xml"), dict) or not isinstance(row.get("source_def"), dict):
            raise SourceBoundFailure(f"F3 {grid} source XML/Def binding is missing")
        if row.get("source_xml_binding", {}).get("alias_or_label_fallback") is not False:
            raise SourceBoundFailure(f"F3 {grid} source binding is not exact")


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_guard = _read_json(manifest_path, "V3 F3 source-bound manifest")
    _validate_runtime(manifest)
    # Re-check the source records against current bytes before delegating to
    # V2/V1.  This closes the exact XML/Def source edge without touching the
    # consumed V2 package.
    for row in manifest["cases"]:
        if isinstance(row, dict) and row.get("sentinel_id") == TARGET:
            _record_exact(row["source_xml"], f"{row['row_key']} source XML")
            _record_exact(row["source_def"], f"{row['row_key']} source Def")
    attempt_root = _abs(attempt_root)
    materialized_dir = attempt_root / "worker-materialized"
    materialized_dir.mkdir(parents=True, exist_ok=True)
    temp_v2 = materialized_dir / "initial-support-manifest-v2-f3-bound.json"
    if temp_v2.exists() or temp_v2.is_symlink():
        raise SourceBoundFailure(f"refusing to overwrite {temp_v2}")
    value = copy.deepcopy(manifest)
    value["schema"] = V2_SCHEMA
    value["status"] = "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2"
    temp_v2.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    compat_output = materialized_dir / "initial-support-v2-f3-bound.json"
    inner = V2.run(temp_v2, attempt_root, compat_output)
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise SourceBoundFailure(f"refusing to overwrite V3 report: {output_path}")
    result = {"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v3-f3-source-bound",
              "status": "COMPLETE_PARTIAL_OWNER_GRID_INITIAL_SUPPORT_V3_F3_SOURCE_BOUND",
              "manifest": manifest_guard, "f3_source_binding": manifest["f3_source_binding"],
              "compat_v2_report": {"path": str(compat_output), "sha256": _sha(compat_output.read_bytes()),
                                   "stat": _stat(compat_output)},
              "cases": inner.get("cases", []), "case_counts": inner.get("case_counts", {}),
              "native_mass_source": "ROOT709_DECODER_FIELDS_ONLY", "native_mass_unknown_if_not_exposed": True,
              "xml_mass_is_not_native": True, "xml_fallback": False,
              "scientific_scope": {"continuous_owner": "UNKNOWN", "native_mass": "UNKNOWN",
                                   "neighbor_grid_truth": False, "mass_rescale": False, **NO_CREDIT},
              "read_scope": {"generated_xml": True, "fluid_vtk": True, "bound_vtk": True,
                              "native_bi4_bytes": True, "source_xml": True, "source_def": True,
                              "solver_launch": False, "gencase_launch": False, "production_hdf5_read": False}}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f3-source-bound-") as td:
        root = Path(td)
        source_xml = root / "owner.xml"; source_xml.write_text("<case owner='F3'/>", encoding="utf-8")
        source_def = root / "owner_Def.xml"; source_def.write_text("<def dp='0.006'/>", encoding="utf-8")
        cases = []
        grids = []
        for grid in GRIDS:
            candidate = root / f"{grid}_Def.xml"; candidate.write_text(f"<def dp='{grid}'/>", encoding="utf-8")
            rec = _record(candidate, f"candidate {grid}")
            grids.append({"label": grid, "candidate_def": rec})
            cases.append({"sentinel_id": TARGET, "grid_label": grid, "candidate_def": rec, "generated_xml": {"path": str(root / f"{grid}.xml")}})
        source = {"schema": SOURCE_SCHEMA, "status": SOURCE_STATUS,
                  "cases": [{"sentinel_id": TARGET, "source_xml": _record(source_xml, "owner XML"),
                             "source_def": _record(source_def, "owner Def"), "grids": grids}]}
        # The helper requires an on-disk owner manifest, so exercise the same
        # public source records through that file.
        owner_path = root / "owner-manifest.json"
        owner_path.write_text(json.dumps(source), encoding="utf-8")
        bound, binding = _bind_f3_rows({"cases": cases}, source, owner_path)
        assert len(bound) == 3 and len(binding["rows"]) == 3
        bad = copy.deepcopy(source); bad["cases"][0]["grids"][1]["candidate_def"]["sha256"] = "0" * 64
        try:
            _bind_f3_rows({"cases": cases}, bad, owner_path)
        except SourceBoundFailure:
            pass
        else:
            raise AssertionError("candidate SHA mutation was accepted")
        assert all(row["source_xml_binding"]["alias_or_label_fallback"] is False for row in bound)
    print("PASS_F3_SOURCE_BOUND_INITIAL_SUPPORT_V3_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--base-manifest", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.build:
            if None in (args.base_manifest, args.source_manifest, args.output_dir):
                parser.error("--build requires --base-manifest, --source-manifest, --output-dir")
            result = build(args.base_manifest, args.source_manifest, args.output_dir)
            print(json.dumps({"status": result["status"], "manifest": result["manifest"],
                              "request": result["request"], "package": result["package"],
                              "f3_rows": result["f3_rows"], "scientific_credit": 0}, sort_keys=True))
            return 0
        if None in (args.manifest, args.attempt_root, args.output):
            parser.error("--run requires --manifest, --attempt-root, --output")
        result = run(args.manifest, args.attempt_root, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output)),
                          "case_counts": result["case_counts"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (SourceBoundFailure, V2.SupportV2Failure, V1.AuditFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F3_SOURCE_BOUND_INITIAL_SUPPORT_V3: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
