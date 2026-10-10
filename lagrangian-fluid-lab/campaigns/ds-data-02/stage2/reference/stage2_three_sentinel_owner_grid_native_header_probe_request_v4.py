#!/usr/bin/env python3
"""Build a runtime-compatible nine-row native-header probe request.

The consumed V3 builder is intentionally left untouched.  Its manifest uses
``...probe-manifest.v3`` while the frozen V2 probe accepts the V2 manifest
schema only.  This additive adapter calls V3 for the source/product joins,
rewrites only the manifest *schema contract* to the V2 value, and rebuilds the
request's runtime fields around the actual V2 ``--run`` command.  It does not
change product paths, hashes, proof records, or the position-only semantics.

The adapter is source preparation: it never reads BI4/VTK/H5 product bytes,
never starts GenCase/solver, and keeps execution disabled.  Its self-test
creates nine tiny runtime-shaped producer/receipt/product rows, then invokes
the real V2 probe function through a subprocess against the adapted manifest.
That catches schema and receipt-identity mistakes which a builder-only test
cannot see.
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
V3_PATH = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_request_v3.py"
PROBE = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
VERIFY_V3 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py"
VERIFY_V4 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v4.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
MANIFEST_SCHEMA_V2 = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
REQUEST_SCHEMA_V4 = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-request.v4"
REQUEST_SCHEMA = "ds02.request.v1"
JSON_CAP = 10 * 1024 * 1024
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")


class BuildFailure(RuntimeError):
    pass


def _load_v3() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_three_sentinel_native_header_request_v3_for_v4", V3_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load V3 builder: {V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_small(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object: {path}")
    record = {
        "path": str(path), "sha256": _sha(raw), "stat": after,
        "bytes": len(raw), "stable_read": True,
        "payload_read_by_builder": False,
    }
    return value, record


def _record_code(path: Path, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "sha256": _sha(raw), "stat": after,
        "bytes": len(raw), "stable_read": True,
        "content_scope": "source_code_or_runtime_metadata",
        "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _literal_python_record() -> tuple[str, dict[str, Any], dict[str, Any]]:
    literal = _abs(PYTHON)
    if not literal.is_symlink():
        raise BuildFailure(f"literal venv argv0 is not a symlink: {literal}")
    resolved = literal.resolve(strict=True)
    resolved_record = _record_code(resolved, "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    cfg_record = _record_code(cfg, "pyvenv.cfg")
    return str(literal), resolved_record, cfg_record


def _adapt_request(request: dict[str, Any], manifest: dict[str, Any],
                   manifest_record: dict[str, Any], static: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Translate V3 source request to the legal generic CPU V8 shape."""
    request = dict(request)
    request["schema"] = REQUEST_SCHEMA
    request["variant_schema"] = REQUEST_SCHEMA_V4
    request["kind"] = "cpu"
    request["cpu_task_kind"] = "audit"
    request["family_id"] = "DS02"
    request["sentinel_id"] = "THREE_SENTINEL_OWNER_GRID"
    request["sentinel_ids"] = list(TARGETS)
    request["physical_case_id"] = "THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE"
    request["case_id"] = "F2_F3_F5_OWNER_GRID_NATIVE_HEADER_PROBE_V4"
    request["attempt_id"] = "PARENT_ASSIGNED_AFTER_NINE_GENCASE"
    request["command"] = [
        str(PYTHON), str(PROBE), "--run",
        "--manifest", manifest_record["path"],
        "--attempt-root", "{attempt_root}",
        "--output", "{attempt_root}/report/native-header-probe-v4.json",
    ]
    request["cwd"] = str(HERE.parents[5] / "lagrangian-fluid-lab")
    request["worktree_root"] = str(HERE.parents[5])
    request["manifest"] = manifest_record
    request["input_records"] = static
    request["input_files"] = sorted(static)
    request["input_sha256"] = {path: static[path]["sha256"] for path in sorted(static)}
    request["resource_scope"] = {
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "memory_max_bytes": 4 * 1024**3, "scratch_max_bytes": 256 * 1024**2,
        "log_max_bytes": 64 * 1024, "estimated_storage_bytes": 256 * 1024**2,
        "gpu": "none",
    }
    request["cpu_threads"] = 1
    request["omp_threads"] = 1
    request["max_wall_seconds"] = 1800
    request["max_memory_bytes"] = 4 * 1024**3
    request["estimated_peak_memory_bytes"] = 4 * 1024**3
    request["estimated_storage_bytes"] = 256 * 1024**2
    request["estimated_input_read_bytes"] = sum(int(item.get("bytes", 0)) for item in static.values())
    request["estimated_native_read_passes"] = 2
    request["output_root"] = "{attempt_root}"
    request["output"] = {"path": "{attempt_root}/report/native-header-probe-v4.json", "atomic": True, "refuse_overwrite": True}
    request["execution_allowed"] = False
    request["launch_disabled"] = True
    request["solver_started"] = False
    request["gencase_launch"] = False
    request["solver_launch"] = False
    request["native_payload_read"] = False
    request["hdf5_read"] = False
    request["ledger_mutation"] = False
    request["source_binding"] = {
        **dict(request.get("source_binding") or {}),
        "manifest_schema_adapter": {
            "builder_schema": "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v3",
            "worker_schema": MANIFEST_SCHEMA_V2,
            "adapter": "V4_rewrites_schema_only_and_rebuilds_request_command",
        },
        "native_mass_source": "decoder_header_only",
        "xml_mass_fallback": False,
        "position_only_initial_support": True,
        "missing_velocity_rhop_mass": "UNKNOWN_NOT_EXPOSED_BY_INITIAL_DECODER",
    }
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    return request


