#!/usr/bin/env python3
"""DS-DATA-02 F5 continuous 3-D wave/run-up generator.

F5 is built from the successful official WaveRunup input contract while giving
this campaign a fresh physical identity.  The two backgrounds are:

``runup_return``
    A finite-width 3-D tank with a continuous up-slope/crest/down-slope bed.
    A prescribed piston generates a long wave train that reaches the slope,
    climbs it, and is observed during the return phase.

``weir_pair``
    The same finite tank, bed, source and wave controls with a finite
    transverse weir.  Two side segments leave a real lateral slot.  Low and
    high crest variants are paired so that overtopping and no-overtopping are
    registered under the same source history and physical axes.

The module writes fresh XML definitions, control files, contracts, manifests,
pre-registrations and shared-runner requests.  It never starts GenCase or the
solver.  CPU GenCase requests must be submitted through the shared DS-DATA-02
runtime; GPU qualification requests are registered only after actual GenCase
receipts are bound.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ds-data-02.f5.generator.v1"
FAMILY_ID = "F5"
GENERATOR_VERSION = "ds_data02_f5.v1"
G = 9.81
RHO0 = 1000.0
EVENT_WINDOW_S = 16.0
REFERENCE_SAVE_INTERVAL_S = 0.02
EVENT_SAVE_INTERVAL_S = 0.005
INTERNAL_DT_S = 0.001
RESOLUTIONS = {"coarse": 0.030, "medium": 0.025, "fine": 0.020}
RESOLUTION_ORDER = ("coarse", "medium", "fine")

SCRIPT_PATH = Path(__file__).resolve()
LAB_ROOT = SCRIPT_PATH.parents[1]
CURRENT_WORKTREE = SCRIPT_PATH.parents[2]
HISTORICAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
if not HISTORICAL_ROOT.is_dir():
    HISTORICAL_ROOT = LAB_ROOT
OFFICIAL_ROOT = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup"
GENCASE = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
RAW_OUTPUT_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/case/attempt")
R3_REPORT = HISTORICAL_ROOT / "campaigns/v0.1-candidate/r3-f5-wave-runup.json"
R3_ALIGNMENT = HISTORICAL_ROOT / "campaigns/v0.1-candidate/r3-f5-reference-alignment.json"
D02_REUSE = HISTORICAL_ROOT / "campaigns/ds-data-01/D02_OFFICIAL_REUSE_RECEIPT.json"
D03_CARDS = HISTORICAL_ROOT / "campaigns/ds-data-01/D03_REFERENCE_CARDS.json"

OFFICIAL_INPUTS = {
    "definition": OFFICIAL_ROOT / "CaseWaveRunup_Def.xml",
    "motion": OFFICIAL_ROOT / "Mov_piston.dat",
    "slope": OFFICIAL_ROOT / "Slope.stl",
    "blocks": OFFICIAL_ROOT / "Blocks_3D_scaled.stl",
    "gauges": OFFICIAL_ROOT / "wg1234.txt",
    "external_reference": OFFICIAL_ROOT / "EXP_CaseWaveRunup_CIEMito.txt",
}

BACKGROUND_SPECS: dict[str, dict[str, Any]] = {
    "runup_return": {
        "mechanism_id": "runup_return",
        "name_zh": "斜坡爬升/退水：完整长时域波传播",
        "geometry_family_id": "F5_GEOM_SLOPE_BERM_RETURN_V1",
        "control_family_id": "F5_CTRL_OFFICIAL_PISTON_V1",
        "recipe_id": "F5_DBC_SLOPE_RUNUP_RETURN_V1",
        "description": "Finite 3-D side-wall tank, continuous up-slope/crest/down-slope bed, and return basin.",
        "weir": False,
        "source_mechanism": "main/17_WaveRunup prescribed piston and slope control",
    },
    "weir_pair": {
        "mechanism_id": "weir_pair",
        "name_zh": "越堤/未越堤配对：带真实侧向缺口的有限堤体",
        "geometry_family_id": "F5_GEOM_NOTCHED_WEIR_SIDE_SLOT_V1",
        "control_family_id": "F5_CTRL_OFFICIAL_PISTON_V1",
        "recipe_id": "F5_DBC_NOTCHED_WEIR_OVERTOP_RETURN_V1",
        "description": "The same continuous bed and wave source with a finite two-segment weir and lateral slot.",
        "weir": True,
        "source_mechanism": "main/17_WaveRunup prescribed piston and fresh notched-weir geometry",
    },
}

CONTROL_SPECS = {
    "regular_piston": {
        "control_family_id": "F5_CTRL_OFFICIAL_PISTON_V1",
        "name": "official_regular_piston",
        "description": "Copied official WaveRunup displacement samples, with amplitude scaling only.",
    },
    "single_packet": {
        "control_family_id": "F5_CTRL_SINGLE_PACKET_HOLDOUT_V1",
        "name": "single_packet_holdout",
        "description": "A single smooth finite wave packet with the same time grid and no late forcing.",
    },
}

# Exact source hashes from the immutable official package; source_audit verifies
# these before any family artifact is generated.
EXPECTED_OFFICIAL_HASHES = {
    "definition": "5f27b624f31b8f7e1bc8617c8c47af8675cac2f6da3b2f6aedf0b4da45553dac",
    "motion": "c8319af36ca85dd33e56b722d888d1646912b0f602577d73814fac267df26a2e",
    "slope": "bb6ed4811e1d24a05d72f2212b887fdc46ab354d93df13481618557333f95c90",
    "blocks": "528052692d4802601a7dbd92bfa9bcc00605559e1920628eadae3b76a39cf118",
    "gauges": "dd696418f14bfe26440b55bdefb43a5c12651670dd410ed0588db14053e2e609",
    "external_reference": "6195706559c8565e22dfef1afe7e5e72f4de3e5c7b4bb97133b71fe8ef88e7d6",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _q(value: float) -> str:
    text = f"{float(value):.9f}".rstrip("0").rstrip(".")
    return text or "0"


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(CURRENT_WORKTREE), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def _relative(path: Path, root: Path | None = None) -> str:
    path = Path(path).resolve()
    if root is not None:
        try:
            return path.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def _bind(path: Path, role: str, *, root: Path | None = None) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": _relative(path, root), "sha256": sha256_file(path), "bytes": path.stat().st_size, "role": role}


def _official_source_audit(*, strict: bool = True) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    missing: list[str] = []
    hash_mismatch: list[str] = []
    for key, path in OFFICIAL_INPUTS.items():
        if not path.is_file():
            missing.append(str(path))
            continue
        actual = sha256_file(path)
        expected = EXPECTED_OFFICIAL_HASHES[key]
        if actual != expected:
            hash_mismatch.append(f"{key}: expected {expected}, got {actual}")
        rows[key] = _bind(path, f"official WaveRunup source: {key}")
    if strict and (missing or hash_mismatch):
        raise FileNotFoundError("official F5 source audit failed: " + "; ".join(missing + hash_mismatch))
    return {
        "schema": "ds-data-02.f5.official-source-audit.v1",
        "source_root": str(OFFICIAL_ROOT),
        "official_inputs": rows,
        "missing": missing,
        "hash_mismatch": hash_mismatch,
        "status": "pass" if not missing and not hash_mismatch else "fail",
        "strict_hashes": True,
    }


def _historical_audit(*, strict: bool = True) -> dict[str, Any]:
    required = [R3_REPORT, R3_ALIGNMENT, D02_REUSE, D03_CARDS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing and strict:
        raise FileNotFoundError("F5 historical audit missing: " + ", ".join(missing))
    report = _json(R3_REPORT) if R3_REPORT.is_file() else {}
    alignment = _json(R3_ALIGNMENT) if R3_ALIGNMENT.is_file() else {}
    reuse = _json(D02_REUSE) if D02_REUSE.is_file() else {}
    cards = _json(D03_CARDS) if D03_CARDS.is_file() else {}
    prepared = report.get("prepared_cases", []) if isinstance(report, dict) else []
    runs = report.get("runs", []) if isinstance(report, dict) else []
    old_cases = []
    for row in prepared:
        old_cases.append({
            "label": row.get("label"),
            "dp_m": row.get("dp_m"),
            "fluid_particles": row.get("fluid_particles"),
            "total_particles": row.get("total_particles"),
            "status": row.get("status"),
            "reuse_status": "candidate_only_not_reused",
            "reason": "old generated XML/BI4/HDF5 is historical evidence and has a different identity",
        })
    run_rows = []
    for row in runs:
        run_rows.append({
            "label": row.get("label"),
            "dp_m": row.get("dp_m"),
            "frames": row.get("frames"),
            "time_end_s": row.get("external_gauge_summary", {}).get("gauges", {}).get("WG1", {}).get("time_end_s"),
            "excluded_particles": row.get("excluded_particles"),
            "status": row.get("status"),
            "reuse_status": "candidate_only_not_reused",
        })
    # The official historical reuse receipt includes these rows among nine
    # candidates.  Keep exact paths and status without promoting their output.
    official_rows = []
    for row in reuse.get("cases", []) if isinstance(reuse, dict) else []:
        if isinstance(row, dict) and str(row.get("case_id", "")).startswith("O5_"):
            official_rows.append({
                "case_id": row.get("case_id"),
                "generated_xml_sha256": row.get("generated_xml_sha256"),
                "normalized_hdf5": row.get("normalized_hdf5"),
                "provenance_status": row.get("provenance_status"),
                "reuse_status": "historical_candidate_only",
            })
    return {
        "schema": "ds-data-02.f5.history-reuse-inventory.v1",
        "generated_at_utc": utc_now(),
        "source_reports": [_relative(path, HISTORICAL_ROOT) for path in required],
        "status": "audit_complete" if not missing else "audit_partial",
        "missing_reports": missing,
        "official_historical_candidates": official_rows,
        "r3_runup_preflight": old_cases,
        "r3_runup_runs": run_rows,
        "r3_alignment": {
            "status": alignment.get("status"),
            "fixed_zero_offset_only": True,
            "local_shift_is_diagnostic": True,
            "external_reference_not_particle_truth": True,
        },
        "d03_scope": {
            "f5_official_runup": "exclude_from_core_or_candidate_requires_repair_or_reclassification",
            "reason": "large old runup exclusions and one refined identity gap are retained as negative evidence",
        },
        "reuse_policy": {
            "formal_reuse_count": 0,
            "old_generated_products_used_as_inputs": False,
            "old_hdf5_used_as_input": False,
            "old_model_or_tracer_revived": False,
            "new_f5_identity_required": True,
        },
        "source_hashes": {
            "r3_report": _bind(R3_REPORT, "historical R3 candidate-only report") if R3_REPORT.is_file() else None,
            "r3_alignment": _bind(R3_ALIGNMENT, "historical candidate-only alignment") if R3_ALIGNMENT.is_file() else None,
            "d02_reuse": _bind(D02_REUSE, "historical official reuse receipt") if D02_REUSE.is_file() else None,
            "d03_cards": _bind(D03_CARDS, "historical scope cards") if D03_CARDS.is_file() else None,
        },
        "read_only": True,
        "no_product_claim": True,
    }


def _copy_official_sources(family: Path) -> dict[str, Any]:
    target = family / "source_provenance"
    target.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Any] = {}
    for key, source in OFFICIAL_INPUTS.items():
        dest = target / source.name
        shutil.copy2(source, dest)
        copied[key] = _bind(dest, f"copied official source: {key}")
        copied[key]["source_hash"] = EXPECTED_OFFICIAL_HASHES[key]
    _write_json(target / "source_manifest.json", {"schema": "ds-data-02.f5.source-manifest.v1", "copied_at_utc": utc_now(), "sources": copied})
    return copied


def _bed_profile(slope_ratio: float = 0.28) -> list[tuple[float, float]]:
    """Return a continuous up/crest/down profile for a physical slope axis."""
    rise_at_crest = 3.0 * float(slope_ratio)
    return [
        (-1.10, 0.00),
        (3.55, 0.00),
        (5.15, (5.15 - 3.55) * float(slope_ratio)),
        (6.55, rise_at_crest),
        (7.15, rise_at_crest),
        (9.45, max(0.14, rise_at_crest - 0.47)),
        (10.50, 0.08),
        (10.85, 0.08),
    ]


BED_PROFILE = _bed_profile()
BED_Y_MIN = -0.72
BED_Y_MAX = 0.72
BED_BOTTOM = -0.24


def _facet(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> str:
    return "  facet normal 0 0 0\n    outer loop\n      vertex " + " ".join(_q(v) for v in a) + "\n      vertex " + " ".join(_q(v) for v in b) + "\n      vertex " + " ".join(_q(v) for v in c) + "\n    endloop\n  endfacet\n"


def _quad(facets: list[str], a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> None:
    facets.append(_facet(a, b, c))
    facets.append(_facet(a, c, d))


def _write_bed_stl(path: Path, *, slope_ratio: float = 0.28) -> dict[str, Any]:
    """Write a closed, finite-width 3-D bed with continuous piecewise slopes."""
    facets: list[str] = []
    y0, y1 = BED_Y_MIN, BED_Y_MAX
    profile = _bed_profile(slope_ratio)
    for (x0, z0), (x1, z1) in zip(profile[:-1], profile[1:]):
        _quad(facets, (x0, y0, z0), (x1, y0, z1), (x1, y1, z1), (x0, y1, z0))
        _quad(facets, (x1, y0, BED_BOTTOM), (x0, y0, BED_BOTTOM), (x0, y1, BED_BOTTOM), (x1, y1, BED_BOTTOM))
        _quad(facets, (x0, y0, BED_BOTTOM), (x1, y0, BED_BOTTOM), (x1, y0, z1), (x0, y0, z0))
        _quad(facets, (x1, y1, BED_BOTTOM), (x0, y1, BED_BOTTOM), (x0, y1, z0), (x1, y1, z1))
    x0, z0 = profile[0]
    x1, z1 = profile[-1]
    _quad(facets, (x0, y0, BED_BOTTOM), (x0, y1, BED_BOTTOM), (x0, y1, z0), (x0, y0, z0))
    _quad(facets, (x1, y0, BED_BOTTOM), (x1, y0, z1), (x1, y1, z1), (x1, y1, BED_BOTTOM))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "solid f5_continuous_bed\n" + "".join(facets) + "endsolid f5_continuous_bed\n"
    path.write_text(text, encoding="ascii")
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size, "facets": len(facets), "profile": profile, "slope_ratio": float(slope_ratio), "y_bounds_m": [BED_Y_MIN, BED_Y_MAX], "bottom_z_m": BED_BOTTOM}


def _slope_code(slope_ratio: float) -> str:
    return f"{float(slope_ratio):.3f}".replace(".", "p")


def _bed_asset_path(family: Path, slope_ratio: float) -> Path:
    return Path(family).resolve() / "definitions/assets" / f"f5_continuous_bed_profile_slope_{_slope_code(slope_ratio)}.stl"


def _read_official_motion() -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for line in OFFICIAL_INPUTS["motion"].read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(rows) < 100 or rows[0][0] != 0.0:
        raise ValueError("official piston control is unexpectedly short")
    return rows


def _write_motion(path: Path, *, scale: float = 1.0, control: str = "regular_piston") -> dict[str, Any]:
    source = _read_official_motion()
    rows: list[tuple[float, float]] = []
    for t in [i * 0.025 for i in range(int(EVENT_WINDOW_S / 0.025) + 1)]:
        if control == "regular_piston":
            if t <= source[-1][0] + 1e-9:
                j = min(int(round(t / 0.025)), len(source) - 1)
                value = source[j][1]
            else:
                value = 0.0
            value *= scale
        elif control == "single_packet":
            # A distinct control holdout: a single compact packet on the same
            # time grid, zero after 7.5 s so the 16 s return window remains.
            tau = t - 1.25
            envelope = math.exp(-0.5 * ((t - 3.20) / 1.15) ** 2)
            value = scale * 0.030 * math.sin(2.0 * math.pi * tau / 1.50) * envelope if 0.0 <= t <= 7.5 else 0.0
        else:
            raise ValueError(f"unknown control template: {control}")
        rows.append((t, value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{t:0.5f} {value:0.8f}\n" for t, value in rows), encoding="ascii")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "control_template": control,
        "scale": scale,
        "time_start_s": rows[0][0],
        "time_end_s": rows[-1][0],
        "row_count": len(rows),
        "dt_s": 0.025,
        "source_official_motion_sha256": EXPECTED_OFFICIAL_HASHES["motion"],
    }


def _solver_parameters(*, time_max: float = EVENT_WINDOW_S, time_out: float = REFERENCE_SAVE_INTERVAL_S) -> dict[str, Any]:
    return {
        "SavePosDouble": 0,
        "StepAlgorithm": 2,
        "VerletSteps": 40,
        "Kernel": 2,
        "ViscoTreatment": 1,
        "Visco": 0.01,
        "ViscoBoundFactor": 0,
        "DensityDT": 2,
        "DensityDTvalue": 0.1,
        "Shifting": 0,
        "ShiftCoef": -2,
        "ShiftTFS": 0,
        "RigidAlgorithm": 1,
        "FtPause": 0.0,
        "CoefDtMin": 0.05,
        "DtIni": 0,
        "DtMin": 0,
        "DtFixed": 0,
        "DtFixedFile": "NONE",
        "DtAllParticles": 0,
        "TimeMax": time_max,
        "TimeOut": time_out,
        "PartsOutMax": 1,
        "RhopOutMin": 700,
        "RhopOutMax": 1300,
    }


def _gauge_xml() -> str:
    gauges = [("WG1", 2.0), ("WG2", 3.1), ("WG3", 4.35), ("WG4", 5.45), ("RunupToe", 3.55), ("Crest", 6.70)]
    parts = []
    for name, x in gauges:
        parts.append(f'''                <swl name="{name}">
                    <pointdp coefdp="0.5" />
                    <point0 x="{_q(x)}" y="0" z="-0.02" />
                    <point2 x="{_q(x)}" y="0" z="1.25" />
                </swl>''')
    return "\n".join(parts)


def _parameter_xml(parameters: Mapping[str, Any]) -> str:
    rows = []
    for key, value in parameters.items():
        if isinstance(value, float):
            value = _q(value)
        rows.append(f'            <parameter key="{key}" value="{value}" />')
    return "\n".join(rows)


def _definition_xml(case: Mapping[str, Any]) -> str:
    dp = float(case["dp_m"])
    depth = float(case["initial_depth_m"])
    amplitude = float(case["amplitude_scale"])
    background = str(case["background"])
    motion_name = Path(str(case["motion_path"])).name
    weir = background == "weir_pair"
    crest_mode = str(case.get("crest_mode", "none"))
    crest_z = float(case.get("crest_z_m") or 0.0)
    slope_ratio = float(case.get("slope_ratio", 0.28))
    # The bed is a closed finite STL.  The explicit tank floor overlaps its
    # lower prism and sidewalls close the y boundaries, preventing accidental
    # periodic extrusion while preserving a continuous bed profile.
    weir_xml = ""
    if weir:
        low_y = float(case.get("notch_y0_m", 0.25))
        high_y = float(case.get("notch_y1_m", 0.50))
        base_z = float(case.get("weir_base_z_m", 0.32))
        weir_xml = f'''
          <setmkbound mk="50" />
          <drawbox cmt="weir_left_side_segment">
            <boxfill>solid</boxfill>
            <point x="4.96" y="-0.70" z="{_q(base_z)}" />
            <size x="0.24" y="{_q(low_y + 0.70)}" z="{_q(crest_z - base_z)}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <drawbox cmt="weir_right_side_segment">
            <boxfill>solid</boxfill>
            <point x="4.96" y="{_q(high_y)}" z="{_q(base_z)}" />
            <size x="0.24" y="{_q(0.70 - high_y)}" z="{_q(crest_z - base_z)}" />
            <layers vdp="0,1,2" />
          </drawbox>'''
    p = _solver_parameters()
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F5 fresh definition; mechanism={background}; physical_case_id={case["physical_case_id"]}; resolution={case["resolution"]} -->
<!-- Official WaveRunup control is copied and hash-bound; old generated products are not reused. -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="3" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="20" />
      <speedsound value="0" auto="true" />
      <coefh value="1.5" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="230" fluidcount="9">
      <mkorientfluid mk="0" orient="Xyz" />
    </mkconfig>
    <geometry>
      <definition dp="{_q(dp)}">
        <pointref x="0" y="0" z="0" />
        <pointmin x="-1.20" y="-0.86" z="-0.25" />
        <pointmax x="11.10" y="0.86" z="1.45" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>dp | actual | bound</setshapemode>
          <setdrawmode mode="solid" />
          <setmkbound mk="0" />
          <drawbox cmt="tank_floor">
            <boxfill>bottom</boxfill>
            <point x="-1.10" y="-0.80" z="-0.25" />
            <size x="11.90" y="1.60" z="0.25" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="30" />
          <drawbox cmt="finite_sidewall_left">
            <boxfill>solid</boxfill>
            <point x="-1.10" y="-0.80" z="-0.25" />
            <size x="11.90" y="0.08" z="1.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <drawbox cmt="finite_sidewall_right">
            <boxfill>solid</boxfill>
            <point x="-1.10" y="0.72" z="-0.25" />
            <size x="11.90" y="0.08" z="1.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="10" />
          <drawbox cmt="prescribed_piston">
            <boxfill>solid</boxfill>
            <point x="-1.08" y="-0.72" z="0" />
            <size x="0.08" y="1.44" z="1.02" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setdrawmode mode="full" />
          <setmkbound mk="40" />
          <drawfilestl file="assets/f5_continuous_bed_profile_slope_{_slope_code(slope_ratio)}.stl" />
          <shapeout file="continuous_bed" reset="true" />
          {weir_xml}
          <setmkfluid mk="0" />
          <fillbox x="2" y="0.18" z="0.10">
            <modefill>void</modefill>
            <point x="-0.90" y="-0.70" z="0.02" />
            <size x="4.20" y="1.40" z="{_q(depth)}" />
          </fillbox>
        </mainlist>
      </commands>
    </geometry>
    <motion>
      <objreal ref="10">
        <begin mov="1" start="0.00" finish="{_q(EVENT_WINDOW_S)}" />
        <mvpredef id="1" duration="{_q(EVENT_WINDOW_S)}">
          <file name="{motion_name}" fields="2" fieldtime="0" fieldx="1" />
        </mvpredef>
      </objreal>
    </motion>
  </casedef>
  <execution>
    <special>
      <gauges>
        <default>
          <savevtkpart value="true" />
          <_computedt value="{_q(REFERENCE_SAVE_INTERVAL_S)}" />
          <_computetime start="0" end="{_q(EVENT_WINDOW_S)}" />
          <output value="true" />
          <_outputdt value="{_q(REFERENCE_SAVE_INTERVAL_S)}" />
          <_outputtime start="0" end="{_q(EVENT_WINDOW_S)}" />
        </default>
{_gauge_xml()}
      </gauges>
    </special>
    <parameters>
{_parameter_xml(p)}
      <simulationdomain>
        <posmin x="-1.15" y="-0.84" z="-0.30" />
        <posmax x="11.00" y="0.84" z="1.45" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def _geometry_contract(case: Mapping[str, Any]) -> dict[str, Any]:
    slope_ratio = float(case.get("slope_ratio", 0.28))
    return {
        "coordinate_components": 3,
        "solver_dimension_required": 3,
        "boundary_semantics": "finite DBC floor, finite sidewalls, finite prescribed piston, continuous bed STL; no periodic y boundary",
        "bed_profile": _bed_profile(slope_ratio),
        "slope_ratio": slope_ratio,
        "bed_y_bounds_m": [BED_Y_MIN, BED_Y_MAX],
        "initial_fluid_box": {"x_min_m": -0.90, "x_max_m": 3.30, "y_min_m": -0.70, "y_max_m": 0.70, "z_min_m": 0.02, "z_max_m": 0.02 + float(case["initial_depth_m"])},
        "transverse_fluid_layers_expected": max(2, int(round(1.40 / float(case["dp_m"])))),
        "weir": {
            "present": case["background"] == "weir_pair",
            "crest_mode": case.get("crest_mode", "none"),
            "crest_z_m": case.get("crest_z_m"),
            "notch_y_interval_m": [case.get("notch_y0_m", 0.25), case.get("notch_y1_m", 0.50)] if case["background"] == "weir_pair" else None,
            "side_segments": 2 if case["background"] == "weir_pair" else 0,
            "finite_destination": "downstream bed and sidewall region is explicit; no post-hoc destination assignment",
        },
    }


def _case_id_hash(values: Mapping[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_case(*, case_id: str, background: str, resolution: str, amplitude_scale: float, initial_depth_m: float, slope_ratio: float, control_template: str, crest_mode: str = "none", pair_id: str | None = None, split: str = "unassigned", group_index: int | None = None, family: Path | None = None) -> dict[str, Any]:
    if background not in BACKGROUND_SPECS:
        raise ValueError(background)
    if resolution not in RESOLUTIONS:
        raise ValueError(resolution)
    if control_template not in CONTROL_SPECS:
        raise ValueError(control_template)
    if background == "weir_pair" and crest_mode not in {"overtop_target", "no_overtop_target"}:
        raise ValueError("weir pair requires an overtopping state")
    if background == "runup_return" and crest_mode != "none":
        raise ValueError("runup background has no weir state")
    dp = RESOLUTIONS[resolution]
    values = {
        "background": background,
        "resolution": resolution,
        "amplitude_scale": round(float(amplitude_scale), 8),
        "initial_depth_m": round(float(initial_depth_m), 8),
        "slope_ratio": round(float(slope_ratio), 8),
        "control_template": control_template,
        "crest_mode": crest_mode,
        "notch_y0_m": 0.25,
        "notch_y1_m": 0.50,
        "crest_z_m": 0.47 if crest_mode == "overtop_target" else (0.68 if crest_mode == "no_overtop_target" else None),
        "weir_base_z_m": 0.32 if crest_mode != "none" else None,
    }
    # Physical geometry is part of the identity: a slope change must produce a
    # different STL asset and physical hash, even when the source control is
    # unchanged.
    if background == "weir_pair":
        base_z = max(0.26, (4.96 - 3.55) * float(slope_ratio) - 0.03)
        crest_z = base_z + (0.11 if crest_mode == "overtop_target" else 0.36)
        values["weir_base_z_m"] = round(base_z, 8)
        values["crest_z_m"] = round(crest_z, 8)
    physical_hash = _case_id_hash({k: values[k] for k in values if k != "resolution"})
    physical_case_id = f"physical_F5_{physical_hash}"
    family = (Path(family) if family is not None else FAMILY_ROOT).resolve()
    defs = family / "definitions"
    motion_name = f"piston_{physical_hash}_{control_template}.dat"
    motion_path = defs / motion_name
    return {
        "schema": "ds-data-02.f5.case.v1",
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "lineage_group_id": f"lineage_{physical_case_id}",
        "paired_background_id": pair_id or f"F5_PAIR_{physical_hash[:8]}",
        "family_id": FAMILY_ID,
        "mechanism_id": background,
        "background": background,
        "geometry_family_id": BACKGROUND_SPECS[background]["geometry_family_id"],
        "control_family_id": CONTROL_SPECS[control_template]["control_family_id"],
        "recipe_id": BACKGROUND_SPECS[background]["recipe_id"],
        "resolution": resolution,
        "dp_m": dp,
        "amplitude_scale": float(amplitude_scale),
        "initial_depth_m": float(initial_depth_m),
        "slope_ratio": float(slope_ratio),
        "control_template": control_template,
        "crest_mode": crest_mode,
        "crest_z_m": values["crest_z_m"],
        "weir_base_z_m": values["weir_base_z_m"],
        "notch_y0_m": 0.25,
        "notch_y1_m": 0.50,
        "split": split,
        "group_index": group_index,
        "nested_membership": {"nested_8": bool(group_index is not None and group_index < 4), "nested_24": bool(group_index is not None and group_index < 12), "nested_48": bool(group_index is not None and group_index < 24)},
        "source_provenance_id": "official_main_17_wave_runup_plus_fresh_f5_geometry_v1",
        "definition_path": str((defs / f"{case_id}.xml").resolve()),
        "motion_path": str(motion_path.resolve()),
        "metadata_path": str((defs / f"{case_id}.metadata.json").resolve()),
        "geometry": _geometry_contract({"background": background, "initial_depth_m": initial_depth_m, "dp_m": dp, "slope_ratio": slope_ratio, "crest_mode": crest_mode, "crest_z_m": values["crest_z_m"], "weir_base_z_m": values["weir_base_z_m"], "notch_y0_m": 0.25, "notch_y1_m": 0.50}),
        "generation_status": "definition_registered_not_gencase_run",
        "qualification_status": "unqualified_until_actual_native_reference_evidence",
        "hdf5_path": None,
        "hdf5_sha256": None,
        "attempt_id": None,
    }


def materialize_case(case: Mapping[str, Any], family: Path, *, write_definition: bool = True) -> dict[str, Any]:
    family = Path(family).resolve()
    defs = family / "definitions"
    defs.mkdir(parents=True, exist_ok=True)
    assets = defs / "assets"
    bed_path = _bed_asset_path(family, float(case.get("slope_ratio", 0.28)))
    if not bed_path.is_file():
        _write_bed_stl(bed_path, slope_ratio=float(case.get("slope_ratio", 0.28)))
    motion_info = _write_motion(Path(str(case["motion_path"])), scale=float(case["amplitude_scale"]), control=str(case["control_template"]))
    definition = Path(str(case["definition_path"]))
    metadata = dict(case)
    metadata["motion"] = motion_info
    metadata["bed_asset"] = _bind(bed_path, "fresh F5 continuous bed STL")
    metadata["official_sources"] = {key: {**value, "expected_hash": EXPECTED_OFFICIAL_HASHES[key]} for key, value in _official_source_audit(strict=True)["official_inputs"].items()}
    metadata["definition_source"] = "freshly emitted F5 XML; official generated XML/BI4/HDF5 are excluded"
    if write_definition:
        definition.write_text(_definition_xml(case), encoding="utf-8")
    metadata["definition_sha256"] = sha256_file(definition)
    metadata["motion_sha256"] = motion_info["sha256"]
    metadata["bed_sha256"] = sha256_file(bed_path)
    metadata["written_at_utc"] = utc_now()
    _write_json(Path(str(case["metadata_path"])), metadata)
    return metadata


def _event_window() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f5.event-window.v1",
        "time_start_s": 0.0,
        "time_end_s": EVENT_WINDOW_S,
        "complete_window_required": True,
        "phases": [
            {"id": "initial_quiescent", "interval_s": [0.0, 0.5], "semantics": "initial fluid and finite boundaries before measurable incident wave"},
            {"id": "wave_generation", "interval_s": [0.0, 3.5], "semantics": "prescribed piston input; no output truncation"},
            {"id": "incident_propagation", "interval_s": [1.0, 5.5], "semantics": "wave reaches upstream gauges and slope toe in chronological order"},
            {"id": "slope_runup", "interval_s": [3.0, 10.0], "semantics": "free surface climbs the continuous slope; peak run-up is recorded"},
            {"id": "weir_passage", "interval_s": [4.0, 12.0], "semantics": "weir crest crossing and lateral-slot passage; right-censored if not reached"},
            {"id": "return_flow", "interval_s": [7.0, 15.5], "semantics": "downslope retreat, reverse toe crossing and downstream residence"},
            {"id": "terminal_accounting", "interval_s": [15.5, 16.0], "semantics": "final category, unknown mass and boundary/closure budget"},
        ],
        "crossing_rules": {
            "surface": "finite free-surface/run-up line crossing from z below to z above with linear interpolation between native saved frames",
            "crest": "signed distance to finite crest top; count first passage and every later signed recrossing separately",
            "return": "same physical line with negative direction; do not relabel a repeated crossing as new fluid",
            "right_censoring": "unseen events at 16 s are censored, not zero and not failed transport",
        },
        "background_specific": {
            "runup_return": ["toe_first_arrival", "runup_first_crossing", "runup_peak", "toe_return_crossing", "terminal_residence"],
            "weir_pair": ["toe_first_arrival", "crest_first_passage", "notch_first_passage", "overtop_or_no_overtop", "return_crossing", "terminal_destination"],
        },
    }


def _quality_contract() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f5.quality-contract.v1",
        "status": "thresholds_frozen_before_native_results",
        "physical_scale": {
            "gravity_m_s2": 9.81,
            "representative_depth_m": 0.40,
            "representative_height_m": 0.40,
            "characteristic_time_s": math.sqrt(0.40 / G),
            "longitudinal_domain_m": 11.9,
            "transverse_width_m": 1.60,
            "event_window_s": EVENT_WINDOW_S,
        },
        "q_i": {
            "solver_dimension": 3,
            "coordinate_components": 3,
            "positive_fluid_particles": True,
            "finite_active_position_velocity_density_mass": True,
            "monotone_finite_time": True,
            "initial_source_mass_positive": True,
            "fluid_y_extent_must_span": [0.90, 1.40],
            "finite_boundary_source_mks": [0, 10, 30, 40, 50],
            "gencase_mk_remapping": "GenCase may remap source mkbound blocks to solver mk values; actual fixed/moving block lists and counts are required in the receipt",
            "no_unregistered_periodic_y": True,
            "motion_control_hash_and_copy_required": True,
            "complete_horizon_required": True,
        },
        "q_n": {
            "scope": "recipe+geometry/control+time-window+observable+resolution",
            "macro_relative_error_budget": 0.05,
            "event_time_relative_error_budget": 0.02,
            "characteristic_event_time_s": math.sqrt(0.40 / G),
            "integration_error_share": 0.20,
            "save_error_share": 0.20,
            "mass_budget": 0.05,
            "required_reference": "all two backgrounds x three spatial resolutions plus independent integral/save controls",
            "no_claim_until_native": True,
        },
        "q_e": {"optional": True, "external_reference": "official CIEMito table retained as diagnostic only until independent review", "does_not_gate_native": True},
        "unknown_policy": "unknown mass is a separate terminal category and remains in the initial-mass denominator",
        "no_model_or_tracer_gate": True,
    }


def _integration_save_plan() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f5.integration-save-plan.v1",
        "sensitivity_background": "weir_pair",
        "sensitivity_case": "F5_REF_WEIR_NOMINAL_MEDIUM",
        "event_window_s": EVENT_WINDOW_S,
        "matrix_output_interval_s": REFERENCE_SAVE_INTERVAL_S,
        "controls": [
            {"id": "native_dt_native_save", "solver_dt": "native", "save_interval_s": REFERENCE_SAVE_INTERVAL_S, "purpose": "reference"},
            {"id": "half_native_dt_native_save", "solver_dt": "half_native", "save_interval_s": REFERENCE_SAVE_INTERVAL_S, "purpose": "independent integration sensitivity"},
            {"id": "native_dt_half_save", "solver_dt": "native", "save_interval_s": REFERENCE_SAVE_INTERVAL_S / 2.0, "purpose": "independent save sensitivity"},
            {"id": "native_dt_event_save", "solver_dt": "native", "save_interval_s": EVENT_SAVE_INTERVAL_S, "purpose": "event crossing sensitivity"},
        ],
        "downsampling_is_not_integration_study": True,
        "thresholds_frozen": True,
        "qualification_status": "none",
    }


def _candidate_records(family: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    axes = [(amp, depth, slope, control) for amp in (0.80, 1.00, 1.20) for depth in (0.34, 0.42) for slope in (0.22, 0.28) for control in ("regular_piston", "single_packet")]
    assert len(axes) == 24
    split_for_group = {**{i: "train" for i in range(0, 12)}, **{i: "validation" for i in range(12, 15)}, **{i: "id_test" for i in range(15, 18)}, **{i: "parameter_ood_test" for i in range(18, 21)}, **{i: "geometry_control_ood_test" for i in range(21, 24)}}
    for group_index, (amp, depth, slope, control) in enumerate(axes):
        # The final geometry/control holdout uses a steeper but still bounded
        # continuous bed; it is materialized as a distinct STL, not a label
        # change on the nominal mesh.
        if group_index >= 21:
            slope = 0.34 + 0.01 * (group_index - 21)
        split = split_for_group[group_index]
        pair_id = f"F5_PAIR_{group_index:02d}"
        crest_mode = "overtop_target" if group_index % 2 == 0 else "no_overtop_target"
        for background in ("runup_return", "weir_pair"):
            case_id = f"F5_{'RUNUP' if background == 'runup_return' else 'WEIR'}_{group_index:02d}"
            case = make_case(case_id=case_id, background=background, resolution="medium", amplitude_scale=amp, initial_depth_m=depth, slope_ratio=slope, control_template=control, crest_mode=crest_mode if background == "weir_pair" else "none", pair_id=pair_id, split=split, group_index=group_index, family=family)
            case["independent_physical_case"] = True
            case["pair_role"] = "slope_reference" if background == "runup_return" else crest_mode
            case["nested_level"] = "nested_8" if group_index < 4 else ("nested_24" if group_index < 12 else "nested_48")
            case["source_control_contract"] = "regular official motion or pre-registered single-packet holdout; control is never changed after result observation"
            records.append(case)
    return records


def _split_plan(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["split"]) for row in records)
    groups = {}
    for row in records:
        groups.setdefault(str(row["paired_background_id"]), {"split": row["split"], "case_ids": []})["case_ids"].append(row["case_id"])
    return {
        "schema": "ds-data-02.f5.split-plan.v1",
        "status": "pre_registered_development_and_test_candidates",
        "counts": dict(counts),
        "expected_counts": {"train": 24, "validation": 6, "id_test": 6, "parameter_ood_test": 6, "geometry_control_ood_test": 6},
        "pair_preserving": True,
        "group_count": len(groups),
        "nested_cases": {"nested_8": 8, "nested_24": 24, "nested_48": 48},
        "group_assignments": groups,
        "parameter_ood": "amplitude/depth combinations outside train support but within the frozen numeric range",
        "geometry_control_ood": "steeper geometry and single-packet control combinations reserved as geometry/control holdout",
        "hidden_test_claim": False,
        "resolution_and_time_views_do_not_add_case_count": True,
    }


def _label_schema() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f5.label-schema.v1",
        "status": "frozen_before_native_results",
        "required_arrays": ["time_s", "particle_id", "particle_zone", "valid", "position_m", "velocity_m_s", "mass_kg", "density_kg_m3", "source_label", "destination_time_series", "first_passage_interval", "residence_time_s", "final_category", "failure_reason", "unknown_mass_kg"],
        "source_labels": ["upstream_reservoir", "piston_adjacent", "slope_toe_band", "lateral_notch_adjacent"],
        "destination_categories": ["upstream_return", "slope_retained", "crest_overtopped", "lateral_notch_passage", "downstream_retained", "inflight_at_end", "unknown_native_exclusion"],
        "mass_denominator": "initial native fluid mass from GenCase, not survivors",
        "repeated_crossing": "signed net and absolute crossing counts are both retained; repeated crossings do not create new material",
        "unknown_not_zero": True,
        "open_boundary": False,
        "tracer_claim": False,
    }


def _write_labels_preview(family: Path) -> dict[str, str]:
    labels = family / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    _write_json(labels / "label_schema.json", _label_schema())
    (labels / "README.md").write_text("""# F5 native transport labels\n\nThe schema is frozen before native results. Source labels follow the initial upstream fluid bands; destination time series and repeated signed crossings are computed from native states. Unknown mass remains explicit in the initial-mass denominator. No material tracer or model is required.\n\nNative arrays and HDF5 paths are pending solver qualification and are never fabricated by this generator.\n""", encoding="utf-8")
    preview = family / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    (preview / "README.md").write_text("""# F5 preview contract\n\nRequired after native solver output: initial state, incident wave at WG1/WG2, slope run-up peak, crest or lateral-slot passage, return-flow frame, and terminal mass/destination frame plus an animation covering 0--16 s. This directory intentionally contains no metadata-only claim of having seen the flow.\n""", encoding="utf-8")
    return {"label_schema": str(labels / "label_schema.json"), "preview_readme": str(preview / "README.md")}


