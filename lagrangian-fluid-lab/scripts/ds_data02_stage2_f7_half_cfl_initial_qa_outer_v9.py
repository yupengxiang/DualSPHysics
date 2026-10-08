#!/usr/bin/env python3
"""Parent-guarded outer entry for the F7 v8 initial typed QA.

The consumed v8 worker performs the two native frame-0 decodes and motion
staging.  This forward outer contract adds the missing XML/GenCase identity
gate (CaseNp/Np/Nb/Nbf, block begins/counts/MK, dp and CFL) and binds the
literal v8 request, worker and all ten input roles.  ``build-request`` and
``preflight`` read only JSON/XML/stat metadata.  ``run --io-slot-approved`` is
the only path that invokes the v8 worker and therefore must be dispatched by
the shared parent CPU guard.  It never launches GenCase, a solver, CFD, GPU,
or HDF5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f7_half_cfl_initial_qa_v8.py"
V8_REQUEST = (SCRIPT_DIR.parent / "campaigns/ds-data-02/stage2/native-reconstruction/"
              "f7-half-cfl-v1/request-007-f7-v8-initial-qa/"
              "f7-s2-half-cfl-initial-typed-qa-request-v8-001.json")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DEFAULT_OUTPUT = Path("/var/tmp/ds02-stage2/F7/F7_HALF_CFL_INITIAL_QA_V9/"
                      "f7-half-cfl-initial-typed-qa-v9-001")
SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-request.v9"
REPORT_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-report.v9"
V8_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-request.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HALF_EXPECTED = {
    "np": 70179, "nb": 29479, "nbf": 27495, "cflnumber": 0.1,
    "dp_m": 0.02, "motion_duration_s": 12.0,
    "blocks": {"fixed": {"begin": 0, "count": 27495, "mk": 10},
               "moving": {"begin": 27495, "count": 1984, "mk": 12},
               "fluid": {"begin": 29479, "count": 40700, "mk": 2}},
}
BASE_EXPECTED = dict(HALF_EXPECTED, cflnumber=0.2)


class OuterQAError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OuterQAError(f"JSON object required: {path}")
    return value


def _snapshot(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns), "inode": int(stat.st_ino),
            "device": int(stat.st_dev), "mode": int(stat.st_mode)}


def _xml_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles") or root.find(".//particles")
    if particles is None:
        raise OuterQAError(f"XML lacks particles block: {path}")
    constants = root.find(".//casedef/constantsdef")
    definition = root.find(".//casedef/geometry/definition")
    cfl_node = constants.find("cflnumber") if constants is not None else None
    motion = root.find(".//casedef/motion/objreal/mvrotfile")
    blocks: dict[str, dict[str, int]] = {}
    for name in ("fixed", "moving", "fluid"):
        child = particles.find(name)
        if child is None:
            raise OuterQAError(f"XML lacks particle block {name}: {path}")
        mk_key = "mk" if child.get("mk") is not None else "mkbound" if child.get("mkbound") is not None else "mkfluid"
        blocks[name] = {"begin": int(child.get("begin")), "count": int(child.get("count")),
                        "mk": int(child.get(mk_key))}
    result = {"np": int(particles.get("np")), "nb": int(particles.get("nb")),
              "nbf": int(particles.get("nbf")),
              "cflnumber": float(cfl_node.get("value")) if cfl_node is not None else None,
              "dp_m": float(definition.get("dp")) if definition is not None else None,
              "motion_duration_s": float(motion.get("duration")) if motion is not None else None,
              "blocks": blocks}
    return result


def _assert_semantics(actual: Mapping[str, Any], expected: Mapping[str, Any], role: str) -> None:
    for key in ("np", "nb", "nbf"):
        if actual.get(key) != expected.get(key):
            raise OuterQAError(f"{role} XML {key} differs from frozen identity")
    for key in ("cflnumber", "dp_m", "motion_duration_s"):
        if actual.get(key) != expected.get(key):
            raise OuterQAError(f"{role} XML {key} differs from frozen control")
    if actual.get("blocks") != expected.get("blocks"):
        raise OuterQAError(f"{role} XML particle block identity differs")


def _input_bindings(inner: Mapping[str, Any]) -> list[dict[str, Any]]:
    inputs = inner.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "half_generated_xml", "baseline_generated_xml", "half_gencase_receipt",
        "half_gencase_stdout", "F7_motion_control", "v5_same_cfl_receipt",
        "v5_same_cfl_RunPARTs", "pinned_native_bi4_decoder", "half_generated_bi4",
        "baseline_generated_bi4"}:
        raise OuterQAError("inner v8 ten-role closure differs")
    result = []
    for role in sorted(inputs):
        item = inputs[role]
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        if not path.is_file() or item.get("role") != role:
            raise OuterQAError(f"inner source is missing or role differs: {role}")
        stat = _snapshot(path)
        expected = {key: int(item[key]) for key in ("bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode")}
        if stat != expected:
            raise OuterQAError(f"inner source stat differs: {role}")
        expected_sha = item.get("sha256")
        if role == "half_generated_bi4":
            if expected_sha is not None or item.get("content_scope") != "PARENT_GUARD_CONTENT_HASH_REQUIRED":
                raise OuterQAError("half BI4 must remain deferred to the parent worker")
        else:
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise OuterQAError(f"inner source SHA missing: {role}")
            if sha256_file(path) != expected_sha:
                raise OuterQAError(f"inner source SHA differs: {role}")
        result.append({"role": role, "path": str(path), **stat,
                       "sha256": expected_sha,
                       "content_scope": item.get("content_scope")})
    return result


def _validate_inner(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    inner = load_json(path)
    if inner.get("schema") != V8_SCHEMA or inner.get("sha256") != canonical_sha(inner):
        raise OuterQAError("inner v8 request is noncanonical")
    if inner.get("status") != "PENDING_PARENT_IO_SLOT" or inner.get("launch_allowed") is not False:
        raise OuterQAError("inner v8 request is not pending development QA")
    execution = inner.get("execution", {})
    if (inner.get("qualification") != UNKNOWN
            or execution.get("model_invoked") is not False
            or execution.get("cfd_invoked") is not False):
        raise OuterQAError("inner v8 request has unsafe scope")
    half_xml = Path(str(inner["inputs"]["half_generated_xml"]["path"])).expanduser().resolve()
    baseline_xml = Path(str(inner["inputs"]["baseline_generated_xml"]["path"])).expanduser().resolve()
    half_sem = _xml_semantics(half_xml)
    base_sem = _xml_semantics(baseline_xml)
    _assert_semantics(half_sem, HALF_EXPECTED, "half")
    _assert_semantics(base_sem, BASE_EXPECTED, "baseline")
    for key in ("np", "nb", "nbf", "dp_m", "motion_duration_s", "blocks"):
        if half_sem[key] != base_sem[key]:
            raise OuterQAError(f"baseline/half initial identity differs in {key}")
    if half_sem["cflnumber"] == base_sem["cflnumber"]:
        raise OuterQAError("half/baseline CFL did not differ")
    return inner, {"half": half_sem, "baseline": base_sem}, _input_bindings(inner)


def build_request(*, inner_request: Path = V8_REQUEST, output: Path,
                  output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    inner_request = inner_request.expanduser().resolve()
    if not inner_request.is_file() or output.exists():
        raise OuterQAError("missing inner request or existing outer output")
    inner, xml_semantics, inputs = _validate_inner(inner_request)
    output_dir = output_dir.expanduser().resolve()
    if not str(output_dir).startswith("/var/tmp/"):
        raise OuterQAError("outer QA output must be on the parent external namespace")
    if output_dir.exists():
        raise OuterQAError(f"outer output namespace already exists: {output_dir}")
    worker_stat = _snapshot(V8_SCRIPT)
    worker = {"role": "f7_initial_qa_worker_v8", "path": str(V8_SCRIPT.resolve()),
              **worker_stat, "sha256": sha256_file(V8_SCRIPT), "content_scope": "source_content"}
    inner_binding = {"role": "f7_initial_qa_request_v8", "path": str(inner_request),
                     **_snapshot(inner_request), "sha256": sha256_file(inner_request),
                     "content_scope": "source_content"}
    value: dict[str, Any] = {
        "schema": SCHEMA, "request_id": "f7-s2-half-cfl-initial-typed-qa-outer-v9-001",
        "status": "READY_FOR_PARENT_CPU_GUARD", "role": "DEVELOPMENT", "family_id": "F7",
        "case_id": inner.get("case_id"), "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False, "launch_allowed": False,
        "inner_request": {"path": str(inner_request), "sha256": inner["sha256"],
                          "schema": inner["schema"], "immutable": True},
        "source_bindings": [inner_binding, worker, *inputs],
        "xml_semantics": xml_semantics,
        "identity_gate": {
            "checks": ["CaseNp", "Np", "Nb", "Nbf", "dp", "CFL", "motion duration",
                        "fixed/moving/fluid begin/count/MK"],
            "half_expected": HALF_EXPECTED, "baseline_expected": BASE_EXPECTED,
            "same_initial_identity_required": True,
            "decoded_arrays_remain_authoritative": True,
        },
        "execution": {
            "python": str(VENV_PYTHON),
            "command": [str(VENV_PYTHON), "-B", str(Path(__file__).resolve()), "run",
                        "--request", "<request>", "--io-slot-approved"],
            "inner_command": [str(VENV_PYTHON), "-B", str(V8_SCRIPT), "run",
                              "--request", str(inner_request), "--io-slot-approved",
                              "--output-dir", str(output_dir)],
            "output_dir": str(output_dir), "requires_shared_four_guard": True,
            "hdf5": False, "solver": False, "cfd": False, "gpu": False,
            "model_invoked": False, "original_path_fallback": "FORBIDDEN",
            "parent_supervised": True,
        },
        "resource_request": {
            "cpu_threads": 1, "max_wall_seconds": 900,
            "max_rss_bytes": 2 * 1024**3, "new_storage_budget_bytes": 512 * 1024**2,
            "source_read_scope": "two frame-0 BI4 files and decoder scratch; no H5/solver",
            "parent_guard_required": True, "qualification": "DEVELOPMENT_UNKNOWN",
        },
        "motion_stage": {
            "source": inner["inputs"]["F7_motion_control"]["path"],
            "source_sha256": inner["inputs"]["F7_motion_control"]["sha256"],
            "target_relative": "solver_input/motion_obstacle_quintic.dat",
            "copy_target_hash_required": True, "solver_launch_allowed": False,
        },
        "parent_accounting": {
            "same_parent_ledger": True, "home_floor_and_external_output_are_separate_fs": True,
            "external_output_namespace_must_be_absent": True,
            "static_source_hashes_are_parent_guarded": True,
            "half_bi4_content_sha_deferred_to_worker": True,
        },
        "limitations": [
            "This outer request adds XML identity checks but does not replace the v8 decoded-array comparison.",
            "No GenCase, solver, CFD, GPU, or HDF5 execution is performed by build/preflight.",
            "The half BI4 content hash remains unknown until the parent-approved CPU worker reads it.",
            "The result remains DEVELOPMENT/UNKNOWN and requires a new solver request after QA and motion staging.",
        ],
    }
    value["sha256"] = canonical_sha(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return value


def preflight(request_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise OuterQAError("outer request is noncanonical")
    inner_path = Path(str(request["inner_request"]["path"])).expanduser().resolve()
    inner, semantics, inputs = _validate_inner(inner_path)
    if request["inner_request"].get("sha256") != inner.get("sha256"):
        raise OuterQAError("outer inner request SHA differs")
    if request.get("xml_semantics") != semantics:
        raise OuterQAError("outer XML semantic snapshot differs")
    for item in request.get("source_bindings", []):
        path = Path(str(item["path"])).expanduser().resolve()
        if not path.is_file() or _snapshot(path) != {key: int(item[key]) for key in ("bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode")}:
            raise OuterQAError(f"outer source stat differs: {path}")
        if item.get("role") != "half_generated_bi4" and item.get("sha256") != sha256_file(path):
            raise OuterQAError(f"outer source SHA differs: {path}")
    return {"status": "READY_FOR_PARENT_CPU_SLOT", "inner_sha256": inner["sha256"],
            "source_count": len(inputs) + 2, "xml_semantics": semantics,
            "output_dir": request["execution"]["output_dir"],
            "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
            "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path, *, io_slot_approved: bool) -> dict[str, Any]:
    request = load_json(request_path)
    checked = preflight(request_path)
    if not io_slot_approved:
        return checked
    output_dir = Path(str(request["execution"]["output_dir"])).expanduser().resolve()
    if output_dir.exists():
        raise OuterQAError("refusing existing outer QA output")
    command = [str(item).replace("<request>", str(request["inner_request"]["path"]))
               .replace("<output-dir>", str(output_dir))
               for item in request["execution"]["inner_command"]]
    # The v8 command already contains the output directory; this explicit
    # subprocess boundary keeps import caches and source paths closed.
    started = time.monotonic()
    completed = subprocess.run(command, cwd=str(SCRIPT_DIR.parents[1]),
                                capture_output=True, text=True,
                                timeout=float(request["resource_request"]["max_wall_seconds"]))
    report = {"schema": REPORT_SCHEMA,
              "status": "PASS_INITIAL_TYPED_QA_DEVELOPMENT_UNKNOWN" if completed.returncode == 0 else "FAILED_INITIAL_TYPED_QA",
              "request_sha256": request.get("sha256"), "inner_request_sha256": checked["inner_sha256"],
              "returncode": completed.returncode, "elapsed_seconds": time.monotonic() - started,
              "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:],
              "output_dir": str(output_dir), "parent_guard": request["parent_accounting"],
              "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    report["sha256"] = canonical_sha(report)
    path = output_dir / "f7-s2-half-cfl-initial-typed-qa-v9-outer-report.json"
    if path.exists():
        raise OuterQAError("refusing existing outer report")
    if not output_dir.is_dir():
        raise OuterQAError("inner worker did not create its output namespace")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--inner-request", type=Path, default=V8_REQUEST)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(inner_request=args.inner_request, output=args.output,
                                  output_dir=args.output_dir)
            result = {"status": value["status"], "sha256": value["sha256"],
                      "source_count": len(value["source_bindings"])}
        elif args.command == "preflight":
            result = preflight(args.request)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if not str(result.get("status", "")).startswith("FAILED") else 2
    except (OuterQAError, OSError, ValueError, TypeError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
