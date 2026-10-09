#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Strict ROOT171 fine selected-native observer.

This additive v2 keeps the consumed v1 decoder path but closes the producer
identity boundary before any native Part is opened.  The supplied ROOT170
request, terminal receipt/proof, generated XML, RunPARTs path, and deferred
raw root must describe exactly one output tree.  The generated XML must carry
the dp=.003, 540000-fluid initial source.  Later fluid-count changes are
reported as observed exclusions rather than silently treated as initial
source equivalence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f3_s2_fine_selected_native_observer_v1.py"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _load_v1():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_fine_selected_native_observer_v1_consumed", V1_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V1_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()
SCHEMA = "ds02.stage2.f3-s2.fine-selected-native-observer.v2"
PASS_STATUS = "PASS_FINE_SELECTED_NATIVE_FIELDS_STRICT_SOURCE_JOIN"
UNKNOWN_STATUS = "UNKNOWN_UNSUPPORTED_FINE_NATIVE_OBSERVER_V2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
EXPECTED_DP_M = 0.003
EXPECTED_INITIAL_FLUID_COUNT = 540000
ROOT169_BI4_SHA = "ad10eb47299148d529883d1e4e4468b19076a8744d227187ec9208b6892e504e"
ROOT169_BI4_BYTES = 48_183_300


def _path(value: Path) -> Path:
    return value.expanduser().resolve()


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