def preflight_definition(definition_path: str | Path, metadata_path: str | Path | None = None, *, require_sources: bool = True) -> dict[str, Any]:
    path = Path(definition_path).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return {"schema": "ds-data-02.f5.input-preflight.v1", "status": "fail", "definition_path": str(path), "errors": ["definition missing"], "warnings": []}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"schema": "ds-data-02.f5.input-preflight.v1", "status": "fail", "definition_path": str(path), "errors": [f"invalid XML: {exc}"], "warnings": []}
    definition = root.find("./casedef/geometry/definition")
    if definition is None or float(definition.attrib.get("dp", "0")) <= 0:
        errors.append("positive geometry dp is required")
    if root.find("./casedef/constantsdef/gravity") is None:
        errors.append("gravity missing")
    if root.find("./casedef/geometry/commands/mainlist/fillbox") is None:
        errors.append("fluid fillbox missing")
    fill = root.find("./casedef/geometry/commands/mainlist/fillbox")
    if fill is not None:
        size = fill.find("size")
        if size is None or any(float(size.attrib.get(axis, "0")) <= 0 for axis in ("x", "y", "z")):
            errors.append("fluid fillbox must have positive 3-D extent")
    commands = root.findall("./casedef/geometry/commands/mainlist/*")
    stl_files = [node.attrib.get("file") for node in commands if node.tag == "drawfilestl"]
    if not stl_files:
        errors.append("continuous 3-D bed STL is required")
    for value in stl_files:
        if not (path.parent / value).is_file():
            errors.append(f"bed asset missing: {value}")
    sidewall_names = {node.attrib.get("cmt") for node in commands if node.tag == "drawbox"}
    if not {"finite_sidewall_left", "finite_sidewall_right"}.issubset(sidewall_names):
        errors.append("both finite sidewalls are required")
    if any(node.tag == "parameter" and node.attrib.get("key") == "YPeriodicIncZ" for node in root.findall(".//parameter")):
        errors.append("periodic-y shortcut is forbidden for F5 finite lateral transport")
    time_values = {node.attrib.get("key"): float(node.attrib.get("value", "nan")) for node in root.findall(".//parameter") if node.attrib.get("key") in {"TimeMax", "TimeOut"}}
    if abs(time_values.get("TimeMax", -1) - EVENT_WINDOW_S) > 1e-9:
        errors.append("TimeMax must cover the full 16 s event window")
    if abs(time_values.get("TimeOut", -1) - REFERENCE_SAVE_INTERVAL_S) > 1e-9:
        errors.append("TimeOut must be the frozen 0.02 s reference cadence")
    motion_file = root.find("./casedef/motion/objreal/mvpredef/file")
    if motion_file is None:
        errors.append("piston motion file missing")
    elif not (path.parent / motion_file.attrib.get("name", "")).is_file():
        errors.append("piston motion file cannot be resolved beside definition")
    if metadata_path is not None:
        meta_path = Path(metadata_path).resolve()
        if not meta_path.is_file():
            errors.append("metadata missing")
        else:
            metadata = _json(meta_path)
            if metadata.get("generation_status") != "definition_registered_not_gencase_run":
                warnings.append("metadata generation status was changed before native receipt")
            if require_sources and metadata.get("official_sources") is None:
                errors.append("official source hashes missing")
            if metadata.get("geometry", {}).get("coordinate_components") != 3:
                errors.append("metadata does not declare three coordinate components")
    return {
        "schema": "ds-data-02.f5.input-preflight.v1",
        "status": "pass" if not errors else "fail",
        "definition_path": str(path),
        "definition_sha256": sha256_file(path),
        "errors": errors,
        "warnings": warnings,
        "actual_native_evidence": False,
        "solver_invoked": False,
    }


