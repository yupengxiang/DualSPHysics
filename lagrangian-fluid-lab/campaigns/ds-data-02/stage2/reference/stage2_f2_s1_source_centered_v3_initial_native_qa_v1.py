#!/usr/bin/env python3
"""Parent-guarded initial-frame QA for one F2 source-centred V3 GenCase.

This worker is intentionally generic over the three V3 rungs.  It consumes a
completed GenCase ``generated.xml``/``generated.bi4`` pair only when the
parent enables the deferred request.  It decodes frame zero with the existing
source-grounded GenCase adapter, checks XML ID ranges and finite fields, and
reports the whole-initial continuum-owner mass gate plus per-MK diagnostics.
The historical 21.114 kg discrete CURRENT sample remains a labelled
diagnostic; it is never used as the V3 continuum acceptance denominator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.source-centered-v3.initial-native-qa.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
ADAPTER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_generated_initial_observer_v1.py"
DECODER_SOURCE_DEFAULT = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
PERIODIC_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPeriodicDef.h")
PERIODIC_BI4_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
PERIODIC_BI4_SOURCE = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")
OWNER_MASS_KG = 18.876
DISCRETE_DIAGNOSTIC_KG = 21.114
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {path}")
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "device": int(value.st_dev), "inode": int(value.st_ino),
            "mode": int(value.st_mode), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "nlink": int(value.st_nlink)}


def stable_record(path: Path, label: str) -> dict[str, Any]:
    before = stat_record(path, label)
    digest = sha256_file(path)
    after = stat_record(path, label)
    if before != after:
        raise RuntimeError(f"{label} changed during hash")
    return {**after, "sha256": digest, "stat_before": before, "stat_after": after}


def record(path: Path, label: str) -> dict[str, Any]:
    return stable_record(path, label)


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable QA output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def load_adapter() -> Any:
    name = "ds02_f2_source_centered_v3_generated_adapter"
    spec = importlib.util.spec_from_file_location(name, ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mass_gate(mass_kg: float) -> dict[str, Any]:
    fraction = (mass_kg - OWNER_MASS_KG) / OWNER_MASS_KG
    absolute = abs(fraction)
    return {
        "sample_mass_kg": mass_kg,
        "whole_initial_continuum_owner_mass_target_kg": OWNER_MASS_KG,
        "relative_fraction": fraction,
        "relative_percent": 100.0 * fraction,
        "preferred_gate": "PASS" if absolute <= 0.01 else "NOT_PASS",
        "marginal_gate": "MARGINAL" if 0.01 < absolute <= 0.02 else ("PASS" if absolute <= 0.01 else "NOT_PASS"),
        "hard_gate": absolute > 0.02,
        "mass_rescale": False,
        "historical_discrete_sample_diagnostic_kg": DISCRETE_DIAGNOSTIC_KG,
        "historical_discrete_sample_role": "diagnostic only; not continuum owner acceptance",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    generated_xml = args.generated_xml.expanduser().resolve()
    generated_bi4 = args.generated_bi4.expanduser().resolve()
    receipt_path = args.gencase_receipt.expanduser().resolve()
    candidate_def = args.candidate_def.expanduser().resolve()
    source_def = args.source_def.expanduser().resolve()
    source_motion = args.source_motion.expanduser().resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    request = receipt.get("request", {})
    receipt_checks = {
        "status_completed": receipt.get("status") == "completed",
        "returncode_zero": receipt.get("returncode") == 0,
        "cpu_task_kind_gencase": request.get("cpu_task_kind") == "gencase",
        "case_id": request.get("case_id") == args.case_id,
    }
    if not all(receipt_checks.values()):
        raise RuntimeError(f"GenCase receipt identity/status failed: {receipt_checks}")
    adapter = load_adapter()
    source = adapter.parse_source_xml(generated_xml)
    blocks = source["blocks"]
    fluid_count = sum(int(block["count"]) for block in blocks if block["kind"] == "fluid")
    total_count = sum(int(block["count"]) for block in blocks)
    if fluid_count != args.expected_fluid_count:
        raise RuntimeError(f"actual XML fluid count {fluid_count} != registered {args.expected_fluid_count}")
    if args.expected_total_count is not None and total_count != args.expected_total_count:
        raise RuntimeError(f"actual XML total count {total_count} != registered {args.expected_total_count}")
    periodic = adapter.gencase_periodic_contract(generated_xml, receipt)
    native_pre = stable_record(generated_bi4, "F2 V3 generated BI4 pre-decode")
    decoder_source = args.decoder_source.expanduser().resolve()
    decoder_contract = adapter.decoder_source_contract(decoder_source)
    if decoder_contract.get("status") != "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT":
        raise RuntimeError("official decoder source contract is not proven")
    semantic_tests = adapter.manufactured_generated_semantic_selftests()
    if semantic_tests.get("status") != "PASS":
        raise RuntimeError("generated-frame semantic self-tests failed")
    decoded = adapter.decode_generated_frame(generated_bi4, args.decoder.expanduser().resolve(), args.scratch_root.expanduser().resolve(), 0, periodic)
    native_post = stable_record(generated_bi4, "F2 V3 generated BI4 post-decode")
    if native_pre["sha256"] != native_post["sha256"] or native_pre["bytes"] != native_post["bytes"] or native_pre["stat_after"] != native_post["stat_before"] or native_pre["stat_before"] != native_post["stat_after"]:
        raise RuntimeError("generated BI4 changed across decode")
    if decoded["saved_file"]["sha256"] != native_pre["sha256"] or decoded["saved_file"]["bytes"] != native_pre["bytes"]:
        raise RuntimeError("decoder-reported generated BI4 differs from guarded source")
    ids = decoded["ids"]
    expected_ids = adapter.np.arange(total_count, dtype=ids.dtype)
    if ids.size != total_count or not adapter.np.array_equal(ids, expected_ids):
        raise RuntimeError("decoded IDs do not exactly cover generated XML begin/count ranges")
    kind, mkfluid, mk_absolute = adapter.assign_particle_ranges(ids, blocks)
    fluid = kind == "fluid"
    if int(fluid.sum()) != fluid_count:
        raise RuntimeError("decoded fluid mask differs from generated XML")
    if not (adapter.np.isfinite(decoded["position"]).all() and adapter.np.isfinite(decoded["velocity"]).all() and adapter.np.isfinite(decoded["density"]).all()):
        raise RuntimeError("decoded initial fields contain NaN/Inf")
    massfluid = source["constants"].get("massfluid_kg")
    if massfluid is None:
        raise RuntimeError("generated XML has no massfluid")
    sample_mass = float(fluid_count) * float(massfluid)
    per_mk: list[dict[str, Any]] = []
    for absolute in sorted(set(int(value) for value in mk_absolute[fluid].tolist())):
        mask = fluid & (mk_absolute == absolute)
        per_mk.append({"mk_absolute": absolute, "particle_count": int(mask.sum()), "sample_mass_kg": float(mask.sum()) * float(massfluid), "relative_to_owner_layer_mass": (float(mask.sum()) * float(massfluid)) / (OWNER_MASS_KG / 3.0) - 1.0})
    audit = mass_gate(sample_mass)
    status = "PASS_INITIAL_NATIVE_FIELDS_CONTINUUM_MASS" if audit["preferred_gate"] == "PASS" else ("MARGINAL_INITIAL_NATIVE_FIELDS_CONTINUUM_MASS" if not audit["hard_gate"] else "FAIL_INITIAL_NATIVE_FIELDS_CONTINUUM_MASS")
    return {
        "schema": SCHEMA, "status": status, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {"family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": args.physical_case_id, "candidate_case_id": args.case_id, "candidate_attempt_id": args.attempt_id, "rung": args.rung_token},
        "scope": {"native_initial_frame_only": True, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "full_time_scan": False, "full_native_tree_scan": False},
        "source": {"candidate_def": record(candidate_def, "candidate Def"), "source_def": record(source_def, "source Def"), "source_motion": record(source_motion, "source motion"), "generated_xml": record(generated_xml, "generated XML"), "gencase_receipt": record(receipt_path, "GenCase receipt"), "decoder": record(args.decoder.expanduser().resolve(), "official decoder"), "decoder_source": decoder_contract, "periodic_contract": periodic},
        "native_source_integrity": {"status": "PASS_PRE_POST_SHA_AND_COMPLETE_STAT", "pre_decode": native_pre, "post_decode": native_post, "sha_equal": True, "cross_decode_stat_equal": True},
        "decoded_identity": {"particle_count": int(ids.size), "fluid_count": int(fluid.sum()), "xml_particle_count": total_count, "xml_fluid_count": fluid_count, "id_exact_xml_begin_count": True, "mkfluid_relative_values": sorted(set(int(value) for value in mkfluid[fluid].tolist())), "mk_absolute_values": sorted(set(int(value) for value in mk_absolute[fluid].tolist()))},
        "decoded_frame": {"time_s": decoded["decoded_time_s"], "field_digest_sha256": decoded["field_digest_sha256"], "dynamic_semantics": decoded["dynamic_semantics"], "position_dtype": decoded["position_dtype"]},
        "sample_mass_audit": {**audit, "massfluid_kg": float(massfluid), "per_mk": per_mk},
        "source_control_audit": {"candidate_definition_dp_m": args.expected_dp, "candidate_definition_and_motion_verified_by_worker": True, "drawboxes_and_execution_control": "candidate Def is additive source-derived; QA does not rewrite it"},
        "scientific_qualification": UNKNOWN,
    }


def self_test() -> dict[str, Any]:
    assert mass_gate(18.876)["preferred_gate"] == "PASS"
    assert mass_gate(21.114)["hard_gate"]
    return {"status": "PASS", "continuum_mass_denominator_kg": OWNER_MASS_KG, "discrete_diagnostic_not_gate": True, "native_payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--generated-bi4", type=Path)
    parser.add_argument("--gencase-receipt", type=Path)
    parser.add_argument("--candidate-def", type=Path)
    parser.add_argument("--source-def", type=Path)
    parser.add_argument("--source-motion", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path, default=DECODER_SOURCE_DEFAULT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--physical-case-id", default="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090")
    parser.add_argument("--case-id", required=False)
    parser.add_argument("--attempt-id", required=False)
    parser.add_argument("--rung-token", required=False)
    parser.add_argument("--expected-dp", type=float, required=False)
    parser.add_argument("--expected-fluid-count", type=int, required=False)
    parser.add_argument("--expected-total-count", type=int, required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.generated_bi4, args.gencase_receipt, args.candidate_def, args.source_def, args.source_motion, args.decoder, args.output, args.scratch_root, args.case_id, args.attempt_id, args.rung_token, args.expected_dp, args.expected_fluid_count]
    if any(value is None for value in required):
        parser.error("all GenCase/QA arguments are required unless --self-test")
    try:
        value = run(args)
        atomic_json(args.output, value)
    except Exception as exc:
        print(json.dumps({"status": "FAIL_SOURCE_CENTERED_V3_INITIAL_NATIVE_QA", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve()), "qualification": UNKNOWN}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
