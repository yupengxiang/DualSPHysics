#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward-only ROOT173/ROOT174 request builder with strict v8 closure.

The consumed v6 requests are left byte-for-byte untouched.  This additive
builder delegates the already audited v6 XML/request construction and then
adds a fresh attempt namespace plus a strict, source-only runtime closure:

* the materializer is invoked through the literal project venv shebang;
* the resolved interpreter and ``pyvenv.cfg`` are bound by SHA/stat;
* the actual V5 -> V4 -> V1 import chain and runtime-v2 API are bound;
* runtime-v6 is explicitly recorded as unnecessary because it is not in the
  V5 source import closure.

V8 additionally binds the validator module itself into ``input_files`` and
checks its actual path, SHA, callable, and V5 API before invoking the shared
V5 preflight.  The isolated-worktree path is intentional: the parent may
rebuild the same request after cherry-picking this file into its main
worktree, at which point the request's validator path and SHA are regenerated
from that main-worktree file.

``--preflight`` validates this closure and calls the shared V5 ``run`` API
with ``io_slot_approved=False``.  It performs no solver launch, payload
hash, ledger mutation, HDF5 open, or native-array read.  Parent reservation,
post-reservation BI4/forcing checks, GPU lease, and launch remain parent-only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
REFERENCE_DIR = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
V6_BUILDER = REFERENCE_DIR / "stage2_f3_s2_middle_overlay_requests_v6.py"
V7_BUILDER = REFERENCE_DIR / "stage2_f3_s2_middle_overlay_requests_v7.py"
V8_BUILDER = Path(__file__).resolve()
V5_RUNNER = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"
V4_RUNNER = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v4.py"
V1_RUNNER = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v1.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
MATERIALIZER = REFERENCE_DIR / "stage2_f3_s2_external_solver_v5_materialize.py"
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV_CFG = VENV_PYTHON.parent.parent / "pyvenv.cfg"
SCHEMA = "ds02.stage2.f3-s2.middle-overlay-external-solver-request.v8"
STRICT_SCHEMA = "ds02.stage2.external-solver-request.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
HEX64 = set("0123456789abcdef")


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _code_record(path: Path, role: str) -> dict[str, Any]:
    record = _stat(path, role)
    record.update({
        "sha256": _sha256(path),
        "content_scope": "source_code_hashed_by_builder_and_parent",
        "content_read_by_builder": True,
    })
    return record


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str,
    ).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_module(path: Path, name: str):
    path = _regular(path, name)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name}: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _literal_runtime_record() -> dict[str, Any]:
    literal = VENV_PYTHON.expanduser()
    if not literal.is_symlink():
        raise ValueError(f"literal venv interpreter must remain a symlink: {literal}")
    resolved = literal.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"literal interpreter target is not a regular file: {resolved}")
    pyvenv = literal.parent.parent / "pyvenv.cfg"
    if not pyvenv.is_file() or pyvenv.is_symlink():
        raise ValueError(f"literal interpreter has no stable pyvenv.cfg: {pyvenv}")
    materializer = _regular(MATERIALIZER, "V5 materializer")
    first_line = materializer.read_text(encoding="utf-8").splitlines()[0]
    expected_shebang = f"#!{literal}"
    if first_line != expected_shebang:
        raise ValueError(f"materializer shebang differs: {first_line!r} != {expected_shebang!r}")
    resolved_sha = _sha256(resolved)
    pyvenv_sha = _sha256(pyvenv)
    return {
        "literal_path": str(literal),
        "literal_is_symlink": True,
        "resolved_path": str(resolved),
        "resolved_sha256": resolved_sha,
        "resolved_bytes": int(resolved.stat().st_size),
        "pyvenv_cfg_path": str(pyvenv),
        "pyvenv_cfg_sha256": pyvenv_sha,
        "pyvenv_cfg_bytes": int(pyvenv.stat().st_size),
        "materializer_path": str(materializer),
        "materializer_shebang": first_line,
        "content_scope": "literal_venv_invocation_with_resolved_binary_and_pyvenv_binding",
    }


