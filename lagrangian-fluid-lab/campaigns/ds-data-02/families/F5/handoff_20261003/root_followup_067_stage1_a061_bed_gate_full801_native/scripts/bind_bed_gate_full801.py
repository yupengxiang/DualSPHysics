#!/usr/bin/env python3
"""Bind a completed F5 A061 short bed audit to a disabled full801 request.

This helper reads JSON metadata and hashes immutable files only.  It never
opens BI4/H5/CSV arrays and never launches GenCase, DualSPHysics, a converter,
or a postprocessor.  The helper refuses to manufacture a bed-audit result:
the receipt and report must already exist.  A structurally complete audit
produces a request marked ready for Root review; every result remains
``launch_allowed: false`` until Root manually enables a fresh full16 request.
Structural audit completeness is separate from scientific acceptance.  The
1DP/2DP counts and depths are preserved as diagnostics, with no threshold
relaxation or automatic repair-success claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


BASE = Path(__file__).resolve().parents[1]
CASE = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061"
)
ROOT061 = BASE.parent / "root_followup_061_stage1_native_bed_repair_candidate_a_strict_v1"
FRESH066 = BASE.parent / (
    "root_followup_066_stage1_a061_short_event_native093_nvme_typed_bed_audit_v2"
)
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
OFFICIAL_BINARY = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)

SOURCE_PLAN_SHA = "268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c"
CANONICAL_TYPED_SHA = "d4a165e67b16f4f4871aa8a37eaf7cef6c08796cbf644cf2c9e101af9f84fbb7"
GENCASE_RECEIPT_SHA = "6a9cc4bb55ccea1fe4266a8c923027492512a1949d0f3041f553a8f73e636ed6"
QA_RECEIPT_SHA = "1417058bf9204284d1d8a2bd285c606e7c0a69aaccc9112f233c0427d2ae9a4a"
QA_REPORT_SHA = "87bf5f1cfcc8846f046d63bcfe16f0ec13a3eaaefafb3e9833de08d6ae818967"
SHORT_RECEIPT_SHA = "141c389666d669920296938a471b308ed67548629568e4cd941f599b76bc6af3"
ROOT037_LEDGER_SHA = "6fadfef279760f18d80875251f51a8f51901cc20a2826ca97afebd5f5bbed3e1"
ROOT037_REPORT_SHA = "2bef081567648bbc49b45f43e3b3797d14752a20582f4408f028cdcc493af7be"

FAMILY_ID = "F5"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_REPAIR_A_V1"
CONDITION_ID = "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_EXPLICIT_CLOSED_MESH"
CANDIDATE_ID = "A_explicit_closed_mesh_only"
REPAIR_ID = "F5_BED_REPAIR_A_REMOVE_DUPLICATE_STL_INVOCATION"
# Root131 is the only enabled short-event audit input for this gate. Keep the
# attempt binding exact so an older 066 receipt cannot be mistaken for the
# actual XMF/typed trajectory audit.
BED_ATTEMPT_ID = "root-stage1-f5-short51-actual-framewise-bed-audit-131"
FULL_ATTEMPT_ID = "root-stage1-f5-explicit-bed-repair-a-full-event-native-801-067"

PROFILE_NODES = [
    [-0.2, 0.0],
    [2.0, 0.0],
    [3.0, 0.28],
    [3.6, 0.448],
    [3.9, 0.448],
    [4.4, 0.05],
    [4.8, 0.05],
]
BED_X_DOMAIN = [-0.2, 4.8]
BED_Y_BOUNDS = [-0.15, 0.15]
DEPTH_BINS = [0.02, 0.04]
EXPECTED_FRAMES_SHORT = 51
EXPECTED_PARTICLE_AXIS = 214385
EXPECTED_FLUID = 40710
FLUID_TYPE = 3


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


def is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def write_json(path: Path, value: Mapping[str, Any], force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path}; use --force")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_receipt(path: Path, label: str, expected_root: Path | None = None) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    value = load(path)
    require(value.get("status") == "completed", f"{label} is not completed")
    require(value.get("returncode") == 0, f"{label} returncode is not zero")
    if expected_root is not None:
        actual_root = Path(str(value.get("output_root", ""))).resolve()
        require(actual_root == expected_root.resolve(), f"{label} output root mismatch")
    return value


def default_paths() -> dict[str, Path]:
    gencase_root = CASE / "root-stage1-f5-explicit-bed-repair-a-genuine-gencase-075"
    qa_root = CASE / "root-stage1-f5-explicit-bed-repair-a-native-qa-083"
    short_root = CASE / "root-stage1-f5-explicit-bed-repair-a-short-event-native-093"
    bed_root = CASE / BED_ATTEMPT_ID
    prepared = gencase_root / "prepared"
    return {
        "manifest": BASE / "manifest.json",
        "binding_template": BASE / "bed-gate-binding-template.json",
        "request_template": BASE / "full801-native-request-template.json",
        "owner": BASE / "owner-metadata.json",
        "gencase_receipt": gencase_root / "execution-receipt.json",
        "gencase_root": gencase_root,
        "qa_receipt": qa_root / "execution-receipt.json",
        "qa_root": qa_root,
        "qa_report": qa_root / "initial-qa/a061-native-initial-qa.json",
        "short_receipt": short_root / "execution-receipt.json",
        "short_root": short_root,
        "prepared_xml": prepared / f"{CASE_ID}.xml",
        "prepared_prefix": prepared / CASE_ID,
        "prepared_bi4": prepared / f"{CASE_ID}.bi4",
        "motion": prepared / "assets/f5_compact_packet_motion.dat",
        "source_definition": ROOT061 / "candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_Def.xml",
        "source_binding": ROOT061 / "physical-binding.json",
        "source_chain": ROOT061 / "strict-source-chain.json",
        "candidate_patch": ROOT061 / "candidate_a_patch.json",
        "gencase_binding": ROOT061 / "gencase-binding.json",
        "root037_ledger": ROOT061 / "root037_failure_ledger_summary.json",
        "root037_report": Path(
            "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
            "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/"
            "root-stage1-runup-coarse-full801-nativefluid-bed-footprint-diagnostic-037/"
            "nativefluid_bed_support_diagnostic.json"
        ),
        "runtime": INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        "strict_dispatch": INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        "bed_worker": FRESH066 / "workers/bed_audit.py",
        "bed_root": bed_root,
        "bed_receipt": bed_root / "execution-receipt.json",
        "bed_report": bed_root / "a061-short-event-bed-footprint-audit.json",
    }


def validate_base(paths: Mapping[str, Path]) -> dict[str, Any]:
    manifest = load(paths["manifest"])
    require(manifest.get("schema") == "ds02.f5.a061.fresh067.bed-gate-full801-manifest.v1", "fresh067 manifest schema mismatch")
    require(manifest.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA, "source-plan hash mismatch")
    require(manifest.get("typed065_canonical_physical_condition_sha256") == CANONICAL_TYPED_SHA, "typed065 canonical hash mismatch")
    require(manifest.get("canonical_source_hash_difference_disclosed") is True, "canonical/source hash difference was not disclosed")
    require(manifest.get("numeric_precision_rewrite") is False, "numeric precision rewrite policy changed")

    gencase = validate_receipt(paths["gencase_receipt"], "actual075 GenCase", paths["gencase_root"])
    require(sha(paths["gencase_receipt"]) == GENCASE_RECEIPT_SHA, "actual075 receipt hash mismatch")
    require(gencase.get("total_particles") == EXPECTED_PARTICLE_AXIS, "actual075 total particle count mismatch")
    require(gencase.get("fluid_particles") == EXPECTED_FLUID, "actual075 fluid count mismatch")
    require(gencase.get("solver_dimension_from_gencase") == 3, "actual075 is not 3-D")

    qa_receipt = validate_receipt(paths["qa_receipt"], "actual083 initial QA", paths["qa_root"])
    require(sha(paths["qa_receipt"]) == QA_RECEIPT_SHA, "actual083 receipt hash mismatch")
    qa_report = load(paths["qa_report"])
    require(sha(paths["qa_report"]) == QA_REPORT_SHA, "actual083 report hash mismatch")
    require(qa_report.get("all_actual_checks_pass") is True, "actual083 checks did not pass")
    require(
        qa_report.get("provenance", {}).get("repair_success")
        == "unknown_until_short_event_and_framewise_bed_audit",
        "actual083 report makes an unexpected repair-success claim",
    )

    short = validate_receipt(paths["short_receipt"], "actual093 short solver", paths["short_root"])
    require(sha(paths["short_receipt"]) == SHORT_RECEIPT_SHA, "actual093 receipt hash mismatch")
    require(short.get("request", {}).get("attempt_id") == "root-stage1-f5-explicit-bed-repair-a-short-event-native-093", "short receipt attempt mismatch")
    command = short.get("command", [])
    require("-tmax:1.0" in command and "-tout:0.02" in command, "actual093 is not the 0..1 s / .02 s short event")

    ledger = load(paths["root037_ledger"])
    require(sha(paths["root037_ledger"]) == ROOT037_LEDGER_SHA, "root037 ledger hash mismatch")
    require(ledger.get("old_failure_preserved") is True, "root037 old failure was not preserved")
    require(ledger.get("root_cause_assigned") is False, "root037 unexpectedly assigns a root cause")
    require(ledger.get("frames_scanned") == 801, "root037 frame count mismatch")
    require(ledger.get("particle_axis_count") == 214515, "root037 particle axis mismatch")

    report = load(paths["root037_report"])
    require(sha(paths["root037_report"]) == ROOT037_REPORT_SHA, "root037 audit report hash mismatch")
    require(report.get("diagnostic_only") is True, "root037 report is not diagnostic-only")
    require(report.get("full16_authorized", True) is False, "root037 unexpectedly authorizes full16")
    require(report.get("scan", {}).get("frames_scanned") == 801, "root037 report scan count mismatch")

    for key in (
        "owner",
        "prepared_xml",
        "motion",
        "source_definition",
        "source_binding",
        "source_chain",
        "candidate_patch",
        "gencase_binding",
        "runtime",
        "strict_dispatch",
        "bed_worker",
        "root037_report",
    ):
        require(paths[key].is_file(), f"required source input missing: {paths[key]}")

    return {
        "gencase": {
            "receipt": str(paths["gencase_receipt"].resolve()),
            "receipt_sha256": sha(paths["gencase_receipt"]),
            "output_root": str(paths["gencase_root"].resolve()),
            "total_particles": gencase["total_particles"],
            "fluid_particles": gencase["fluid_particles"],
            "dimension": gencase["solver_dimension_from_gencase"],
        },
        "initial_qa": {
            "receipt": str(paths["qa_receipt"].resolve()),
            "receipt_sha256": sha(paths["qa_receipt"]),
            "report": str(paths["qa_report"].resolve()),
            "report_sha256": sha(paths["qa_report"]),
            "all_actual_checks_pass": True,
        },
        "short_solver": {
            "receipt": str(paths["short_receipt"].resolve()),
            "receipt_sha256": sha(paths["short_receipt"]),
            "attempt_id": short["request"]["attempt_id"],
        },
        "root037": {
            "ledger": str(paths["root037_ledger"].resolve()),
            "ledger_sha256": sha(paths["root037_ledger"]),
            "report": str(paths["root037_report"].resolve()),
            "report_sha256": sha(paths["root037_report"]),
            "frames_scanned": 801,
            "particle_axis_count": 214515,
            "full16_authorized": False,
            "root_cause_assigned": False,
        },
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def validate_bed_audit(
    receipt_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    require(receipt_path.is_file(), f"actual bed-audit receipt is missing: {receipt_path}")
    require(report_path.is_file(), f"actual bed-audit report is missing: {report_path}")
    receipt = load(receipt_path)
    report = load(report_path)
    receipt_root = Path(str(receipt.get("output_root", ""))).resolve()
    expected_root = (CASE / BED_ATTEMPT_ID).resolve()
    require(receipt.get("status") == "completed", "bed-audit receipt is not completed")
    require(receipt.get("returncode") == 0, "bed-audit receipt returncode is not zero")
    require(receipt.get("request", {}).get("attempt_id") == BED_ATTEMPT_ID, "bed-audit receipt attempt mismatch")
    require(receipt_root == expected_root, "bed-audit receipt output root is not the Root131 output root")
    require(receipt_root == report_path.parent.resolve(), "bed-audit report is outside receipt output root")

    checks: dict[str, bool] = {}
    failures: list[dict[str, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append({"check": name, "detail": detail})

    scan = _mapping(report.get("scan"))
    time_info = _mapping(report.get("time_provenance"))
    uid_reference = _mapping(report.get("initial_fluid_uid_reference"))
    interpretation = _mapping(report.get("interpretation_boundary"))
    check("schema", report.get("schema") == "ds02.f5.stage1.a061.short-event-bed-footprint-audit.v1", "unexpected report schema")
    check("completed_worker_output", report.get("status") == "completed_worker_output_pending_root_review", "report is not the completed worker output")
    check("diagnostic_only", report.get("diagnostic_only") is True, "report is not diagnostic-only")
    check("full16_still_disabled", report.get("full16_authorized") is False, "report authorizes full16")
    check("production_none", report.get("production_approval") == "none", "report has production approval")
    check("q_n_not_granted", report.get("q_n_status") == "not_granted", "report grants Q-N")
    check("source_arrays_unchanged", report.get("source_arrays_modified") is False and report.get("source_arrays_dropped_or_masked") is False, "report changes or drops source arrays")
    check("frames_scanned", scan.get("frames_scanned") == EXPECTED_FRAMES_SHORT and scan.get("full_scan_range") == [0, 50], "not all 51 frames were scanned")
    check("particle_axis", scan.get("particle_axis_count") == EXPECTED_PARTICLE_AXIS, "particle axis is not 214385")
    check("initial_fluid_count", scan.get("initial_fluid_uid_count") == EXPECTED_FLUID, "initial Type-3 UID count is not 40710")
    check("fluid_type", scan.get("fluid_type_code") == FLUID_TYPE, "fluid Type-3 contract missing")
    check("profile_nodes", scan.get("bed_nodes_xz_m") == PROFILE_NODES, "exact profile nodes are missing or changed")
    check("profile_x_domain", scan.get("bed_x_domain_m") == BED_X_DOMAIN, "exact profile x domain is missing or changed")
    check("bed_y_domain", scan.get("bed_y_domain_m") == BED_Y_BOUNDS, "bed y footprint is missing or changed")
    check("depth_bins", scan.get("depth_tolerances_m") == DEPTH_BINS, "1DP/2DP bins are missing or changed")
    check("time_axis_match", time_info.get("match") is True and time_info.get("frame_count") == EXPECTED_FRAMES_SHORT, "actual time axis metadata is incomplete")
    check("time_axis_monotonic", time_info.get("strictly_increasing") is True and time_info.get("uniform_spacing_assumption") is False, "time axis uses an invalid spacing assumption")
    check("uid_reference", uid_reference.get("uid_count") == EXPECTED_FLUID and uid_reference.get("all_uids_retained_as_reference_denominator") is True, "frame-zero UID denominator is incomplete")
    check("penetration_scope", "exact x profile" in str(interpretation.get("penetration_scope", "")) and "[-0.15,0.15]" in str(interpretation.get("penetration_scope", "")), "penetration scope is not exact bed footprint")
    check("no_causal_claim", interpretation.get("repair_success") == "not inferred from this source-only worker" and "cause" in str(interpretation.get("nonfinite_or_lost_uid", "")), "audit makes an unsupported causal claim")

    frame_reports = report.get("frame_reports")
    frame_ok = isinstance(frame_reports, list) and len(frame_reports) == EXPECTED_FRAMES_SHORT
    check("frame_report_count", frame_ok, "frame_reports does not contain all 51 reports")
    metrics: list[dict[str, Any]] = []
    if frame_ok:
        previous_time: float | None = None
        seen_frames: list[int] = []
        for expected_frame, raw in enumerate(frame_reports):
            frame = _mapping(raw)
            index = frame.get("frame")
            time_s = frame.get("time_s")
            seen_frames.append(index if isinstance(index, int) else -1)
            check(f"frame_{expected_frame}_index", index == expected_frame, f"frame index {index!r} is not {expected_frame}")
            increasing = finite_number(time_s) and (previous_time is None or float(time_s) > previous_time)
            check(f"frame_{expected_frame}_time", increasing, "frame time is nonfinite or not strictly increasing")
            if finite_number(time_s):
                previous_time = float(time_s)
            check(f"frame_{expected_frame}_particle_axis", frame.get("particle_axis_count") == EXPECTED_PARTICLE_AXIS, "particle axis count mismatch")
            for field in ("finite_position_current_fluid_count", "nonfinite_position_current_fluid_count", "nonfinite_initial_fluid_uid_count"):
                check(f"frame_{expected_frame}_{field}", isinstance(frame.get(field), int) and frame.get(field) >= 0, f"{field} missing")
            uid_tracking = _mapping(frame.get("uid_tracking"))
            missing = _mapping(uid_tracking.get("missing_initial_uid"))
            extra = _mapping(uid_tracking.get("unexpected_current_uid"))
            check(f"frame_{expected_frame}_uid_tracking", isinstance(frame.get("uid_tracking"), Mapping) and isinstance(missing.get("count"), int) and isinstance(extra.get("count"), int), "UID tracking fields missing")
            domain = _mapping(frame.get("bed_domain"))
            check(f"frame_{expected_frame}_exact_domain", domain.get("profile_nodes_xz_m") == PROFILE_NODES and domain.get("x_bounds_m") == BED_X_DOMAIN and domain.get("y_bounds_m") == BED_Y_BOUNDS, "frame exact profile/y footprint fields missing")
            check(f"frame_{expected_frame}_footprint_count", isinstance(domain.get("finite_bed_footprint_evaluable_count"), int) and domain.get("finite_bed_footprint_evaluable_count") >= 0, "finite bed-footprint denominator missing")
            penetration = _mapping(frame.get("penetration"))
            check(f"frame_{expected_frame}_penetration_scope", penetration.get("only_finite_current_type3_inside_exact_x_y_bed_footprint") is True, "penetration scope is not exact finite Type-3 bed footprint")
            one = _mapping(penetration.get("one_dp"))
            two = _mapping(penetration.get("two_dp"))
            for label, value, threshold in (("one_dp", one, 0.02), ("two_dp", two, 0.04)):
                check(f"frame_{expected_frame}_{label}", isinstance(value.get("count"), int) and finite_number(value.get("fraction_of_initial_fluid_uid_set")) and value.get("threshold_m") == threshold and "deepest_depth_m" in value and isinstance(value.get("deepest_samples"), list), f"{label} counts/fractions/depth/samples incomplete")
                check(f"frame_{expected_frame}_{label}_diagnostic", value.get("threshold_interpretation") == "diagnostic bin; not an acceptance threshold", f"{label} was turned into an acceptance threshold")
            unexplained = _mapping(frame.get("unexplained_state"))
            check(f"frame_{expected_frame}_unexplained", unexplained.get("cause_assigned") is False, "UID/nonfinite cause was assigned")
            metrics.append({
                "frame": index,
                "time_s": time_s,
                "below_1dp_count": one.get("count"),
                "below_1dp_fraction_initial_uid": one.get("fraction_of_initial_fluid_uid_set"),
                "below_2dp_count": two.get("count"),
                "below_2dp_fraction_initial_uid": two.get("fraction_of_initial_fluid_uid_set"),
                "max_depth_1dp_m": one.get("deepest_depth_m"),
                "max_depth_2dp_m": two.get("deepest_depth_m"),
                "finite_position_current_fluid_count": frame.get("finite_position_current_fluid_count"),
                "nonfinite_position_current_fluid_count": frame.get("nonfinite_position_current_fluid_count"),
                "nonfinite_initial_fluid_uid_count": frame.get("nonfinite_initial_fluid_uid_count"),
                "missing_initial_uid_count": missing.get("count"),
                "unexpected_current_uid_count": extra.get("count"),
            })
        check("frame_indices_complete", seen_frames == list(range(EXPECTED_FRAMES_SHORT)), "frame indices are not exactly 0..50")

    def max_metric(field: str) -> float | int | None:
        values = [item[field] for item in metrics if isinstance(item.get(field), (int, float)) and not isinstance(item.get(field), bool)]
        return max(values) if values else None

    audit_summary = {
        "frames": len(metrics),
        "first_time_s": metrics[0]["time_s"] if metrics else None,
        "last_time_s": metrics[-1]["time_s"] if metrics else None,
        "max_below_1dp_count": max_metric("below_1dp_count"),
        "max_below_1dp_fraction_initial_uid": max_metric("below_1dp_fraction_initial_uid"),
        "max_below_2dp_count": max_metric("below_2dp_count"),
        "max_below_2dp_fraction_initial_uid": max_metric("below_2dp_fraction_initial_uid"),
        "maximum_reported_depth_1dp_m": max_metric("max_depth_1dp_m"),
        "maximum_reported_depth_2dp_m": max_metric("max_depth_2dp_m"),
        "maximum_nonfinite_position_current_fluid_count": max_metric("nonfinite_position_current_fluid_count"),
        "maximum_nonfinite_initial_fluid_uid_count": max_metric("nonfinite_initial_fluid_uid_count"),
        "maximum_missing_initial_uid_count": max_metric("missing_initial_uid_count"),
        "maximum_unexpected_current_uid_count": max_metric("unexpected_current_uid_count"),
        "per_frame_metrics": metrics,
    }
    passed = not failures
    return {
        "receipt": str(receipt_path.resolve()),
        "receipt_sha256": sha(receipt_path),
        "report": str(report_path.resolve()),
        "report_sha256": sha(report_path),
        "receipt_status": receipt.get("status"),
        "report_status": report.get("status"),
        "structural_checks_pass": passed,
        "checks": checks,
        "failures": failures,
        "summary": audit_summary,
    }


def input_paths(paths: Mapping[str, Path], binding_path: Path, bed_receipt: Path, bed_report: Path) -> list[Path]:
    return [
        BASE / "manifest.json",
        BASE / "full801-native-request-template.json",
        BASE / "bed-gate-binding-template.json",
        paths["owner"],
        paths["gencase_receipt"],
        paths["qa_receipt"],
        paths["qa_report"],
        paths["short_receipt"],
        paths["prepared_xml"],
        paths["motion"],
        paths["source_definition"],
        paths["source_binding"],
        paths["source_chain"],
        paths["candidate_patch"],
        paths["gencase_binding"],
        paths["root037_ledger"],
        paths["root037_report"],
        paths["runtime"],
        paths["strict_dispatch"],
        OFFICIAL_BINARY,
        paths["bed_worker"],
        bed_receipt,
        bed_report,
        binding_path,
    ]


def bind(
    *,
    paths: Mapping[str, Path],
    bed_receipt: Path,
    bed_report: Path,
    output_dir: Path,
    force: bool,
) -> dict[str, Any]:
    base = validate_base(paths)
    bed = validate_bed_audit(bed_receipt, bed_report)
    binding = load(paths["binding_template"])
    gate_status = "ready_for_root_review_then_manual_enable" if bed["structural_checks_pass"] else "blocked_bed_audit_validation"
    binding.update(
        {
            "gencase_receipt": base["gencase"]["receipt"],
            "gencase_receipt_sha256": base["gencase"]["receipt_sha256"],
            "initial_qa_receipt": base["initial_qa"]["receipt"],
            "initial_qa_receipt_sha256": base["initial_qa"]["receipt_sha256"],
            "initial_qa_report": base["initial_qa"]["report"],
            "initial_qa_report_sha256": base["initial_qa"]["report_sha256"],
            "short_solver_receipt": base["short_solver"]["receipt"],
            "short_solver_receipt_sha256": base["short_solver"]["receipt_sha256"],
            "bed_audit_receipt": bed["receipt"],
            "bed_audit_receipt_sha256": bed["receipt_sha256"],
            "bed_audit_report": bed["report"],
            "bed_audit_report_sha256": bed["report_sha256"],
            "gate_status": gate_status,
            "full16_eligibility": "eligible_for_manual_root_review" if bed["structural_checks_pass"] else "blocked_audit_validation",
            "audit_structural_checks_pass": bed["structural_checks_pass"],
            "audit_checks": bed["checks"],
            "audit_failures": bed["failures"],
            "audit_summary": bed["summary"],
            "full16_authorized": False,
            "launch_allowed": False,
            "manual_root_enablement_required": True,
            "no_automatic_enablement": True,
            "repair_success": "unknown_until_root_review",
            "bound_status": gate_status,
            "bound_by": "fresh067/scripts/bind_bed_gate_full801.py",
        }
    )
    binding_path = output_dir / "bed-gate-binding.json"
    write_json(binding_path, binding, force)

    request = load(paths["request_template"])
    request.update(
        {
            "gencase_receipt": base["gencase"]["receipt"],
            "gencase_receipt_sha256": base["gencase"]["receipt_sha256"],
            "initial_qa_receipt": base["initial_qa"]["receipt"],
            "initial_qa_receipt_sha256": base["initial_qa"]["receipt_sha256"],
            "initial_typed_qa": base["initial_qa"]["report"],
            "initial_typed_qa_sha256": base["initial_qa"]["report_sha256"],
            "short_solver_receipt": base["short_solver"]["receipt"],
            "short_solver_receipt_sha256": base["short_solver"]["receipt_sha256"],
            "bed_audit_receipt": bed["receipt"],
            "bed_audit_receipt_sha256": bed["receipt_sha256"],
            "bed_audit_report": bed["report"],
            "bed_audit_report_sha256": bed["report_sha256"],
            "bed_audit_binding": str(binding_path.resolve()),
            "bed_audit_structural_checks_pass": bed["structural_checks_pass"],
            "bed_audit_summary": bed["summary"],
            "root037_failure_ledger_summary": base["root037"]["ledger"],
            "root037_failure_ledger_summary_sha256": base["root037"]["ledger_sha256"],
            "source_plan_physical_condition_sha256": SOURCE_PLAN_SHA,
            "canonical_conversion_physical_condition_sha256": CANONICAL_TYPED_SHA,
            "declared_campaign_physical_condition_sha256": SOURCE_PLAN_SHA,
            "physical_condition_hash_match": False,
            "launch_allowed": False,
            "full16_authorized": False,
            "root_review_required": True,
            "manual_root_enablement_required": True,
            "no_automatic_enablement": True,
            "bound_status": gate_status,
            "launch_disabled_reason": (
                "disabled because actual 51-frame bed-audit metadata is incomplete; full801 remains blocked"
                if not bed["structural_checks_pass"]
                else "disabled until Root manually reviews the complete 51-frame bed audit and enables this exact full801 request; no penetration threshold is relaxed"
            ),
            "source_prepared_without_solver_or_array_read": True,
            "native_arrays_read": False,
            "bi4_read": False,
            "h5_read": False,
            "csv_read": False,
            "independent_case_count_increment": 0,
            "q_n_granted": False,
            "production_approval": "none",
            "numerical_reference_status": (
                "full801 request bound to actual 51-frame bed audit; manual Root review required; no full16 authorization"
                if bed["structural_checks_pass"]
                else "full801 blocked because actual 51-frame bed audit metadata checks failed; no full16 authorization"
            ),
        }
    )
    files = input_paths(paths, binding_path, bed_receipt, bed_report)
    missing = [str(path) for path in files if not path.is_file()]
    require(not missing, f"full801 request inputs missing: {missing}")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        absolute = path.resolve()
        if str(absolute) not in seen:
            seen.add(str(absolute))
            unique.append(absolute)
    request["input_files"] = [str(path) for path in unique]
    request["input_sha256"] = {str(path): sha(path) for path in unique}
    request_path = output_dir / "full801-native-request.json"
    write_json(request_path, request, force)
    return {
        "gate_status": gate_status,
        "bed_audit_structural_checks_pass": bed["structural_checks_pass"],
        "bed_audit_receipt": bed["receipt"],
        "bed_audit_report": bed["report"],
        "bed_audit_receipt_sha256": bed["receipt_sha256"],
        "bed_audit_report_sha256": bed["report_sha256"],
        "bed_gate_binding": str(binding_path.resolve()),
        "full801_request": str(request_path.resolve()),
        "launch_allowed": False,
        "full16_authorized": False,
        "input_count": len(unique),
    }


def source_check(paths: Mapping[str, Path]) -> None:
    manifest = load(paths["manifest"])
    binding = load(paths["binding_template"])
    request = load(paths["request_template"])
    require(manifest.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA, "manifest source hash check failed")
    require(manifest.get("typed065_canonical_physical_condition_sha256") == CANONICAL_TYPED_SHA, "manifest canonical hash check failed")
    require(binding.get("physical_condition_hash_match") is False, "binding template collapses hash distinction")
    require(binding.get("full16_authorized") is False and binding.get("launch_allowed") is False, "binding template is enabled")
    require(request.get("attempt_id") == FULL_ATTEMPT_ID, "full801 attempt template mismatch")
    require(request.get("expected_frames") == 801 and request.get("expected_total_particles") == EXPECTED_PARTICLE_AXIS, "full801 frame/particle contract mismatch")
    require(request.get("launch_allowed") is False and request.get("full16_authorized") is False, "full801 template is enabled")
    require(request.get("full16_gate", {}).get("actual_bed_audit_required") is True, "full801 bed gate missing")
    require(request.get("full16_gate", {}).get("audit_does_not_auto_authorize") is True, "full801 auto-authorization policy missing")
    ledger = load(paths["root037_ledger"])
    require(sha(paths["root037_ledger"]) == ROOT037_LEDGER_SHA, "root037 ledger source check hash mismatch")
    require(ledger.get("old_failure_preserved") is True and ledger.get("root_cause_assigned") is False, "root037 rejection semantics changed")
    print("fresh067 source-only template checks passed; no actual bed receipt/report was consumed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bed-receipt", type=Path, help="actual completed bed-audit execution receipt")
    parser.add_argument("--bed-report", type=Path, help="actual completed 51-frame bed-audit report")
    parser.add_argument("--output-dir", type=Path, default=BASE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true", help="check source templates without requiring future bed outputs")
    args = parser.parse_args(argv)
    paths = default_paths()
    if args.check:
        source_check(paths)
        return 0
    receipt = (args.bed_receipt or paths["bed_receipt"]).resolve()
    report = (args.bed_report or paths["bed_report"]).resolve()
    result = bind(
        paths=paths,
        bed_receipt=receipt,
        bed_report=report,
        output_dir=args.output_dir.resolve(),
        force=args.force,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
