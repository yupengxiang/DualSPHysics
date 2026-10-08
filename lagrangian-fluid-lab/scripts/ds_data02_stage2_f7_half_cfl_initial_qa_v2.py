#!/usr/bin/env python3
"""Prepare a bounded frame-0 QA request for the actual F7 half-CFL GenCase.

The GenCase output is real and its XML/count semantics are checked here, but
the half BI4 is eleven bytes different from the consumed baseline BI4.  This
forward builder therefore records BI4 stat only and leaves content hashing and
native decoding to one parent-approved CPU slot.  It binds the actual motion
file (6aed...), records GenCase's missing-copy warning and observed 16-thread
runtime, and refuses to turn XML counts into typed-array QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]
CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
HALF_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/f7-half-cfl-gencase-v8-001-root-001"
)
BASELINE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085"
)
MOTION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/root-stage1-f7-target030-065-actual-motion-preparation-074/"
    f"prepared/{CASE}/motion_obstacle_quintic.dat"
)
HALF_REQUEST = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/f7-half-cfl-v1/request-004/f7-s2-half-cfl-gencase-request-v8-001.json"
CURRENT = LAB / "campaigns/ds-data-02/stage2/CURRENT336.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-request.v2"
QA_SCHEMA = "ds02.stage2.f7-half-cfl-initial-qa.v2"
BASELINE_BI4_SHA = "f905a45f615304877f2a753471639bf812021d1741df7fcd4b5dc536b258864a"


class InitialQAError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InitialQAError(f"JSON object required: {path}")
    return value


def _stat(path: Path, *, content: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise InitialQAError(f"bound source is missing: {path}")
    value: dict[str, Any] = {"path": str(path), "bytes": path.stat().st_size,
                             "mtime_ns": path.stat().st_mtime_ns}
    if content:
        value["sha256"] = sha256_file(path)
        value["content_scope"] = "source_content"
    else:
        value["sha256"] = None
        value["content_scope"] = "PARENT_GUARD_CONTENT_HASH_REQUIRED"
    return value


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _xml_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = root.find("./casedef/constantsdef")
    definition = root.find("./casedef/geometry/definition")
    particles = root.find("./execution/particles")
    params = {item.get("key"): _float(item.get("value"))
              for item in root.findall("./execution/parameters/parameter")
              if item.get("key")}
    cfl = None
    if constants is not None:
        value = constants.find("cflnumber")
        cfl = _float(value.get("value")) if value is not None else None
    particle_blocks: dict[str, Any] = {}
    if particles is not None:
        particle_blocks = {key: int(particles.get(key)) for key in ("np", "nb", "nbf")
                           if particles.get(key) is not None}
        for name in ("fixed", "moving", "fluid"):
            item = particles.find(name)
            if item is not None:
                particle_blocks[name] = {
                    "count": int(item.get("count")), "mk": int(item.get("mk", item.get("mkbound", item.get("mkfluid", "-1"))))
                }
    motion = root.find("./casedef/motion/objreal/mvrotfile")
    motion_file = motion.find("file") if motion is not None else None
    return {
        "cflnumber": cfl,
        "dp_m": _float(definition.get("dp")) if definition is not None else None,
        "parameters": params,
        "particles": particle_blocks,
        "motion": {
            "objreal_ref": root.find("./casedef/motion/objreal").get("ref") if root.find("./casedef/motion/objreal") is not None else None,
            "duration_s": _float(motion.get("duration")) if motion is not None else None,
            "file_name": motion_file.get("name") if motion_file is not None else None,
        },
    }


def _binding(path: Path, role: str, *, content: bool = True) -> dict[str, Any]:
    value = _stat(path, content=content)
    value["role"] = role
    return value


def build(output_dir: Path | str) -> dict[str, Any]:
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    old_request = load_json(HALF_REQUEST)
    gencase_receipt = HALF_ROOT / "execution-receipt.json"
    gencase_stdout = HALF_ROOT / "stdout.log"
    half_xml = HALF_ROOT / "prepared" / f"{CASE}_half_cfl01.xml"
    half_bi4 = HALF_ROOT / "prepared" / f"{CASE}_half_cfl01.bi4"
    baseline_xml = BASELINE_ROOT / "prepared" / f"{CASE}.xml"
    baseline_bi4 = BASELINE_ROOT / "prepared" / f"{CASE}.bi4"
    for path in (gencase_receipt, gencase_stdout, half_xml, half_bi4, baseline_xml, baseline_bi4, MOTION, DECODER, CURRENT):
        if not path.is_file():
            raise InitialQAError(f"required source is missing: {path}")
    receipt = load_json(gencase_receipt)
    if receipt.get("status") != "completed" or receipt.get("request", {}).get("attempt_id") != "f7-half-cfl-gencase-v8-001-root-001":
        raise InitialQAError("actual half GenCase receipt is not the bound completed attempt")
    half_semantics = _xml_semantics(half_xml)
    baseline_semantics = _xml_semantics(baseline_xml)
    observed_warnings = [line.strip() for line in gencase_stdout.read_text(errors="replace").splitlines()
                         if "WARNING" in line or "not found to copy" in line]
    stdout_text = gencase_stdout.read_text(errors="replace")
    omp = re.search(r"OmpThreads:\s*(\d+)", stdout_text)
    observed_threads = int(omp.group(1)) if omp else None
    requested_threads = int(receipt.get("request", {}).get("cpu_threads", -1))
    if half_bi4.stat().st_size == baseline_bi4.stat().st_size:
        raise InitialQAError("fixture no longer represents the known distinct half/baseline BI4 pair")
    motion_sha = sha256_file(MOTION)
    old_variant_motion_sha = old_request.get("variant_contract", {}).get("motion_sha256")
    qa: dict[str, Any] = {
        "schema": QA_SCHEMA,
        "status": "PENDING_INITIAL_TYPED_QA",
        "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": CASE,
        "gencase": {
            "receipt": _binding(gencase_receipt, "half_cfl_gencase_receipt"),
            "stdout": _binding(gencase_stdout, "half_cfl_gencase_stdout"),
            "status": receipt.get("status"),
            "requested_cpu_threads": requested_threads,
            "observed_omp_threads": observed_threads,
            "thread_contract_status": "MISMATCH_OBSERVED" if observed_threads != requested_threads else "MATCH",
            "warnings": observed_warnings,
        },
        "source": {
            "current": _binding(CURRENT, "CURRENT336"),
            "half_definition": _binding(Path(str(old_request["input_files"][1])), "half_cfl_definition"),
            "motion": _binding(MOTION, "F7_motion_control"),
            "motion_hash_provenance": {
                "actual_input_sha256": motion_sha,
                "old_request_variant_contract_sha256": old_variant_motion_sha,
                "old_request_variant_contract_mismatch": old_variant_motion_sha != motion_sha,
                "binding_rule": "actual receipt/input path SHA wins; stale variant field cannot be used",
            },
            "decoder": _binding(DECODER, "pinned_native_bi4_decoder"),
        },
        "generated": {
            "half_xml": _binding(half_xml, "half_generated_xml"),
            "half_bi4": _binding(half_bi4, "half_generated_bi4", content=False),
            "baseline_xml": _binding(baseline_xml, "baseline_generated_xml"),
            "baseline_bi4": {**_binding(baseline_bi4, "baseline_generated_bi4", content=False),
                             "producer_guard_attested_sha256": BASELINE_BI4_SHA},
        },
        "xml_semantics": {"half": half_semantics, "baseline": baseline_semantics},
        "xml_comparison": {
            "same_initial_particle_intent": all(
                half_semantics["particles"].get(key) == baseline_semantics["particles"].get(key)
                for key in ("np", "nb", "nbf", "fixed", "moving", "fluid")
            ),
            "same_dp_m": half_semantics["dp_m"] == baseline_semantics["dp_m"],
            "half_cfl_is_0p1": half_semantics["cflnumber"] == 0.1,
            "baseline_cfl_is_0p2": baseline_semantics["cflnumber"] == 0.2,
            "same_motion_file_name": half_semantics["motion"]["file_name"] == baseline_semantics["motion"]["file_name"],
            "typed_arrays_compared": False,
        },
        "qualification": dict(UNKNOWN),
        "limitations": [
            "XML/count agreement is initial intent only; it is not typed-array QA.",
            "Half and baseline BI4 sizes differ (3089317 vs 3089306); parent must hash/decode both in a bounded CPU slot.",
            "GenCase stdout reports two missing motion-file copy warnings; solver launch requires a staged motion file bound to the actual 6aed... SHA.",
            "GenCase requested two CPU threads but stdout observed OmpThreads=16; this control mismatch must be resolved or explicitly accounted before solver launch.",
            "No HDF5/BI4 content was opened by this builder; no QI/QN/QE credit is granted.",
        ],
    }
    qa["sha256"] = canonical_sha(qa)
    qa_path = output_dir / "f7-s2-half-cfl-initial-qa-v2-001.json"
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PENDING_PARENT_IO_SLOT",
        "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": CASE,
        "qa_evidence": {"path": str(qa_path), "sha256": qa["sha256"], "immutable": True},
        "inputs": {
            "half_bi4": _binding(half_bi4, "half_generated_bi4", content=False),
            "baseline_bi4": {**_binding(baseline_bi4, "baseline_generated_bi4", content=False),
                             "producer_guard_attested_sha256": BASELINE_BI4_SHA},
            "half_xml": _binding(half_xml, "half_generated_xml"),
            "baseline_xml": _binding(baseline_xml, "baseline_generated_xml"),
            "motion": _binding(MOTION, "F7_motion_control"),
            "decoder": _binding(DECODER, "pinned_native_bi4_decoder"),
        },
        "compare_contract": {
            "decode_scope": "frame0/header/identity only",
            "fields": ["CaseNp", "Dp", "B", "Rhop0", "MassBound", "MassFluid", "Zone", "Idp", "type", "mk", "mass", "position", "valid"],
            "identity_key": "(Zone,Idp)",
            "expected_particle_count": 70179,
            "expected_mk_counts": {"fixed_mk10": 27495, "moving_mk12": 1984, "fluid_mk2": 40700},
            "invalid_or_missing_identity": "FAIL; never substitute XML counts",
            "half_bi4_content_hash": "PARENT_GUARD_REQUIRED",
            "baseline_bi4_content_hash": BASELINE_BI4_SHA,
            "motion_source_must_be_staged_before_solver": True,
        },
        "resource_request": {
            "cpu_threads": 1, "max_wall_seconds": 900,
            "max_rss_bytes": 8 * 1024**3, "new_storage_budget_bytes": 2 * 1024**3,
            "gpu": False, "hdf5": False, "solver": False, "cfd": False,
            "bi4_read": "two frame-0 decodes only after parent guard approves",
        },
        "execution": {
            "command_template": [str(DECODER), "<half_or_baseline_bi4>", "<fresh_absent_decode_prefix>"],
            "fresh_output_required": True,
            "no_original_path_fallback": True,
            "model_invoked": False, "cfd_invoked": False,
        },
        "launch_allowed": False,
        "qualification": dict(UNKNOWN),
        "limitations": qa["limitations"],
    }
    request["sha256"] = canonical_sha(request)
    request_path = output_dir / "f7-s2-half-cfl-initial-typed-qa-request-v2-001.json"
    return {"qa": qa, "qa_path": qa_path, "request": request, "request_path": request_path}


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise InitialQAError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output_dir)
    write_new(result["qa_path"], result["qa"])
    write_new(result["request_path"], result["request"])
    print(json.dumps({"qa": str(result["qa_path"]), "qa_sha256": result["qa"]["sha256"],
                      "request": str(result["request_path"]), "request_sha256": result["request"]["sha256"],
                      "status": result["request"]["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