def _matrix_cases(family: Path) -> list[dict[str, Any]]:
    specs = [
        ("runup_return", "F5_REF_RUNUP_NOMINAL", "none"),
        ("weir_pair", "F5_REF_WEIR_NOMINAL", "overtop_target"),
    ]
    rows = []
    for background, stem, crest_mode in specs:
        for resolution in RESOLUTION_ORDER:
            case = make_case(case_id=f"{stem}_{resolution.upper()}", background=background, resolution=resolution, amplitude_scale=1.0, initial_depth_m=0.40, slope_ratio=0.28, control_template="regular_piston", crest_mode=crest_mode, pair_id="F5_REFERENCE_PAIR_NOMINAL", split="reference", group_index=None, family=family)
            metadata = materialize_case(case, family)
            case = dict(case)
            case.update({"definition_sha256": metadata["definition_sha256"], "motion_sha256": metadata["motion_sha256"], "bed_sha256": metadata["bed_sha256"], "metadata_sha256": sha256_file(Path(case["metadata_path"]))})
            rows.append(case)
    return rows


def write_family_design(family_dir: str | Path, *, strict_source: bool = True) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    family.mkdir(parents=True, exist_ok=True)
    source_audit = _official_source_audit(strict=strict_source)
    history = _historical_audit(strict=strict_source)
    _write_json(family / "history_reuse_inventory.json", history)
    copied_sources = _copy_official_sources(family)
    bed_info = _write_bed_stl(_bed_asset_path(family, 0.28), slope_ratio=0.28)
    # Freeze both control templates at the family boundary before any result.
    control_files = {}
    for template in CONTROL_SPECS:
        info = _write_motion(family / "definitions" / f"control_{template}.dat", scale=1.0, control=template)
        control_files[template] = info
    records = _candidate_records(family)
    for row in records:
        # Registry rows point at a deterministic materialization recipe; the
        # 48 candidate definitions are generated only when a production batch
        # is authorized, so no resolution or preview is miscounted as a case.
        row["generator"] = str(SCRIPT_PATH)
        row["materialization"] = {"command": "ds_data02_f5.py materialize", "status": "registered_not_materialized", "resolution_views": list(RESOLUTION_ORDER)}
        row["control_source_hash"] = EXPECTED_OFFICIAL_HASHES["motion"] if row["control_template"] == "regular_piston" else control_files["single_packet"]["sha256"]
        row["bed_asset_path"] = str(_bed_asset_path(family, float(row["slope_ratio"])).resolve())
        row["bed_source_hash"] = None
    (family / "case_registry.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records), encoding="utf-8")
    _write_json(family / "split_plan.json", _split_plan(records))
    manifests = []
    manifest_dir = family / "case_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for row in records:
        manifest = dict(row)
        manifest.update({
            "manifest_schema": "ds-data-02.f5.case-manifest.v1",
            "hdf5": {"path": None, "sha256": None, "status": "pending_native_solver"},
            "native_attempt": {"attempt_id": None, "runner_receipt": None, "returncode": None},
            "labels": {"status": "pending_native_solver", "path": None, "sha256": None},
            "quality": {"q_i": "pending_native_solver", "q_n": "not_assessed", "q_e": "optional_not_assessed"},
            "physical_case_id_is_independent": True,
            "not_a_resolution_case": True,
        })
        out = manifest_dir / f"{row['case_id']}.json"
        _write_json(out, manifest)
        manifests.append(str(out))
    matrix_rows = _matrix_cases(family)
    matrix_preflight = [preflight_definition(row["definition_path"], row["metadata_path"], require_sources=True) for row in matrix_rows]
    matrix = {
        "schema": "ds-data-02.f5.reference-matrix.v1",
        "status": "definitions_written_preflight_only",
        "qualification_claim": "none",
        "event_window_s": EVENT_WINDOW_S,
        "backgrounds": list(BACKGROUND_SPECS),
        "resolutions": RESOLUTIONS,
        "matrix": matrix_rows,
        "preflight": matrix_preflight,
        "all_preflight": all(row["status"] == "pass" for row in matrix_preflight),
        "native_evidence": False,
        "q_n_status": "not_assessed",
        "production_status": "closed_until_primary_process",
    }
    _write_json(family / "definitions/reference_matrix.json", matrix)
    _write_json(family / "event_definitions.json", _event_window())
    _write_json(family / "quality_contract.json", _quality_contract())
    _write_json(family / "integration_save_plan.json", _integration_save_plan())
    _write_json(family / "source_audit.json", source_audit)
    _write_json(family / "qualified_recipes.json", {
        "schema": "ds-data-02.f5.qualified-recipes.v1",
        "qualification_claim": "none",
        "recipes": [{"background": key, "recipe_id": value["recipe_id"], "qualified": False, "required_scope": "recipe+geometry/control+16s+native observations+resolution", "evidence": None} for key, value in BACKGROUND_SPECS.items()],
        "q_e_optional": True,
        "models_or_tracers_required": False,
    })
    label_preview = _write_labels_preview(family)
    family_card = {
        "schema": "ds-data-02.f5.family-card.v1",
        "family_id": FAMILY_ID,
        "generator": str(SCRIPT_PATH),
        "generator_version": GENERATOR_VERSION,
        "status": "definition_ready_waiting_shared_runner",
        "qualification_claim": "none",
        "mechanisms": BACKGROUND_SPECS,
        "physical_axes": ["amplitude_scale", "initial_depth_m", "slope_ratio", "crest_state", "control_template"],
        "geometry": "finite-width 3-D tank, continuous bed profile, finite sidewalls, and a two-segment lateral-slot weir",
        "event_window_s": EVENT_WINDOW_S,
        "resolution_ladder_m": RESOLUTIONS,
        "reference_matrix": {"background_count": 2, "resolution_count": 3, "case_count": 6, "unique_physical_cases": 2},
        "registry": {"independent_physical_cases": len(records), "nested_8": 8, "nested_24": 24, "nested_48": 48, "split_counts": dict(Counter(row["split"] for row in records))},
        "official_source_audit": source_audit,
        "copied_source_files": copied_sources,
        "fresh_bed_asset": bed_info,
        "control_files": control_files,
        "historical_reuse": {"formal_reuse_count": 0, "candidate_only": True},
        "quality": {"q_i": "thresholds frozen; native evidence pending", "q_n": "not assessed", "q_e": "optional"},
        "no_model": True,
        "no_tracer_gate": True,
    }
    _write_json(family / "family_card.json", family_card)
    handoff = f'''# F5 family handoff\n\nF5 is a fresh DS-DATA-02 3-D wave/run-up family.  The historical official WaveRunup and R3 16 s/801-frame runs were audited as candidate-only evidence.  Their generated XML/BI4/HDF5 and trajectory data are not reused as native inputs; the formal reuse count is zero.\n\nThe `runup_return` background uses a finite-width tank with a closed continuous bed profile that rises from the upstream floor to a crest and descends into a downstream return region.  The `weir_pair` background keeps the same bed, source and piston control but adds a finite two-segment transverse weir.  The segments leave a 0.25 m lateral slot, so sidewise transport is an explicit geometry event.  Alternating pre-registered crest states define paired overtopping and no-overtopping targets.\n\nThe piston control is copied from the official 17_WaveRunup motion source on a 0.025 s grid through 15.6 s and held at zero through the 16 s window.  A single-packet control template is frozen as a control holdout.  The reference ladder is dp=0.030/0.025/0.020 m; all matrix rows use TimeMax=16 s and TimeOut=0.02 s.  Thresholds, event crossings, initial-mass denominator, unknown handling, and independent integral/save controls were written before any native result.\n\nThe registry has 48 independent physical cases, pair-preserving splits train=24, validation=6, ID test=6, parameter-OOD=6 and geometry/control-OOD=6.  Resolution, integration, save and preview views do not add cases.\n\nNo solver, GPU or native labels were launched by this family.  The next executable task is to submit the two bounded CPU GenCase requests through the shared runtime, then bind actual 3-D particle/mass/side-layer/boundary/control evidence before registering qualification requests.\n'''
    (family / "FAMILY_HANDOFF.md").write_text(handoff, encoding="utf-8")
    return {"family_dir": str(family), "family_card": str(family / "family_card.json"), "matrix": matrix, "registry_count": len(records), "manifests": len(manifests), "labels": label_preview, "git_commit": _git_commit()}


def _request_inputs(row: Mapping[str, Any], family: Path, history_path: Path) -> list[str]:
    metadata = Path(row["metadata_path"]).resolve()
    definition = Path(row["definition_path"]).resolve()
    motion = Path(row["motion_path"]).resolve()
    bed = _bed_asset_path(family, float(row.get("slope_ratio", 0.28)))
    source_manifest = family / "source_provenance/source_manifest.json"
    return [str(SCRIPT_PATH), str(history_path), str(family / "family_card.json"), str(family / "quality_contract.json"), str(family / "event_definitions.json"), str(family / "integration_save_plan.json"), str(family / "case_registry.jsonl"), str(family / "definitions/reference_matrix.json"), str(definition), str(metadata), str(motion), str(bed), str(source_manifest)]


def _gencase_request(*, family: Path, row: Mapping[str, Any], history_path: Path, attempt_id: str) -> dict[str, Any]:
    definition = Path(row["definition_path"]).resolve()
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": row["case_id"],
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{row['case_id']}", "-save:all"],
        "cwd": str(definition.parent),
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "input_files": _request_inputs(row, family, history_path),
        "worktree_root": str(CURRENT_WORKTREE),
        "launch_commit": _git_commit(),
        "source_mother": row["background"],
        "definition_sha256": row["definition_sha256"],
        "motion_sha256": row["motion_sha256"],
        "geometry_asset_sha256": row["bed_sha256"],
        "event_window_s": EVENT_WINDOW_S,
        "generation_status": "definition_written_not_gencase_run",
        "solver_launch_forbidden": True,
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "request_note": "Submit only through the shared DS-DATA-02 runtime; CPU GenCase preflight only.",
    }


