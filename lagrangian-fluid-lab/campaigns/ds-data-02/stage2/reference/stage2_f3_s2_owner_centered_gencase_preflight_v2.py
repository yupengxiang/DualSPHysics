#!/usr/bin/env python3
"""Build launch-disabled F3-S2 owner-centered GenCase preflight metadata.

This forward-only builder creates one new coarse XML representation and two
review requests.  It never invokes GenCase.  The dp=0.006 request points at
the already completed ROOT086 source clone and is explicitly reuse-only; the
dp=0.015 request is a bounded, owner-centered GenCase candidate whose actual
counts/mass/support remain UNKNOWN until a parent-guarded run.

The current XML and forcing file are source inputs.  The forcing file is
referenced by its already verified SHA and is not copied or re-hashed by this
builder.  Existing receipts and reports are provenance inputs only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.owner-centered-gencase-preflight.v2"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_XML = DATA_ROOT / (
    "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
    "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
    "prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
)
CURRENT_CONTROL = DATA_ROOT / (
    "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
    "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
    "prepared/pitch120_ay0750/CaseSloshingAccData.csv"
)
CURRENT_SOURCE_DEF = DATA_ROOT / (
    "families/F3/F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005/"
    "root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056/prepared/"
    "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005_Def.xml"
)
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
INPUT_ROOT = Path(__file__).with_name("stage2_f3_s2_owner_centered_gencase_inputs_v2")
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f3-s2-owner-centered-gencase-v2"
PLAN = Path(__file__).with_name("stage2_f3_s2_matched_three_grid_plan_v2.json")

FORCING_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
GENCASE_SHA = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
ROOT086_RECEIPT = DATA_ROOT / (
    "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/"
    "f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/execution-receipt.json"
)
ROOT086_SUPPORT = DATA_ROOT / (
    "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/"
    "f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/"
    "f3-s2-root086-vtk-support-qa-v2.json"
)
ROOT102_RECEIPT = DATA_ROOT / (
    "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/"
    "f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/execution-receipt.json"
)
ROOT104_SUPPORT = DATA_ROOT / (
    "families/F3/F3_S2_DP003_ACTUAL_INITIAL_SUPPORT_QA_ROOT_104/"
    "f3-s2-dp003-initial-support-qa-v1-root-104-001-root-forward-030-001/"
    "f3-s2-dp003-initial-support-qa-v1.json"
)
OWNER_LOW = (-0.45, -0.09, 0.0)
OWNER_SIZE = (0.9, 0.18, 0.09)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, known_sha: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": known_sha or sha256_file(path),
    }


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite consumed/new input: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def owner_phase(dp: float) -> dict[str, Any]:
    half = dp / 2.0
    return {
        "pointref_m": [half, half, half],
        "fluid_low_m": [OWNER_LOW[i] + half for i in range(3)],
        "fluid_size_m": [OWNER_SIZE[i] - dp for i in range(3)],
        "bound_low_m": [OWNER_LOW[i] - half for i in range(3)],
        "bound_size_m": [OWNER_SIZE[0] + dp, OWNER_SIZE[1] + dp, 0.51 + half],
        "bound_semantics": "closed x/y and bottom support envelope around the fixed 0.51 m tank; top remains open",
    }


def replace_once(data: bytes, pattern: bytes, replacement: bytes, label: str) -> bytes:
    updated, count = re.subn(pattern, replacement, data, count=1)
    if count != 1:
        raise ValueError(f"expected exactly one {label} replacement, found {count}")
    return updated


def derive_coarse_xml() -> tuple[Path, dict[str, Any]]:
    source = CURRENT_XML.read_bytes()
    phase = owner_phase(0.015)
    target = INPUT_ROOT / "coarse" / "F3_S2_OWNER_CENTERED_DP015.xml"
    updated = source
    updated = replace_once(updated, rb'<definition dp="0\.006"', rb'<definition dp="0.015"', "definition dp")
    updated = replace_once(
        updated,
        rb'<pointref x="0\.003" y="0\.003" z="0\.003"',
        b'<pointref x="0.0075" y="0.0075" z="0.0075"',
        "pointref",
    )
    updated = replace_once(
        updated,
        rb'<point x="-0\.447" y="-0\.087" z="0\.003" />',
        b'<point x="-0.4425" y="-0.0825" z="0.0075" />',
        "fluid point",
    )
    updated = replace_once(
        updated,
        rb'<size x="0\.894" y="0\.174" z="0\.084" />',
        b'<size x="0.885" y="0.165" z="0.075" />',
        "fluid size",
    )
    updated = replace_once(
        updated,
        rb'<point x="-0\.453" y="-0\.093" z="-0\.003" />',
        b'<point x="-0.4575" y="-0.0975" z="-0.0075" />',
        "bound point",
    )
    updated = replace_once(
        updated,
        rb'<size x="0\.906" y="0\.186" z="0\.513" />',
        b'<size x="0.915" y="0.195" z="0.5175" />',
        "bound size",
    )
    atomic_write(target, updated)
    return target, phase


def common_inputs(*, candidate_xml: Path | None) -> list[str]:
    values = [
        str(Path(__file__).resolve()),
        str(GENCASE),
        str(CURRENT_XML),
        str(CURRENT_CONTROL),
        str(CURRENT_SOURCE_DEF),
        str(ROOT086_RECEIPT),
        str(ROOT086_SUPPORT),
        str(ROOT102_RECEIPT),
        str(ROOT104_SUPPORT),
        str(PLAN),
    ]
    if candidate_xml is not None:
        values.append(str(candidate_xml))
    return values


def known_hashes(paths: list[str], *, candidate_xml: Path | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in paths:
        path = Path(value)
        if path == CURRENT_CONTROL:
            result[value] = FORCING_SHA
        elif path == GENCASE:
            result[value] = GENCASE_SHA
        else:
            result[value] = sha256_file(path)
    if candidate_xml is not None:
        result[str(candidate_xml)] = sha256_file(candidate_xml)
    return result


def base_request(case_id: str, attempt_id: str, command: list[str], inputs: list[str], hashes: dict[str, str], *, dp: float, phase: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "F3",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 134217728 if mode == "new_gencase" else 0,
        "worktree_root": str(REPO),
        "cwd": str((INPUT_ROOT / "coarse").resolve()),
        "command": command,
        "input_files": inputs,
        "input_hashes": hashes,
        "launch_disabled": True,
        "source_only": True,
        "solver_launch": False,
        "gpu": "none",
        "scope": {
            "sentinel_id": "F3-S2",
            "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
            "dp_m": dp,
            "owner_low_m": list(OWNER_LOW),
            "owner_size_m": list(OWNER_SIZE),
            "owner_mass_kg": 14.58,
            "phase": phase,
            "control_sha256": FORCING_SHA,
            "mass_policy": "native MassFluid, no rescale; preferred <=1%, hard >2%",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "mode": mode,
        },
        "preflight_contract": {
            "official_gencase_sha256": GENCASE_SHA,
            "expected_checks": [
                "generated XML actual dp and fluid blocks",
                "actual MassFluid and total/fixed/fluid counts",
                "finite Fluid/Bound points and Idp mapping",
                "fluid owner-envelope containment",
                "current XML/control normalized identity with only resolution fields changed",
            ],
            "no_physical_flux_or_no_penetration_credit": True,
            "parent_dispatch_required": True,
        },
    }


def build() -> dict[str, Path]:
    for path in (CURRENT_XML, CURRENT_CONTROL, CURRENT_SOURCE_DEF, GENCASE, ROOT086_RECEIPT, ROOT086_SUPPORT, ROOT102_RECEIPT, ROOT104_SUPPORT, PLAN):
        if not path.is_file():
            raise FileNotFoundError(path)
    coarse_xml, coarse_phase = derive_coarse_xml()
    coarse_prefix = str(coarse_xml.with_suffix(""))
    coarse_inputs = common_inputs(candidate_xml=coarse_xml)
    coarse_hashes = known_hashes(coarse_inputs, candidate_xml=coarse_xml)
    coarse = base_request(
        "F3_S2_OWNER_CENTERED_DP015_GENCASE_PREFLIGHT",
        "f3-s2-owner-centered-dp015-gencase-preflight-v2-root-prepared-001",
        [str(GENCASE), coarse_prefix, "{attempt_root}/generated", "-save:all", "-threads:1"],
        coarse_inputs,
        coarse_hashes,
        dp=0.015,
        phase=coarse_phase,
        mode="new_gencase",
    )
    coarse["candidate_registration"] = {
        "arithmetic_axis_counts": [60, 12, 6],
        "arithmetic_fluid_count": 4320,
        "arithmetic_sample_mass_kg": 14.58,
        "actual_count_status": "UNKNOWN_UNTIL_GENCASE",
        "arithmetic_values_are_not_a_gate": True,
        "candidate_xml": record(coarse_xml),
    }

    middle_inputs = common_inputs(candidate_xml=None)
    middle_hashes = known_hashes(middle_inputs, candidate_xml=None)
    middle = base_request(
        "F3_S2_OWNER_CENTERED_DP006_PREFLIGHT_REUSE",
        "f3-s2-owner-centered-dp006-preflight-reuse-v1-root-prepared-001",
        [str(GENCASE), str(CURRENT_SOURCE_DEF).removesuffix("_Def.xml"), "{attempt_root}/generated", "-save:all", "-threads:1"],
        middle_inputs,
        middle_hashes,
        dp=0.006,
        phase=owner_phase(0.006),
        mode="reuse_existing_receipt",
    )
    middle["reuse_existing_receipt"] = {
        "status": "DO_NOT_RERUN_IDENTITY",
        "gencase_receipt": record(ROOT086_RECEIPT),
        "support_report": record(ROOT086_SUPPORT),
        "actual_counts": {"fluid": 67500, "fixed": 111708, "total": 179208},
        "sample_mass_kg": 14.58,
        "reason": "ROOT086 already produced the exact owner-centered dp=0.006 current-source branch; use its actual receipt/support provenance and do not schedule a duplicate GenCase."
    }

    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    coarse_path = REQUEST_ROOT / "f3_s2_owner_centered_dp015_gencase_preflight_v2.json"
    middle_path = REQUEST_ROOT / "f3_s2_owner_centered_dp006_preflight_reuse_v2.json"
    atomic_write(coarse_path, json_bytes(coarse))
    atomic_write(middle_path, json_bytes(middle))
    manifest = {
        "schema": SCHEMA,
        "status": "BUILT_LAUNCH_DISABLED",
        "requests": [str(coarse_path), str(middle_path)],
        "coarse_candidate_xml": record(coarse_xml),
        "source_control_sha256": FORCING_SHA,
        "old_receipt_reuse": record(ROOT086_RECEIPT),
        "solver_started": False,
        "gencase_started": False,
    }
    manifest_path = REQUEST_ROOT / "manifest.json"
    atomic_write(manifest_path, json_bytes(manifest))
    return {"coarse": coarse_path, "middle": middle_path, "manifest": manifest_path, "xml": coarse_xml}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="write new XML and launch-disabled request metadata")
    args = parser.parse_args()
    if not args.build:
        parser.error("--build is required to create new immutable metadata")
    paths = build()
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
