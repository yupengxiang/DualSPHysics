#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Strict source-bound full-window native observer for F3 middle/fine runs.

This additive wrapper reuses the consumed bounded stream decoder only after
joining one terminal external-solver request to its receipt/proof, generated
XML, RunPARTs path, raw output root, and BI4 snapshot proof.  It is
parameterized by the source grid (ROOT177 middle or ROOT178 fine); no grid
identity is inferred from a neighboring run.  The builder hashes only small
terminal metadata and the generated XML; the parent guard owns every native
Part read and its pre/decode/post SHA/stat checks.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
V2_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v2.py"


def _load_v2():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v2_consumed", V2_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V2_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()
SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v3"
PASS_STATUS = "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN"
UNKNOWN_STATUS = "UNKNOWN_F3_FULL_NATIVE_STREAM"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _regular(path: Path, label: str) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _returncode(value: dict[str, Any]) -> Any:
    execution = value.get("execution")
    if isinstance(execution, dict) and "returncode" in execution:
        return execution.get("returncode")
    return value.get("returncode", value.get("return_code"))


def _terminal_status(value: Any) -> bool:
    text = str(value or "").upper()
    return text in {"COMPLETED", "COMPLETE", "SUCCESS", "COMPLETED0"} or text.startswith("COMPLETED_")


def _request_binding(value: dict[str, Any], request_path: Path, request_sha: str, label: str) -> None:
    binding = value.get("request")
    if not isinstance(binding, dict):
        raise ValueError(f"{label} lacks request provenance")
    bound_sha = binding.get("sha256") or binding.get("request_sha256")
    if bound_sha != request_sha:
        raise ValueError(f"{label} request SHA mismatch")
    bound_path = binding.get("path") or binding.get("request_path")
    if bound_path is not None and _path(str(bound_path)) != request_path:
        raise ValueError(f"{label} request path mismatch")


def _identity(value: dict[str, Any], label: str) -> None:
    for key, expected in (("family_id", "F3"), ("sentinel_id", "F3-S2"), ("physical_case_id", PHYSICAL_CASE_ID)):
        if value.get(key) not in (None, expected):
            raise ValueError(f"{label} {key} mismatch: {value.get(key)!r}")


def _path_value(value: Any, label: str) -> str:
    if isinstance(value, dict):
        value = value.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} has no path")
    return value


