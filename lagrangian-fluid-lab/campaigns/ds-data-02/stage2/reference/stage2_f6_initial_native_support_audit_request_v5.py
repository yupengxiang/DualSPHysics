#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Prepare the source-bound ROOT272 F6 frame-0 support audit.

Only ROOT244's and ROOT252's proof/report, receipts and small XML files are read while
building.  BI4 and VTK records are stat'ed but never hashed or opened here;
the parent runtime must reserve the request and the worker then performs the
pre/content/post checks.  Existing source/current and coarse/fine GenCase
products are kept as six independent producer identities for each sentinel.
The emitted manifest selects ``POSITION_ONLY_INITIAL_SUPPORT``: Idp and
Pos/Posd are required, while Vel/Rhop/Mass are measured only if the GenCase
decoder actually emits them and otherwise remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = PYTHON.resolve()
PYVENV_CFG = PYTHON.parent.parent / "pyvenv.cfg"
WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
CALIBRATED = HERE / "stage2_f1_native_selected_observer_v1.py"
CONTRACT = HERE / "stage2_f6_initial_native_support_audit_contract_v5.json"
REQUEST_BUILDER = HERE / "stage2_f6_initial_native_support_audit_request_v5.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")
RUNTIME_V2 = HERE.parents[3] / "scripts/ds_data02_runtime_v2.py"
STRICT_V1 = HERE.parents[3] / "scripts/ds_data02_strict_dispatch_v1.py"
BATCH = HERE.parents[3] / "scripts/ds_data02_batch_runner.py"
PROOF_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_OWNER_RIGID_METADATA_V1_ACTUAL_ROOT_VERIFICATION_244.json"
OWNER_PROOF_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_V1_ACTUAL_ROOT_VERIFICATION_252.json"
PRIOR_FAILURE_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_INITIAL_NATIVE_SUPPORT_V4_ACTUAL_POSITIONAL_VTK_INTERFACE_FAILURE_ROOT_VERIFICATION_267.json"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v5"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f6-initial-native-support-request.v5"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
MAX_SMALL = 16 * 1024 * 1024
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")


