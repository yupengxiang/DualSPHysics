#!/usr/bin/env python3
"""Prepare launch-disabled full-window solver requests for F1-S1 owner rungs.

The two owner-centred GenCase products (``dp=.005`` and ``dp=.0025``) now
have independent native initial-state and support proofs.  This forward
builder creates a new XML overlay for each rung and for same/half CFL.  The
overlay changes only the official ``execution.special.savedt`` logging node
and, for the half-CFL case, the two generated CFL values.  The original XML,
BI4, receipts, and consumed QA/support requests remain immutable.

The large BI4 is deliberately deferred.  A parent v8 guard must verify its
stable hash and materialise a hardlink next to the committed overlay XML
before enabling a request.  This module does not start a solver, read BI4 or
H5, or grant QI/QN/QE credit.  ``--self-test`` is metadata/XML-only; ``--prepare``
also writes four small overlay XML files and four launch-disabled requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f1-s1.owner-matched-solver-requests.v2"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DISPATCH_ROOT = MAIN
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
OWNER = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
OWNER_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
QA_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/" \
    "F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
SUPPORT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/" \
    "F1_OWNER_DP0025_SUPPORT_V5_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
DP005_SUPPORT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/" \
    "F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
DP0025_GENCASE_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/" \
    "F1_OWNER_DP0025_V3_GENCASE_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
INPUT_ROOT = REFERENCE / "stage2_f1_s1_owner_matched_solver_inputs_v2"
REQUEST_ROOT = STAGE2 / "requests/stage2-f1-s1-owner-matched-solver-v2"
REPORT = REFERENCE / "stage2_f1_s1_owner_matched_solver_requests_v2.json"
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}
WINDOW_END_S = 1.600082994772861
SAVE_INTERVAL_S = 0.005
OWNER_MASS_KG = 40.2

CASES: dict[str, dict[str, Any]] = {
    "dp005": {
        "token": "DP005",
        "case_id": "F1_S1_OWNER_CENTERED_DP0p005000_V2",
        "dp_m": 0.005,
        "fluid_particles": 321600,
        "particles": 1087099,
        "sample_mass_kg": 40.2,
        "generated_root": DATA_ROOT / "families/F1/F1_S1_OWNER_CENTERED_DP0p005000_V2/"
        "f1-s1-owner-centered-dp0p005000-v2-root-001-root-forward-030-001",
        "proof": DP005_SUPPORT_PROOF,
        "proof_status": "PASS_ACTUAL_DP005_FLUID_SUPPORT_AND_SOURCE_CONTROL_COMPARE",
        # A planning reservation only.  Parent terminal tree bytes win.
        "storage_bytes": 20_000_000_000,
        "wall_seconds": 7200,
    },
    "dp0025": {
        "token": "DP0025",
        "case_id": "F1_S1_OWNER_CENTERED_DP0p002500_V3",
        "dp_m": 0.0025,
        "fluid_particles": 2572800,
        "particles": 7445049,
        "sample_mass_kg": 40.2,
        "generated_root": DATA_ROOT / "families/F1/F1_S1_OWNER_CENTERED_DP0p002500_V3/"
        "f1-s1-owner-centered-dp0p002500-v3-root-001-root-forward-030-001",
        "proof": SUPPORT_PROOF,
        "proof_status": "PASS_ACTUAL_DP0025_VTK_SUPPORT_STABLE_PRE_POST_SOURCE",
        "storage_bytes": 132_000_000_000,
        "wall_seconds": 7200,
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, *, deferred: bool = False) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": "PARENT_V8_GUARD_REQUIRED" if deferred else sha256_file(path),
    }


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(f"refuse overwrite of immutable file: {path}")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def record_json(path: Path) -> dict[str, Any]:
    return file_record(path)


def savedt_fragment(indent: str) -> str:
    child = indent + "    "
    return (
        f'{child}<savedt active="true">\n'
        f'{child}    <start value="0" comment="per-step dt starts at initial time" />\n'
        f'{child}    <finish value="0" comment="official v5.4 zero means no finish limit" />\n'
        f'{child}    <interval value="{SAVE_INTERVAL_S:g}" comment="explicit positive interval" />\n'
        f'{child}    <fullinfo value="0" comment="compact statistics" />\n'
        f'{child}    <alldt value="1" comment="all final-step dt rows" />\n'
        f'{child}</savedt>\n'
    )


def add_savedt(source_text: str) -> str:
    if re.search(r"<savedt\b", source_text):
        raise ValueError("source XML unexpectedly already contains savedt")
    execution = re.search(r"<execution(?:\s[^>]*)?>", source_text)
    if execution is None:
        raise ValueError("source XML has no execution node")
    end = source_text.find("</execution>", execution.end())
    if end < 0:
        raise ValueError("source XML has no execution close")
    line_start = source_text.rfind("\n", 0, end) + 1
    indent = source_text[line_start:end]
    special = f"{indent}<special>\n{savedt_fragment(indent)}{indent}</special>\n"
    return source_text[:line_start] + special + source_text[line_start:]


def half_cfl(source_text: str) -> tuple[str, list[str]]:
    values = re.findall(r'<cflnumber\b[^>]*\bvalue="([^"]+)"', source_text)
    if values != ["0.2", "0.2"]:
        raise ValueError(f"F1 owner source CFL changed unexpectedly: {values}")
    changed = source_text.replace('value="0.2"', 'value="0.1"')
    if changed.count('value="0.1"') < 2:
        raise ValueError("half-CFL overlay did not change both CFL values")
    return changed, ["cflnumber[0].value:0.2->0.1", "cflnumber[1].value:0.2->0.1"]


def overlay(case: dict[str, Any], mode: str) -> tuple[Path, dict[str, Any]]:
    source_xml = case["generated_root"] / "generated.xml"
    source_text = source_xml.read_text(encoding="utf-8")
    text = add_savedt(source_text)
    edits = ["execution.special.savedt insertion"]
    if mode == "half_cfl":
        text, cfl_edits = half_cfl(text)
        edits.extend(cfl_edits)
    elif mode != "same_cfl":
        raise ValueError(mode)
    path = INPUT_ROOT / case["token"] / mode / f"F1_S1_OWNER_{case['token']}_{mode}_SAVEDT.xml"
    atomic_bytes(path, text.encode("utf-8"))
    values = re.findall(r'<cflnumber\b[^>]*\bvalue="([^"]+)"', text)
    return path, {
        "source_xml": file_record(source_xml),
        "overlay_xml": file_record(path),
        "source_cfl_values": ["0.2", "0.2"],
        "overlay_cfl_values": values,
        "declared_text_edits": edits,
        "savedt": {"active": True, "start_s": 0.0, "finish_s": 0.0,
                   "interval_s": SAVE_INTERVAL_S, "fullinfo": 0, "alldt": 1},
        "bi4_materialization": "parent v8 guard must hardlink exact source BI4 next to overlay XML; no copy/rescale",
    }


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def request_for(case: dict[str, Any], mode: str, overlay_path: Path, diff: dict[str, Any], source_commit: str) -> tuple[Path, dict[str, Any]]:
    generated_root = case["generated_root"]
    source_xml = generated_root / "generated.xml"
    source_bi4 = generated_root / "generated.bi4"
    gencase_receipt = generated_root / "execution-receipt.json"
    if not source_bi4.is_file() or not gencase_receipt.is_file():
        raise FileNotFoundError(f"missing owner source input: {source_bi4} or {gencase_receipt}")
    token = case["token"]
    mode_token = "SAMECFL" if mode == "same_cfl" else "HALFCFL"
    case_id = f"F1_S1_OWNER_{token}_{mode_token}_SAVEDT_DENSE"
    attempt = case_id.lower().replace("_", "-") + "-v1-root-001"
    prefix = overlay_path.with_suffix("")
    proof = case["proof"]
    inputs = [
        DISPATCH, STRICT, RUNTIME, Path(__file__).resolve(),
        OWNER, OWNER_BINDING, QA_PROOF, SUPPORT_PROOF, DP005_SUPPORT_PROOF,
        DP0025_GENCASE_PROOF, source_xml, gencase_receipt, overlay_path,
    ]
    # Current owner BI4 and solver are deferred parent inputs.  They are kept
    # separate from small source/proof files so a launch cannot accidentally
    # treat an unverified planning digest as a completed source hash.
    input_hashes: dict[str, str] = {}
    for path in inputs:
        input_hashes[str(path.resolve())] = sha256_file(path)
    input_hashes[str(source_bi4.resolve())] = "PARENT_V8_GUARD_REQUIRED"
    input_hashes[str(SOLVER.resolve())] = "PARENT_V8_GUARD_REQUIRED"
    input_files = [str(path.resolve()) for path in inputs] + [str(source_bi4.resolve()), str(SOLVER.resolve())]
    # Avoid duplicate entries while preserving the audit order.
    input_files = list(dict.fromkeys(input_files))
    mode_cfl = 0.2 if mode == "same_cfl" else 0.1
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": case_id,
        "attempt_id": attempt,
        "kind": "qualification",
        "qualification_stage": "stage2_f1_s1_owner_matched_full_window_savedt_v1_pending_parent_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": case["wall_seconds"],
        "estimated_storage_bytes": case["storage_bytes"],
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(overlay_path.parent),
        "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output",
                    f"-tmax:{WINDOW_END_S:.17g}", f"-tout:{SAVE_INTERVAL_S:.17g}"],
        "gencase_receipt": str(gencase_receipt.resolve()),
        "gencase_receipt_sha256": sha256_file(gencase_receipt),
        "expected_particles": case["particles"],
        "expected_fluid_particles": case["fluid_particles"],
        "expected_native_frames": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS",
        "expected_dimension": 3,
        "physical_window_s": [0.0, WINDOW_END_S],
        "save_interval_s": SAVE_INTERVAL_S,
        "source_binding": {
            "schema": "ds02.stage2.f1-s1.owner-matched-binding.v1",
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "continuous_owner": {
                "path": str(OWNER.resolve()),
                "sha256": sha256_file(OWNER),
                "mass_kg": OWNER_MASS_KG,
                "low_m": [0.0, 0.0, 0.0],
                "size_m": [0.4, 0.67, 0.15],
            },
            "resolution_rung": {
                "token": token,
                "dp_m": case["dp_m"],
                "particles": case["particles"],
                "fluid_particles": case["fluid_particles"],
                "sample_mass_kg": case["sample_mass_kg"],
                "sample_mass_error_fraction_vs_owner": 0.0,
                "sample_mass_role": "discrete_native_diagnostic; not a continuum rescale or rigid-body mass",
            },
            "generated_source": {
                "xml": file_record(source_xml),
                "bi4": file_record(source_bi4, deferred=True),
                "gencase_receipt": file_record(gencase_receipt),
                "actual_proof": record_json(proof),
            },
            "qa_proof": record_json(QA_PROOF),
            "support_proof": record_json(SUPPORT_PROOF),
            "source_def_control": "owner-centered selector/control source is frozen; only SaveDt and declared CFL overlay edits are introduced",
            "motion": "none in generated XML; gravity z=-9.81 m/s^2 retained",
        },
        "effective_conditions": {
            "cfl_mode": mode,
            "source_cfl": 0.2,
            "effective_cfl": mode_cfl,
            "source_xml_TimeMax_s": 1.6,
            "requested_cli_tmax_s": WINDOW_END_S,
            "source_xml_TimeOut_s": 0.01,
            "requested_cli_tout_s": SAVE_INTERVAL_S,
            "gravity_m_per_s2": [0.0, 0.0, -9.81],
            "overlay_diff": diff,
            "control_scope": "same owner geometry, material, gravity, particle state and source controls; intentional CFL/save logging variation only",
        },
        "dt_observability": {
            "savedt_active": True,
            "start_s": 0.0,
            "finish_s": 0.0,
            "finish_semantics": "official v5.4 finish<=0 means no finish limit",
            "interval_s": SAVE_INTERVAL_S,
            "fullinfo": 0,
            "alldt": 1,
            "RunPARTs_DTsMin": "count only, not seconds or a full per-step trace",
            "clamp_status": "UNKNOWN_UNTIL_TERMINAL_RECEIPT",
            "terminal_step_flush": "UNKNOWN_UNTIL_TERMINAL_RECEIPT",
        },
        "output_plan": {
            "native_raw": "retain every Part_*.bi4 over [0, requested CLI tmax]; no deletion",
            "query_times_s": [0.0, 0.4, 0.8, 1.2, WINDOW_END_S],
            "time_policy": "EXACT/EXACT_OR_LEFT/BRACKETED from actual RunPARTs times; no frame-index assumptions or extrapolation",
            "typed_conversion": "separate parent-dispatched task after terminal source receipt; no duplicate full typed copy assumed here",
            "output_downsample": "derived after raw retention; not a solver replacement",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "cost": {
            "reservation_bytes": case["storage_bytes"],
            "planning_proxy": "source F1 dp=.01 Part_0000 ratio scaled by exact particle count with 25% guard margin; terminal receipt/tree bytes are authoritative",
            "same_half_pair_policy": "run sequentially under parent ledger; do not reserve both full trees concurrently",
            "owner_dp_particle_scale_vs_source_dp01": case["particles"] / 141636.0,
        },
        "preconditions": [
            {"path": str(QA_PROOF.resolve()), "sha256": sha256_file(QA_PROOF), "required_status": "PASS_ACTUAL_TWO_F1_GENCASE_NATIVE_INITIAL_FIELDS_AND_SAMPLE_MASS"},
            {"path": str(SUPPORT_PROOF.resolve()), "sha256": sha256_file(SUPPORT_PROOF), "required_status": "PASS_ACTUAL_DP0025_VTK_SUPPORT_STABLE_PRE_POST_SOURCE"},
            {"path": str(case["proof"].resolve()), "sha256": sha256_file(case["proof"]), "required_status": case["proof_status"]},
            {"path": str(source_bi4.resolve()), "sha256": "PARENT_V8_GUARD_REQUIRED", "require_stable_pre_post_stat": True},
        ],
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_parent_hashes": [
            {"path": str(source_bi4.resolve()), "reason": "parent v8 must hash exact owner BI4 immediately before materialising overlay prefix and after solver"},
            {"path": str(SOLVER.resolve()), "reason": "parent v8 must bind official solver binary"},
        ],
        "materialization": {
            "overlay_xml": str(overlay_path.resolve()),
            "overlay_prefix": str(prefix.resolve()),
            "source_bi4": str(source_bi4.resolve()),
            "required_action": "parent v8 guard creates one hardlink named overlay_prefix+'.bi4' after stable source hash; refuse symlink/copy mismatch",
            "source_bi4_sha256_expected": "PARENT_V8_GUARD_REQUIRED",
        },
        "launch_policy": {
            "launch_disabled": True,
            "execution_allowed": False,
            "solver_launch_owner": "root",
            "primary_gpu_dispatch_required": True,
            "gpu_uuid_authorization": "PENDING_PRIMARY_FRESH_UUID_LEASE",
            "protected_external_gpu": PROTECTED_GPU,
            "parent_guard": str(DISPATCH),
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": source_commit,
            "cpu_parent_binding": "required",
            "gpu_uuid_lease": "primary only; none granted in preparation",
            "source_output_protection": "new attempt output only; immutable GenCase/QA/support artifacts",
            "protected_gpu6": PROTECTED_GPU,
        },
        "scope": {
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "rung": token,
            "mode": mode,
            "full_physical_window": True,
            "solver_started": False,
            "gpu_started": False,
            "hdf5_read_in_preparation": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    path = REQUEST_ROOT / f"f1_s1_owner_{token.lower()}_{mode}_savedt_dense_v1.json"
    atomic_json(path, request)
    return path, request


def load_owner() -> dict[str, Any]:
    value = json.loads(OWNER.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("owner.json must be an object")
    if value.get("mass_kg") not in (OWNER_MASS_KG, None):
        raise ValueError(f"unexpected owner mass: {value.get('mass_kg')}")
    # Current owner records have varied nesting; verify the authoritative
    # dimensions if present without guessing missing geometry.
    raw = json.dumps(value, sort_keys=True)
    for required in ("0.4", "0.67", "0.15"):
        if required not in raw:
            raise ValueError(f"owner geometry token {required} absent from exact owner record")
    return value


def self_test() -> dict[str, Any]:
    load_owner()
    checks: list[dict[str, Any]] = []
    for key, case in CASES.items():
        source_xml = case["generated_root"] / "generated.xml"
        source = source_xml.read_text(encoding="utf-8")
        if re.findall(r'<cflnumber\b[^>]*\bvalue="([^"]+)"', source) != ["0.2", "0.2"]:
            raise AssertionError(f"{key}: source CFL")
        if "<savedt" in source:
            raise AssertionError(f"{key}: source already has savedt")
        for mode in ("same_cfl", "half_cfl"):
            path, diff = overlay(case, mode)
            text = path.read_text(encoding="utf-8")
            if text.count("<savedt") != 1:
                raise AssertionError(f"{key}/{mode}: savedt count")
            got = re.findall(r'<cflnumber\b[^>]*\bvalue="([^"]+)"', text)
            expected = ["0.2", "0.2"] if mode == "same_cfl" else ["0.1", "0.1"]
            if got != expected:
                raise AssertionError(f"{key}/{mode}: CFL {got} != {expected}")
            if not all(token in text for token in ("TimeMax", "gravity", "<motion")):
                raise AssertionError(f"{key}/{mode}: source controls missing")
            checks.append({"rung": key, "mode": mode, "overlay": str(path), "sha256": sha256_file(path), "edits": diff["declared_text_edits"]})
    return {"schema": SCHEMA, "status": "PASS_OWNER_MATCHED_OVERLAY_SELF_TEST", "checks": checks, "solver_started": False, "native_or_h5_read": False}


def prepare() -> dict[str, Any]:
    load_owner()
    commit = git_head()
    requests: list[dict[str, Any]] = []
    for _, case in CASES.items():
        for mode in ("same_cfl", "half_cfl"):
            overlay_path, diff = overlay(case, mode)
            path, request = request_for(case, mode, overlay_path, diff, commit)
            requests.append({"path": str(path.resolve()), "sha256": sha256_file(path),
                             "rung": case["token"], "mode": mode,
                             "storage_bytes": request["estimated_storage_bytes"],
                             "solver_started": False})
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_F1_S1_OWNER_MATCHED_SAVEDT_REQUESTS_LAUNCH_DISABLED",
        "generated_at_commit": commit,
        "owner": file_record(OWNER),
        "owner_mass_kg": OWNER_MASS_KG,
        "physical_window_s": [0.0, WINDOW_END_S],
        "save_interval_s": SAVE_INTERVAL_S,
        "rungs": [{"token": c["token"], "dp_m": c["dp_m"], "fluid_particles": c["fluid_particles"], "particles": c["particles"], "sample_mass_kg": c["sample_mass_kg"], "support_or_gencase_proof": str(c["proof"].resolve())} for c in CASES.values()],
        "requests": requests,
        "pair_dispatch_policy": "parent may schedule one full raw tree at a time; same/half CFL are distinct solver runs",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "solver_started": False,
        "gpu_started": False,
        "native_or_h5_read_by_builder": False,
    }
    atomic_json(REPORT, report)
    return {"report": REPORT, "requests": requests}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.prepare:
        parser.error("choose exactly one of --self-test or --prepare")
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
    else:
        result = prepare()
        print(json.dumps({"status": "PREPARED_F1_S1_OWNER_MATCHED_SAVEDT_REQUESTS_LAUNCH_DISABLED", "report": str(result["report"]), "requests": result["requests"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