def _api_record() -> dict[str, Any]:
    module = _load_module(V5_RUNNER, "ds02_f3_s2_v5_api_probe")
    run = getattr(module, "run", None)
    if not callable(run):
        raise ValueError("shared V5 runner has no callable run API")
    signature = inspect.signature(run)
    names = list(signature.parameters)
    if names != ["request_path", "io_slot_approved", "parent_pid"]:
        raise ValueError(f"unexpected V5 run signature: {names}")
    if signature.parameters["io_slot_approved"].default is not False:
        raise ValueError("V5 io_slot_approved default is not False")
    if signature.parameters["parent_pid"].default is not None:
        raise ValueError("V5 parent_pid default is not None")
    return {
        "module_path": str(_regular(V5_RUNNER, "V5 runner")),
        "module_sha256": _sha256(V5_RUNNER),
        "symbol": "run",
        "parameters": names,
        "preflight_call": "run(request_path, io_slot_approved=False, parent_pid=None)",
        "solver_launch": False,
    }


def _source_import_closure() -> dict[str, Any]:
    modules = [
        _code_record(V5_RUNNER, "external solver v5 entry"),
        _code_record(V4_RUNNER, "external solver v4 imported by v5"),
        _code_record(V1_RUNNER, "external solver v1 imported by v4/v5"),
        _code_record(RUNTIME_V2, "shared runtime v2 dynamically loaded by v5"),
    ]
    api = _api_record()
    if api["module_sha256"] != modules[0]["sha256"]:
        raise ValueError("V5 API probe SHA differs from import-closure record")
    return {
        "schema": "ds02.stage2.external-solver-v5-source-import-closure.v1",
        "entrypoint": modules[0],
        "modules": modules,
        "runtime_binding_role": "shared_runtime_v2",
        "api": api,
        "runtime6": {
            "required": False,
            "path": None,
            "reason": "V5/V4/V1 source closure imports runtime_v2; no runtime6 import or API requirement was observed",
        },
        "content_scope": "source_code_and_runtime_metadata_only; no solver/payload read",
    }


def _add_input(request: dict[str, Any], path: Path, sha: str, scope: str) -> None:
    canonical_path = str(path.expanduser().resolve())
    files = list(request.get("input_files", []))
    if canonical_path not in files:
        files.append(canonical_path)
    request["input_files"] = sorted(set(files))
    hashes = dict(request.get("input_sha256", {}))
    hashes[canonical_path] = sha
    request["input_sha256"] = hashes
    scopes = dict(request.get("input_content_scope", {}))
    scopes[canonical_path] = scope
    request["input_content_scope"] = scopes


def _check_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return value


