#!/usr/bin/env python3
"""Forward fine175 PartVTKOut audit with complete native runtime provenance.

The consumed decoder attempt remains immutable. This version audits a new
completed decoder receipt (the primary002 attempt) and accepts the real
strace -> PartVTKOut_linux64 argv only when the wrapper prefix, expanded tool
argv, source identity, launch/end input hashes, official tool digest, and
DsphConfig.xml input are all bound. It rejects the old primary001 receipt, a
nominal unwrapped command, and a command that merely contains the official
tool at an arbitrary position.

No H5, trajectory Part_*.bi4, solver, or CFD data are read here. The output is
a native identity/time/motive/mass lower-bound ledger; fate and dynamics stay
UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PARTVTKOUT_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
STRACE_DEFAULT = Path("/usr/bin/strace")
RUNTIME_V4_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4_DEFAULT = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
V1_SCRIPT_DEFAULT = SCRIPT.parent / "ds_data02_stage2_f2_s1_fine_native_impact_v1.py"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FINE_CASE_ID = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
DECODER_CASE_ID = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2"
AUDIT_CASE_ID = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2_AUDIT"
AUDIT_ATTEMPT_ID = "f2-s1-fine-native-impact-v2-audit-002"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-fine-native-impact-v2.v2"


class FineAuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FineAuditError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FineAuditError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FineAuditError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_v1(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_f2_fine_native_impact_v1", path)
    if spec is None or spec.loader is None:
        raise FineAuditError(f"cannot load preserved v1 parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expanded(command: list[Any], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root)) for value in command]


def flag_value(command: list[Any], flag: str, label: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise FineAuditError(f"{label} command lacks {flag}")


def stable_input(receipt: dict[str, Any], path: Path, *, label: str) -> str:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise FineAuditError(f"{label} is not stable across decoder launch/end: {key}")
    if sha256(path) != declared:
        raise FineAuditError(f"{label} changed after decoder completion: {key}")
    return str(declared)


def fixed_native_argv(tool: Path, raw_dir: Path, output_root: Path) -> list[str]:
    return [
        str(tool.resolve()), "-dirdata", str(raw_dir.resolve()),
        "-savecsv", str((output_root / "PartOut.csv").resolve()),
        "-saveresume", str((output_root / "resume.csv").resolve()),
        "-createdirs:1", "-csvsep:1",
    ]


def trace_opened(trace_path: Path, needle: str) -> bool:
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    return any(
        needle in line and "openat(" in line and "= " in line and "= -1" not in line
        for line in text.splitlines()
    )


def validate_decoder(decoder_path: Path, source: dict[str, Any], v1: Any) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    decoder_path, decoder = read_json(decoder_path, "PartVTKOut primary002 receipt")
    if decoder.get("schema") != "ds02.execution-receipt.v1" or decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise FineAuditError("primary002 decoder receipt is not completed code 0")
    output_root = Path(str(decoder.get("output_root", ""))).expanduser().resolve()
    if output_root != decoder_path.parent:
        raise FineAuditError("decoder output_root is inconsistent with receipt path")
    request = decoder.get("request", {})
    if request.get("family_id") != "F2" or request.get("case_id") != DECODER_CASE_ID:
        raise FineAuditError("decoder request case identity differs")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise FineAuditError("decoder physical identity differs")
    source_receipt = str(source["solver_receipt_path"])
    if request.get("source_solver_receipt") != source_receipt:
        raise FineAuditError("decoder source solver receipt is not exact")
    source_fields = {
        "source_raw_partout": source["raw_partout"],
        "source_runparts": source["runparts"],
        "source_run_out": source["run_out"],
        "source_generated_xml": source["generated_xml"],
        "source_gencase_receipt": source["gencase_receipt"],
    }
    for field, path in source_fields.items():
        if request.get(field) != str(path):
            raise FineAuditError(f"decoder {field} is not exact")
    request_command = request.get("command", [])
    command = [str(value) for value in decoder.get("command", [])]
    if not isinstance(request_command, list) or not isinstance(command, list):
        raise FineAuditError("decoder command is not argv")
    if expanded(request_command, output_root) != command:
        raise FineAuditError("decoder receipt command differs from expanded request")
    trace_prefix = [
        "/usr/bin/strace", "-f", "-qq", "-e", "trace=openat,open,statx",
        "-o", str((output_root / "native-openat.trace").resolve()),
    ]
    if command[:7] != trace_prefix:
        raise FineAuditError("decoder does not use the exact registered strace prefix")
    if len(command) < 8:
        raise FineAuditError("decoder command has no tool argv")
    tool = require_file(command[7], "official PartVTKOut tool in decoder command")
    if tool != PARTVTKOUT_DEFAULT.resolve():
        raise FineAuditError("decoder official tool path differs")
    raw_dir = Path(flag_value(command[8:], "-dirdata", "decoder")).resolve()
    if raw_dir != Path(source["raw_partout"]).parent.resolve():
        raise FineAuditError("decoder -dirdata is not source solver raw root")
    if command[7:] != fixed_native_argv(tool, raw_dir, output_root):
        raise FineAuditError("decoder tool argv is not the exact registered native command")
    if any(str(value).startswith("-threads") for value in command):
        raise FineAuditError("decoder carries unsupported threads flag")
    trace_path = Path(flag_value(command[:7], "-o", "strace")).resolve()
    if trace_path != (output_root / "native-openat.trace").resolve() or not trace_path.is_file():
        raise FineAuditError("decoder trace path is not the guarded output trace")
    if not trace_opened(trace_path, "DsphConfig.xml") or not trace_opened(trace_path, "PartOut_000.obi4"):
        raise FineAuditError("decoder trace lacks successful DsphConfig.xml and PartOut_000.obi4 opens")
    config = tool.parent / "DsphConfig.xml"
    if not config.is_file():
        raise FineAuditError("official DsphConfig.xml is missing")
    if decoder.get("binary_sha256") != sha256(STRACE_DEFAULT):
        raise FineAuditError("receipt binary_sha256 is not the bound strace digest")
    declared = request.get("input_sha256", {})
    files = {str(Path(value).resolve()) for value in request.get("input_files", [])}
    if set(declared) != files or not files:
        raise FineAuditError("decoder input digest map is incomplete")
    for value in sorted(files):
        stable_input(decoder, Path(value), label=Path(value).name)
    tool_key, strace_key, config_key = str(tool), str(STRACE_DEFAULT.resolve()), str(config.resolve())
    for key in (tool_key, strace_key, config_key):
        if key not in files:
            raise FineAuditError(f"decoder request does not bind runtime source: {key}")
    if any(Path(value).name.startswith("Part_") and Path(value).suffix == ".bi4" for value in files):
        raise FineAuditError("decoder request unexpectedly binds trajectory Part_*.bi4")
    partout_csv = require_file(flag_value(command, "-savecsv", "decoder"), "decoded PartOut.csv")
    resume = require_file(flag_value(command, "-saveresume", "decoder"), "decoder resume CSV")
    if partout_csv.parent != output_root or resume.parent != output_root:
        raise FineAuditError("decoder outputs are outside guarded output root")
    return decoder, partout_csv, resume, {
        "official_tool": {"path": str(tool), "sha256": sha256(tool), "bytes": tool.stat().st_size},
        "strace": {"path": str(STRACE_DEFAULT.resolve()), "sha256": sha256(STRACE_DEFAULT), "bytes": STRACE_DEFAULT.stat().st_size},
        "config": {"path": str(config), "sha256": sha256(config), "bytes": config.stat().st_size},
        "trace": {"path": str(trace_path), "sha256": sha256(trace_path), "bytes": trace_path.stat().st_size,
                  "opened_DsphConfig_xml": True, "opened_PartOut_000_obi4": True},
        "command": command,
        "tool_argv": command[7:],
    }


def audit(solver_receipt_path: Path, decoder_receipt_path: Path, v1_script_path: Path, output: Path) -> dict[str, Any]:
    v1 = load_v1(require_file(v1_script_path, "preserved fine v1 audit script"))
    solver_receipt_path, solver_receipt = read_json(solver_receipt_path, "fine solver receipt")
    source = v1._solver_sources(solver_receipt_path, solver_receipt)
    decoder, partout_csv, resume, closure = validate_decoder(decoder_receipt_path, source, v1)
    with tempfile.TemporaryDirectory(prefix="f2-fine-audit-v2-") as temp:
        base_path = Path(temp) / "v1-ledger.json"
        v1.audit(solver_receipt_path=solver_receipt_path, decoder_receipt_path=decoder_receipt_path, output=base_path)
        result = json.loads(base_path.read_text(encoding="utf-8"))
    result["schema"] = OUTPUT_SCHEMA
    result["status"] = "completed"
    result["decoder_provenance_v2"] = {
        "decoder_receipt": {"path": str(decoder_receipt_path.resolve()), "sha256": sha256(decoder_receipt_path)},
        **closure,
        "request_case_id": decoder["request"]["case_id"],
        "request_attempt_id": decoder["request"]["attempt_id"],
        "source_request_sha256": decoder.get("request_sha256"),
    }
    result["source_policy"] = {
        "h5_opened": False, "trajectory_part_content_opened": False,
        "decoder_raw_partout_source": "official PartOut_000.obi4",
        "dsph_config_bound": True, "official_tool_bound": True,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
    }
    result["qualification"] = {
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
    }
    atomic_json(output, result)
    return result


def prepare(decoder_receipt_path: Path, solver_receipt_path: Path, v1_script_path: Path,
            output_request: Path, partvtkout: Path, strace: Path,
            runtime_v4: Path, runtime_v2: Path, dispatch_v4: Path, strict_v4: Path) -> dict[str, Any]:
    v1 = load_v1(require_file(v1_script_path, "preserved fine v1 audit script"))
    solver_path, solver = read_json(solver_receipt_path, "fine solver receipt")
    source = v1._solver_sources(solver_path, solver)
    decoder_path, decoder = read_json(decoder_receipt_path, "primary002 decoder receipt")
    if decoder.get("schema") != "ds02.execution-receipt.v1" or decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise FineAuditError("primary002 decoder must be completed before audit request preparation")
    if decoder.get("request", {}).get("case_id") != DECODER_CASE_ID:
        raise FineAuditError("decoder is not the v2 primary002 case")
    decoder, partout_csv, resume, closure = validate_decoder(decoder_path, source, v1)
    files: list[Path] = [
        SCRIPT, v1_script_path, decoder_path, partout_csv, resume,
        Path(closure["trace"]["path"]), Path(closure["official_tool"]["path"]),
        Path(closure["strace"]["path"]), Path(closure["config"]["path"]),
        runtime_v4, runtime_v2, dispatch_v4, strict_v4,
        source["solver_receipt_path"], source["generated_xml"], source["generated_bi4"],
        source["runparts"], source["run_out"], source["raw_partout"], source["gencase_receipt"],
    ]
    files.extend(Path(value) for value in decoder["request"].get("input_files", []))
    unique = list(dict.fromkeys(Path(value).resolve() for value in files))
    for path in unique:
        require_file(path, f"audit input {path.name}")
    digests = {str(path): sha256(path) for path in unique}
    request = {
        "schema": "ds02.request.v1", "family_id": "F2", "case_id": AUDIT_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID, "attempt_id": AUDIT_ATTEMPT_ID,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 128 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(SCRIPT.parents[2]),
        "command": [
            str(VENV), str(SCRIPT), "audit",
            "--solver-receipt", str(source["solver_receipt_path"]),
            "--decoder-receipt", str(decoder_path),
            "--v1-script", str(v1_script_path),
            "--output", "{attempt_root}/f2-s1-fine-native-impact-v2.json",
        ],
        "input_files": [str(path) for path in unique], "input_sha256": digests,
        "source_solver_receipt": str(source["solver_receipt_path"]),
        "source_solver_receipt_sha256": sha256(source["solver_receipt_path"]),
        "source_decoder_receipt": str(decoder_path),
        "source_decoder_receipt_sha256": sha256(decoder_path),
        "source_decoder_request_sha256": decoder.get("request_sha256"),
        "source_partout_csv": str(partout_csv), "source_partout_csv_sha256": sha256(partout_csv),
        "source_resume_csv": str(resume), "source_resume_csv_sha256": sha256(resume),
        "native_runtime_closure": closure,
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True,
        "foreign_process_protection_required": True, "shared_lease_required": True,
        "solver_launch_forbidden": True, "trajectory_h5_read": False,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": (
            "Forward v2 small-input audit of primary002. It requires the exact "
            "strace-prefixed official decoder argv, complete source receipt input "
            "stability, official DsphConfig.xml/tool hashes, and native PartOut/RunPARTs "
            "joins. Primary001 remains immutable and is not credited."
        ),
    }
    atomic_json(output_request, request)
    return {
        "status": "prepared", "request": str(output_request.resolve()),
        "request_sha256": sha256(output_request), "input_count": len(unique),
        "partout_csv": str(partout_csv), "decoder_receipt": str(decoder_path),
        "config": closure["config"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--decoder-receipt", type=Path, required=True)
    prep.add_argument("--solver-receipt", type=Path, required=True)
    prep.add_argument("--v1-script", type=Path, default=V1_SCRIPT_DEFAULT)
    prep.add_argument("--output-request", type=Path, required=True)
    prep.add_argument("--partvtkout", type=Path, default=PARTVTKOUT_DEFAULT)
    prep.add_argument("--strace", type=Path, default=STRACE_DEFAULT)
    prep.add_argument("--runtime-v4", type=Path, default=RUNTIME_V4_DEFAULT)
    prep.add_argument("--runtime-v2", type=Path, default=RUNTIME_V2_DEFAULT)
    prep.add_argument("--dispatch-v4", type=Path, default=DISPATCH_V4_DEFAULT)
    prep.add_argument("--strict-v4", type=Path, default=STRICT_V4_DEFAULT)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--solver-receipt", type=Path, required=True)
    audit_parser.add_argument("--decoder-receipt", type=Path, required=True)
    audit_parser.add_argument("--v1-script", type=Path, default=V1_SCRIPT_DEFAULT)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.decoder_receipt, args.solver_receipt, args.v1_script,
                             args.output_request, args.partvtkout, args.strace,
                             args.runtime_v4, args.runtime_v2, args.dispatch_v4, args.strict_v4)
        else:
            result = audit(args.solver_receipt, args.decoder_receipt, args.v1_script, args.output)
    except FineAuditError as exc:
        raise SystemExit(f"FineAuditError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
