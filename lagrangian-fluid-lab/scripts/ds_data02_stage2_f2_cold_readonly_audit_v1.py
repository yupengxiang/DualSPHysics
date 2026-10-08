#!/usr/bin/env python3
"""Read-only audit for the fresh F2 cold run and evaluator handoff.

The audit consumes JSON reports, the small 24-role provenance sidecar, and
the filtered ``strace -ff`` text.  It does not open HDF5, BI4, raw source
arrays, or start a worker.  Trace groups are supplied explicitly: source-copy
PIDs may open the original source inputs, while private worker/evaluator PIDs
must stay within the relocated target/output roots.  A missing or unclassified
PID is a pending/failed audit condition, never portable credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-cold-readonly-audit.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
QUOTED = re.compile(r'"((?:\\.|[^"\\])*)"')


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"JSON object required: {target}")
    return value


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def _within(path: str | Path, root: str | Path) -> bool:
    candidate = os.path.normpath(str(path))
    base = os.path.normpath(str(root))
    return candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep)


def _trace_files(prefix: Path) -> list[Path]:
    prefix = prefix.expanduser().resolve()
    candidates = []
    if prefix.is_file():
        candidates.append(prefix)
    candidates.extend(path for path in prefix.parent.glob(prefix.name + ".*")
                      if path.is_file() and not path.is_symlink())
    return sorted(set(candidates))


def _trace_pid(path: Path, prefix: Path) -> int | None:
    name = path.name
    base = prefix.name
    if name == base:
        return None
    suffix = name[len(base) + 1:] if name.startswith(base + ".") else ""
    return int(suffix) if suffix.isdigit() else None


def _decode_quoted(raw: str) -> str:
    try:
        return str(json.loads('"' + raw + '"'))
    except json.JSONDecodeError:
        return raw.replace('\\"', '"').replace('\\\\', '\\')


def _path_tokens(line: str) -> Iterable[str]:
    for match in QUOTED.finditer(line):
        value = _decode_quoted(match.group(1))
        if value.startswith("/"):
            yield os.path.normpath(value)


def classify_trace(prefix: Path, *, source_pids: set[int], private_pids: set[int],
                   original_roots: Sequence[str], target_root: str,
                   output_root: str) -> dict[str, Any]:
    files = _trace_files(prefix)
    if not files:
        raise AuditError(f"no trace files found for {prefix}")
    groups: dict[str, dict[str, Any]] = {}
    for path in files:
        pid = _trace_pid(path, prefix)
        pid_key = str(pid) if pid is not None else "unclassified"
        group = groups.setdefault(pid_key, {"pid": pid, "files": [],
                                             "bytes": 0, "original_hits": [],
                                             "target_hits": [], "other_absolute_hits": []})
        group["files"].append(str(path))
        group["bytes"] += int(path.stat().st_size)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            for token in _path_tokens(line):
                is_original = any(_within(token, root) for root in original_roots)
                is_target = _within(token, target_root) or _within(token, output_root)
                if is_original:
                    group["original_hits"].append(token)
                elif is_target:
                    group["target_hits"].append(token)
                elif token.startswith(("/home/", "/var/tmp/", "/tmp/")):
                    group["other_absolute_hits"].append(token)
    for group in groups.values():
        for key in ("original_hits", "target_hits", "other_absolute_hits"):
            group[key] = sorted(set(group[key]))
        group["access_role"] = (
            "source_copy" if group["pid"] in source_pids else
            "private_worker_or_evaluator" if group["pid"] in private_pids else
            "unclassified")
    unknown = sorted(pid for pid, group in groups.items() if group["access_role"] == "unclassified")
    private_violations = {
        pid: group["original_hits"] for pid, group in groups.items()
        if group["access_role"] == "private_worker_or_evaluator" and group["original_hits"]
    }
    missing_source = sorted(pid for pid in source_pids if str(pid) not in groups)
    missing_private = sorted(pid for pid in private_pids if str(pid) not in groups)
    return {
        "prefix": str(prefix.resolve()), "files": [str(path) for path in files],
        "groups": groups, "source_pids": sorted(source_pids),
        "private_pids": sorted(private_pids), "unknown_groups": unknown,
        "missing_source_pids": missing_source, "missing_private_pids": missing_private,
        "private_original_path_violations": private_violations,
        "source_copy_original_access_allowed": True,
        "private_target_only_required": True,
        "trace_bytes": sum(int(path.stat().st_size) for path in files),
    }


def _binding_files(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    bindings = sidecar.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 24:
        raise AuditError("provenance sidecar must contain exactly 24 bindings")
    checked = []
    for item in bindings:
        if not isinstance(item, Mapping):
            raise AuditError("provenance binding is malformed")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        expected = item.get("sha256")
        if not path.is_file() or not isinstance(expected, str) or len(expected) != 64:
            raise AuditError(f"provenance binding is unavailable: {path}")
        if int(item.get("bytes", -1)) != int(path.stat().st_size):
            raise AuditError(f"provenance byte stat differs: {path}")
        if sha256_file(path) != expected:
            raise AuditError(f"provenance SHA differs: {path}")
        if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".dat"}:
            raise AuditError(f"content source was incorrectly included in provenance sidecar: {path}")
        checked.append({"role": item.get("role"), "path": str(path), "sha256": expected,
                        "scope": item.get("scope")})
    if sidecar.get("sha256") != canonical_sha(sidecar):
        raise AuditError("provenance sidecar canonical SHA differs")
    excluded = sidecar.get("excluded_content", {})
    if not all(isinstance(excluded, Mapping) and excluded.get(key) is True
               for key in ("hdf5", "bi4", "raw_source_tree")):
        raise AuditError("provenance sidecar does not explicitly exclude H5/BI4/raw content")
    return {"count": len(checked), "bindings": checked,
            "status": sidecar.get("status"),
            "license_scope": sidecar.get("license_scope") or sidecar.get("licenses"),
            "license_scope_status": "DECLARED" if sidecar.get("license_scope") or sidecar.get("licenses")
            else "MISSING_EXPLICIT_LICENSE_SCOPE"}


def _product_paths(executor_report: Mapping[str, Any], target_root: str, output_root: str) -> dict[str, Any]:
    private_runtime = executor_report.get("stages", {}).get("private_runtime", {})
    audit_path = private_runtime.get("audit")
    audit = load_json(audit_path) if isinstance(audit_path, str) and Path(audit_path).is_file() else None
    module_files = private_runtime.get("module_files", {})
    module_violations: dict[str, str] = {}
    if isinstance(module_files, Mapping):
        for role, path in module_files.items():
            if not isinstance(path, str) or not (_within(path, target_root) or _within(path, output_root)):
                module_violations[str(role)] = str(path)
    else:
        module_violations["module_files"] = "missing"
    if audit is None:
        module_violations["audit"] = str(audit_path)
    return {"audit_path": audit_path, "audit_present": audit is not None,
            "module_files": module_files, "module_original_path_violations": module_violations}


def audit(*, executor_report_path: Path, v34_request_path: Path,
          provenance_path: Path, trace_prefix: Path, source_pids: Sequence[int],
          private_pids: Sequence[int], target_root: Path, output_root: Path,
          v16_proof: Path | None = None, v16_result: Path | None = None,
          evaluator_report_path: Path | None = None) -> dict[str, Any]:
    executor_report = load_json(executor_report_path)
    v34 = load_json(v34_request_path)
    sidecar = load_json(provenance_path)
    if executor_report.get("original_path_fallback") != "FORBIDDEN":
        raise AuditError("executor report permits original-path fallback")
    if v34.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise AuditError("v34 request schema differs")
    if v34.get("sha256") != canonical_sha(v34):
        raise AuditError("v34 request canonical SHA differs")
    original_roots: set[str] = set()
    for item in v34.get("source_entries", []):
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            path = os.path.normpath(item["path"])
            original_roots.add(os.path.dirname(path))
            original_roots.add(path)
    for item in v34.get("runtime_sources", []):
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            path = os.path.normpath(item["path"])
            original_roots.add(os.path.dirname(path))
            original_roots.add(path)
    # Bind the request and provenance files themselves.  Adding their parent
    # directories would make a relocated target nested below a campaign
    # directory look like an original source tree and would reject legitimate
    # target accesses.  Source/runtime directory coverage is supplied by the
    # declared entries above.
    original_roots.update({str(v34_request_path.expanduser().resolve()),
                           str(provenance_path.expanduser().resolve())})
    trace = classify_trace(trace_prefix, source_pids=set(int(x) for x in source_pids),
                           private_pids=set(int(x) for x in private_pids),
                           original_roots=sorted(original_roots),
                           target_root=str(target_root.expanduser().resolve()),
                           output_root=str(output_root.expanduser().resolve()))
    provenance = _binding_files(sidecar)
    stages = executor_report.get("stages", {})
    raw_stage = stages.get("raw_to_typed_to_label", {}) if isinstance(stages, Mapping) else {}
    raw_report_path = raw_stage.get("report") if isinstance(raw_stage, Mapping) else None
    raw_report = load_json(raw_report_path) if isinstance(raw_report_path, str) and Path(raw_report_path).is_file() else None
    fresh = {"executor_report": {"path": str(executor_report_path.resolve()),
                                  "sha256": sha256_file(executor_report_path)},
             "raw_report": {"path": str(Path(raw_report_path).resolve()),
                             "sha256": sha256_file(raw_report_path)} if raw_report is not None else None,
             "v16": None}
    if v16_proof is not None or v16_result is not None:
        if v16_proof is None or v16_result is None:
            raise AuditError("V16 proof and result must be supplied together")
        proof = load_json(v16_proof)
        result_sha = sha256_file(v16_result)
        proof_v16 = proof.get("labels", {}).get("v16_sha256") if isinstance(proof.get("labels"), Mapping) else proof.get("v16_sha256")
        if proof_v16 != result_sha:
            raise AuditError("fresh V16 proof SHA does not equal the fresh result")
        if proof.get("qualification") not in (None, UNKNOWN):
            raise AuditError("fresh V16 proof qualification is not UNKNOWN")
        fresh["v16"] = {"proof": str(v16_proof.resolve()), "proof_sha256": sha256_file(v16_proof),
                         "result": str(v16_result.resolve()), "result_sha256": result_sha}
    evaluator = None
    if evaluator_report_path is not None:
        evaluator = load_json(evaluator_report_path)
        if evaluator.get("original_path_fallback") != "FORBIDDEN":
            raise AuditError("evaluator report permits original-path fallback")
        if evaluator.get("hdf5_or_bi4_content_read") is not False or evaluator.get("model_invoked") is not False:
            raise AuditError("evaluator report has an invalid content/model flag")
        if evaluator.get("qualification") != UNKNOWN:
            raise AuditError("evaluator report qualification is not UNKNOWN")
    product = _product_paths(executor_report, str(target_root), str(output_root))
    blockers: list[str] = []
    if trace["unknown_groups"] or trace["missing_source_pids"] or trace["missing_private_pids"]:
        blockers.append("trace PID groups are incomplete or unclassified")
    if trace["private_original_path_violations"]:
        blockers.append("private worker/evaluator opened an original source/runtime path")
    if product["module_original_path_violations"]:
        blockers.append("private runtime module audit is missing or points outside relocated roots")
    license_scope_pending = provenance["license_scope_status"] != "DECLARED"
    if license_scope_pending:
        blockers.append("dependency/license scope is not explicitly declared")
    if fresh["v16"] is None:
        blockers.append("fresh V16 proof/result has not been supplied")
    if evaluator is None:
        blockers.append("fresh evaluator-parent report has not been supplied")
    hard_blockers = [item for item in blockers
                     if item != "dependency/license scope is not explicitly declared"]
    status = (
        "PENDING_OR_FAILED_READONLY_AUDIT" if hard_blockers
        else "PASS_READONLY_BINDING_AUDIT_LICENSE_SCOPE_PENDING"
        if license_scope_pending
        else "PASS_READONLY_BINDING_AUDIT"
    )
    return {
        "schema": SCHEMA, "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "executor_report": fresh["executor_report"], "raw_report": fresh["raw_report"],
        "fresh_v16": fresh["v16"], "evaluator_report": None if evaluator is None else {
            "path": str(evaluator_report_path.resolve()), "sha256": sha256_file(evaluator_report_path)},
        "trace": trace, "private_runtime": product, "provenance": provenance,
        "source_copy_original_access": "ALLOWED_FOR_SOURCE_PHASE",
        "private_worker_original_access": "FORBIDDEN",
        "hdf5_or_bi4_content_read": False, "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "blockers": blockers,
        "credit_boundary": "Read-only binding evidence only; no portability or scientific qualification credit is granted by this audit.",
    }


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise AuditError(f"refusing existing audit output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(value)
    body["sha256"] = canonical_sha(body)
    path.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-report", type=Path, required=True)
    parser.add_argument("--v34-request", type=Path, required=True)
    parser.add_argument("--provenance-sidecar", type=Path, required=True)
    parser.add_argument("--trace-prefix", type=Path, required=True)
    parser.add_argument("--source-pids", type=int, nargs="+", required=True)
    parser.add_argument("--private-pids", type=int, nargs="+", required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--v16-proof", type=Path)
    parser.add_argument("--v16-result", type=Path)
    parser.add_argument("--evaluator-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = audit(executor_report_path=args.executor_report,
                      v34_request_path=args.v34_request,
                      provenance_path=args.provenance_sidecar,
                      trace_prefix=args.trace_prefix,
                      source_pids=args.source_pids,
                      private_pids=args.private_pids,
                      target_root=args.target_root,
                      output_root=args.output_root,
                      v16_proof=args.v16_proof,
                      v16_result=args.v16_result,
                      evaluator_report_path=args.evaluator_report)
        if args.output:
            _write_new(args.output, value)
            value = dict(value, output_path=str(args.output.resolve()), output_sha256=sha256_file(args.output))
    except (AuditError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"cold readonly audit v1: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