def _validate_forward_validator_binding(
    request: Mapping[str, Any],
    closure: Mapping[str, Any],
    *,
    expected_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the validator that will actually be called before V5.

    A SHA-shaped string is insufficient here: the path, file bytes, request
    input edge, runtime-closure edge, and importable callable must all point
    at the same source file.  ``expected_path`` is injectable only for the
    same-size mutation negative test; normal request validation uses the
    current V8 module path.
    """

    expected = (expected_path or V8_BUILDER).expanduser().resolve()
    forward = request.get("forward_validator_binding")
    if not isinstance(forward, Mapping):
        raise ValueError("forward closure validator binding is missing")
    if forward.get("schema") != "ds02.stage2.f3-s2.middle-overlay-closure-validator.v2":
        raise ValueError("forward closure validator binding has the wrong schema")
    raw_path = forward.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("forward validator path is missing")
    bound = Path(raw_path).expanduser()
    if bound.is_symlink() or not bound.is_file():
        raise ValueError("forward validator path is not a regular non-symlink file")
    bound = bound.resolve()
    if bound != expected:
        raise ValueError(f"forward validator path differs: {bound} != {expected}")
    actual_sha = _sha256(bound)
    bound_sha = _check_hex(forward.get("sha256"), "forward validator SHA")
    if bound_sha != actual_sha:
        raise ValueError("forward validator SHA does not match bound source bytes")
    if forward.get("callable") != "validate_closure":
        raise ValueError("forward validator callable is not validate_closure")
    if forward.get("role") != "forward_validator_before_shared_v5_run":
        raise ValueError("forward validator role is not the pre-V5 gate")

    closure_forward = closure.get("forward_validator")
    if not isinstance(closure_forward, Mapping):
        raise ValueError("runtime closure has no forward validator edge")
    if closure_forward.get("path") != str(bound) or closure_forward.get("sha256") != actual_sha:
        raise ValueError("runtime closure forward validator edge differs from binding")
    if closure_forward.get("callable") != "validate_closure":
        raise ValueError("runtime closure forward validator callable differs")

    input_files = {str(path) for path in request.get("input_files", [])}
    input_hashes = request.get("input_sha256")
    if not isinstance(input_hashes, Mapping):
        raise ValueError("request input_sha256 map is missing")
    if str(bound) not in input_files:
        raise ValueError("forward validator is not an actionable input file")
    if input_hashes.get(str(bound)) != actual_sha:
        raise ValueError("forward validator input SHA does not match source bytes")
    input_scopes = request.get("input_content_scope")
    if not isinstance(input_scopes, Mapping) or str(bound) not in input_scopes:
        raise ValueError("forward validator input content scope is missing")

    # Load precisely the bound module and verify the API that the parent gate
    # will call.  This catches a same-sized replacement with a stale SHA as
    # well as a path that happens to contain a similarly named file.
    module = _load_module(bound, f"ds02_f3_s2_v8_validator_{actual_sha[:12]}")
    if not callable(getattr(module, "validate_closure", None)):
        raise ValueError("bound validator module has no callable validate_closure")
    module_v5 = getattr(module, "V5_RUNNER", None)
    if not isinstance(module_v5, Path) or module_v5.expanduser().resolve() != V5_RUNNER.resolve():
        raise ValueError("bound validator module does not use the declared V5 runner")
    if not callable(getattr(module, "source_only_preflight", None)):
        raise ValueError("bound validator module has no source-only preflight API")
    return {
        "path": str(bound),
        "sha256": actual_sha,
        "callable": "validate_closure",
        "module_loaded": True,
        "v5_runner_path": str(V5_RUNNER.resolve()),
    }


def validate_closure(request: Mapping[str, Any]) -> None:
    """Validate the strict V8 closure before entering the shared V5 API."""

    if request.get("schema") != STRICT_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("request is not a strict READY_FOR_PARENT_GUARD V5 request")
    if request.get("qualification") != UNKNOWN:
        raise ValueError("request must remain QI/QN/QE UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ValueError("request invocation flags are not source-only")
    if request.get("sha256") != _canonical(request):
        raise ValueError("request canonical SHA mismatch")
    closure = request.get("runtime_closure")
    if not isinstance(closure, Mapping) or closure.get("schema") != "ds02.stage2.external-solver-v5-runtime-closure.v2":
        raise ValueError("runtime closure is missing or has the wrong schema")

    literal = closure.get("literal_venv_invocation")
    actual_literal = _literal_runtime_record()
    if not isinstance(literal, Mapping):
        raise ValueError("literal venv invocation record is missing")
    for key in ("literal_path", "resolved_path", "resolved_sha256", "pyvenv_cfg_path", "pyvenv_cfg_sha256", "materializer_shebang"):
        if literal.get(key) != actual_literal.get(key):
            raise ValueError(f"literal venv closure mismatch: {key}")
    if literal.get("literal_is_symlink") is not True:
        raise ValueError("literal venv path is not recorded as a symlink")

    runtime = request.get("runtime_binding")
    if not isinstance(runtime, Mapping) or Path(str(runtime.get("path", ""))).expanduser().resolve() != RUNTIME_V2.resolve():
        raise ValueError("runtime_binding is not shared runtime v2")
    if runtime.get("sha256") != _sha256(RUNTIME_V2):
        raise ValueError("runtime v2 SHA differs")

    imports = closure.get("source_import_closure")
    if not isinstance(imports, Mapping):
        raise ValueError("source import closure is missing")
    expected = {
        str(V5_RUNNER): _sha256(V5_RUNNER),
        str(V4_RUNNER): _sha256(V4_RUNNER),
        str(V1_RUNNER): _sha256(V1_RUNNER),
        str(RUNTIME_V2): _sha256(RUNTIME_V2),
    }
    observed = {
        str(item.get("path")): item.get("sha256")
        for item in imports.get("modules", []) if isinstance(item, Mapping)
    }
    if observed != expected:
        raise ValueError(f"source import closure differs: {observed!r}")
    runtime6 = imports.get("runtime6")
    if not isinstance(runtime6, Mapping) or runtime6.get("required") is not False or runtime6.get("path") is not None:
        raise ValueError("runtime6 must remain explicitly unnecessary")
    api = imports.get("api")
    if not isinstance(api, Mapping) or api.get("symbol") != "run" or api.get("parameters") != ["request_path", "io_slot_approved", "parent_pid"]:
        raise ValueError("V5 API closure is incomplete")

    pyvenv_path = str(PYVENV_CFG.resolve())
    input_files = {str(path) for path in request.get("input_files", [])}
    if str(VENV_PYTHON.resolve()) not in input_files or pyvenv_path not in input_files:
        raise ValueError("resolved interpreter and pyvenv.cfg are not in actionable input closure")
    if request.get("input_sha256", {}).get(pyvenv_path) != actual_literal["pyvenv_cfg_sha256"]:
        raise ValueError("pyvenv.cfg input SHA differs")
    if request.get("input_sha256", {}).get(str(VENV_PYTHON.resolve())) != actual_literal["resolved_sha256"]:
        raise ValueError("resolved interpreter input SHA differs")

    _validate_forward_validator_binding(request, closure)

    study = request.get("study")
    source_binding = request.get("source_binding")
    if not isinstance(study, Mapping) or study.get("only_semantic_change") is not True:
        raise ValueError("one-variable study contract is missing")
    if not isinstance(source_binding, Mapping) or source_binding.get("only_one_semantic_xml_change") is not True:
        raise ValueError("source binding is not one-variable")
    if source_binding.get("source_control_and_motion_unchanged") is not True:
        raise ValueError("source control/motion immutability is not bound")
    if "ROOT178" in json.dumps(request, sort_keys=True):
        raise ValueError("running ROOT178 must not be bound into ROOT173/174 request")


def _load_v6():
    return _load_module(V6_BUILDER, "stage2_f3_s2_middle_overlay_requests_v6")


def _study_values(study: str) -> tuple[str, str, str, str]:
    if study == "half_cfl":
        return (
            "F3_S2_MATCHED_MIDDLE_HALF_CFL_ROOT173_V8",
            "f3-s2-matched-middle-half-cfl-root-173-v8-001",
            "ROOT173_V8",
            "f3_s2_middle_half_cfl_v8",
        )
    if study == "half_output":
        return (
            "F3_S2_MATCHED_MIDDLE_HALF_OUTPUT_ROOT174_V8",
            "f3-s2-matched-middle-half-output-root-174-v8-001",
            "ROOT174_V8",
            "f3_s2_middle_half_output_v8",
        )
    raise ValueError(f"unknown study {study}")


def build_request(study: str, overlay: Path, output: Path, launch_commit: str) -> dict[str, Any]:
    """Build one fresh v8 request through the consumed v6 delegate."""

    case_id, attempt_id, study_id, namespace = _study_values(study)
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    v6 = _load_v6()
    temp = output.with_name(f".{output.name}.{os.getpid()}.v6.tmp")
    if temp.exists() or temp.is_symlink():
        raise FileExistsError(f"temporary request exists: {temp}")
    try:
        v6._build_via_delegate(study, overlay.expanduser().resolve(), temp, launch_commit)
        request = _load_json(temp)
    finally:
        temp.unlink(missing_ok=True)

    request["case_id"] = case_id
    request["attempt_id"] = attempt_id
    request["launch_commit"] = launch_commit
    request["request_variant_schema"] = SCHEMA
    request["request_variant_status"] = "READY_FOR_PARENT_GUARD_V8_STRICT_VALIDATOR_CLOSURE"
    request["storage_scope"] = dict(request.get("storage_scope", {}))
    request["storage_scope"]["output_root"] = str(EXTERNAL_ROOT / "F3" / case_id / attempt_id)
    request["storage_scope"]["reservation_basis"] = dict(request["storage_scope"].get("reservation_basis", {}))
    request["storage_scope"]["reservation_basis"]["fresh_v8_namespace"] = namespace

    literal = _literal_runtime_record()
    imports = _source_import_closure()
    v8_builder_record = {
        "path": str(V8_BUILDER),
        "source_path_at_build": str(V8_BUILDER),
        "sha256": _sha256(V8_BUILDER),
        "content_scope": "forward_validator_module_hashed_at_build_and_by_parent_after_integration",
        "callable": "validate_closure",
    }
    forward_validator = {
        "schema": "ds02.stage2.f3-s2.middle-overlay-closure-validator.v2",
        "path": str(V8_BUILDER),
        "sha256": v8_builder_record["sha256"],
        "role": "forward_validator_before_shared_v5_run",
        "callable": "validate_closure",
        "source_only": True,
    }
    request["runtime_closure"] = {
        "schema": "ds02.stage2.external-solver-v5-runtime-closure.v2",
        "literal_venv_invocation": literal,
        "source_import_closure": imports,
        "forward_validator": dict(forward_validator),
        "runtime6": {"required": False, "path": None},
        "parent_content_check": "parent reservation then pre/post hash of BI4, forcing, actionable inputs",
        "solver_or_native_payload_read_by_builder": False,
    }
    request["forward_validator_binding"] = forward_validator
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    request["source_provenance"]["v8_validator_module"] = v8_builder_record
    request["source_provenance"]["runtime_closure"] = "runtime2 + v5/v4/v1 import chain; literal venv and pyvenv bound"
    request["source_provenance"]["runtime6"] = "not required by actual V5 source closure"
    request["execution"] = dict(request.get("execution", {}))
    request["execution"]["forward_validator"] = {
        "path": str(V8_BUILDER),
        "callable": "validate_closure",
        "order": "before_shared_v5_run",
    }
    request["execution"]["solver_launch"] = "PARENT_ONLY"
    request["qualification"] = dict(UNKNOWN)
    request["physical_qualification"] = {**UNKNOWN, "reason": "source-only v8 closure; one-variable overlay; no terminal scientific credit"}
    request["solver_started"] = False
    request["cfd_invoked"] = False
    request["raw_opened"] = False
    request["hdf5_opened"] = False

    # The resolved interpreter is already an actionable input in the v6
    # delegate.  Add pyvenv.cfg explicitly; the literal symlink itself is
    # represented in runtime_closure because V5 canonicalizes input paths.
    _add_input(request, PYVENV_CFG, literal["pyvenv_cfg_sha256"], "post_reservation_hash")
    # The validator is executable source, not merely descriptive metadata.
    # Make it an actionable input edge so parent V5 pre/post accounting cannot
    # run a different same-named module than the one validated here.
    _add_input(request, V8_BUILDER, v8_builder_record["sha256"], "source_validator_hashed_before_v5_and_parent_pre_post")
    # Keep a small explicit source-import manifest in the request, while the
    # four imported modules remain the existing actionable code inputs.
    request["source_import_closure"] = imports
    request["sha256"] = _canonical(request)
    _write_once(output, request)
    validate_closure(request)
    return {
        "status": "PASS_V8_SOURCE_ONLY_REQUEST",
        "output": str(output),
        "request_sha256": request["sha256"],
        "canonical_sha256": request["sha256"],
        "study": study,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "input_count": len(request["input_files"]),
        "runtime6_required": False,
        "literal_venv_bound": True,
        "pyvenv_bound": True,
        "validator_bound": True,
        "validator_sha256": v8_builder_record["sha256"],
        "solver_started": False,
        "payload_read": False,
    }


def source_only_preflight(request_path: Path) -> dict[str, Any]:
    request = _load_json(request_path)
    validate_closure(request)
    v5 = _load_module(V5_RUNNER, "stage2_f3_s2_shared_v5_preflight")
    result = v5.run(request_path, io_slot_approved=False, parent_pid=None)
    if not isinstance(result, Mapping) or result.get("status") != "READY_FOR_PARENT_IO_SLOT":
        raise RuntimeError(f"shared V5 strict source-only preflight did not pass: {result!r}")
    return {
        "status": "PASS_V8_CLOSURE_AND_SHARED_V5_SOURCE_ONLY_PREFLIGHT",
        "request": str(request_path.expanduser().resolve()),
        "shared_v5_status": result.get("status"),
        "shared_v5_report_schema": result.get("schema"),
        "request_sha256": result.get("request_sha256"),
        "ledger_mutated": False,
        "solver_started": False,
        "payload_read": False,
        "hdf5_opened": False,
    }


def negative_closure_test(request_path: Path) -> dict[str, Any]:
    request = _load_json(request_path)
    validator_path = str(V8_BUILDER.resolve())
    pyvenv_path = str(PYVENV_CFG.resolve())

    def expect_reject(label: str, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate["sha256"] = _canonical(candidate)
        try:
            validate_closure(candidate)
        except Exception as exc:
            return {
                "label": label,
                "status": "REJECTED_AS_EXPECTED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        raise AssertionError(f"negative closure case was accepted: {label}")

    cases: list[dict[str, Any]] = []

    missing_validator = json.loads(json.dumps(request))
    missing_validator["input_files"] = [path for path in missing_validator.get("input_files", []) if path != validator_path]
    missing_validator.get("input_sha256", {}).pop(validator_path, None)
    missing_validator.get("input_content_scope", {}).pop(validator_path, None)
    cases.append(expect_reject("missing_validator_input_edge", missing_validator))

    missing_cfg = json.loads(json.dumps(request))
    missing_cfg["input_files"] = [path for path in missing_cfg.get("input_files", []) if path != pyvenv_path]
    missing_cfg.get("input_sha256", {}).pop(pyvenv_path, None)
    missing_cfg.get("input_content_scope", {}).pop(pyvenv_path, None)
    cases.append(expect_reject("missing_pyvenv_cfg_input_edge", missing_cfg))

    wrong_sha = json.loads(json.dumps(request))
    wrong_sha["forward_validator_binding"]["sha256"] = "0" * 64
    wrong_sha["runtime_closure"]["forward_validator"]["sha256"] = "0" * 64
    cases.append(expect_reject("wrong_validator_sha", wrong_sha))

    # Keep file length and path shape while changing one source byte.  The
    # temporary file is never used as a request input or imported; this tests
    # the content-SHA gate without touching the immutable V8 module.
    with tempfile.TemporaryDirectory(prefix="ds02-v8-validator-negative-") as directory:
        mutated_path = Path(directory) / V8_BUILDER.name
        data = bytearray(V8_BUILDER.read_bytes())
        if not data:
            raise AssertionError("V8 validator source unexpectedly empty")
        index = min(len(data) - 1, 17)
        data[index] ^= 0x01
        mutated_path.write_bytes(data)
        mutated = json.loads(json.dumps(request))
        mutated["forward_validator_binding"]["path"] = str(mutated_path)
        mutated["forward_validator_binding"]["sha256"] = _sha256(V8_BUILDER)
        mutated["runtime_closure"]["forward_validator"]["path"] = str(mutated_path)
        mutated["runtime_closure"]["forward_validator"]["sha256"] = _sha256(V8_BUILDER)
        mutated["input_files"] = [path for path in mutated.get("input_files", []) if path != validator_path]
        mutated["input_files"].append(str(mutated_path))
        mutated["input_sha256"] = dict(mutated.get("input_sha256", {}))
        mutated["input_sha256"].pop(validator_path, None)
        mutated["input_sha256"][str(mutated_path)] = _sha256(V8_BUILDER)
        mutated["input_content_scope"] = dict(mutated.get("input_content_scope", {}))
        mutated["input_content_scope"].pop(validator_path, None)
        mutated["input_content_scope"][str(mutated_path)] = "same_size_mutation_negative_fixture"
        mutated["sha256"] = _canonical(mutated)
        try:
            _validate_forward_validator_binding(
                mutated,
                mutated["runtime_closure"],
                expected_path=mutated_path,
            )
        except Exception as exc:
            cases.append({
                "label": "same_size_validator_code_mutation",
                "status": "REJECTED_AS_EXPECTED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
        else:
            raise AssertionError("same-size validator code mutation was accepted")

    return {
        "status": "PASS_V8_NEGATIVE_CLOSURE_SUITE",
        "request": str(request_path.expanduser().resolve()),
        "cases": cases,
        "solver_started": False,
        "payload_read": False,
    }


def self_test() -> dict[str, Any]:
    literal = _literal_runtime_record()
    imports = _source_import_closure()
    if imports["runtime6"]["required"] is not False:
        raise AssertionError("runtime6 was incorrectly required")
    if literal["materializer_shebang"] != f"#!{VENV_PYTHON}":
        raise AssertionError("materializer literal shebang mismatch")
    bound = {
        "schema": "ds02.stage2.f3-s2.middle-overlay-closure-validator.v2",
        "path": str(V8_BUILDER),
        "sha256": _sha256(V8_BUILDER),
        "role": "forward_validator_before_shared_v5_run",
        "callable": "validate_closure",
    }
    synthetic = {
        "input_files": [str(V8_BUILDER)],
        "input_sha256": {str(V8_BUILDER): _sha256(V8_BUILDER)},
        "input_content_scope": {str(V8_BUILDER): "self_test"},
        "forward_validator_binding": bound,
        "runtime_closure": {"forward_validator": dict(bound)},
    }
    checked = _validate_forward_validator_binding(synthetic, synthetic["runtime_closure"])
    return {
        "status": "PASS_V8_RUNTIME_CLOSURE_SELF_TEST",
        "literal_venv_bound": True,
        "pyvenv_bound": True,
        "source_import_roles": [item["label"] for item in imports["modules"]],
        "runtime6_required": False,
        "validator_path": checked["path"],
        "validator_sha256": checked["sha256"],
        "validator_module_loaded": checked["module_loaded"],
        "solver_started": False,
        "payload_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--build-request", action="store_true")
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--negative-closure-test", action="store_true")
    parser.add_argument("--study", choices=("half_cfl", "half_output"))
    parser.add_argument("--overlay-xml", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--launch-commit", default="source-only-v8-forward-pending-parent")
    args = parser.parse_args()
    try:
        if args.self_test:
            value = self_test()
        elif args.build_request:
            if args.study is None or args.overlay_xml is None or args.output is None:
                parser.error("--build-request requires --study, --overlay-xml and --output")
            value = build_request(args.study, args.overlay_xml, args.output, args.launch_commit)
        elif args.preflight:
            if args.request is None:
                parser.error("--preflight requires --request")
            value = source_only_preflight(args.request)
        else:
            if args.request is None:
                parser.error("--negative-closure-test requires --request")
            value = negative_closure_test(args.request)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED_V8_SOURCE_ONLY", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