class BuildFailure(RuntimeError):
    pass


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _stable_read(path: Path, label: str, *, parse_json: bool = False, max_bytes: int = MAX_SMALL) -> tuple[Any, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise BuildFailure(f"{label} exceeds bounded preparation read: {before['bytes']}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block); chunks.append(block)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while read")
    value: Any = None
    if parse_json:
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildFailure(f"{label} is not JSON") from exc
        if not isinstance(value, dict):
            raise BuildFailure(f"{label} JSON is not an object")
    return value, {"path": str(path), "label": label, "bytes": after["bytes"],
                   "sha256": digest.hexdigest(), "stat": after, "stable_read": True}


def _small(path: Path, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    return _stable_read(path, label, parse_json=parse_json, max_bytes=MAX_SMALL)


def _payload_record(path: Path, label: str, *, known_sha256: str | None, role: str,
                    sentinel_id: str, grid: str) -> dict[str, Any]:
    path = _regular(path, label)
    stat = _stat(path)
    return {"path": str(path), "label": label, "role": role, "sentinel_id": sentinel_id,
            "grid": grid, "frame": 0, "bytes": stat["bytes"],
            "stat_at_prepare": stat, "known_sha256": known_sha256,
            "sha_source": "ROOT244/source producer trusted SHA" if known_sha256 else "UNKNOWN_UNTIL_PARENT_AFTER_RESERVATION",
            "worker_must_full_sha_pre_and_post": True, "worker_must_reject_stat_or_sha_change": True}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite of immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _python_binding() -> dict[str, Any]:
    literal = _regular(PYTHON, "literal venv Python") if not PYTHON.is_symlink() else PYTHON.expanduser().absolute()
    if not PYTHON.is_symlink():
        raise BuildFailure("literal venv Python must remain a symlink")
    resolved = _regular(PYTHON_TARGET, "resolved venv Python")
    target_rec = _small(resolved, "resolved venv Python")
    cfg = _small(PYVENV_CFG, "pyvenv.cfg")
    return {"argv0_literal": str(literal), "literal_required": True,
            "resolved": target_rec[1], "pyvenv_cfg": cfg[1]}


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _case_paths(sentinel: str, grid: str) -> dict[str, Path]:
    if sentinel == "F6-S1":
        source_root = DATA / "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025/root-stage1-f6-omega-95p0-genuine-gencase-082"
        source_stem = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025"
        roots = {"coarse": DATA / "F6_S1_SPATIAL_V1_COARSE_DP0p031250/f6_s1_spatial_v1_coarse_dp0p031250-001",
                 "fine": DATA / "F6_S1_SPATIAL_V1_FINE_DP0p020000/f6_s1_spatial_v1_fine_dp0p020000-001"}
    elif sentinel == "F6-S2":
        source_root = DATA / "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025/root-stage1-f6-2p0-genuine-gencase-073"
        source_stem = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025"
        roots = {"coarse": DATA / "F6_S2_SPATIAL_V1_COARSE_DP0p031250/f6_s2_spatial_v1_coarse_dp0p031250-001",
                 "fine": DATA / "F6_S2_SPATIAL_V1_FINE_DP0p020000/f6_s2_spatial_v1_fine_dp0p020000-001"}
    else:
        raise BuildFailure(f"unknown sentinel {sentinel}")
    if grid == "source_current":
        return {"root": source_root, "xml": source_root / f"{source_stem}.xml", "bi4": source_root / f"{source_stem}.bi4",
                "receipt": source_root / "execution-receipt.json", "fluid_vtk": source_root / f"{source_stem}_Fluid.vtk",
                "bound_vtk": source_root / f"{source_stem}_Bound.vtk"}
    root = roots[grid]
    return {"root": root, "xml": root / "generated.xml", "bi4": root / "generated.bi4", "receipt": root / "execution-receipt.json",
            "fluid_vtk": root / "generated_Fluid.vtk", "bound_vtk": root / "generated_Bound.vtk"}


def _report_case(report: dict[str, Any], sentinel: str, grid: str, xml_path: Path) -> dict[str, Any]:
    matches = [case for case in report.get("cases", []) if case.get("sentinel_id") == sentinel]
    if len(matches) != 1:
        raise BuildFailure(f"ROOT244 report missing unique {sentinel}")
    case = matches[0]
    if grid == "source_current":
        record = case.get("source_xml")
        expected = record.get("path") if isinstance(record, dict) else None
    else:
        grids = [item for item in case.get("candidate_grids", []) if item.get("grid") == grid]
        if len(grids) != 1:
            raise BuildFailure(f"ROOT244 report missing {sentinel}/{grid}")
        record = grids[0].get("generated_xml_record") or grids[0].get("generated_xml")
        expected = record.get("path") if isinstance(record, dict) else record
    if Path(str(expected)).absolute() != xml_path.absolute():
        raise BuildFailure(f"ROOT244 report/XML identity mismatch for {sentinel}/{grid}")
    return case


def _case_manifest(sentinel: str, grid: str, report: dict[str, Any], records: dict[str, dict[str, Any]],
                   deferred: list[dict[str, Any]]) -> dict[str, Any]:
    paths = _case_paths(sentinel, grid)
    source_case = _report_case(report, sentinel, grid, paths["xml"])
    _, xml_rec = _small(paths["xml"], f"{sentinel}/{grid} generated XML")
    report_xml = source_case.get("source_xml") if grid == "source_current" else next(item for item in source_case["candidate_grids"] if item.get("grid") == grid).get("generated_xml_record")
    if isinstance(report_xml, dict) and report_xml.get("sha256") and report_xml["sha256"] != xml_rec["sha256"]:
        raise BuildFailure(f"{sentinel}/{grid} XML differs from ROOT244 report")
    receipt, receipt_rec = _small(paths["receipt"], f"{sentinel}/{grid} producer receipt", parse_json=True)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise BuildFailure(f"{sentinel}/{grid} producer receipt is not completed rc=0")
    output_root = Path(str(receipt.get("output_root", ""))).absolute()
    if output_root != paths["root"].absolute() or paths["xml"].parent != output_root:
        raise BuildFailure(f"{sentinel}/{grid} receipt output root does not contain generated XML")
    records[xml_rec["path"]] = xml_rec; records[receipt_rec["path"]] = receipt_rec
    known = None
    if grid == "source_current":
        known = {"F6-S1": "c02c61da2ec567c4326bcf5259d3b488b7e60cba7daa70731433107dc9eaa6d6",
                 "F6-S2": "b7617cbd0f14cdf46b36d9fba483fc7cb76eecf7ab651c4590aab261e71ebccc"}[sentinel]
    items: dict[str, dict[str, Any]] = {}
    for role, path in (("native_bi4", paths["bi4"]), ("fluid_vtk", paths["fluid_vtk"]), ("bound_vtk", paths["bound_vtk"])):
        item = _payload_record(path, f"{sentinel}/{grid} {role}", known_sha256=known if role == "native_bi4" else None,
                               role=role, sentinel_id=sentinel, grid=grid)
        items[role] = item; deferred.append(item)
    producer_request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    physical = str(producer_request.get("physical_case_id") or sentinel)
    case_id = str(producer_request.get("case_id") or sentinel)
    return {"sentinel_id": sentinel, "physical_case_id": physical, "producer_case_id": case_id,
            "grid": grid, "xml": xml_rec,
            "producer_receipt": receipt_rec, "deferred": items,
            "decoder": {"path": str(DECODER)}, "decoder_source": {"path": str(DECODER_SOURCE)},
            "field_scope": "POSITION_ONLY_INITIAL_SUPPORT",
            "optional_initial_fields": {"Vel": "UNKNOWN_IF_MISSING", "Rhop": "UNKNOWN_IF_MISSING",
                                         "MassFluid": "UNKNOWN_IF_MISSING", "MassBound": "UNKNOWN_IF_MISSING"},
            "expected_initial_product_only": True, "solver_dynamic_truth": "UNKNOWN_NOT_RUN"}


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, proof_rec = _small(args.proof, "ROOT244 proof", parse_json=True)
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise BuildFailure("ROOT244 proof is not an actual proof")
    report_path = Path(str(proof.get("report", ""))).expanduser().absolute()
    report, report_rec = _small(report_path, "ROOT244 report", parse_json=True)
    if proof.get("report_sha256") != report_rec["sha256"] or report.get("schema") != "ds02.stage2.f6-owner-rigid-metadata-audit.v1":
        raise BuildFailure("ROOT244 proof/report join failed")
    owner_proof, owner_proof_rec = _small(args.owner_proof, "ROOT252 continuous-owner proof", parse_json=True)
    if owner_proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(owner_proof.get("status", "")):
        raise BuildFailure("ROOT252 proof is not an actual verification proof")
    owner_report_path = Path(str(owner_proof.get("report", ""))).expanduser().absolute()
    owner_report, owner_report_rec = _small(owner_report_path, "ROOT252 continuous-owner report", parse_json=True)
    if owner_proof.get("report_sha256") != owner_report_rec["sha256"] or owner_report.get("schema") != "ds02.stage2.f6-continuous-owner-geometry-audit.v1":
        raise BuildFailure("ROOT252 proof/report join failed")
    prior_failure, prior_failure_rec = _small(PRIOR_FAILURE_DEFAULT, "ROOT267 V4 failure proof", parse_json=True)
    if prior_failure.get("schema") != "ds02.stage2.root-actual-verification.v1" or "FAIL" not in str(prior_failure.get("status", "")):
        raise BuildFailure("ROOT267 prior failure proof is not an actual failure proof")
    prior_request_path = Path(str(prior_failure.get("request", ""))).expanduser().absolute()
    prior_request, prior_request_rec = _small(prior_request_path, "ROOT267 V4 consumed request", parse_json=True)
    if prior_failure.get("request_sha256") != prior_request_rec["sha256"]:
        raise BuildFailure("ROOT267 failure proof/request SHA join failed")
    records: dict[str, dict[str, Any]] = {proof_rec["path"]: proof_rec, report_rec["path"]: report_rec,
                                           owner_proof_rec["path"]: owner_proof_rec, owner_report_rec["path"]: owner_report_rec,
                                           prior_failure_rec["path"]: prior_failure_rec, prior_request_rec["path"]: prior_request_rec}
    deferred: list[dict[str, Any]] = []
    cases = [_case_manifest(sentinel, grid, report, records, deferred) for sentinel in ("F6-S1", "F6-S2") for grid in ("source_current", "coarse", "fine")]
    py = _python_binding()
    for item in (py["resolved"], py["pyvenv_cfg"]): records[item["path"]] = item
    for path, label in ((WORKER, "ROOT272 F6 native support worker"), (REQUEST_BUILDER, "ROOT272 request builder"), (OBSERVER, "native observer v2"), (CALIBRATED, "calibrated native observer helpers"), (CONTRACT, "ROOT272 contract"),
                        (DECODER, "official BI4 decoder"), (DECODER_SOURCE, "official BI4 decoder source"),
                        (RUNTIME_V2, "runtime v2"), (STRICT_V1, "strict dispatch v1"), (BATCH, "batch runner"),
                        (HERE / "stage2_f6_continuous_owner_geometry_audit_v1.py", "F6 XML owner audit dependency")):
        _, rec = _small(path, label, parse_json=False)
        records[rec["path"]] = rec
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_ROOT272_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V5",
                "root244_proof": proof.get("status"), "proof": proof_rec, "report": report_rec,
                "root252_owner_proof": owner_proof.get("status"), "owner_proof": owner_proof_rec,
                "owner_report": owner_report_rec, "prior_v4_failure_proof": prior_failure_rec,
                "prior_v4_failure_request": prior_request_rec, "cases": cases,
                "deferred_input_records": deferred,
                "source_binding": {"continuous_owner_mass_kg": 4851.988676250775, "continuous_owner_basis": "explicit XML fluid drawbox volume times rhop0",
                                    "physical_massbody_kg": 128.0, "legacy_source_sample_mass_kg": 5120.0,
                                    "sample_mass_is_not_continuous_owner": True, "no_rescale": True,
                                    "world_axis_calibration": "UNKNOWN", "fluid_initial_velocity": "MEASURED_ONLY_IF_NATIVE_FRAME_EXPOSES_IT",
                                    "root252_continuous_owner_geometry_join": "actual XML drawbox owner diagnostic; native support remains to be measured by this worker",
                                    "native_integrity": "V5 pre-SHA/stat before decoder; on success decoder saved_file.path/bytes/sha256 plus post-SHA/stat; on decoder failure post-SHA/stat and cleanup are checked while the original decoder exception is preserved",
                                    "initial_field_scope": "POSITION_ONLY_INITIAL_SUPPORT",
                                    "missing_initial_fields": "Vel/Rhop/Mass remain UNKNOWN; no fabricated zero or XML-derived value"},
                "read_scope": {"builder_reads": "ROOT244 proof/report/receipts/XML and stat-only deferred payload records",
                               "builder_native_payload_read": False, "builder_vtk_payload_read": False, "worker_native_frame_count": 6,
                               "worker_vtk_file_count": 12, "solver_launch": False, "hdf5_read": False},
                "qualification": QUALIFICATION}
    _write_once(args.manifest_output, manifest)
    _, manifest_rec = _small(args.manifest_output, "ROOT272 manifest", parse_json=True)
    records[manifest_rec["path"]] = manifest_rec
    static_paths = sorted(records)
    static_hashes = {path: records[path]["sha256"] for path in static_paths}
    payload_native_bytes = sum(int(item["bytes"]) for item in deferred if item["role"] == "native_bi4")
    payload_vtk_bytes = sum(int(item["bytes"]) for item in deferred if item["role"] in {"fluid_vtk", "bound_vtk"})
    native_passes = 4  # wrapper pre-SHA + decoder's frame SHA + decoder read + wrapper post-SHA
    vtk_passes = 3      # wrapper pre-SHA + bounded parser read + wrapper post-SHA
    request = {"schema": REQUEST_SCHEMA, "variant_schema": VARIANT_SCHEMA,
               "status": "READY_FOR_PARENT_V8_F6_INITIAL_NATIVE_SUPPORT_ROOT272_V5", "kind": "cpu", "cpu_task_kind": "audit",
               "request_id": "f6-initial-native-support-audit-root272-v5", "family_id": "F6", "sentinel_ids": ["F6-S1", "F6-S2"],
               "case_id": args.case_id, "attempt_id": args.attempt_id, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY),
               "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f6_initial_native_support_manifest_v5.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f6_initial_native_support_audit_v5.json"],
               "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG), "resolved_sha256": py["resolved"]["sha256"]},
               "input_files": static_paths, "input_sha256": static_hashes, "input_records": records, "manifest": manifest_rec,
               "prior_failure_proof": prior_failure_rec, "prior_failure_request": prior_request_rec,
               "deferred_input_files": sorted(item["path"] for item in deferred), "deferred_input_records": deferred,
               "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "worker_post_sha_and_stat": True,
                                          "required_stat_fields": list(STAT_FIELDS), "known_sha_checked_when_present": True,
                                          "source_replace_or_stat_change": "FAIL", "worker_not_parent_v8_deferred_hash": True},
               "source_binding": manifest["source_binding"],
               "resources": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 2 * 1024**3,
                             "external_storage_max_bytes": 1024 * 1024**3, "home_storage_max_bytes": 128 * 1024**2,
                             "log_max_bytes": 1024 * 1024, "scratch_max_bytes": 1024 * 1024**3, "parent_guard_required": True},
               "estimated_native_read_passes": native_passes, "estimated_native_read_bytes": payload_native_bytes * native_passes,
               "estimated_vtk_read_passes": vtk_passes, "estimated_vtk_read_bytes": payload_vtk_bytes * vtk_passes,
               "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()) + payload_native_bytes * native_passes + payload_vtk_bytes * vtk_passes,
               "estimated_read_bytes_scope": "static proof/report/receipt/XML/code closure plus six BI4 frame-0 and twelve Fluid/Bound VTK files; V5 pre-SHA/stat before decoder, success saved_file.path/bytes/sha256, failure post-SHA/stat and cleanup with original decoder exception preserved",
               "storage_scope": {"native_payload_read": "six frame-0 BI4 files plus twelve Fluid/Bound VTK files only", "full_native_tree_scan": False, "hdf5_read": False, "solver_launch": False, "output_root": "{attempt_root}"},
               "qualification": QUALIFICATION, "launch_disabled": True, "execution_allowed": False, "solver_started": False, "native_payload_read": False, "hdf5_read": False, "ledger_mutation": False}
    request["sha256"] = _canonical(request)
    _write_once(args.output_request, request)
    return manifest, request


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root272-builder-") as directory:
        path = Path(directory) / "payload.bi4"
        path.write_bytes(b"tiny")
        record = _payload_record(path, "fixture BI4", known_sha256=None, role="native_bi4", sentinel_id="F6-S1", grid="coarse")
        assert record["bytes"] == 4 and record["known_sha256"] is None and record["stat_at_prepare"]["bytes"] == 4
        assert _canonical({"x": 1}) == _canonical({"x": 1})
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V5_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    parser.add_argument("--proof", type=Path, default=PROOF_DEFAULT)
    parser.add_argument("--owner-proof", type=Path, default=OWNER_PROOF_DEFAULT)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F6_INITIAL_NATIVE_SUPPORT_AUDIT_ROOT272_V5")
    parser.add_argument("--attempt-id", default="f6-initial-native-support-audit-root272-v5-001")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest_output is None or args.output_request is None:
        parser.error("--manifest-output and --output-request are required with --build")
    try:
        manifest, request = build(args)
    except Exception as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V1: {exc}")
        return 2
    print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output.absolute()), "request": str(args.output_request.absolute()), "sha256": request["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