def write_runner_requests(family_dir: str | Path, *, launch_commit: str | None = None) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    matrix = _json(family / "definitions/reference_matrix.json")
    if not matrix.get("all_preflight"):
        raise ValueError("F5 reference matrix preflight failed")
    history_path = family / "history_reuse_inventory.json"
    specs = [("runup_return", "F5_REF_RUNUP_NOMINAL_COARSE", "gencase_runup_request.json", "gencase-f5-runup-coarse-v1"), ("weir_pair", "F5_REF_WEIR_NOMINAL_COARSE", "gencase_weir_request.json", "gencase-f5-weir-coarse-v1")]
    requests: dict[str, str] = {}
    for background, case_id, filename, attempt_id in specs:
        row = next(item for item in matrix["matrix"] if item["background"] == background and item["resolution"] == "coarse")
        request = _gencase_request(family=family, row=row, history_path=history_path, attempt_id=attempt_id)
        if launch_commit:
            request["launch_commit"] = launch_commit
        path = family / filename
        _write_json(path, request)
        requests[filename] = str(path)
    index = {
        "schema": "ds-data-02.f5.runner-request-index.v1",
        "family_id": FAMILY_ID,
        "launch_commit": launch_commit or _git_commit(),
        "resource_guard": {"solver_invoked_by_generator": False, "gpu_launch_allowed_here": False, "cpu_threads_max": 4, "max_wall_seconds": 300, "storage_bytes_max": 256 * 1024 * 1024, "shared_runner_required": True, "foreign_processes_protected": True},
        "cpu_preflight_requests": requests,
        "qualification_requests": "registered after each completed GenCase receipt; no GPU launch here",
        "reference_matrix": {"background_count": 2, "resolution_count_per_background": 3, "case_count": 6, "independent_physical_case_count": 2, "resolution_views_are_not_independent": True},
        "qualification_scope_claim": "none until native receipts and Q-I/Q-N evidence",
        "production_claim": "none",
    }
    _write_json(family / "runner_request.json", index)
    index["path"] = str(family / "runner_request.json")
    index["sha256"] = sha256_file(family / "runner_request.json")
    return index


