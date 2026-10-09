#!/usr/bin/env python3
"""Bind a ROOT191 typed product for a later portable V2 parent run.

This is the source-only bridge for the next guarded attempt.  It joins the
small ROOT191 request, ROOT200 evidence, the frozen V15 request, and the
179C producer receipts, while treating the 62 MiB V16 JSON as a deferred
payload.  The builder records its known SHA/size and a fresh stat snapshot;
it never opens or hashes that result.  A parent may later copy the declared
roles after reservation and invoke the existing V2 command:

``python ...ds_data02_stage2_f2_typed_only_portable_rebind_v2.py run``

The output is an admission/command contract, not portable or scientific
credit.  QI/QN/QE and cold-replay credit remain UNKNOWN/NOT_CLAIMED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
LITERAL_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV_CFG = LITERAL_PYTHON.parent.parent / "pyvenv.cfg"

REQUEST_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-validation.v1"
ROOT191_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v3"
ROOT200_INNER_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V15_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
FULL_STAT_FIELDS = ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
DECLARED_STAT_FIELDS = ("bytes", "mode_bits", "mtime_ns")


class Root213Error(RuntimeError):
    """A strict ROOT213 metadata or path-contract failure."""


def _abs(value: Any, role: str, *, allow_symlink: bool = False) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root213Error(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() and not allow_symlink:
        raise Root213Error(f"{role} may not be a symlink: {path}")
    return path


def _stat(path: Path, role: str) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise Root213Error(f"{role} must be a regular non-symlink file: {path}")
    info = path.stat()
    return {"bytes": int(info.st_size), "mode_bits": int(info.st_mode & 0o7777),
            "mtime_ns": int(info.st_mtime_ns), "ctime_ns": int(info.st_ctime_ns),
            "st_dev": int(info.st_dev), "st_ino": int(info.st_ino)}


def _sha(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> str:
    observed = _stat(path, role)
    if observed["bytes"] > maximum:
        raise Root213Error(f"{role} exceeds the bounded metadata limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, role: str) -> dict[str, Any]:
    observed = _stat(path, role)
    if observed["bytes"] > MAX_METADATA_BYTES:
        raise Root213Error(f"{role} exceeds the bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root213Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Root213Error(f"{role} must be a JSON object")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _sha_value(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise Root213Error(f"{role} must be a lowercase SHA-256")
    return value


def _expected_stat(value: Any, role: str, fields: Sequence[str] = FULL_STAT_FIELDS) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise Root213Error(f"{role} is missing its stat contract")
    result: dict[str, int] = {}
    for field in fields:
        raw = value.get(field)
        if isinstance(raw, bool) or raw is None:
            raise Root213Error(f"{role}.{field} is missing or not an integer")
        try:
            result[field] = int(raw)
        except (TypeError, ValueError) as error:
            raise Root213Error(f"{role}.{field} is not an integer") from error
    return result


def _small_binding(value: Any, role: str, *, expected_sha_key: str = "file_sha256") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Root213Error(f"{role} binding is missing")
    path = _abs(value.get("path"), role)
    expected_sha = _sha_value(value.get(expected_sha_key), f"{role}.{expected_sha_key}")
    actual_sha = _sha(path, role)
    if actual_sha != expected_sha:
        raise Root213Error(f"{role} content SHA differs")
    result = {"path": str(path), "file_sha256": actual_sha, "stat": _stat(path, role)}
    if "canonical_sha256" in value:
        result["canonical_sha256"] = _sha_value(value["canonical_sha256"], f"{role}.canonical_sha256")
    if "schema" in value:
        result["schema"] = value["schema"]
    if "case_id" in value:
        result["case_id"] = value["case_id"]
    if "attempt_id" in value:
        result["attempt_id"] = value["attempt_id"]
    return result


def _deferred_result(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Root213Error(f"{role} deferred binding is missing")
    path = _abs(value.get("path"), role)
    expected_sha = _sha_value(value.get("sha256"), f"{role}.sha256")
    raw_bytes = value.get("bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, (int, float)) or int(raw_bytes) < 0:
        raise Root213Error(f"{role}.bytes is invalid")
    declared = _expected_stat(value.get("stat"), f"{role}.stat", FULL_STAT_FIELDS)
    current: dict[str, int] | None = None
    if path.exists():
        current = _stat(path, role)
        if current != declared:
            raise Root213Error(f"{role} current stat differs from its frozen stat contract")
        if current["bytes"] != int(raw_bytes):
            raise Root213Error(f"{role} current bytes differs from its frozen byte contract")
    return {"path": str(path), "sha256": expected_sha, "bytes": int(raw_bytes),
            "expected_stat": declared, "current_stat": current,
            "content_read_by_builder": False,
            "read_phase": "PARENT_AFTER_RESERVATION_AND_SOURCE_COPY"}


def _deferred_h5(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Root213Error(f"{role} binding is missing")
    path = _abs(value.get("path"), role)
    return {"path": str(path), "sha256": _sha_value(value.get("sha256"), f"{role}.sha256"),
            "bytes": int(value.get("bytes", -1)), "content_read_by_builder": False,
            "read_phase": "NEVER_BY_TYPED_ONLY_PORTABLE_CONSUMER"}


def _require_unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise Root213Error(f"{role} must remain QI/QN/QE UNKNOWN")


def _root191_runtime(request: Mapping[str, Any]) -> dict[str, Any]:
    primary = request.get("root191_primary_builder")
    if not isinstance(primary, Mapping):
        raise Root213Error("ROOT191 primary builder metadata is missing")
    closure = primary.get("runtime_closure")
    if not isinstance(closure, Mapping) or closure.get("original_worktree_fallback") not in {"FORBIDDEN", "REJECT"}:
        raise Root213Error("ROOT191 runtime closure does not forbid original fallback")
    roles = closure.get("roles")
    if not isinstance(roles, list) or not roles:
        raise Root213Error("ROOT191 runtime closure has no roles")
    copied: list[dict[str, Any]] = []
    for item in roles:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise Root213Error("ROOT191 runtime role is malformed")
        path = _abs(item.get("path"), f"runtime.{item['role']}")
        expected_sha = _sha_value(item.get("sha256"), f"runtime.{item['role']}.sha256")
        observed_sha = _sha(path, f"runtime.{item['role']}")
        if observed_sha != expected_sha:
            raise Root213Error(f"runtime.{item['role']} content SHA differs")
        copied.append({"role": item["role"], "source_path": str(path),
                       "source_sha256": observed_sha, "source_stat": _stat(path, f"runtime.{item['role']}"),
                       "copy_after_parent_reservation": True,
                       "target_relative_path": f"runtime/{path.name}"})
    interpreter = closure.get("literal_interpreter")
    if not isinstance(interpreter, Mapping):
        raise Root213Error("ROOT191 literal interpreter binding is missing")
    # The project venv invocation is the one explicit environment exception:
    # preserve its literal symlink path and never replace argv[0] with the
    # resolved system interpreter.
    invocation = _abs(interpreter.get("invocation_path"), "literal interpreter", allow_symlink=True)
    pyvenv = interpreter.get("pyvenv_cfg")
    if not isinstance(pyvenv, Mapping):
        raise Root213Error("ROOT191 pyvenv binding is missing")
    pyvenv_binding = _small_binding(pyvenv, "literal interpreter pyvenv", expected_sha_key="sha256")
    if bool(interpreter.get("do_not_resolve_argv0")) is not True:
        raise Root213Error("literal interpreter must preserve argv0 without resolve")
    interpreter_meta = {"invocation_path": str(invocation), "argv0_literal": True,
                        "no_original_system_python_fallback": True,
                        "pyvenv_cfg": pyvenv_binding,
                        "provenance_target_stat": interpreter.get("target_stat")}
    return {"schema": closure.get("schema"), "import_mode": closure.get("import_mode"),
            "original_worktree_fallback": "REJECT", "roles": copied,
            "literal_interpreter": interpreter_meta,
            "preferred_entrypoint": closure.get("preferred_entrypoint")}


def _root200_evidence(request: Mapping[str, Any]) -> dict[str, Any]:
    root = request.get("root200_binding")
    if not isinstance(root, Mapping):
        raise Root213Error("ROOT191 root200_binding is missing")
    inner = root.get("inner_request")
    wrapper = root.get("outer_wrapper")
    for role, binding in (("ROOT200 inner request", inner), ("ROOT200 outer wrapper", wrapper)):
        if not isinstance(binding, Mapping):
            raise Root213Error(f"{role} binding is missing")
    inner_path = _abs(inner.get("path"), "ROOT200 inner request")
    inner_value = _json(inner_path, "ROOT200 inner request")
    if inner_value.get("schema") != ROOT200_INNER_SCHEMA:
        raise Root213Error("ROOT200 inner request schema differs")
    if inner_value.get("sha256") != _canonical(inner_value):
        raise Root213Error("ROOT200 inner request canonical SHA differs")
    inner_file_sha = _sha(inner_path, "ROOT200 inner request")
    if inner_file_sha != _sha_value(inner.get("file_sha256"), "ROOT200 inner request.file_sha256"):
        raise Root213Error("ROOT200 inner request file SHA differs")
    wrapper_binding = _small_binding(wrapper, "ROOT200 outer wrapper")
    evidence: dict[str, Any] = {
        "inner_request": {"path": str(inner_path), "file_sha256": inner_file_sha,
                           "canonical_sha256": _sha_value(inner.get("canonical_sha256"), "ROOT200 inner canonical")},
        "outer_wrapper": wrapper_binding,
    }
    for key, role in (("completed_execution_receipt", "ROOT200 execution receipt"),
                      ("actual_verification_checkpoint", "ROOT200 verification checkpoint"),
                      ("fresh_v12_proof", "ROOT200 V12 proof")):
        binding = root.get(key)
        evidence[key] = _small_binding(binding, role)
    result = root.get("result")
    evidence["deferred_result"] = _deferred_result(result, "ROOT200 typed result")
    evidence["deferred_typed_h5"] = _deferred_h5(root.get("typed_h5"), "ROOT200 typed H5")
    # These are the small actionable edges that the relocated V2 child must
    # copy and rebind.  The source-request field nested in v12_forward is
    # provenance for the producer join; it is intentionally not treated as an
    # executable fallback path.
    current = inner_value.get("current_manifest_binding")
    marker = inner_value.get("v12_forward")
    sidecar = marker.get("semantic_sidecar") if isinstance(marker, Mapping) else None
    parent = inner_value.get("v66_parent_binding")
    nested = parent.get("nested_worker_report") if isinstance(parent, Mapping) else None
    evidence["nested_actionable_metadata"] = {
        "current_manifest": _small_binding(current, "ROOT200 CURRENT manifest", expected_sha_key="sha256"),
        "v12_semantic_sidecar": _small_binding(sidecar, "ROOT200 V12 semantic sidecar", expected_sha_key="sha256"),
        "producer_nested_report": _small_binding(nested, "ROOT200 producer nested report", expected_sha_key="sha256"),
        "source_request_provenance_only": (
            dict(marker.get("source_request")) if isinstance(marker, Mapping)
            and isinstance(marker.get("source_request"), Mapping) else None),
    }
    return evidence


def _producer_evidence(request: Mapping[str, Any]) -> dict[str, Any]:
    producer = request.get("producer_179c_binding")
    if not isinstance(producer, Mapping):
        raise Root213Error("ROOT191 producer_179c_binding is missing")
    values: dict[str, Any] = {}
    for key in ("request", "completed_receipt", "parent_report", "root_proof"):
        values[key] = _small_binding(producer.get(key), f"179C {key}")
    return {"request": values["request"], "completed_receipt": values["completed_receipt"],
            "parent_report": values["parent_report"], "root_proof": values["root_proof"],
            "same_source_case": producer.get("same_source_case")}


def build_request(*, root191_request: Path | str, output: Path | str,
                  fresh_output_root: Path | str, case_id: str, attempt_id: str) -> dict[str, Any]:
    source_path = _abs(str(root191_request), "ROOT191 request")
    source = _json(source_path, "ROOT191 request")
    if source.get("schema") != ROOT191_SCHEMA or source.get("status") != "READY_FOR_PARENT_GUARD":
        raise Root213Error("ROOT191 request is not the expected ready V4 request")
    if source.get("role") != "DEVELOPMENT" or source.get("product_mode") != "TYPED_ONLY_LABELS":
        raise Root213Error("ROOT191 request is not a typed-only DEVELOPMENT product")
    if source.get("model_invoked") is not False or source.get("cfd_invoked") is not False:
        raise Root213Error("ROOT191 request opens model/CFD execution")
    if source.get("ledger_mutated") is not False or source.get("old_proof_reuse") is not False:
        raise Root213Error("ROOT191 request has ledger mutation or old-proof reuse")
    if source.get("fresh_cold_credit") is not False:
        raise Root213Error("ROOT191 request is not explicitly cold-credit false")
    _require_unknown(source.get("qualification"), "ROOT191 qualification")
    _require_unknown(source.get("quality"), "ROOT191 quality")
    execution = source.get("execution")
    if not isinstance(execution, Mapping) or execution.get("raw_opened") is not False or execution.get("read_hdf5_or_bi4") is not False:
        raise Root213Error("ROOT191 execution content boundary is not closed")
    root200 = _root200_evidence(source)
    producer = _producer_evidence(source)
    frozen = _small_binding(source.get("source_frozen_request"), "frozen V15 request")
    if frozen.get("schema") != V15_SCHEMA:
        raise Root213Error("frozen source is not the actual V15 replay request")
    runtime = _root191_runtime(source)
    output_root = _abs(str(fresh_output_root), "ROOT213 fresh output root")
    if output_root.exists():
        raise Root213Error(f"refusing an existing ROOT213 output namespace: {output_root}")
    if not case_id or "ROOT213" not in case_id:
        raise Root213Error("case_id must carry ROOT213 identity")
    if not attempt_id or "root-forward-030-001" not in attempt_id:
        raise Root213Error("attempt_id must retain the strict root-forward suffix")
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "case_id": case_id, "attempt_id": attempt_id, "role": "DEVELOPMENT",
        "product_mode": "TYPED_ONLY_PORTABLE_TYPED_CONSUMER",
        "qualification": dict(UNKNOWN), "quality": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        "root191_source": {"path": str(source_path), "file_sha256": _sha(source_path, "ROOT191 request"),
                            "canonical_sha256": _sha_value(source.get("sha256"), "ROOT191 request canonical")},
        "root200_evidence": root200, "producer_179c_evidence": producer, "frozen_v15": frozen,
        "runtime_closure": runtime,
        "deferred_products": {
            "v16_result": root200["deferred_result"],
            "typed_h5": root200["deferred_typed_h5"],
        },
        "relocation": {
            "fresh_output_root": str(output_root), "target_runtime_root": "runtime",
            "target_evidence_root": "evidence", "target_product_root": "products",
            "source_provenance_only": True, "original_absolute_path_fallback": "REJECT",
            "symlink_targets": "REJECT", "source_inode_mtime_equivalence": "NOT_CLAIMED",
        },
        "payload_actions_after_parent_reservation": {
            "copy_v16_result": {"source": root200["deferred_result"], "target_relative_path": "products/v16-result.json",
                                 "verify_pre_post_sha_and_full_stat": True, "read_by_this_builder": False},
            "copy_typed_h5": {"source": root200["deferred_typed_h5"], "target_relative_path": "products/typed-result.h5",
                               "read_by_this_typed_only_consumer": False, "copy_forbidden_in_v2_run": True},
            "copy_small_evidence_and_runtime": True,
            "read_raw_bi4_or_native_frames": False,
        },
        "v2_interface": {
            "schema": "ds02.stage2.f2-typed-only-portable-rebind-interface.v2",
            "source_script": str(SCRIPT), "source_script_sha256": _sha(SCRIPT, "ROOT213 V2 bridge"),
            "v2_script": str(V2_SCRIPT), "v2_script_sha256": _sha(V2_SCRIPT, "portable V2 entrypoint"),
            "literal_python": str(LITERAL_PYTHON), "pyvenv_cfg": str(PYVENV_CFG),
            "command_template": [str(LITERAL_PYTHON), "-B", "-I", "{copied_v2_entrypoint}", "run",
                                  "--request", "{sealed_v2_request}", "--output-relative", "reports/v2-report.json",
                                  "--python", "{copied_literal_python}", "--parent-pid", "{parent_pid}",
                                  "--max-wall-seconds", "900"],
            "parent_reservation_before_deferred_result_read": True,
            "guard_scope": "same_parent_ledger; no nested ledger; no model/CFD/raw/H5",
        },
        "metadata_read_pass": {
            "root191_root200_179c_and_v15_json_read": True,
            "runtime_code_hashes_read": True, "deferred_v16_content_read": False,
            "typed_h5_content_read": False, "bi4_native_content_read": False,
            "solver_evaluator_launched": False,
        },
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "source_content_read_by_builder": False,
    }
    request["sha256"] = _canonical(request)
    destination = _abs(str(output), "ROOT213 output")
    if destination.exists():
        raise Root213Error(f"refusing to overwrite ROOT213 request: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(destination),
            "file_sha256": _sha(destination, "ROOT213 request"), "canonical_sha256": request["sha256"],
            "payload_read": False, "deferred_result_bytes": request["deferred_products"]["v16_result"]["bytes"]}


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path = _abs(str(path), "ROOT213 request")
    request = _json(request_path, "ROOT213 request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != _canonical(request):
        raise Root213Error("ROOT213 request schema/canonical SHA differs")
    if request.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise Root213Error("ROOT213 request is not parent-ready")
    if request.get("source_content_read_by_builder") is not False:
        raise Root213Error("ROOT213 builder content boundary is open")
    deferred = request.get("deferred_products")
    if not isinstance(deferred, Mapping) or not isinstance(deferred.get("v16_result"), Mapping):
        raise Root213Error("ROOT213 deferred result binding is missing")
    result = deferred["v16_result"]
    path_result = _abs(result.get("path"), "ROOT213 deferred result")
    expected = _expected_stat(result.get("expected_stat"), "ROOT213 deferred result.expected_stat")
    if path_result.exists() and _stat(path_result, "ROOT213 deferred result") != expected:
        raise Root213Error("ROOT213 deferred result stat changed before parent reservation")
    runtime = request.get("runtime_closure")
    if not isinstance(runtime, Mapping) or runtime.get("original_worktree_fallback") != "REJECT":
        raise Root213Error("ROOT213 runtime fallback policy is not strict")
    interface = request.get("v2_interface")
    if not isinstance(interface, Mapping) or interface.get("parent_reservation_before_deferred_result_read") is not True:
        raise Root213Error("ROOT213 V2 interface lacks parent reservation boundary")
    return {"schema": REPORT_SCHEMA, "status": "ROOT213_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": _sha(request_path, "ROOT213 request"),
                        "canonical_sha256": request["sha256"]},
            "deferred_result": {"path": str(path_result), "expected_stat": expected,
                                "bytes": result["bytes"], "sha256": result["sha256"],
                                "content_read": False},
            "command_template": interface["command_template"], "payload_read": False,
            "portable_cold_replay_credit": request.get("portable_cold_replay_credit")}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--root191-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(root191_request=args.root191_request, output=args.output,
                                  fresh_output_root=args.fresh_output_root, case_id=args.case_id,
                                  attempt_id=args.attempt_id)
        else:
            value = validate_request(args.request)
    except (Root213Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT213 portable typed parent: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