def _terminal_context(args: argparse.Namespace) -> dict[str, Any]:
    request_path = _path(args.solver_request)
    receipt_path = _path(args.terminal_receipt)
    proof_path = _path(args.terminal_proof)
    request = _load_json(request_path, "terminal solver request")
    receipt = _load_json(receipt_path, "terminal solver receipt")
    proof = _load_json(proof_path, "terminal solver proof")
    if request.get("schema") != "ds02.stage2.external-solver-request.v5" or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("terminal request is not a completed external-v5 source request")
    _identity(request, "terminal request")
    request_sha = _sha256(request_path)
    if not _terminal_status(receipt.get("status")) or _returncode(receipt) not in (0, None):
        raise ValueError("terminal receipt is not completed with zero return code")
    _request_binding(receipt, request_path, request_sha, "terminal receipt")
    if proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("terminal proof is not an actual verification")
    _identity(proof, "terminal proof")
    if proof.get("request_sha256") not in (None, request_sha):
        raise ValueError("terminal proof request SHA mismatch")
    if proof.get("receipt") is not None and _path(str(proof["receipt"])) != receipt_path:
        raise ValueError("terminal proof receipt path mismatch")
    if proof.get("receipt_sha256") not in (None, _sha256(receipt_path)):
        raise ValueError("terminal proof receipt SHA mismatch")
    run_summary = proof.get("RunPARTs_summary")
    if not isinstance(run_summary, dict) or int(run_summary.get("rows", 0) or 0) < 2:
        raise ValueError("terminal proof lacks RunPARTs summary")

    requested_root = request.get("storage_scope", {}).get("output_root")
    if not requested_root:
        raise ValueError("terminal request lacks storage_scope.output_root")
    requested_root = _path(str(requested_root))
    receipt_root = receipt.get("filesystem", {}).get("output_root") if isinstance(receipt.get("filesystem"), dict) else None
    if receipt_root is not None and _path(str(receipt_root)) != requested_root:
        raise ValueError("terminal receipt output root differs from request")
    output_root = _path(str(receipt_root or requested_root))
    expected_raw = output_root / "solver_output" / "data"
    expected_runparts = output_root / "solver_output" / "RunPARTs.csv"
    if _path(args.raw_root) != expected_raw:
        raise ValueError("raw root is not request.output_root/solver_output/data")
    if _path(args.runparts) != expected_runparts:
        raise ValueError("RunPARTs is not request.output_root/solver_output/RunPARTs.csv")

    source = request.get("source_provenance") if isinstance(request.get("source_provenance"), dict) else {}
    expected_xml = source.get("generated_xml")
    if expected_xml is None:
        expected_xml = request.get("fine_generated_path_contract", {}).get("generated_xml")
    expected_xml = _path(_path_value(expected_xml, "request generated XML"))
    generated_xml = _path(args.generated_xml)
    if generated_xml != expected_xml:
        raise ValueError("generated XML path is not the request-bound source")
    expected_xml_sha = request.get("input_sha256", {}).get(str(generated_xml))
    if not expected_xml_sha or _sha256(generated_xml) != expected_xml_sha:
        raise ValueError("generated XML SHA differs from request binding")
    if run_summary.get("path") is not None and _path(str(run_summary["path"])) != _path(args.runparts):
        raise ValueError("terminal proof RunPARTs path mismatch")

    snapshot_binding = request.get("bi4_snapshot_binding")
    if not isinstance(snapshot_binding, dict) or not isinstance(snapshot_binding.get("bi4"), dict):
        raise ValueError("request lacks BI4 snapshot binding")
    bi4 = snapshot_binding["bi4"]
    snapshot_proof_path = _path(args.source_snapshot_proof)
    expected_snapshot_proof = snapshot_binding.get("proof")
    if not expected_snapshot_proof or snapshot_proof_path != _path(str(expected_snapshot_proof)):
        raise ValueError("source snapshot proof path differs from request binding")
    actual_snapshot_proof_sha = _sha256(snapshot_proof_path)
    if snapshot_binding.get("proof_sha256") not in (None, actual_snapshot_proof_sha):
        raise ValueError("source snapshot proof SHA differs from request binding")
    snapshot_proof = _load_json(snapshot_proof_path, "source snapshot proof")
    if snapshot_proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(snapshot_proof.get("status", "")):
        raise ValueError("source snapshot proof is not actual")
    snapshot = snapshot_proof.get("worker_source_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("sha256") != bi4.get("content_sha256") or int(snapshot.get("bytes", 0)) != int(bi4.get("expected_bytes", 0)):
        raise ValueError("source snapshot proof does not match terminal request BI4 binding")
    if snapshot_proof.get("parent_actual_prepost_content_hashes_equal") is not True or snapshot_proof.get("native_particle_fields_decoded") is not False:
        raise ValueError("source snapshot proof exceeds its source-only contract")
    snapshot_report_path = _path(args.source_snapshot_report)
    if snapshot_proof.get("report") is not None and _path(str(snapshot_proof["report"])) != snapshot_report_path:
        raise ValueError("source snapshot report path mismatch")
    snapshot_report_sha = _sha256(snapshot_report_path)
    if snapshot_proof.get("report_sha256") not in (None, snapshot_report_sha):
        raise ValueError("source snapshot report SHA mismatch")
    return {
        "request": request,
        "receipt": receipt,
        "proof": proof,
        "request_sha256": request_sha,
        "output_root": output_root,
        "generated_xml_sha256": expected_xml_sha,
        "snapshot_proof_sha256": actual_snapshot_proof_sha,
        "snapshot_report_sha256": snapshot_report_sha,
        "bi4_sha256": bi4.get("content_sha256"),
        "bi4_bytes": int(bi4.get("expected_bytes", 0)),
    }


def _xml_gate(path: Path, expected_dp: float, expected_count: int) -> dict[str, Any]:
    root = ET.parse(_regular(path, "generated XML")).getroot()
    values: list[float] = []
    for element in root.findall(".//constants/dp") + root.findall(".//definition"):
        raw = element.get("value") if element.tag == "dp" else element.get("dp")
        if raw is not None:
            values.append(float(raw))
    if not values or any(not math.isclose(item, expected_dp, rel_tol=0.0, abs_tol=1.0e-12) for item in values):
        raise ValueError(f"generated XML dp values {values!r} do not match expected {expected_dp}")
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles section")
    counts = [int(node.get("count")) for node in particles.findall("fluid") if node.get("count") is not None]
    count = sum(counts)
    if count != expected_count:
        raise ValueError(f"generated XML initial fluid count {count} != expected {expected_count}")
    return {"dp_values_m": values, "initial_fluid_count": count, "fluid_block_counts": counts}


def _header_value(observation: dict[str, Any], name: str) -> Any:
    header = observation.get("native_header")
    if not isinstance(header, dict) or not isinstance(header.get(name), dict):
        return None
    return header[name].get("value")


def _fluid_count(observation: dict[str, Any]) -> int | None:
    for key in ("fluid_observable_using_native_header_mass", "fluid_observables"):
        value = observation.get(key)
        if isinstance(value, dict) and isinstance(value.get("fluid_count"), int):
            return int(value["fluid_count"])
    return None


def _unknown(output: Path, reason: str, expected_dp: float, expected_count: int) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "scope": {"full_native_window": True, "expected_dp_m": expected_dp, "expected_initial_fluid_count": expected_count, "typed_conversion": "NOT_PERFORMED", "hdf5_read": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    V2.atomic_json(_path(output), value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    if _path(args.output).exists() or _path(args.output).is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable full observer output: {args.output}")
    context = _terminal_context(args)
    xml_gate = _xml_gate(_path(args.generated_xml), float(args.expected_dp_m), int(args.expected_initial_fluid_count))
    temporary = _path(args.output).with_name(f".{_path(args.output).name}.{os.getpid()}.v2-adapter.json")
    delegated = argparse.Namespace(**vars(args))
    delegated.output = temporary
    try:
        value = V2.run(delegated)
        observations = value.get("observations")
        if not isinstance(observations, list) or not observations:
            raise V2.base.UnsupportedSemantics("full stream produced no observations")
        initial_count = _fluid_count(observations[0])
        if initial_count != int(args.expected_initial_fluid_count):
            raise V2.base.UnsupportedSemantics(f"frame-0 fluid count {initial_count} != expected source count {args.expected_initial_fluid_count}")
        for index, observation in enumerate(observations):
            dp = _header_value(observation, "Dp")
            if dp is None or not math.isclose(float(dp), float(args.expected_dp_m), rel_tol=0.0, abs_tol=1.0e-12):
                raise V2.base.UnsupportedSemantics(f"native frame {index} Dp {dp!r} != expected {args.expected_dp_m}")
        value["schema"] = SCHEMA
        value["status"] = PASS_STATUS
        value["scope"] = dict(value.get("scope", {}))
        value["scope"].update({"strict_terminal_source_join": True, "expected_dp_m": float(args.expected_dp_m), "expected_initial_fluid_count": int(args.expected_initial_fluid_count), "later_fluid_counts_are_observed": True})
        value["strict_source_binding"] = {"terminal_request_sha256": context["request_sha256"], "output_root": str(context["output_root"]), "raw_root": str(_path(args.raw_root)), "runparts": str(_path(args.runparts)), "generated_xml_sha256": context["generated_xml_sha256"], "source_snapshot_proof_sha256": context["snapshot_proof_sha256"], "source_snapshot_report_sha256": context["snapshot_report_sha256"], "bi4_sha256": context["bi4_sha256"], "bi4_bytes": context["bi4_bytes"], "xml_gate": xml_gate}
        value["scientific_qualification"] = {"QI": "PASS_LIMITED_FULL_NATIVE_FIELDS_STRICT_SOURCE_JOIN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scope_note": "full native finite/identity/header/time stream only; continuum equivalence, dynamics, output/integration error, event and spatial truth remain unknown"}
        V2.atomic_json(_path(args.output), value)
        return value
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V2.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    return {"status": "PASS", "schema": SCHEMA, "parameterized_grid": True, "full_window": True, "payload_read": "parent_after_reservation", "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--calibration-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=300.0)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=256 * 1024 * 1024)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof, args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml, args.decoder, args.decoder_source, args.calibration_contract, args.output, args.scratch_root, args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m, args.expected_initial_fluid_count, args.query_times)
    if any(item is None for item in required):
        parser.error("strict full observer requires terminal/source provenance and all bounded decoder arguments")
    try:
        result = run(args)
    except V2.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr); return 143
    except V2.base.UnsupportedSemantics as exc:
        try:
            result = _unknown(args.output, str(exc), float(args.expected_dp_m), int(args.expected_initial_fluid_count))
        except FileExistsError:
            print(str(exc), file=sys.stderr); return 2
        print(json.dumps({"status": result["status"], "output": str(_path(args.output))}, ensure_ascii=False)); return 2
    except Exception as exc:
        print(f"strict full native observer failed: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "output": str(_path(args.output)), "frame_count": result.get("scope", {}).get("frame_count")}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