def _parse_gencase_facts(receipt: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    output_root = Path(str(receipt["output_root"])).resolve()
    stdout_path = output_root / "stdout.log"
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
    def num(pattern: str) -> int | None:
        match = re.search(pattern, stdout)
        return int(match.group(1).replace(",", "")) if match else None
    generated_prefix = output_root / row["case_id"]
    generated_xml = generated_prefix.with_suffix(".xml")
    generated_bi4 = generated_prefix.with_suffix(".bi4")
    copied_motion = output_root / Path(row["motion_path"]).name
    fluid_vtk = next(iter(output_root.glob("*_Fluid.vtk")), None)
    facts: dict[str, Any] = {
        "output_root": str(output_root),
        "input_prefix": str(generated_prefix),
        "generated_xml": {"path": str(generated_xml), "exists": generated_xml.is_file(), "sha256": sha256_file(generated_xml) if generated_xml.is_file() else None, "bytes": generated_xml.stat().st_size if generated_xml.is_file() else None},
        "generated_bi4": {"path": str(generated_bi4), "exists": generated_bi4.is_file(), "sha256": sha256_file(generated_bi4) if generated_bi4.is_file() else None, "bytes": generated_bi4.stat().st_size if generated_bi4.is_file() else None},
        "copied_motion": {"path": str(copied_motion), "exists": copied_motion.is_file(), "sha256": sha256_file(copied_motion) if copied_motion.is_file() else None, "bytes": copied_motion.stat().st_size if copied_motion.is_file() else None},
        "total_particles_stdout": num(r"Total particles:\s*([\d,]+)"),
        "fluid_particles_stdout": num(r"Fluid\.+:\s*([\d,]+)"),
        "fixed_particles_stdout": num(r"Fixed\.+:\s*([\d,]+)"),
        "moving_particles_stdout": num(r"Moving\.+:\s*([\d,]+)"),
        "stdout_sha256": sha256_file(stdout_path) if stdout_path.is_file() else None,
    }
    if fluid_vtk is not None:
        facts["fluid_vtk"] = {"path": str(fluid_vtk), "sha256": sha256_file(fluid_vtk), "bytes": fluid_vtk.stat().st_size}
        facts["fluid_vtk_bounds_m"] = _vtk_point_bounds(fluid_vtk)
    if generated_xml.is_file():
        try:
            tree = ET.parse(generated_xml)
            root = tree.getroot()
            data2d = root.find(".//constants/data2d")
            particles = root.find(".//particles")
            pos = root.find(".//particles/_summary/positions")
            pos_min = pos.find("posmin") if pos is not None else None
            pos_max = pos.find("posmax") if pos is not None else None
            constants = root.find(".//constants")
            facts["solver_dimension_from_gencase"] = 2 if data2d is not None and data2d.attrib.get("value") == "true" else 3
            fixed_nodes = root.findall(".//particles/fixed")
            moving_nodes = root.findall(".//particles/moving")
            facts["generated_xml_summary"] = {
                "particles_np": int(particles.attrib.get("np", "0")) if particles is not None else None,
                "particles_nb": int(particles.attrib.get("nb", "0")) if particles is not None else None,
                "particles_nbf": int(particles.attrib.get("nbf", "0")) if particles is not None else None,
                "massfluid_kg": float(constants.find("massfluid").attrib.get("value")) if constants is not None and constants.find("massfluid") is not None else None,
                "massbound_kg": float(constants.find("massbound").attrib.get("value")) if constants is not None and constants.find("massbound") is not None else None,
                "position_bounds_m": ({"min": {key: float(pos_min.attrib[key]) for key in ("x", "y", "z") if pos_min is not None and key in pos_min.attrib}, "max": {key: float(pos_max.attrib[key]) for key in ("x", "y", "z") if pos_max is not None and key in pos_max.attrib}} if pos is not None else {}),
                "fixed_boundary_blocks": [dict(node.attrib) for node in fixed_nodes],
                "moving_boundary_blocks": [dict(node.attrib) for node in moving_nodes],
                "actual_fixed_mk_values": [int(node.attrib["mk"]) for node in fixed_nodes if "mk" in node.attrib],
                "actual_moving_mk_values": [int(node.attrib["mk"]) for node in moving_nodes if "mk" in node.attrib],
            }
            if pos_min is not None and pos_max is not None and "y" in pos_min.attrib and "y" in pos_max.attrib:
                facts["fluid_transverse_extent_m"] = {"min": float(pos_min.attrib["y"]), "max": float(pos_max.attrib["y"])}
            fluid_count = facts.get("fluid_particles_stdout") or facts["generated_xml_summary"].get("particles_np", 0) - facts["generated_xml_summary"].get("particles_nb", 0)
            massfluid = facts["generated_xml_summary"].get("massfluid_kg") or 0.0
            facts["initial_fluid_mass_kg"] = float(fluid_count) * float(massfluid)
        except (ET.ParseError, ValueError, TypeError) as exc:
            facts["generated_xml_parse_error"] = str(exc)
    motion_audit = _motion_audit(copied_motion if copied_motion.is_file() else Path(row["motion_path"]))
    facts["motion_audit"] = motion_audit
    facts["native_artifacts_complete"] = all(item["exists"] for item in (facts["generated_xml"], facts["generated_bi4"], facts["copied_motion"]))
    facts["three_dimensional"] = facts.get("solver_dimension_from_gencase") == 3
    facts["nonzero_fluid"] = int(facts.get("fluid_particles_stdout") or 0) > 0
    summary = facts.get("generated_xml_summary", {})
    facts["finite_boundary_and_control"] = bool(facts.get("fixed_particles_stdout", 0) and facts.get("moving_particles_stdout", 0) and summary.get("fixed_boundary_blocks") and summary.get("moving_boundary_blocks") and facts.get("motion_audit", {}).get("finite"))
    return facts


def _vtk_point_bounds(path: Path) -> dict[str, Any] | None:
    """Read only the binary VTK POINTS block for an actual fluid extent audit."""
    data = Path(path).read_bytes()
    marker = b"POINTS "
    start = data.find(marker)
    if start < 0:
        return None
    line_end = data.find(b"\n", start)
    if line_end < 0:
        return None
    header = data[start:line_end].decode("ascii", errors="replace").split()
    if len(header) < 3 or header[2].lower() != "float":
        return None
    try:
        count = int(header[1])
    except ValueError:
        return None
    payload_start = line_end + 1
    payload_end = payload_start + count * 3 * 4
    if payload_end > len(data):
        return None
    values = struct.unpack(f">{count * 3}f", data[payload_start:payload_end])
    xs = values[0::3]
    ys = values[1::3]
    zs = values[2::3]
    return {"count": count, "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)], "finite": all(math.isfinite(value) for value in values)}


def _motion_audit(path: Path) -> dict[str, Any]:
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    rows.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
    return {"path": str(path), "rows": len(rows), "time_start_s": rows[0][0] if rows else None, "time_end_s": rows[-1][0] if rows else None, "finite": bool(rows) and all(math.isfinite(t) and math.isfinite(x) for t, x in rows), "monotone_time": all(b[0] > a[0] for a, b in zip(rows[:-1], rows[1:])), "max_abs_displacement_m": max((abs(x) for _, x in rows), default=None)}


def record_gencase_receipts(family_dir: str | Path, runup_receipt: str | Path, weir_receipt: str | Path) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    matrix_path = family / "definitions/reference_matrix.json"
    matrix = _json(matrix_path)
    receipt_rows = []
    for background, receipt_path, case_id in (("runup_return", Path(runup_receipt), "F5_REF_RUNUP_NOMINAL_COARSE"), ("weir_pair", Path(weir_receipt), "F5_REF_WEIR_NOMINAL_COARSE")):
        receipt = _json(receipt_path)
        row = next(item for item in matrix["matrix"] if item["background"] == background and item["resolution"] == "coarse")
        facts = _parse_gencase_facts(receipt, row)
        quality = {
            "completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "actual_3d": facts.get("three_dimensional") is True,
            "nonzero_fluid": facts.get("nonzero_fluid") is True,
            "native_artifacts_complete": facts.get("native_artifacts_complete") is True,
            "finite_transverse_layers": ((facts.get("fluid_vtk_bounds_m", {}).get("max", [0, 0, 0])[1] - facts.get("fluid_vtk_bounds_m", {}).get("min", [0, 0, 0])[1]) > 0.90 and facts.get("fluid_vtk_bounds_m", {}).get("finite", False)) if facts.get("fluid_vtk_bounds_m") else False,
            "positive_initial_mass": float(facts.get("initial_fluid_mass_kg") or 0.0) > 0.0,
            "finite_boundary_and_control": facts.get("finite_boundary_and_control") is True,
            "q_n": "not_assessed_genCase_only",
        }
        receipt_rows.append({"background": background, "case_id": case_id, "receipt_path": str(receipt_path.resolve()), "receipt_sha256": sha256_file(receipt_path), "receipt_status": receipt.get("status"), "returncode": receipt.get("returncode"), "facts": facts, "quality_interpretation": quality})
        for target in matrix["matrix"]:
            if target["background"] == background and target["resolution"] == "coarse":
                target["native_preflight"] = {"receipt": str(receipt_path.resolve()), "receipt_sha256": sha256_file(receipt_path), "facts": facts, "quality_interpretation": quality}
                target["generation_status"] = "gencase_completed_native_solver_pending"
    evidence = {
        "schema": "ds-data-02.f5.gencase-preflight-evidence.v1",
        "recorded_at_utc": utc_now(),
        "qualification_claim": "none",
        "solver_launched_by_family": False,
        "rows": receipt_rows,
        "checks": {
            "both_completed": all(row["quality_interpretation"]["completed"] for row in receipt_rows),
            "both_3d": all(row["quality_interpretation"]["actual_3d"] for row in receipt_rows),
            "both_nonzero_fluid": all(row["quality_interpretation"]["nonzero_fluid"] for row in receipt_rows),
            "both_native_artifacts_complete": all(row["quality_interpretation"]["native_artifacts_complete"] for row in receipt_rows),
            "both_positive_mass": all(row["quality_interpretation"]["positive_initial_mass"] for row in receipt_rows),
            "both_finite_boundary_and_control": all(row["quality_interpretation"]["finite_boundary_and_control"] for row in receipt_rows),
            "q_n": "native solver reference and independent sensitivity still required",
        },
        "raw_outputs_external": True,
        "raw_output_root": str(RAW_OUTPUT_ROOT),
    }
    _write_json(family / "gencase_preflight_evidence.json", evidence)
    _write_json(family / "reference_evidence.json", evidence)
    matrix["status"] = "gencase_preflight_bound_pending_solver"
    matrix["native_evidence"] = True
    matrix["preflight_evidence_path"] = str(family / "gencase_preflight_evidence.json")
    matrix["all_gencase_preflight"] = all(evidence["checks"].values() if isinstance(evidence["checks"], dict) else [])
    _write_json(matrix_path, matrix)
    return {"path": str(family / "gencase_preflight_evidence.json"), "sha256": sha256_file(family / "gencase_preflight_evidence.json"), "evidence": evidence}


def write_qualification_request(family_dir: str | Path, background: str, gencase_receipt: str | Path, *, attempt_id: str | None = None) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    matrix = _json(family / "definitions/reference_matrix.json")
    row = next(item for item in matrix["matrix"] if item["background"] == background and item["resolution"] == "coarse")
    receipt_path = Path(gencase_receipt).resolve()
    receipt = _json(receipt_path)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0 or int(receipt.get("fluid_particles", 0)) <= 0 or receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError("qualification requires completed 3-D GenCase receipt with positive actual fluid count")
    generated_root = Path(str(receipt["output_root"])).resolve()
    input_prefix = generated_root / row["case_id"]
    native_xml = input_prefix.with_suffix(".xml")
    native_bi4 = input_prefix.with_suffix(".bi4")
    copied_motion = generated_root / Path(row["motion_path"]).name
    if not all(path.is_file() for path in (native_xml, native_bi4, copied_motion)):
        raise ValueError("qualification requires actual completedGenCase XML, BI4 and copied motion input")
    native_inputs = [native_xml, native_bi4, copied_motion]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": row["case_id"],
        "attempt_id": attempt_id or f"qualification-f5-{background}-coarse-v2",
        "kind": "qualification",
        "command": [str(SOLVER), str(input_prefix), "{attempt_root}/solver_output", f"-tmax:{_q(EVENT_WINDOW_S)}", f"-tout:{_q(REFERENCE_SAVE_INTERVAL_S)}"],
        "cwd": str(generated_root),
        "input_prefix": str(input_prefix),
        "input_files": [str(SCRIPT_PATH), str(family / "history_reuse_inventory.json"), str(family / "family_card.json"), str(family / "quality_contract.json"), str(family / "event_definitions.json"), str(family / "integration_save_plan.json"), str(family / "case_registry.jsonl"), str(family / "definitions/reference_matrix.json"), str(Path(row["definition_path"]).resolve()), str(Path(row["metadata_path"]).resolve()), str(_bed_asset_path(family, float(row.get("slope_ratio", 0.28)))), str(receipt_path), *[str(path) for path in native_inputs]],
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 5 * 1024 * 1024 * 1024,
        "estimated_peak_gpu_mib": 2048,
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256_file(receipt_path),
        "native_artifacts": {"xml": str(native_xml), "xml_sha256": sha256_file(native_xml), "bi4": str(native_bi4), "bi4_sha256": sha256_file(native_bi4), "copied_motion": str(copied_motion), "copied_motion_sha256": sha256_file(copied_motion)},
        "worktree_root": str(CURRENT_WORKTREE),
        "launch_commit": _git_commit(),
        "recipe_id": row["recipe_id"],
        "mechanism_id": background,
        "solver_dimension_required": 3,
        "event_window_s": EVENT_WINDOW_S,
        "observables": ["WG1", "WG2", "WG3", "WG4", "runup_peak", "toe_first_arrival", "crest_first_passage", "lateral_notch_passage", "return_crossing", "initial_mass", "terminal_destination", "boundary_identity_audit"],
        "qualification_scope": "recipe+fresh_geometry/control+complete_16s_event_window+native_wave_runup_weir_observables; Q-E optional; no model/tracer gate",
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "request_note": "Registered after actual completedGenCase artifact audit; family owner does not launch GPU.",
    }
    path = family / f"qualification_{background}_request.json"
    _write_json(path, request)
    request["path"] = str(path)
    request["sha256"] = sha256_file(path)
    return request


def _write_registry_manifests_if_needed(family: Path) -> None:
    registry = family / "case_registry.jsonl"
    if not registry.is_file():
        raise FileNotFoundError(registry)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("source-audit", "generate", "design"):
        p = sub.add_parser(name)
        p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
        p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("preflight")
    p.add_argument("--definition", type=Path, required=True)
    p.add_argument("--metadata", type=Path)
    p.add_argument("--allow-missing-source", action="store_true")
    p = sub.add_parser("runner-request")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--launch-commit")
    p = sub.add_parser("record-gencase")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--runup-receipt", type=Path, required=True)
    p.add_argument("--weir-receipt", type=Path, required=True)
    p = sub.add_parser("qualification-request")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--background", choices=sorted(BACKGROUND_SPECS), required=True)
    p.add_argument("--gencase-receipt", type=Path, required=True)
    p.add_argument("--attempt-id")
    p = sub.add_parser("materialize")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--case-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "source-audit":
        result = {"official": _official_source_audit(strict=not args.allow_missing), "history": _historical_audit(strict=not args.allow_missing)}
    elif args.command in {"generate", "design"}:
        result = write_family_design(args.family_dir, strict_source=not args.allow_missing)
    elif args.command == "preflight":
        result = preflight_definition(args.definition, args.metadata, require_sources=not args.allow_missing_source)
    elif args.command == "runner-request":
        result = write_runner_requests(args.family_dir, launch_commit=args.launch_commit)
    elif args.command == "record-gencase":
        result = record_gencase_receipts(args.family_dir, args.runup_receipt, args.weir_receipt)
    elif args.command == "qualification-request":
        result = write_qualification_request(args.family_dir, args.background, args.gencase_receipt, attempt_id=args.attempt_id)
    elif args.command == "materialize":
        family = Path(args.family_dir).resolve()
        registry = [json.loads(line) for line in (family / "case_registry.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        row = next(row for row in registry if row["case_id"] == args.case_id)
        result = materialize_case(row, family)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status", "pass") not in {"fail", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
