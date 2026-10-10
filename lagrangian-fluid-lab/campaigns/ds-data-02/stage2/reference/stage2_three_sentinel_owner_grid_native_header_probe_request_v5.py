#!/usr/bin/env python3
"""Runtime-compatible V5 adapter for the nine-row native-header probe.

The consumed V4 adapter is retained unchanged.  This version adds the
transitive verifier/worker import closure, derives readiness from the actual
completed-row counts rather than a mutable V3 status string, and keeps the
manifest status expected by the frozen V2 probe.  It also materializes the
final manifest before binding the command, so no temporary manifest path can
escape into a parent request.

The self-test builds nine manufactured producer rows, obtains each
runtime-shaped receipt from a real tiny subprocess, invokes the V4 builder and
the frozen V2 probe through subprocesses, and rejects a producer-request byte
mutation.  It is a fixture-only ABI test and grants no production/scientific
credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_request_v4.py"
PROBE = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_SOURCES = (
    HERE.parents[4] / "lagrangian-fluid-lab/scripts/ds_data02_runtime.py",
    HERE.parents[4] / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
)
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
VARIANT_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-request.v5"
BUILDER_VARIANT = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-request.v5-transitive-status-filter"
JSON_CAP = 10 * 1024 * 1024
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
EXPECTED_ROWS = 9

# V2 loads V3, V3 loads V2, and V2 loads V1 plus the guarded audit worker.
# V1's worker loads the geometry helper.  Bind all of these source files in
# the request instead of relying on the primary checkout at launch time.
TRANSITIVE = (
    "stage2_three_sentinel_owner_grid_initial_support_verify_v2.py",
    "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py",
    "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py",
    "stage2_four_sentinel_gencase_geometry_support_audit_v1.py",
)


class BuildFailure(RuntimeError):
    pass


def _load_v4() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_native_header_request_v4_for_v5", V4_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load V4 adapter: {V4_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds 10 MiB source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "label": label, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "stat": after,
            "payload_read_by_builder": False}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_abs(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object")
    return value


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable V5 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _replace_exact(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_exact(item, old, new) for item in value]
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            result[new if key == old else key] = _replace_exact(item, old, new)
        return result
    return value


def _normalise_and_validate(manifest: dict[str, Any], request: dict[str, Any], *, ready: bool, final_manifest: Path) -> None:
    """Own the status/ABI filter; do not trust a V3 status string."""
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise BuildFailure(f"V4 did not produce accepted V2 manifest: {manifest.get('schema')!r}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_ROWS:
        raise BuildFailure("native-header manifest does not contain exactly nine cases")
    expected_manifest_status = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE" if ready else "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS"
    # The frozen probe accepts only the historical READY spelling.  Keep that
    # worker ABI while exposing V5 status separately on the request.
    manifest["status"] = expected_manifest_status
    manifest["status_filter_v5"] = {"ready_from_actual_rows": ready, "scientific_credit": 0}
    request["schema"] = REQUEST_SCHEMA
    request["variant_schema"] = VARIANT_SCHEMA
    # The native-header probe spans F2/F3/F5 source rows.  Runtime V8 only
    # accepts infra or a single F1..F7 family identifier; ``DS02`` and the
    # historical three-sentinel label are source-package labels, not runtime
    # families.  Keep them in the descriptive fields and use the legal
    # cross-family value for the executable request.
    request["family_id"] = "infra"
    request["cwd"] = str(HERE.parents[4] / "lagrangian-fluid-lab")
    request["worktree_root"] = str(HERE.parents[4])
    request["status"] = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V5" if ready else "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS_V5"
    request["kind"] = "cpu"
    request["cpu_task_kind"] = "audit"
    request["execution_allowed"] = False
    request["launch_disabled"] = True
    request["gencase_launch"] = False
    request["solver_launch"] = False
    request["native_payload_read"] = False
    request["ledger_mutation"] = False
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    if request["family_id"] != "infra":
        raise BuildFailure("native-header V5 must use the legal infra cross-family runtime family")
    if request["cwd"] != str(HERE.parents[4] / "lagrangian-fluid-lab"):
        raise BuildFailure("native-header V5 cwd is not the current worktree's lab root")
    if ready and request.get("status_filter_v5") is None:
        request["status_filter_v5"] = "READY_FROM_NINE_COMPLETED_ROWS"
    deferred = request.get("deferred_input_records")
    if not isinstance(deferred, list) or len(deferred) != 45:
        raise BuildFailure("native-header request does not retain the 45 deferred product records")
    if not isinstance(request.get("input_records"), dict):
        raise BuildFailure("native-header request lacks static input records")
    records = request["input_records"]
    if request.get("input_files") != sorted(records):
        raise BuildFailure("native-header input_files is not the exact static record key set")
    input_sha = request.get("input_sha256")
    if not isinstance(input_sha, dict) or set(input_sha) != set(records):
        raise BuildFailure("native-header input SHA map is not exact")
    for path_text, record in records.items():
        if not isinstance(record, dict) or record.get("path") != path_text:
            raise BuildFailure(f"native-header static path record mismatch: {path_text}")
        record_stat = record.get("stat") if isinstance(record.get("stat"), dict) else {}
        record_bytes = record.get("bytes", record_stat.get("bytes", JSON_CAP + 1))
        if int(record_bytes) > JSON_CAP:
            raise BuildFailure(f"native-header static record exceeds 10 MiB: {path_text}")
        if path_text.startswith("/tmp/"):
            raise BuildFailure(f"native-header request retains temporary path: {path_text}")
    command = request.get("command")
    if not isinstance(command, list) or not command or command[0] != str(_abs(PYTHON)):
        raise BuildFailure("native-header command does not retain literal venv argv0")
    if "--manifest" not in command:
        raise BuildFailure("native-header command lacks --manifest")
    index = command.index("--manifest")
    if index + 1 >= len(command) or command[index + 1] != str(final_manifest):
        raise BuildFailure("native-header command does not point to final manifest")
    if str(_abs(PROBE)) not in [str(item) for item in command if isinstance(item, str)]:
        raise BuildFailure("native-header command does not invoke V2 probe")
    if request.get("manifest", {}).get("path") != str(final_manifest):
        raise BuildFailure("native-header manifest record path is not final")


def build(initial_manifest: Path, product_map: Path, decoder: Path, output_dir: Path,
          initial_request: Path | None = None, admission_manifest: Path | None = None) -> dict[str, Any]:
    v4 = _load_v4()
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing non-empty output directory: {output_dir}")
    with tempfile.TemporaryDirectory(prefix="native-header-v5-v4-staging-") as stage:
        stage_out = Path(stage) / "v4-output"
        v4_result = v4.build(_abs(initial_manifest), _abs(product_map), _abs(decoder), stage_out,
                             _abs(initial_request) if initial_request else None,
                             _abs(admission_manifest) if admission_manifest else None)
        manifest = _read_json(Path(v4_result["manifest"]), "V4 native-header manifest")
        request = _read_json(Path(v4_result["request"]), "V4 native-header request")
        ready = int(v4_result.get("actual_rows", 0)) == EXPECTED_ROWS and int(v4_result.get("proof_rows", 0)) == EXPECTED_ROWS
        # V4 records its staging manifest before V5 has a stable output path.
        # Remove that record and rebind all exact references before validation;
        # otherwise the source-cap/path gate would reject V4's disposable
        # /tmp staging path even though it never enters the final request.
        old_manifest = str(_abs(v4_result["manifest"]))
        final_manifest = output_dir / "native-header-probe-manifest-v5.json"
        request = _replace_exact(request, old_manifest, str(final_manifest))
        early_static = request.get("input_records")
        if isinstance(early_static, dict):
            early_static.pop(old_manifest, None)
            request["input_records"] = early_static
            request["input_files"] = sorted(early_static)
            request["input_sha256"] = {path: early_static[path]["sha256"] for path in early_static}
        _normalise_and_validate(manifest, request, ready=ready, final_manifest=output_dir / "native-header-probe-manifest-v5.json")

        # Add the complete local import closure to the static request.  The
        # old V4 closure omitted the V2/V1 verifier chain and geometry helper.
        closure = {str(_abs(V4_PATH)): _record(V4_PATH, "V4 request adapter")}
        closure[str(_abs(__file__))] = _record(Path(__file__), "V5 request adapter")
        v3_path = getattr(v4, "V3_PATH", None)
        if isinstance(v3_path, Path):
            closure[str(_abs(v3_path))] = _record(v3_path, "V3 request adapter")
        closure[str(_abs(PROBE))] = _record(PROBE, "V2 native-header probe worker")
        for name in TRANSITIVE:
            path = HERE / name
            closure[str(_abs(path))] = _record(path, f"native-header transitive source: {name}")
        for path in RUNTIME_SOURCES:
            closure[str(_abs(path))] = _record(path, f"runtime ABI source: {path.name}")
        static = request.get("input_records")
        if not isinstance(static, dict):
            raise BuildFailure("V4 request static input map is missing")
        for path, record in closure.items():
            static[path] = record
        request["input_records"] = static
        request["input_files"] = sorted(static)
        request["input_sha256"] = {path: static[path]["sha256"] for path in request["input_files"]}
        request.setdefault("runtime_closure", {})["transitive_import_records"] = closure
        request["runtime_closure"]["transitive_import_complete"] = True
        request["runtime_closure"]["runner_source_records"] = {
            path: record for path, record in closure.items() if path in {str(_abs(item)) for item in RUNTIME_SOURCES}
        }
        request["source_binding"] = {
            **dict(request.get("source_binding") or {}),
            "native_header_request_v5": str(_abs(__file__)),
            "native_header_status_filter": "actual_rows_and_proof_rows_exactly_nine",
            "native_header_worker_manifest_schema": MANIFEST_SCHEMA,
            "xml_mass_fallback": False,
            "velocity_rhop_mass_missing": "UNKNOWN_NOT_EXPOSED_BY_INITIAL_DECODER",
        }
        final_request = output_dir / "native-header-probe-request-v5.json"
        _write_once(final_manifest, manifest)
        final_manifest_record = _record(final_manifest, "V5 native-header manifest")
        request = _replace_exact(request, old_manifest, str(final_manifest))
        command = request["command"]
        command[command.index("--manifest") + 1] = str(final_manifest)
        request["command"] = command
        static = request["input_records"]
        static.pop(old_manifest, None)
        static[str(final_manifest)] = final_manifest_record
        request["input_records"] = static
        request["input_files"] = sorted(static)
        request["input_sha256"] = {path: static[path]["sha256"] for path in request["input_files"]}
        request["manifest"] = final_manifest_record
        _normalise_and_validate(manifest, request, ready=ready, final_manifest=final_manifest)
        _write_once(final_request, request)
        request_record = _record(final_request, "V5 native-header request")
        return {"status": request["status"], "manifest": str(final_manifest), "request": str(final_request),
                "actual_rows": int(v4_result.get("actual_rows", 0)), "proof_rows": int(v4_result.get("proof_rows", 0)),
                "static_input_count": len(static), "deferred_input_count": len(request["deferred_input_records"]),
                "request_record": request_record, "production_payload_read": False, "scientific_credit": 0}


def _tiny_runtime_receipt(runtime: Path, producer: Path, receipt: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(PYTHON), str(runtime), str(producer), str(receipt)], capture_output=True, text=True, timeout=20, check=False)


def _real_fixture_self_test() -> None:
    """Exercise nine receipt subprocesses, V4 build, then the real V2 probe."""
    # Keep fixture paths inside this checkout.  Production requests reject
    # /tmp paths from their static source closure; placing the disposable
    # fixture beside the builder exercises that same admission rule instead
    # of adding a test-only exception.
    with tempfile.TemporaryDirectory(prefix="native-header-v5-real-cli-", dir=HERE) as td:
        root = Path(td)
        runtime = root / "tiny-runtime.py"
        runtime.write_text(
            "import hashlib,json,pathlib,sys\n"
            "p=pathlib.Path(sys.argv[1]); o=pathlib.Path(sys.argv[2]); d=json.loads(p.read_text());\n"
            "r={'schema':'ds02.execution-receipt.v1','status':'completed','returncode':0,"
            "'request':d,'request_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),"
            "'output_root':str(o.parent.resolve()),'input_hashes_at_launch':{},'input_hashes_after_run':{}}\n"
            "o.write_text(json.dumps(r,sort_keys=True)+'\\n')\n", encoding="utf-8")
        decoder = root / "bi4_dump"
        decoder.write_text(
            "#!/usr/bin/env python3\nimport pathlib,sys\n"
            "pathlib.Path(sys.argv[2]+'.xml').write_text(\"<data><item name='Header'><item name='MassFluid' value='0.5'/><item name='MassBound' value='1.25'/><item name='Dp' value='0.01'/><item name='Nfluid' value='2'/><item name='Nbound' value='1'/></item></data>\")\n", encoding="utf-8")
        decoder.chmod(0o755)
        initial_rows: list[dict[str, Any]] = []
        product_rows: list[dict[str, Any]] = []
        names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                 "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                 "gencase_receipt": "execution-receipt.json"}
        for sid in TARGETS:
            for grid in GRIDS:
                key = f"{sid}:{grid}"
                case_id = f"{sid.replace('-', '_')}_{grid}"
                attempt_id = f"{grid}_attempt"
                out = root / "products" / case_id / attempt_id
                out.mkdir(parents=True, exist_ok=True)
                producer = root / "producers" / f"{case_id}.json"
                producer.parent.mkdir(parents=True, exist_ok=True)
                producer_doc = {"schema": REQUEST_SCHEMA, "family_id": sid.split("-", 1)[0],
                                "sentinel_id": sid, "case_id": case_id, "attempt_id": attempt_id,
                                "kind": "cpu", "cpu_task_kind": "gencase", "execution_allowed": True,
                                "gencase_launch": True, "output_root": str(out)}
                producer.write_text(json.dumps(producer_doc, sort_keys=True) + "\n", encoding="utf-8")
                receipt = out / "execution-receipt.json"
                completed = _tiny_runtime_receipt(runtime, producer, receipt)
                if completed.returncode != 0:
                    raise BuildFailure(f"tiny runtime receipt failed: {completed.stderr}")
                products: dict[str, Any] = {}
                for role, name in names.items():
                    path = out / name
                    if role == "gencase_receipt":
                        raw = path.read_bytes()
                    else:
                        path.write_bytes((role + "-fixture\n").encode())
                        raw = path.read_bytes()
                    st = _stat(path)
                    products[role] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": st}
                proof = root / "proofs" / f"{case_id}.json"
                proof.parent.mkdir(parents=True, exist_ok=True)
                proof.write_text(json.dumps({"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_GENCASE_FIXTURE", "row_key": key}) + "\n", encoding="utf-8")
                control = root / "control" / f"{case_id}.csv"
                control.parent.mkdir(parents=True, exist_ok=True)
                control.write_text("time,forcing\n0,0\n", encoding="utf-8")
                initial_rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid.split("-", 1)[0], "physical_case_id": key})
                product_rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid.split("-", 1)[0],
                                     "physical_case_id": key, "producer_request": {"path": str(producer), "sha256": hashlib.sha256(producer.read_bytes()).hexdigest()},
                                     "products": products, "actual_proof": {"path": str(proof), "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(), "stat": _stat(proof)},
                                     "control_closure": {"forcing": {"path": str(control), "sha256": hashlib.sha256(control.read_bytes()).hexdigest(), "stat": _stat(control)}},
                                     "status": "COMPLETED"})
        initial = root / "initial.json"
        initial.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1", "cases": initial_rows}) + "\n", encoding="utf-8")
        product_map = root / "product-map.json"
        product_map.write_text(json.dumps({"schema": "ds02.stage2.root-nine-gencase-product-map.v2", "status": "COMPLETED", "products": product_rows}) + "\n", encoding="utf-8")
        result = build(initial, product_map, decoder, root / "out")
        if result["actual_rows"] != EXPECTED_ROWS or result["proof_rows"] != EXPECTED_ROWS:
            raise AssertionError(f"V5 did not derive ready from nine completed rows: {result}")
        manifest = Path(result["manifest"])
        request = _read_json(Path(result["request"]), "V5 fixture request")
        if request["command"][request["command"].index("--manifest") + 1] != str(manifest):
            raise AssertionError("V5 fixture command lost stable manifest path")
        if request.get("family_id") != "infra":
            raise AssertionError("V5 fixture did not emit the legal infra runtime family")
        expected_cwd = str(HERE.parents[4] / "lagrangian-fluid-lab")
        if request.get("cwd") != expected_cwd:
            raise AssertionError("V5 fixture did not bind the current worktree lab cwd")
        # Exercise the actual shared runtime request validator without calling
        # its reservation/ledger runner.  This catches ABI drift that a direct
        # probe invocation cannot see while keeping the fixture source-only.
        runtime_spec = importlib.util.spec_from_file_location("ds_data02_runtime_v2_for_v5", RUNTIME_SOURCES[1])
        if runtime_spec is None or runtime_spec.loader is None:
            raise AssertionError("cannot load runtime V2 validator fixture")
        runtime_module = importlib.util.module_from_spec(runtime_spec)
        runtime_spec.loader.exec_module(runtime_module)
        validated_hashes = runtime_module.validate_request(request)
        if set(validated_hashes) != {str(Path(item).resolve()) for item in request["input_files"]}:
            raise AssertionError("runtime validator did not hash the exact V5 static closure")
        probe_attempt = root / "probe-attempt"
        output = probe_attempt / "report.json"
        command = list(request["command"])
        command = [str(probe_attempt) if item == "{attempt_root}" else str(output) if item == "{attempt_root}/report/native-header-probe-v4.json" else item for item in command]
        # The request command's output suffix is V4's fixed string; replace
        # it explicitly for this fixture invocation.
        for index, item in enumerate(command):
            if isinstance(item, str) and item.startswith("{attempt_root}/"):
                command[index] = str(probe_attempt / item.split("{attempt_root}/", 1)[1])
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode != 0 or not output.exists():
            raise AssertionError(f"V5 builder→V2 probe failed: {completed.stdout}\n{completed.stderr}")
        report = _read_json(output, "V5 probe report")
        if len(report.get("cases", [])) != EXPECTED_ROWS or not all(row.get("status") == "PASS_NATIVE_HEADER_FIELDS" for row in report["cases"]):
            raise AssertionError("V5 probe did not pass all nine manufactured rows")
        # A producer-request byte mutation must be rejected by the frozen V3
        # receipt join, even though the native fixture remains unchanged.
        first_producer = Path(product_rows[0]["producer_request"]["path"])
        first_producer.write_text(first_producer.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        bad_output = probe_attempt / "bad.json"
        bad_command = list(command)
        bad_command[bad_command.index("--output") + 1] = str(bad_output)
        bad = subprocess.run(bad_command, cwd=root, capture_output=True, text=True, timeout=60, check=False)
        if bad.returncode == 0:
            raise AssertionError("V5 probe accepted producer request byte mutation")


def self_test() -> None:
    _real_fixture_self_test()
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V5_REAL_RUNTIME_CLI_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--initial-manifest", type=Path)
    parser.add_argument("--initial-request", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V5_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    required = (args.initial_manifest, args.product_map, args.decoder, args.output_dir)
    if any(value is None for value in required):
        parser.error("--build requires --initial-manifest, --product-map, --decoder, and --output-dir")
    try:
        result = build(args.initial_manifest, args.product_map, args.decoder, args.output_dir,
                       args.initial_request, args.admission_manifest)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V5: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: result[key] for key in ("status", "manifest", "request", "actual_rows", "proof_rows", "static_input_count", "deferred_input_count", "production_payload_read", "scientific_credit")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