def _stable_sha256(path: Path) -> tuple[str, dict[str, int], dict[str, int]]:
    path = _regular(path, "stable hash input")
    before = path.stat()
    digest = _sha256(path)
    after = path.stat()
    before_fields = {"bytes": int(before.st_size), "mtime_ns": int(before.st_mtime_ns), "ctime_ns": int(before.st_ctime_ns), "st_dev": int(before.st_dev), "st_ino": int(before.st_ino)}
    after_fields = {"bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns), "st_dev": int(after.st_dev), "st_ino": int(after.st_ino)}
    if before_fields != after_fields:
        raise ValueError(f"stable hash input changed while reading: {path}")
    return digest, before_fields, after_fields


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _request_binding(value: dict[str, Any], request_path: Path, request_sha: str, label: str) -> None:
    binding = value.get("request")
    if not isinstance(binding, dict):
        raise ValueError(f"{label} lacks request provenance")
    if binding.get("sha256") != request_sha:
        raise ValueError(f"{label} request SHA does not match ROOT170 request")
    if binding.get("path") is None or _path(Path(str(binding["path"]))) != request_path:
        raise ValueError(f"{label} request path does not match ROOT170 request")


def _terminal_context(args: argparse.Namespace) -> dict[str, Any]:
    request_path = _path(args.solver_request)
    receipt_path = _path(args.terminal_receipt)
    proof_path = _path(args.terminal_proof)
    request = _load_json(request_path, "ROOT170 solver request")
    receipt = _load_json(receipt_path, "ROOT170 terminal receipt")
    proof = _load_json(proof_path, "ROOT170 terminal proof")
    if request.get("schema") != "ds02.stage2.external-solver-request.v5" or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("ROOT170 request schema/status is not the consumed external-v5 request")
    for key, expected in (("family_id", "F3"), ("sentinel_id", "F3-S2"), ("physical_case_id", PHYSICAL_CASE_ID)):
        if request.get(key) != expected:
            raise ValueError(f"ROOT170 request {key} mismatch")
    request_sha = _sha256(request_path)
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    filesystem = receipt.get("filesystem") if isinstance(receipt.get("filesystem"), dict) else {}
    if not str(receipt.get("status", "")).lower().startswith("completed") or execution.get("returncode", receipt.get("returncode")) != 0:
        raise ValueError("ROOT170 receipt is not completed successfully")
    _request_binding(receipt, request_path, request_sha, "ROOT170 receipt")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT170 proof is not an actual terminal proof")
    if proof.get("request_sha256") != request_sha:
        raise ValueError("ROOT170 proof request SHA mismatch")
    if proof.get("receipt") is None or _path(Path(str(proof["receipt"]))) != receipt_path:
        raise ValueError("ROOT170 proof receipt path mismatch")
    if proof.get("receipt_sha256") != _sha256(receipt_path):
        raise ValueError("ROOT170 proof receipt SHA mismatch")
    run_summary = proof.get("RunPARTs_summary")
    if not isinstance(run_summary, dict) or int(run_summary.get("rows", 0) or 0) < 2:
        raise ValueError("ROOT170 proof lacks terminal RunPARTs summary")
    runparts_sha = run_summary.get("sha256")
    if not isinstance(runparts_sha, str) or len(runparts_sha) != 64:
        raise ValueError("ROOT170 proof lacks a RunPARTs SHA")
    request_output_root = request.get("storage_scope", {}).get("output_root")
    if not request_output_root:
        raise ValueError("ROOT170 request has no storage_scope.output_root")
    request_output_root = _path(Path(str(request_output_root)))
    receipt_output_root = filesystem.get("output_root")
    if receipt_output_root is not None and _path(Path(str(receipt_output_root))) != request_output_root:
        raise ValueError("ROOT170 receipt output_root differs from solver request output_root")
    output_root = receipt_output_root or request_output_root
    if not output_root:
        raise ValueError("ROOT170 output root is absent from receipt/request")
    output_root = _path(Path(str(output_root)))
    expected_raw = output_root / "solver_output" / "data"
    expected_runparts = output_root / "solver_output" / "RunPARTs.csv"
    if _path(args.raw_root) != expected_raw:
        raise ValueError("fine raw root is not ROOT170 storage_scope.output_root/solver_output/data")
    if _path(args.runparts) != expected_runparts:
        raise ValueError("fine RunPARTs path is not ROOT170 solver_output/RunPARTs.csv")
    if int(run_summary.get("rows", 0)) != int(args.expected_frame_count):
        raise ValueError("ROOT170 RunPARTs row count differs from the requested frame contract")
    proof_final_time = run_summary.get("final_time_s")
    if proof_final_time is None or abs(float(proof_final_time) - float(args.expected_final_time_s)) > float(args.final_time_tolerance_s):
        raise ValueError("ROOT170 RunPARTs final time differs from the requested terminal contract")
    actual_runparts_sha, _, _ = _stable_sha256(_path(args.runparts))
    if actual_runparts_sha != runparts_sha:
        raise ValueError("ROOT170 RunPARTs SHA differs from terminal proof")
    generated_xml = _path(args.generated_xml)
    expected_xml = request.get("source_provenance", {}).get("generated_xml")
    if isinstance(expected_xml, dict):
        expected_xml = expected_xml.get("path")
    if expected_xml is None:
        expected_xml = request.get("fine_generated_path_contract", {}).get("generated_xml")
        if isinstance(expected_xml, dict):
            expected_xml = expected_xml.get("path")
    if not expected_xml or generated_xml != _path(Path(str(expected_xml))):
        raise ValueError("fine generated XML is not the exact ROOT170 source-bound generated XML")
    expected_xml_sha = request.get("input_sha256", {}).get(str(generated_xml))
    if not expected_xml_sha:
        raise ValueError("ROOT170 request has no generated XML SHA binding")
    actual_xml_sha = _sha256(generated_xml)
    if actual_xml_sha != expected_xml_sha:
        raise ValueError("ROOT170 generated XML SHA differs from the request binding")
    summary_path = run_summary.get("path")
    if summary_path is None or _path(Path(str(summary_path))) != _path(args.runparts):
        raise ValueError("ROOT170 proof RunPARTs path does not match supplied RunPARTs")
    return {"request": request, "receipt": receipt, "proof": proof, "request_sha256": request_sha, "output_root": output_root, "request_output_root": request_output_root, "generated_xml_sha256": actual_xml_sha}


def _xml_source(generated_xml: Path) -> dict[str, Any]:
    root = ET.parse(_regular(generated_xml, "fine generated XML")).getroot()
    dp_values: list[float] = []
    for element in root.findall(".//constants/dp") + root.findall(".//definition"):
        raw = element.get("value") if element.tag == "dp" else element.get("dp")
        if raw is not None:
            try:
                dp_values.append(float(raw))
            except ValueError as exc:
                raise ValueError(f"generated XML has nonnumeric dp={raw!r}") from exc
    if not dp_values or any(not math.isclose(value, EXPECTED_DP_M, rel_tol=0.0, abs_tol=1.0e-12) for value in dp_values):
        raise ValueError(f"generated XML dp values are not the fine .003 source: {dp_values}")
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no execution particles section")
    fluid_counts: list[int] = []
    for fluid in particles.findall("fluid"):
        if fluid.get("count") is None:
            continue
        fluid_counts.append(int(fluid.get("count")))
    initial_fluid_count = sum(fluid_counts)
    if initial_fluid_count != EXPECTED_INITIAL_FLUID_COUNT:
        raise ValueError(f"generated XML initial fluid count {initial_fluid_count} != {EXPECTED_INITIAL_FLUID_COUNT}")
    return {"dp_values_m": dp_values, "initial_fluid_count": initial_fluid_count, "fluid_block_counts": fluid_counts}


def _root169_join(args: argparse.Namespace, request: dict[str, Any]) -> dict[str, Any]:
    proof_path = _path(args.root169_proof)
    report_path = _path(args.root169_report)
    binding = request.get("bi4_snapshot_binding") if isinstance(request.get("bi4_snapshot_binding"), dict) else {}
    expected_proof = binding.get("proof")
    if not expected_proof or proof_path != _path(Path(str(expected_proof))):
        raise ValueError("ROOT169 proof path does not match ROOT170 bi4_snapshot_binding")
    expected_proof_sha = binding.get("proof_sha256")
    if not isinstance(expected_proof_sha, str) or len(expected_proof_sha) != 64:
        raise ValueError("ROOT169 binding lacks a proof SHA")
    actual_proof_sha = _sha256(proof_path)
    if expected_proof_sha != actual_proof_sha:
        raise ValueError("ROOT169 proof SHA differs from ROOT170 binding")
    proof = _load_json(proof_path, "ROOT169 snapshot proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT169 proof is not actual")
    worker = proof.get("worker_source_snapshot")
    if not isinstance(worker, dict) or worker.get("sha256") != ROOT169_BI4_SHA or int(worker.get("bytes", 0)) != ROOT169_BI4_BYTES:
        raise ValueError("ROOT169 proof does not bind fine BI4 SHA/bytes")
    if proof.get("parent_actual_prepost_content_hashes_equal") is not True or proof.get("native_particle_fields_decoded") is not False:
        raise ValueError("ROOT169 proof scope/closure is not the source snapshot contract")
    if proof.get("report") is None or _path(Path(str(proof["report"]))) != report_path:
        raise ValueError("ROOT169 report path does not match proof")
    report_sha = _sha256(report_path)
    if proof.get("report_sha256") != report_sha:
        raise ValueError("ROOT169 report SHA does not match proof")
    return {"proof_path": str(proof_path), "proof_sha256": actual_proof_sha, "report_path": str(report_path), "report_sha256": report_sha, "bi4_sha256": ROOT169_BI4_SHA}


def _strict_source_join(args: argparse.Namespace) -> dict[str, Any]:
    terminal = _terminal_context(args)
    xml = _xml_source(args.generated_xml)
    root169 = _root169_join(args, terminal["request"])
    return {"terminal": terminal, "xml": xml, "root169": root169}


def _unknown(output: Path, reason: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "scope": {"selected_frames_only": True, "fine_grid_dp_m": EXPECTED_DP_M, "initial_fluid_count_expected": EXPECTED_INITIAL_FLUID_COUNT, "typed_conversion": "NOT_PERFORMED", "hdf5_read": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    V1.middle.base.atomic_json(_path(output), value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    strict = _strict_source_join(args)
    output = _path(args.output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable fine v2 observer output: {output}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.v1-adapter.json")
    delegated = argparse.Namespace(**vars(args))
    delegated.output = temporary
    try:
        value = V1.run(delegated)
        if not isinstance(value, dict) or value.get("status") != V1.PASS_STATUS:
            raise V1.middle.base.UnsupportedSemantics(f"fine v1 delegate did not PASS: {value.get('status') if isinstance(value, dict) else type(value).__name__}")
        observations = value.get("observations")
        if not isinstance(observations, list) or not observations:
            raise V1.middle.base.UnsupportedSemantics("fine delegate has no observations")
        initial_fields = observations[0].get("fluid_observable_using_native_header_mass", {})
        if initial_fields.get("fluid_count") != EXPECTED_INITIAL_FLUID_COUNT:
            raise V1.middle.base.UnsupportedSemantics("fine frame 0 native/XML-range fluid count is not 540000")
        for index, observation in enumerate(observations):
            header = observation.get("native_header", {})
            dp = header.get("Dp", {}).get("value") if isinstance(header.get("Dp"), dict) else None
            if dp is None or not math.isclose(float(dp), EXPECTED_DP_M, rel_tol=0.0, abs_tol=1.0e-12):
                raise V1.middle.base.UnsupportedSemantics(f"selected fine frame {index} native Dp is not .003")
        value["schema"] = SCHEMA
        value["status"] = PASS_STATUS
        value["scope"] = dict(value.get("scope", {}))
        value["scope"].update({"fine_grid_dp_m": EXPECTED_DP_M, "strict_terminal_source_join": True, "initial_fluid_count_expected": EXPECTED_INITIAL_FLUID_COUNT, "later_fluid_counts_are_observed_not_rewritten": True})
        value["strict_source_binding"] = {"ROOT170": {"solver_request_sha256": strict["terminal"]["request_sha256"], "output_root": str(strict["terminal"]["output_root"]), "generated_xml_sha256": strict["terminal"]["generated_xml_sha256"], "raw_root": str(_path(args.raw_root)), "runparts": str(_path(args.runparts))}, "ROOT169": strict["root169"], "generated_xml_source": strict["xml"]}
        value["fine_source_binding"] = {"dp_m": EXPECTED_DP_M, "initial_fluid_count": EXPECTED_INITIAL_FLUID_COUNT, "native_mass_role": "selected BI4 header MassFluid; discrete diagnostic only", "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM"}
        value["scientific_qualification"] = {"QI": "PASS_LIMITED_FINE_SELECTED_NATIVE_FIELDS_STRICT_SOURCE_JOIN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scope_note": "strict ROOT170 output/source join plus native Dp/.003 and frame-0 540000-fluid checks; later exclusions remain observed diagnostics"}
        V1.middle.base.atomic_json(output, value)
        return value
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if not V1.self_test().get("status") == "PASS":
        raise AssertionError("fine v1 delegate self-test failed")
    # A complete tiny ROOT162-shaped receipt/proof fixture exercises the
    # actual preflight path join.  It intentionally fails before any native
    # file is opened, using a wrong raw-root path.
    with tempfile.TemporaryDirectory(prefix="f3-fine-v2-selftest-") as tmp:
        root = _path(Path(tmp))
        request_path = root / "requests" / "root170.json"
        receipt_path = root / "attempt" / "execution-receipt.json"
        proof_path = root / "checkpoints" / "root170-proof.json"
        xml_path = root / "generated.xml"
        output_root = root / "attempt"
        request_path.parent.mkdir(parents=True)
        receipt_path.parent.mkdir(parents=True)
        proof_path.parent.mkdir(parents=True)
        xml_path.write_text(
            '<case><constants><dp value="0.003"/></constants>'
            '<execution><particles np="1"><fluid count="1"/></particles></execution></case>',
            encoding="utf-8",
        )
        request = {
            "schema": "ds02.stage2.external-solver-request.v5",
            "status": "READY_FOR_PARENT_GUARD",
            "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID,
            "storage_scope": {"output_root": str(output_root)},
            "source_provenance": {"generated_xml": str(xml_path)},
            "input_sha256": {str(xml_path): _sha256(xml_path)},
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        request_sha = _sha256(request_path)
        receipt = {
            "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
            "execution": {"returncode": 0},
            "filesystem": {"output_root": str(output_root)},
            "request": {"path": str(request_path), "sha256": request_sha},
        }
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        proof = {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "status": "VERIFIED_ACTUAL_ROOT162_SHAPED_FIXTURE",
            "request_sha256": request_sha,
            "receipt": str(receipt_path),
            "receipt_sha256": _sha256(receipt_path),
            # The production contract requires a producer-computed digest.  A
            # deliberately wrong digest is enough for this fixture because
            # the raw-root path rejection must happen before RunPARTs is read.
            "RunPARTs_summary": {"rows": 2, "sha256": "0" * 64, "final_time_s": 1.0},
        }
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        args = argparse.Namespace(
            solver_request=request_path, terminal_receipt=receipt_path, terminal_proof=proof_path,
            raw_root=root / "wrong-attempt" / "solver_output" / "data",
            runparts=output_root / "solver_output" / "RunPARTs.csv", generated_xml=xml_path,
        )
        try:
            _terminal_context(args)
        except ValueError as exc:
            if "raw root" not in str(exc):
                raise AssertionError(f"wrong-path fixture failed for the wrong reason: {exc}") from exc
        else:
            raise AssertionError("ROOT162-shaped wrong raw-root fixture was accepted")
    return {"status": "PASS", "schema": SCHEMA, "strict_terminal_output_join": True, "native_dp_check": EXPECTED_DP_M, "initial_fluid_count": EXPECTED_INITIAL_FLUID_COUNT, "payload_read": "parent_after_reservation_selected_frames", "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--root169-proof", type=Path)
    parser.add_argument("--root169-report", type=Path)
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
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--frames", type=int, nargs="+")
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=300.0)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=256 * 1024 * 1024)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.terminal_proof, args.root169_proof, args.root169_report, args.raw_root, args.runparts, args.generated_xml, args.decoder, args.decoder_source, args.calibration_contract, args.output, args.scratch_root, args.expected_frame_count, args.expected_final_time_s, args.frames, args.query_times)
    if any(value is None for value in required):
        parser.error("strict fine observer requires ROOT170/ROOT169 provenance and all v1 decoder arguments")
    try:
        result = run(args)
    except V1.middle.full.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr); return 143
    except V1.middle.base.UnsupportedSemantics as exc:
        try:
            result = _unknown(args.output, str(exc))
        except FileExistsError:
            print(str(exc), file=sys.stderr); return 2
        print(json.dumps({"status": result["status"], "output": str(_path(args.output))}, ensure_ascii=False)); return 2
    except Exception as exc:
        print(f"fine strict observer failed: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "output": str(_path(args.output)), "selected_frames": len(result.get("observations", []))}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