def build(initial_manifest: Path, product_map: Path, decoder: Path,
          output_dir: Path, initial_request: Path | None = None,
          admission_manifest: Path | None = None) -> dict[str, Any]:
    """Build V4 outputs through the frozen V3 source/product join."""
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="owner-grid-native-header-v3-stage-") as staging:
        staged = Path(staging)
        v3_result = V3.build(
            _abs(initial_manifest),
            _abs(initial_request) if initial_request else None,
            _abs(product_map), _abs(decoder), staged,
            _abs(admission_manifest) if admission_manifest else None,
        )
        v3_manifest_path = _abs(v3_result["manifest"])
        v3_request_path = _abs(v3_result["request"])
        manifest, _ = _read_small(v3_manifest_path, "V3 generated manifest")
        request, _ = _read_small(v3_request_path, "V3 generated request")

        if manifest.get("status") == "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE":
            status = manifest["status"]
        else:
            status = "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS"
        manifest = dict(manifest)
        manifest["schema"] = MANIFEST_SCHEMA_V2
        manifest["source_manifest_schema"] = V3.SCHEMA
        manifest["adapter_schema"] = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-adapter.v4"
        manifest["status"] = status
        manifest["read_cap_bytes"] = JSON_CAP
        manifest["runtime_worker_compatibility"] = {
            "probe": "stage2_three_sentinel_owner_grid_native_header_probe_v2.py",
            "accepted_manifest_schema": MANIFEST_SCHEMA_V2,
            "command_entrypoint": "literal_venv_then_probe_v2_run",
        }
        manifest_path = output_dir / "native-header-probe-manifest-v4.json"
        _write_once(manifest_path, manifest)
        manifest_record = _record_code(manifest_path, "V4 manifest")
        manifest_record["content_scope"] = "bounded_manifest_json"

        static: dict[str, dict[str, Any]] = {}
        old_records = request.get("input_records")
        if isinstance(old_records, dict):
            for path_text, record in old_records.items():
                if not isinstance(path_text, str) or not isinstance(record, dict):
                    continue
                # Never retain the temporary V3 manifest in a final request.
                if _abs(path_text) == v3_manifest_path:
                    continue
                static[str(_abs(path_text))] = record
        for path, label in (
            (V3_PATH, "V3 builder source"),
            (PROBE, "V2 native-header probe worker"),
            (VERIFY_V3, "initial-support V3 verifier"),
            (VERIFY_V4, "initial-support V4 verifier"),
            (HERE / "stage2_three_sentinel_owner_grid_native_header_probe_request_v4.py", "V4 adapter"),
        ):
            rec = _record_code(path, label)
            static[rec["path"]] = rec
        literal, resolved, cfg = _literal_python_record()
        static[literal] = {**resolved, "path": literal, "label": "literal venv argv0", "literal_argv0": True,
                           "resolved_target": resolved["path"], "content_scope": "runtime_interpreter"}
        static[resolved["path"]] = resolved
        static[cfg["path"]] = cfg
        static[manifest_record["path"]] = manifest_record

        final_request = _adapt_request(request, manifest, manifest_record, static)
        final_request["deferred_input_records"] = request.get("deferred_input_records", [])
        final_request["deferred_input_files"] = request.get("deferred_input_files", [])
        final_request["source_builder_inputs"] = {
            "initial_support_manifest": str(_abs(initial_manifest)),
            "product_map": str(_abs(product_map)),
            "decoder": str(_abs(decoder)),
            "source_join_v3_status": v3_result["status"],
            "actual_rows": int(v3_result.get("actual_rows", 0)),
            "proof_rows": int(v3_result.get("proof_rows", 0)),
            "production_payload_read": False,
        }
        request_path = output_dir / "native-header-probe-request-v4.json"
        _write_once(request_path, final_request)
        request_record = _record_code(request_path, "V4 request")
        return {
            "schema": REQUEST_SCHEMA_V4,
            "status": status,
            "manifest": str(manifest_path),
            "request": str(request_path),
            "actual_rows": int(v3_result.get("actual_rows", 0)),
            "proof_rows": int(v3_result.get("proof_rows", 0)),
            "static_input_count": len(static),
            "deferred_input_count": len(final_request["deferred_input_records"]),
            "request_record": request_record,
            "production_payload_read": False,
        }


