#!/usr/bin/env python3
"""Bind Root129's actual 51-frame XMF to a disabled F5 bed-audit request.

This source-only binder reads JSON/XML metadata and file hashes.  It never
opens the trajectory H5 datasets, BI4 files, CSV arrays, or starts a worker.
The copied bed worker is Root-owned and is the only component that may read
the actual particle arrays.  The request remains disabled because a short
bed audit is diagnostic evidence and cannot authorize the full16 run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


BASE = Path(__file__).resolve().parents[1]
FRESH066 = BASE.parent / "root_followup_066_stage1_a061_short_event_native093_nvme_typed_bed_audit_v2"
ROOT061 = BASE.parent / "root_followup_061_stage1_native_bed_repair_candidate_a_strict_v1"
CASE = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061"
)
ROOT129 = CASE / "root-stage1-f5-short51-normal-dynamic-129"
GENCASE_ROOT = CASE / "root-stage1-f5-explicit-bed-repair-a-genuine-gencase-075"
QA_ROOT = CASE / "root-stage1-f5-explicit-bed-repair-a-native-qa-083"
SHORT_ROOT = CASE / "root-stage1-f5-explicit-bed-repair-a-short-event-native-093"
TYPED_ROOT = CASE / "root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")

SOURCE_PLAN_SHA = "268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c"
CANONICAL_SHA = "d4a165e67b16f4f4871aa8a37eaf7cef6c08796cbf644cf2c9e101af9f84fbb7"
GENCASE_RECEIPT_SHA = "6a9cc4bb55ccea1fe4266a8c923027492512a1949d0f3041f553a8f73e636ed6"
QA_RECEIPT_SHA = "1417058bf9204284d1d8a2bd285c606e7c0a69aaccc9112f233c0427d2ae9a4a"
QA_REPORT_SHA = "87bf5f1cfcc8846f046d63bcfe16f0ec13a3eaaefafb3e9833de08d6ae818967"
SHORT_RECEIPT_SHA = "141c389666d669920296938a471b308ed67548629568e4cd941f599b76bc6af3"
TYPED_RECEIPT_SHA = "9119684bf4ef93b4f40dded190fbc473a6a1919b8fb06fe6e027709b090f2dcd"
CONVERSION_REPORT_SHA = "eeeebc983411d29c97dab30f0f61d6ec9d2969e20bf67a5489e3923fd3c1bbcf"
TRAJECTORY_H5_SHA = "bf8f8767a9f348abb269e56b46d6a4eee2781f10360ac9217733bc9837a81d31"
ROOT129_RECEIPT_SHA = "b04bc8b14db78db2d9484e5463755f86c3d49a9db699eff31ea59e414952f120"
ROOT129_MANIFEST_SHA = "f46947df8ed9bd28d33331808b0975c98205e738a259c8ae2deb2f32d5d6ed60"
ROOT129_XMF_SHA = "cda1bf4f448226ebb6b2d9e2c6023ab86ff5cafdd1093cabcb7f6388d7d413de"

EXPECTED_FRAMES = 51
EXPECTED_PARTICLES = 214385
EXPECTED_FLUID = 40710
PROFILE_NODES = [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448], [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]]
BED_X = [-0.2, 4.8]
BED_Y = [-0.15, 0.15]
DEPTH_BINS = [0.02, 0.04]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: Mapping[str, Any], force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path}; use --force")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_paths() -> dict[str, Path]:
    prepared = GENCASE_ROOT / "prepared"
    return {
        "manifest": BASE / "manifest.json",
        "binding_template": BASE / "bed-audit-binding-template.json",
        "request_template": BASE / "bed-audit-request-template.json",
        "owner": BASE / "owner-metadata.json",
        "worker": BASE / "workers/bed_audit.py",
        "root129_receipt": ROOT129 / "execution-receipt.json",
        "root129_manifest": ROOT129 / "manifest.json",
        "root129_xmf": ROOT129 / "case.xmf",
        "gencase_receipt": GENCASE_ROOT / "execution-receipt.json",
        "gencase_root": GENCASE_ROOT,
        "qa_receipt": QA_ROOT / "execution-receipt.json",
        "qa_root": QA_ROOT,
        "qa_report": QA_ROOT / "initial-qa/a061-native-initial-qa.json",
        "short_receipt": SHORT_ROOT / "execution-receipt.json",
        "short_root": SHORT_ROOT,
        "typed_receipt": TYPED_ROOT / "execution-receipt.json",
        "conversion_report": TYPED_ROOT / "conversion-report.json",
        "trajectory_h5": TYPED_ROOT / "trajectory.h5",
        "prepared_xml": prepared / "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061.xml",
        "motion": prepared / "assets/f5_compact_packet_motion.dat",
        "source_definition": ROOT061 / "candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_Def.xml",
        "source_binding": ROOT061 / "physical-binding.json",
        "source_chain": ROOT061 / "strict-source-chain.json",
        "candidate_patch": ROOT061 / "candidate_a_patch.json",
        "gencase_binding": ROOT061 / "gencase-binding.json",
        "root037_ledger": ROOT061 / "root037_failure_ledger_summary.json",
        "runtime": INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        "strict_dispatch": INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        "bed_root": CASE / "root-stage1-f5-short51-normal-dynamic-bed-audit-068",
    }


def validate_receipt(path: Path, label: str, expected_root: Path | None = None) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    value = load(path)
    require(value.get("status") == "completed", f"{label} is not completed")
    require(value.get("returncode") == 0, f"{label} returncode is not zero")
    if expected_root is not None:
        require(Path(str(value.get("output_root", ""))).resolve() == expected_root.resolve(), f"{label} output root mismatch")
    return value


def validate_base(paths: Mapping[str, Path]) -> dict[str, Any]:
    manifest = load(paths["manifest"])
    require(manifest.get("schema") == "ds02.f5.a061.fresh068.root129-xmf-bed-audit-manifest.v1", "fresh068 manifest schema mismatch")
    require(manifest.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA, "source-plan hash mismatch")
    require(manifest.get("canonical_conversion_physical_condition_sha256") == CANONICAL_SHA, "canonical hash mismatch")
    require(manifest.get("physical_condition_hash_match") is False, "source/canonical hash distinction collapsed")

    gencase = validate_receipt(paths["gencase_receipt"], "actual075 GenCase", paths["gencase_root"])
    require(sha(paths["gencase_receipt"]) == GENCASE_RECEIPT_SHA, "actual075 receipt hash mismatch")
    require(gencase.get("total_particles") == EXPECTED_PARTICLES and gencase.get("fluid_particles") == EXPECTED_FLUID, "actual075 particle metadata mismatch")
    require(gencase.get("solver_dimension_from_gencase") == 3, "actual075 is not 3-D")

    qa_receipt = validate_receipt(paths["qa_receipt"], "actual083 QA", paths["qa_root"])
    require(sha(paths["qa_receipt"]) == QA_RECEIPT_SHA, "actual083 receipt hash mismatch")
    qa_report = load(paths["qa_report"])
    require(sha(paths["qa_report"]) == QA_REPORT_SHA and qa_report.get("all_actual_checks_pass") is True, "actual083 QA report mismatch")

    short = validate_receipt(paths["short_receipt"], "actual093 short solver", paths["short_root"])
    require(sha(paths["short_receipt"]) == SHORT_RECEIPT_SHA, "actual093 receipt hash mismatch")
    require(short.get("request", {}).get("attempt_id") == "root-stage1-f5-explicit-bed-repair-a-short-event-native-093", "actual093 attempt mismatch")
    require("-tmax:1.0" in short.get("command", []) and "-tout:0.02" in short.get("command", []), "actual093 command mismatch")

    typed = validate_receipt(paths["typed_receipt"], "actual065 typed conversion", TYPED_ROOT)
    require(sha(paths["typed_receipt"]) == TYPED_RECEIPT_SHA, "actual065 receipt hash mismatch")
    require(typed.get("request", {}).get("attempt_id") == "root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065", "actual065 attempt mismatch")
    conversion = load(paths["conversion_report"])
    require(sha(paths["conversion_report"]) == CONVERSION_REPORT_SHA, "conversion report hash mismatch")
    require(conversion.get("conversion_status") == "completed", "conversion is not completed")
    require(conversion.get("frames") == EXPECTED_FRAMES and conversion.get("particles") == EXPECTED_PARTICLES, "conversion frame/particle metadata mismatch")
    require(conversion.get("solver_dimension", {}).get("solver_dimension") == 3, "conversion is not 3-D")
    require(str(conversion.get("output_hdf5", "")).endswith("trajectory.h5"), "conversion H5 output metadata missing")
    require(paths["trajectory_h5"].is_file(), "typed065 trajectory H5 missing")

    receipt = validate_receipt(paths["root129_receipt"], "Root129 XMF receipt", ROOT129)
    require(sha(paths["root129_receipt"]) == ROOT129_RECEIPT_SHA, "Root129 receipt hash mismatch")
    root_request = receipt.get("request", {})
    require(root_request.get("attempt_id") == "root-stage1-f5-short51-normal-dynamic-129", "Root129 attempt mismatch")
    require(root_request.get("expected_frames") == EXPECTED_FRAMES and root_request.get("expected_particles") == EXPECTED_PARTICLES, "Root129 receipt frame/particle metadata mismatch")
    require(root_request.get("full16_authorized") is False, "Root129 receipt authorizes full16")
    require(root_request.get("canonical_conversion_physical_condition_sha256") == CANONICAL_SHA, "Root129 canonical hash mismatch")
    require(root_request.get("declared_campaign_physical_condition_sha256") == SOURCE_PLAN_SHA, "Root129 source-plan hash mismatch")

    root_manifest = load(paths["root129_manifest"])
    require(sha(paths["root129_manifest"]) == ROOT129_MANIFEST_SHA, "Root129 manifest hash mismatch")
    require(root_manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "Root129 manifest schema mismatch")
    require(root_manifest.get("expected_frames") == EXPECTED_FRAMES and root_manifest.get("expected_particles") == EXPECTED_PARTICLES, "Root129 manifest frame/particle metadata mismatch")
    require(root_manifest.get("physical_condition_sha256") == CANONICAL_SHA, "Root129 manifest canonical hash mismatch")
    require(root_manifest.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA, "Root129 manifest source-plan hash mismatch")
    require(root_manifest.get("physical_condition_hash_match") is False, "Root129 manifest collapses hash distinction")
    require(root_manifest.get("trajectory_h5_sha256") == TRAJECTORY_H5_SHA, "Root129 H5 provenance hash mismatch")
    require(root_manifest.get("xdmf_sha256") == ROOT129_XMF_SHA, "Root129 XMF manifest hash mismatch")
    require(root_manifest.get("time_axis_policy", {}).get("uniform_spacing_assumption") is False, "Root129 time policy assumes equal spacing")
    actual_times = root_manifest.get("actual_time_s")
    require(isinstance(actual_times, list) and len(actual_times) == EXPECTED_FRAMES, "Root129 actual time metadata is not 51 values")
    require(all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in actual_times), "Root129 actual times are nonfinite")
    require(actual_times[0] == 0.0 and actual_times[-1] >= 1.0 and all(b > a for a, b in zip(actual_times, actual_times[1:])), "Root129 actual time axis is not monotonic 0..1 s")
    require(paths["root129_xmf"].is_file(), "Root129 case.xmf missing")
    require(sha(paths["root129_xmf"]) == ROOT129_XMF_SHA, "Root129 case.xmf hash mismatch")
    xmf_root = ET.parse(paths["root129_xmf"]).getroot()
    xmf_times = [float(node.attrib["Value"]) for node in xmf_root.iter("Time")]
    require(len(xmf_times) == EXPECTED_FRAMES, "Root129 XMF has no 51 Time nodes")
    require(all(math.isfinite(value) for value in xmf_times) and all(b > a for a, b in zip(xmf_times, xmf_times[1:])), "Root129 XMF times are nonfinite or nonmonotonic")
    require(all(abs(a - b) <= 1.0e-12 for a, b in zip(xmf_times, actual_times)), "Root129 XMF times differ from manifest actual_time_s")

    for key in ("owner", "worker", "prepared_xml", "motion", "source_definition", "source_binding", "source_chain", "candidate_patch", "gencase_binding", "runtime", "strict_dispatch"):
        require(paths[key].is_file(), f"source input missing: {paths[key]}")

    return {
        "gencase_receipt": str(paths["gencase_receipt"].resolve()),
        "gencase_receipt_sha256": sha(paths["gencase_receipt"]),
        "initial_qa_receipt": str(paths["qa_receipt"].resolve()),
        "initial_qa_receipt_sha256": sha(paths["qa_receipt"]),
        "initial_qa_report": str(paths["qa_report"].resolve()),
        "initial_qa_report_sha256": sha(paths["qa_report"]),
        "short_solver_receipt": str(paths["short_receipt"].resolve()),
        "short_solver_receipt_sha256": sha(paths["short_receipt"]),
        "typed_receipt": str(paths["typed_receipt"].resolve()),
        "typed_receipt_sha256": sha(paths["typed_receipt"]),
        "native_receipt": str(paths["short_receipt"].resolve()),
        "native_receipt_sha256": sha(paths["short_receipt"]),
        "native_conversion_report": str(paths["conversion_report"].resolve()),
        "native_conversion_report_sha256": sha(paths["conversion_report"]),
        "trajectory_h5": str(paths["trajectory_h5"].resolve()),
        "trajectory_h5_sha256": TRAJECTORY_H5_SHA,
        "xmf_receipt": str(paths["root129_receipt"].resolve()),
        "xmf_receipt_sha256": sha(paths["root129_receipt"]),
        "xdmf": str(paths["root129_xmf"].resolve()),
        "xdmf_sha256": sha(paths["root129_xmf"]),
        "xmf_manifest": str(paths["root129_manifest"].resolve()),
        "xmf_manifest_sha256": sha(paths["root129_manifest"]),
        "actual_time_s": actual_times,
        "time_axis_policy": {
            "source": "Root129 manifest actual_time_s and case.xmf Time/@Value",
            "preserve_actual_values": True,
            "uniform_spacing_assumption": False,
            "nominal_save_interval_s": 0.02,
            "first_s": float(actual_times[0]),
            "last_s": float(actual_times[-1]),
            "min_actual_step_s": min(b - a for a, b in zip(actual_times, actual_times[1:])),
            "max_actual_step_s": max(b - a for a, b in zip(actual_times, actual_times[1:])),
            "actual_time_s": actual_times,
        },
    }


def input_files(paths: Mapping[str, Path], binding_path: Path) -> list[Path]:
    return [
        BASE / "manifest.json",
        BASE / "bed-audit-binding-template.json",
        BASE / "bed-audit-request-template.json",
        paths["worker"],
        binding_path,
        paths["owner"],
        paths["root129_receipt"],
        paths["root129_manifest"],
        paths["root129_xmf"],
        paths["gencase_receipt"],
        paths["qa_receipt"],
        paths["qa_report"],
        paths["short_receipt"],
        paths["typed_receipt"],
        paths["conversion_report"],
        paths["trajectory_h5"],
        paths["prepared_xml"],
        paths["motion"],
        paths["source_definition"],
        paths["source_binding"],
        paths["source_chain"],
        paths["candidate_patch"],
        paths["gencase_binding"],
        paths["runtime"],
        paths["strict_dispatch"],
    ]


def bind(paths: Mapping[str, Path], output_dir: Path, force: bool) -> dict[str, Any]:
    actual = validate_base(paths)
    binding = load(paths["binding_template"])
    binding.update(actual)
    binding.update(
        {
            "bound_status": "root-bound-after-actual-root129-xmf",
            "bound_by": "fresh068/scripts/bind_root129_bed_audit.py",
            "full16_authorized": False,
            "q_n_granted": False,
            "production_approval": "none",
            "independent_case_count_increment": 0,
            "root_review_required": True,
            "launch_allowed": False,
            "repair_success": "unknown_until_actual_51_frame_bed_audit_and_root_review",
            "source_arrays_read": False,
            "xmf_attempt_id": "root-stage1-f5-short51-normal-dynamic-129",
        }
    )
    binding_path = output_dir / "bed-audit-binding.json"
    write_json(binding_path, binding, force)

    request = load(paths["request_template"])
    request.update(
        {
            "input_binding": str(binding_path.resolve()),
            "gencase_receipt": actual["gencase_receipt"],
            "gencase_receipt_sha256": actual["gencase_receipt_sha256"],
            "initial_qa_receipt": actual["initial_qa_receipt"],
            "initial_qa_receipt_sha256": actual["initial_qa_receipt_sha256"],
            "initial_typed_qa": actual["initial_qa_report"],
            "initial_qa_report": actual["initial_qa_report"],
            "initial_qa_report_sha256": actual["initial_qa_report_sha256"],
            "short_solver_receipt": actual["short_solver_receipt"],
            "short_solver_receipt_sha256": actual["short_solver_receipt_sha256"],
            "typed_receipt": actual["typed_receipt"],
            "typed_receipt_sha256": actual["typed_receipt_sha256"],
            "native_receipt": actual["native_receipt"],
            "native_receipt_sha256": actual["native_receipt_sha256"],
            "native_conversion_report": actual["native_conversion_report"],
            "native_conversion_report_sha256": actual["native_conversion_report_sha256"],
            "trajectory_h5": actual["trajectory_h5"],
            "trajectory_h5_sha256": actual["trajectory_h5_sha256"],
            "xmf_attempt_id": "root-stage1-f5-short51-normal-dynamic-129",
            "xmf_receipt": actual["xmf_receipt"],
            "xmf_receipt_sha256": actual["xmf_receipt_sha256"],
            "xmf_manifest": actual["xmf_manifest"],
            "xmf_manifest_sha256": actual["xmf_manifest_sha256"],
            "xdmf": actual["xdmf"],
            "xdmf_sha256": actual["xdmf_sha256"],
            "time_axis_policy": actual["time_axis_policy"],
            "physical_condition_sha256": CANONICAL_SHA,
            "canonical_conversion_physical_condition_sha256": CANONICAL_SHA,
            "source_plan_physical_condition_sha256": SOURCE_PLAN_SHA,
            "declared_campaign_physical_condition_sha256": SOURCE_PLAN_SHA,
            "physical_condition_hash_match": False,
            "launch_allowed": False,
            "root_review_required": True,
            "full16_authorized": False,
            "q_n_granted": False,
            "production_approval": "none",
            "independent_case_count_increment": 0,
            "bound_status": "ready_for_root_review_then_enable",
            "source_prepared_without_solver_or_array_read": True,
            "native_arrays_read": False,
            "bi4_read": False,
            "h5_read": False,
            "csv_read": False,
        }
    )
    files = input_files(paths, binding_path)
    missing = [str(path) for path in files if not path.is_file()]
    require(not missing, f"bed request inputs missing: {missing}")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        absolute = path.resolve()
        if str(absolute) not in seen:
            seen.add(str(absolute))
            unique.append(absolute)
    request["input_files"] = [str(path) for path in unique]
    request["input_sha256"] = {str(path): (TRAJECTORY_H5_SHA if path.resolve() == paths["trajectory_h5"].resolve() else sha(path)) for path in unique}
    request_path = output_dir / "bed-audit-request.json"
    write_json(request_path, request, force)
    return {
        "bound_status": "ready_for_root_review_then_enable",
        "xmf_attempt_id": "root-stage1-f5-short51-normal-dynamic-129",
        "xmf_receipt_sha256": actual["xmf_receipt_sha256"],
        "xmf_manifest_sha256": actual["xmf_manifest_sha256"],
        "xdmf_sha256": actual["xdmf_sha256"],
        "bed_binding": str(binding_path.resolve()),
        "bed_request": str(request_path.resolve()),
        "launch_allowed": False,
    }


def source_check(paths: Mapping[str, Path]) -> None:
    manifest = load(paths["manifest"])
    template = load(paths["request_template"])
    require(manifest.get("root129_xmf", {}).get("receipt_sha256") == ROOT129_RECEIPT_SHA, "Root129 receipt hash template mismatch")
    require(manifest.get("root129_xmf", {}).get("manifest_sha256") == ROOT129_MANIFEST_SHA, "Root129 manifest hash template mismatch")
    require(manifest.get("root129_xmf", {}).get("case_xmf_sha256") == ROOT129_XMF_SHA, "Root129 XMF hash template mismatch")
    require(template.get("attempt_id") == "root-stage1-f5-short51-normal-dynamic-bed-audit-068", "fresh068 bed attempt mismatch")
    require(template.get("launch_allowed") is False and template.get("full16_authorized") is False, "fresh068 bed request is enabled")
    require(template.get("uniform_spacing_assumption") is False, "fresh068 time policy assumes equal spacing")
    print("fresh068 source-only checks passed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=BASE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    paths = default_paths()
    if args.check:
        source_check(paths)
        return 0
    result = bind(paths, args.output_dir.resolve(), args.force)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