def _write_fixture_decoder(path: Path, include_mass: bool = True) -> None:
    fields = "<item name='MassFluid' value='0.5'/><item name='MassBound' value='1.25'/><item name='Dp' value='0.01'/><item name='Nfluid' value='2'/><item name='Nbound' value='1'/>" if include_mass else "<item name='Nfluid' value='2'/>"
    xml = f"<data><item name='Header'>{fields}</item></data>"
    path.write_text(
        "#!/usr/bin/env python3\nimport pathlib,sys\n"
        f"pathlib.Path(sys.argv[2] + '.xml').write_text({xml!r}, encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _self_test() -> None:
    """Run the actual V3 builder -> V4 adapter -> V2 probe subprocess path."""
    with tempfile.TemporaryDirectory(prefix="owner-grid-native-header-v4-") as td:
        root = Path(td)
        initial_cases: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                 "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                 "gencase_receipt": "execution-receipt.json"}
        decoder = root / "bi4_dump"
        _write_fixture_decoder(decoder)
        for sid in TARGETS:
            for grid in GRIDS:
                key = f"{sid}:{grid}"
                # The frozen receipt verifier derives case_id and attempt_id
                # from the two final output-root components.  Keep the tiny
                # fixture shaped like the runtime receipt, rather than using
                # a convenient sentinel/grid directory pair.
                key_case = key
                key_attempt = f"{key}-attempt"
                out = root / "products" / key_case / key_attempt
                out.mkdir(parents=True, exist_ok=True)
                producer = {
                    "schema": REQUEST_SCHEMA, "family_id": sid.split("-", 1)[0],
                    "sentinel_id": sid, "case_id": key_case, "attempt_id": key_attempt,
                    "kind": "cpu", "cpu_task_kind": "gencase", "execution_allowed": True,
                    "gencase_launch": True, "output_root": str(out),
                }
                producer_path = root / "producers" / f"{sid.replace('-', '_')}_{grid}.json"
                producer_path.parent.mkdir(parents=True, exist_ok=True)
                producer_raw = json.dumps(producer, sort_keys=True, separators=(",", ":")) + "\n"
                producer_path.write_text(producer_raw, encoding="utf-8")
                receipt = {
                    "schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
                    "request": producer, "request_sha256": _sha(producer_raw.encode()),
                    "output_root": str(out), "input_hashes_at_launch": {}, "input_hashes_after_run": {},
                }
                receipt_path = out / "execution-receipt.json"
                receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
                products: dict[str, dict[str, Any]] = {}
                for role, name in names.items():
                    path = out / name
                    if role == "gencase_receipt":
                        raw = path.read_bytes()
                    else:
                        path.write_bytes((role + "\n").encode())
                        raw = path.read_bytes()
                    products[role] = {"path": str(path), "sha256": _sha(raw), "stat": _stat(path)}
                proof_path = root / "proofs" / f"{sid.replace('-', '_')}_{grid}.json"
                proof_path.parent.mkdir(parents=True, exist_ok=True)
                proof_path.write_text(json.dumps({"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_GENCASE_FIXTURE", "row_key": key}) + "\n", encoding="utf-8")
                control_path = root / "control" / f"{sid.replace('-', '_')}_{grid}.csv"
                control_path.parent.mkdir(parents=True, exist_ok=True)
                control_path.write_text("time,forcing\n0,0\n", encoding="utf-8")
                initial_cases.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid.split("-", 1)[0], "physical_case_id": key})
                rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid.split("-", 1)[0],
                             "physical_case_id": key, "producer_request": {"path": str(producer_path), "sha256": _sha(producer_raw.encode())},
                             "products": products, "actual_proof": {"path": str(proof_path), "sha256": _sha(proof_path.read_bytes()), "stat": _stat(proof_path)},
                             "control_closure": {"forcing": {"path": str(control_path), "sha256": _sha(control_path.read_bytes()), "stat": _stat(control_path)}},
                             "status": "COMPLETED"})
        initial = root / "initial.json"
        initial.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1", "cases": initial_cases}) + "\n", encoding="utf-8")
        product_map = root / "products.json"
        product_map.write_text(json.dumps({"schema": "ds02.stage2.root-nine-gencase-product-map.v2", "status": "COMPLETED", "products": rows}) + "\n", encoding="utf-8")
        result = build(initial, product_map, decoder, root / "out")
        assert result["status"] == "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE"
        manifest = Path(result["manifest"])
        request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
        assert json.loads(manifest.read_text(encoding="utf-8"))["schema"] == MANIFEST_SCHEMA_V2
        assert request["kind"] == "cpu" and request["cpu_task_kind"] == "audit"
        assert request["execution_allowed"] is False
        completed = subprocess.run([
            str(PYTHON), str(PROBE), "--run", "--manifest", str(manifest),
            "--attempt-root", str(root / "probe-attempt"),
            "--output", str(root / "probe-attempt" / "report.json"),
        ], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(f"adapted manifest rejected by V2 probe: {completed.stdout}\n{completed.stderr}")
        report = json.loads((root / "probe-attempt" / "report.json").read_text(encoding="utf-8"))
        assert report["schema"] == "ds02.stage2.native-header-probe.v2"
        assert len(report["cases"]) == 9
        assert all(item["status"] == "PASS_NATIVE_HEADER_FIELDS" for item in report["cases"])
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V4_REAL_CLI_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    parser.add_argument("--initial-manifest", type=Path)
    parser.add_argument("--initial-request", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V4_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    required = (args.initial_manifest, args.product_map, args.decoder, args.output_dir)
    if any(item is None for item in required):
        parser.error("--build requires --initial-manifest, --product-map, --decoder, and --output-dir")
    try:
        result = build(args.initial_manifest, args.product_map, args.decoder, args.output_dir,
                       args.initial_request, args.admission_manifest)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V4: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: result[key] for key in ("status", "manifest", "request", "actual_rows", "proof_rows", "static_input_count", "deferred_input_count", "production_payload_read")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
