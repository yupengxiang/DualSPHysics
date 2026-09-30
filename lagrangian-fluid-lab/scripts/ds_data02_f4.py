#!/usr/bin/env python3
"""DS-DATA-02 F4 finite-liquid family generator and registration.

F4 keeps two finite, closed-initial-mass mechanisms executable with the native
DualSPHysics v5.4 GenCase recipe:

* a finite block falling onto a finite pool in a tank with five finite wall
  faces; and
* two finite blocks with equal and opposite oblique velocities.

The official F4 definitions and their successful GenCase logs are read from
the immutable lab checkout.  New definitions use the same DBC/Verlet/Wendland
recipe but materialise fluid boxes on a registered centre lattice.  This
avoids the edge-cell over-count in the old raw drawboxes while retaining a
finite initial mass and a visible transverse (y) layer count.  No solver is
started by this module.  CPU requests are emitted for the shared DS-DATA-02
runner; GPU qualification requests are emitted only after a real GenCase
receipt is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable


WORKTREE_ROOT = Path(__file__).resolve().parents[2]
LAB = WORKTREE_ROOT / "lagrangian-fluid-lab"
SOURCE_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
SOURCE_CASES = SOURCE_LAB / "cases" / "F4"
FAMILY_ROOT = LAB / "campaigns" / "ds-data-02" / "families" / "F4"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OUTPUT_ROOT = DATA_ROOT / "families" / "F4" / "case" / "attempt"
BIN_ROOT = SOURCE_LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"

SCRIPT_PATH = Path(__file__).resolve()
RESOLUTIONS: dict[str, float] = {"coarse": 0.04, "medium": 0.03, "fine": 0.02}
MECHANISMS = ("finite_drop_pool", "oblique_finite_columns")
TIME_MAX_S = {"finite_drop_pool": 1.20, "oblique_finite_columns": 1.20}
OUTPUT_INTERVAL_S = 0.001
HALF_OUTPUT_INTERVAL_S = 0.0005
GRAVITY_M_S2 = 9.81
RHO_KG_M3 = 1000.0
SPATIAL_ERROR_BUDGET = 0.05
EVENT_TIME_ERROR_BUDGET = 0.02
TEMPORAL_SHARE = 0.20

MOTHER_CASES: dict[str, dict[str, Path | str]] = {
    "finite_drop_pool": {
        "template": SOURCE_CASES / "F4_drop_onto_pool" / "F4_drop_onto_pool_Def.xml",
        "generated": SOURCE_CASES / "F4_drop_onto_pool" / "generated" / "F4_drop_onto_pool.xml",
        "gencase_log": SOURCE_CASES / "F4_drop_onto_pool" / "generated" / "gencase.log",
        "case_name": "F4_drop_onto_pool",
    },
    "oblique_finite_columns": {
        "template": SOURCE_CASES / "F4_oblique_columns" / "F4_oblique_columns_Def.xml",
        "generated": SOURCE_CASES / "F4_oblique_columns" / "generated" / "F4_oblique_columns.xml",
        "gencase_log": SOURCE_CASES / "F4_oblique_columns" / "generated" / "gencase.log",
        "case_name": "F4_oblique_columns",
    },
}

# The source recipe has a fixed tank and five finite faces.  The top remains
# physically open so that a displaced finite liquid volume is not trapped by a
# fictitious lid; it is not an inlet and no new liquid can be born there.
TANK = {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.6]}
CLOSED_FACES = ["bottom", "left", "right", "front", "back"]
OPEN_FACES = ["top"]
POOL_LOW = [0.08, 0.04, 0.04]
# The source depth is 0.14 m.  0.16 m is the frozen F4 core depth: it is a
# one-cell registration repair that keeps the native pool mass within the
# initialisation budget at all three registered spacings.
POOL_SIZE = [1.04, 0.32, 0.16]
DROP_LOW = [0.47, 0.12, 0.40]
DROP_SIZE = [0.26, 0.16, 0.14]
COLUMN_LEFT_LOW = [0.12, 0.04, 0.24]
COLUMN_RIGHT_LOW = [0.86, 0.20, 0.24]
COLUMN_SIZE = [0.22, 0.16, 0.18]

# Counts are chosen once per mechanism and resolution to minimise native
# rho*dp^3 representation error while retaining at least four y layers.  The
# renderer materialises exactly these centre counts; it never rescales mass.
NATIVE_COUNTS: dict[str, dict[str, dict[str, tuple[int, int, int]]]] = {
    "finite_drop_pool": {
        "pool": {"coarse": (26, 8, 4), "medium": (35, 11, 5), "fine": (52, 16, 8)},
        "drop": {"coarse": (6, 4, 4), "medium": (9, 5, 5), "fine": (13, 8, 7)},
    },
    "oblique_finite_columns": {
        "left_column": {"coarse": (6, 4, 4), "medium": (8, 5, 6), "fine": (11, 8, 9)},
        "right_column": {"coarse": (6, 4, 4), "medium": (8, 5, 6), "fine": (11, 8, 9)},
    },
}

COLUMN_NATIVE_COUNTS_BY_LENGTH: dict[float, dict[str, dict[str, tuple[int, int, int]]]] = {
    0.20: {
        "left_column": {"coarse": (6, 4, 4), "medium": (7, 5, 6), "fine": (10, 8, 9)},
        "right_column": {"coarse": (6, 4, 4), "medium": (7, 5, 6), "fine": (10, 8, 9)},
    },
    0.22: NATIVE_COUNTS["oblique_finite_columns"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _token(value: float, places: int = 5) -> str:
    return f"{float(value):.{places}f}".replace("-", "m").replace(".", "p")


def _number(value: float) -> str:
    return f"{float(value):.17g}"


def _finite_vector(values: Iterable[float], name: str) -> list[float]:
    result = [float(value) for value in values]
    if len(result) != 3 or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain three finite coordinates")
    return result


def _resolution_name(value: str | float) -> str:
    if isinstance(value, str) and value in RESOLUTIONS:
        return value
    value = float(value)
    for name, candidate in RESOLUTIONS.items():
        if math.isclose(value, candidate, rel_tol=0.0, abs_tol=1e-12):
            return name
    raise ValueError(f"unregistered F4 resolution: {value!r}")


def _git_state() -> dict[str, str]:
    def run(args: list[str]) -> str:
        return subprocess.run(["git", *args], cwd=WORKTREE_ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    return {
        "commit": run(["rev-parse", "HEAD"]),
        "status": run(["status", "--porcelain"]),
        "diff_sha256": hashlib.sha256(run(["diff", "HEAD"]).encode()).hexdigest(),
    }


def _center_box(low: list[float], size: list[float], dp: float,
                counts: tuple[int, int, int], source_name: str) -> dict[str, Any]:
    low = _finite_vector(low, f"{source_name}.low")
    size = _finite_vector(size, f"{source_name}.size")
    if any(value <= 0.0 for value in size) or dp <= 0.0:
        raise ValueError(f"{source_name} has non-positive size or dp")
    if any(int(count) < 3 for count in counts):
        raise ValueError(f"{source_name} needs at least three layers per axis")
    first_index = [math.ceil(value / dp - 1.0e-10) for value in low]
    first = [index * dp for index in first_index]
    draw_size = [(int(count) - 1) * dp for count in counts]
    represented_size = [int(count) * dp for count in counts]
    continuous_volume = math.prod(size)
    native_volume = math.prod(represented_size)
    return {
        "source_name": source_name,
        "continuous_low_m": low,
        "continuous_size_m": size,
        "first_center_m": first,
        "draw_size_m": draw_size,
        "counts": [int(value) for value in counts],
        "fluid_y_layers": int(counts[1]),
        "continuous_volume_m3": continuous_volume,
        "native_volume_m3": native_volume,
        "continuous_mass_kg": continuous_volume * RHO_KG_M3,
        "native_mass_kg": native_volume * RHO_KG_M3,
        "relative_mass_error": (native_volume / continuous_volume) - 1.0,
        "particle_mass_kg": RHO_KG_M3 * dp ** 3,
        "mass_rescaling": False,
    }


def _common_controls(mechanism: str, *, time_variant: str) -> dict[str, Any]:
    if mechanism not in MECHANISMS:
        raise ValueError(f"unknown F4 mechanism: {mechanism}")
    if time_variant not in {"native", "half_dt", "half_save"}:
        raise ValueError(f"unknown F4 time variant: {time_variant}")
    cfl = 0.1 if time_variant == "half_dt" else 0.2
    tout = HALF_OUTPUT_INTERVAL_S if time_variant == "half_save" else OUTPUT_INTERVAL_S
    return {
        "step_algorithm": "Verlet",
        "verlet_steps": 40,
        "kernel": "Wendland",
        "viscosity": 0.08,
        "density_dt": 2,
        "density_dt_value": 0.1,
        "boundary": "DBC",
        "cfl": cfl,
        "time_variant": time_variant,
        "time_max_s": TIME_MAX_S[mechanism],
        "output_interval_s": tout,
        "native_source_output_interval_s": 0.05,
        "independent_controls": {
            "native": {"cfl": 0.2, "output_interval_s": OUTPUT_INTERVAL_S},
            "half_dt": {"cfl": 0.1, "output_interval_s": OUTPUT_INTERVAL_S},
            "half_save": {"cfl": 0.2, "output_interval_s": HALF_OUTPUT_INTERVAL_S},
        },
    }


def _base_config(mechanism: str, resolution: str | float, *, stage: str,
                 time_variant: str, parameters: dict[str, Any]) -> dict[str, Any]:
    resolution_name = _resolution_name(resolution)
    dp = RESOLUTIONS[resolution_name]
    if stage not in {"canary", "matrix", "nested8", "nested24", "nested48"}:
        raise ValueError(f"unknown F4 stage: {stage}")
    controls = _common_controls(mechanism, time_variant=time_variant)
    base = {
        "schema": "ds02.f4.definition.v1",
        "family_id": "F4",
        "mechanism_id": mechanism,
        "geometry_family_id": f"F4_{mechanism}_finite_geometry_v1",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "recipe_id": f"F4_{mechanism}_native_dbc_v1",
        "resolution": resolution_name,
        "dp_m": dp,
        "stage": stage,
        "time_variant": time_variant,
        "gravity_m_s2": [0.0, 0.0, -GRAVITY_M_S2],
        "density_kg_m3": RHO_KG_M3,
        "continuum_geometry": {"tank": TANK, "closed_faces": CLOSED_FACES,
                               "open_faces": OPEN_FACES},
        "initialization_rule": {
            "name": "center_lattice_balanced_count_v1",
            "mass_policy": "native_rho_dp_cubed_no_rescaling",
            "purpose": "remove inclusive-edge overcount in historical raw drawboxes",
            "continuum_geometry_is_frozen": True,
        },
        "controls": controls,
        "parameters": parameters,
        "finite_initial_mass": True,
        "open_inlet": False,
        "periodic_boundary": False,
        "qualification_status": "definition_only_until_real_gencase_and_solver_receipts",
        "claims_excluded": [
            "air_entrainment", "droplet_or_spray_truth", "capillary_breakup",
            "material_identity_beyond_native_source_label",
        ],
        "observables": [
            "precontact_center_of_mass_trajectory",
            "first_contact_time",
            "maximum_spread_or_deflection_extent",
            "source_mass_fraction_in_destination_region",
            "finite_plane_first_passage_and_residence",
            "recontact_or_transport_completion_time",
            "active_mass_and_linear_momentum_accounting",
        ],
    }
    base["case_id"] = _case_id(base)
    base["physical_case_id"] = base["case_id"]
    base["lineage_group_id"] = f"{mechanism}_frozen_geometry_control_domain"
    base["paired_background_id"] = mechanism
    return base


def _case_id(config: dict[str, Any]) -> str:
    mechanism = str(config["mechanism_id"])
    p = config["parameters"]
    if mechanism == "finite_drop_pool":
        return (
            f"F4_DROP_gap{_token(p['gap_m'])}_xoff{_token(p['x_offset_m'])}"
            f"_yoff{_token(p['y_offset_m'])}_uz{_token(p['speed_m_per_s'])}"
        )
    return (
        f"F4_COL_gap{_token(p['edge_gap_m'])}_vy{_token(p['transverse_speed_m_per_s'])}"
        f"_yoff{_token(p['right_y_offset_m'])}_lx{_token(p['column_length_x_m'])}"
    )


def drop_config(resolution: str | float = "coarse", *, gap_m: float = 0.22,
                x_offset_m: float = 0.0, y_offset_m: float = 0.0,
                speed_m_per_s: float = 0.5, stage: str = "canary",
                time_variant: str = "native") -> dict[str, Any]:
    """Build one finite drop-on-pool definition from the frozen axes."""
    values = [gap_m, x_offset_m, y_offset_m, speed_m_per_s]
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("drop parameters must be finite")
    drop_low = [DROP_LOW[0] + x_offset_m, DROP_LOW[1] + y_offset_m,
                POOL_LOW[2] + POOL_SIZE[2] + gap_m]
    if gap_m not in (0.18, 0.22, 0.24) or x_offset_m not in (-0.08, 0.0, 0.08) \
            or y_offset_m not in (-0.04, 0.0, 0.04) or speed_m_per_s not in (0.4, 0.5, 0.6):
        raise ValueError("drop values must be in the registered axis set")
    dp_name = _resolution_name(resolution)
    boxes = {
        "pool": _center_box(POOL_LOW, POOL_SIZE, RESOLUTIONS[dp_name],
                            NATIVE_COUNTS["finite_drop_pool"]["pool"][dp_name], "pool"),
        "drop": _center_box(drop_low, DROP_SIZE, RESOLUTIONS[dp_name],
                            NATIVE_COUNTS["finite_drop_pool"]["drop"][dp_name], "drop"),
    }
    if drop_low[0] < 0 or drop_low[1] < 0 or drop_low[2] < 0 \
            or drop_low[0] + DROP_SIZE[0] > TANK["size"][0] \
            or drop_low[1] + DROP_SIZE[1] > TANK["size"][1] \
            or drop_low[2] + DROP_SIZE[2] > TANK["size"][2]:
        raise ValueError("drop box leaves the finite tank domain")
    parameters = {
        "gap_m": float(gap_m), "x_offset_m": float(x_offset_m),
        "y_offset_m": float(y_offset_m), "speed_m_per_s": float(speed_m_per_s),
    }
    config = _base_config("finite_drop_pool", dp_name, stage=stage,
                          time_variant=time_variant, parameters=parameters)
    config["geometry"] = {
        "pool": {"low_m": POOL_LOW, "size_m": POOL_SIZE, "mkfluid": 0},
        "drop": {"low_m": drop_low, "size_m": DROP_SIZE, "mkfluid": 1},
        "wall_box": TANK,
        "native_boxes": boxes,
    }
    config["initial_state"] = {
        "velocities_m_per_s": {"mkfluid:0": [0.0, 0.0, 0.0],
                                "mkfluid:1": [0.0, 0.0, -speed_m_per_s]},
        "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
        "initial_mass_by_source_kg": {name: box["native_mass_kg"]
                                       for name, box in boxes.items()},
        "initial_mass_total_kg": sum(box["native_mass_kg"] for box in boxes.values()),
        "continuum_mass_by_source_kg": {name: box["continuous_mass_kg"]
                                         for name, box in boxes.items()},
    }
    config["event_window"] = {
        "time_start_s": 0.0, "time_end_s": TIME_MAX_S["finite_drop_pool"],
        "sequence": ["separated_initial_state", "first_pool_contact",
                     "maximum_spread", "rebound_or_recontact", "transport_tail"],
        "expected_first_contact_range_s": [0.17, 0.35],
        "right_censor_policy": "qualification_requires_completed_tail_or_explicit_censoring",
    }
    config["scale_contract"] = {
        "L_m": 0.16,
        "U_m_per_s": math.sqrt(GRAVITY_M_S2 * 0.16),
        "T_s": math.sqrt(0.16 / GRAVITY_M_S2),
        "event_time_error_budget_s": EVENT_TIME_ERROR_BUDGET * math.sqrt(0.16 / GRAVITY_M_S2),
        "macro_error_budget_fraction": SPATIAL_ERROR_BUDGET,
        "temporal_allocation_each_fraction": TEMPORAL_SHARE,
        "threshold_policy": "all spatial regions and plane bands are max(3*dp,0.02 m); no single-particle topology",
    }
    config["case_id"] = _case_id(config)
    config["physical_case_id"] = config["case_id"]
    return config


def columns_config(resolution: str | float = "coarse", *, edge_gap_m: float = 0.52,
                   transverse_speed_m_per_s: float = 0.25,
                   right_y_offset_m: float = 0.0, column_length_x_m: float = 0.22,
                   stage: str = "canary", time_variant: str = "native") -> dict[str, Any]:
    """Build one finite oblique two-column definition."""
    if edge_gap_m not in (0.36, 0.52, 0.60) or transverse_speed_m_per_s not in (0.20, 0.25, 0.30) \
            or right_y_offset_m not in (-0.02, 0.0, 0.02) or column_length_x_m not in (0.20, 0.22):
        raise ValueError("column values must be in the registered axis set")
    dp_name = _resolution_name(resolution)
    left_low = list(COLUMN_LEFT_LOW)
    right_low = [COLUMN_LEFT_LOW[0] + column_length_x_m + edge_gap_m,
                 COLUMN_RIGHT_LOW[1] + right_y_offset_m, COLUMN_RIGHT_LOW[2]]
    size = [column_length_x_m, COLUMN_SIZE[1], COLUMN_SIZE[2]]
    count_table = COLUMN_NATIVE_COUNTS_BY_LENGTH[float(column_length_x_m)]
    boxes = {
        "left_column": _center_box(left_low, size, RESOLUTIONS[dp_name],
                                   count_table["left_column"][dp_name],
                                   "left_column"),
        "right_column": _center_box(right_low, size, RESOLUTIONS[dp_name],
                                    count_table["right_column"][dp_name],
                                    "right_column"),
    }
    for low in (left_low, right_low):
        if low[0] < 0 or low[1] < 0 or low[2] < 0 \
                or low[0] + column_length_x_m > TANK["size"][0] \
                or low[1] + COLUMN_SIZE[1] > TANK["size"][1] \
                or low[2] + COLUMN_SIZE[2] > TANK["size"][2]:
            raise ValueError("column leaves the finite tank domain")
    parameters = {
        "edge_gap_m": float(edge_gap_m),
        "transverse_speed_m_per_s": float(transverse_speed_m_per_s),
        "right_y_offset_m": float(right_y_offset_m),
        "column_length_x_m": float(column_length_x_m),
    }
    config = _base_config("oblique_finite_columns", dp_name, stage=stage,
                          time_variant=time_variant, parameters=parameters)
    config["geometry"] = {
        "left_column": {"low_m": left_low, "size_m": size, "mkfluid": 0},
        "right_column": {"low_m": right_low, "size_m": size, "mkfluid": 1},
        "wall_box": TANK,
        "native_boxes": boxes,
    }
    config["initial_state"] = {
        "velocities_m_per_s": {
            "mkfluid:0": [1.0, transverse_speed_m_per_s, 0.0],
            "mkfluid:1": [-1.0, -transverse_speed_m_per_s, 0.0],
        },
        "source_labels": {"mkfluid:0": "left_column", "mkfluid:1": "right_column"},
        "initial_mass_by_source_kg": {name: box["native_mass_kg"]
                                       for name, box in boxes.items()},
        "initial_mass_total_kg": sum(box["native_mass_kg"] for box in boxes.values()),
        "continuum_mass_by_source_kg": {name: box["continuous_mass_kg"]
                                         for name, box in boxes.items()},
    }
    config["event_window"] = {
        "time_start_s": 0.0, "time_end_s": TIME_MAX_S["oblique_finite_columns"],
        "sequence": ["separated_initial_state", "first_column_contact",
                     "maximum_deflection", "recontact_or_merge", "transport_tail"],
        "expected_first_contact_range_s": [0.15, 0.40],
        "right_censor_policy": "qualification_requires_completed_tail_or_explicit_censoring",
    }
    config["scale_contract"] = {
        "L_m": 0.16,
        "U_m_per_s": math.sqrt(1.0 ** 2 + transverse_speed_m_per_s ** 2),
        "T_s": 0.16 / math.sqrt(1.0 ** 2 + transverse_speed_m_per_s ** 2),
        "event_time_error_budget_s": EVENT_TIME_ERROR_BUDGET * 0.16 / math.sqrt(1.0 ** 2 + transverse_speed_m_per_s ** 2),
        "macro_error_budget_fraction": SPATIAL_ERROR_BUDGET,
        "temporal_allocation_each_fraction": TEMPORAL_SHARE,
        "threshold_policy": "all spatial regions and plane bands are max(3*dp,0.02 m); no single-particle topology",
    }
    config["case_id"] = _case_id(config)
    config["physical_case_id"] = config["case_id"]
    return config


def make_config(mechanism: str, resolution: str | float = "coarse", **kwargs: Any) -> dict[str, Any]:
    if mechanism == "finite_drop_pool":
        return drop_config(resolution, **kwargs)
    if mechanism == "oblique_finite_columns":
        return columns_config(resolution, **kwargs)
    raise ValueError(f"unknown F4 mechanism: {mechanism}")


def _find_fluid_drawboxes(root: ET.Element) -> list[tuple[int, ET.Element]]:
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("definition has no geometry mainlist")
    active: int | None = None
    result: list[tuple[int, ET.Element]] = []
    for node in list(mainlist):
        if node.tag == "setmkfluid":
            active = int(node.get("mk", "-1"))
        elif node.tag == "setmkbound":
            active = None
        elif node.tag == "drawbox" and active is not None:
            result.append((active, node))
    return result


def _set_child_xyz(node: ET.Element, tag: str, values: Iterable[float]) -> None:
    child = node.find(tag)
    if child is None:
        raise ValueError(f"drawbox has no {tag}")
    for axis, value in zip("xyz", values):
        child.set(axis, _number(value))


def _set_parameter(root: ET.Element, key: str, value: float) -> None:
    node = root.find(f"./execution/parameters/parameter[@key='{key}']")
    if node is None:
        raise ValueError(f"definition has no execution parameter {key}")
    node.set("value", _number(value))


def render_definition(config: dict[str, Any], target: Path, *, template: Path | None = None) -> dict[str, Any]:
    """Materialise one extensionless-compatible GenCase definition."""
    mechanism = str(config["mechanism_id"])
    source = Path(template or MOTHER_CASES[mechanism]["template"])
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("definition has no geometry definition")
    definition.set("dp", _number(config["dp_m"]))
    boxes = config["geometry"]["native_boxes"]
    drawboxes = _find_fluid_drawboxes(root)
    expected = [(0, "pool"), (1, "drop")] if mechanism == "finite_drop_pool" \
        else [(0, "left_column"), (1, "right_column")]
    if len(drawboxes) != 2 or [item[0] for item in drawboxes] != [0, 1]:
        raise ValueError(f"unexpected fluid drawboxes in source: {[(mk, node.tag) for mk, node in drawboxes]}")
    for (mk, node), (expected_mk, name) in zip(drawboxes, expected):
        if mk != expected_mk:
            raise ValueError("source fluid mk order changed")
        _set_child_xyz(node, "point", boxes[name]["first_center_m"])
        _set_child_xyz(node, "size", boxes[name]["draw_size_m"])
    velocities = config["initial_state"]["velocities_m_per_s"]
    initials = root.find("./casedef/initials")
    if initials is None:
        raise ValueError("definition has no initials block")
    velocity_nodes = {int(node.get("mkfluid", "-1")): node
                      for node in initials.findall("velocity")}
    # The historical drop mother leaves the resting pool implicit.  Materialise
    # that zero velocity in the new core definition so the finite initial state
    # is auditable and the preflight sees both sources explicitly.
    for mk in (0, 1):
        node = velocity_nodes.get(mk)
        if node is None:
            node = ET.SubElement(initials, "velocity", {"mkfluid": str(mk)})
        velocity = velocities.get(f"mkfluid:{mk}")
        if velocity is None:
            raise ValueError(f"missing registered velocity for mkfluid:{mk}")
        for axis, value in zip("xyz", velocity):
            node.set(axis, _number(value))
    controls = config["controls"]
    _set_parameter(root, "TimeMax", controls["time_max_s"])
    _set_parameter(root, "TimeOut", controls["output_interval_s"])
    cfl = root.find("./casedef/constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("definition has no cflnumber")
    cfl.set("value", _number(controls["cfl"]))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_xml": str(source), "source_sha256": sha256(source),
        "configured_xml": str(target), "configured_sha256": sha256(target),
        "extensionless_input": str(target.with_suffix("")),
        "case_id": config["case_id"], "mechanism_id": mechanism,
        "resolution": config["resolution"], "dp_m": config["dp_m"],
        "time_max_s": controls["time_max_s"],
        "output_interval_s": controls["output_interval_s"],
        "time_variant": config["time_variant"],
        "native_box_counts": {name: box["counts"] for name, box in boxes.items()},
    }


def validate_definition(path: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform bounded XML checks before a shared GenCase request."""
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    data2d = root.find("./execution/particles/../constants/data2d")
    if definition is None or float(definition.get("dp", "0")) <= 0:
        raise ValueError("definition dp is missing or non-positive")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("definition has no mainlist")
    fluid_boxes = _find_fluid_drawboxes(root)
    if len(fluid_boxes) != 2 or [mk for mk, _ in fluid_boxes] != [0, 1]:
        raise ValueError("F4 requires exactly two finite fluid blocks with mkfluid 0 and 1")
    wall_boxes = [node for node in mainlist.findall("drawbox")
                  if "bottom" in node.findtext("boxfill", default="")]
    if len(wall_boxes) != 1:
        raise ValueError("F4 requires one finite five-face wall drawbox")
    fill = wall_boxes[0].findtext("boxfill", default="")
    if any(face not in fill for face in CLOSED_FACES) or "top" in fill:
        raise ValueError("wall faces are not the registered finite five-face recipe")
    if root.findall(".//inout") or root.findall(".//periodic"):
        raise ValueError("finite core cannot contain inlet/outlet or periodic commands")
    velocity_nodes = root.findall("./casedef/initials/velocity")
    if len(velocity_nodes) != 2:
        raise ValueError("F4 needs two explicit finite-source velocities")
    for node in velocity_nodes:
        if not all(math.isfinite(float(node.get(axis, "nan"))) for axis in "xyz"):
            raise ValueError("initial velocity contains a non-finite value")
    result: dict[str, Any] = {
        "path": str(Path(path).resolve()), "sha256": sha256(path),
        "solver_dimension": "3D_definition_pending_gencase_confirmation",
        "fluid_blocks": [{"mkfluid": mk, "has_point": node.find("point") is not None,
                           "has_size": node.find("size") is not None}
                          for mk, node in fluid_boxes],
        "finite_wall_faces": CLOSED_FACES,
        "open_faces": OPEN_FACES,
        "initial_velocity_count": len(velocity_nodes),
    }
    if config is not None:
        result["case_id"] = config["case_id"]
        if not math.isclose(float(definition.get("dp")), float(config["dp_m"]), abs_tol=1e-12):
            raise ValueError("definition dp does not match config")
        result["expected_native_counts"] = {name: box["counts"]
                                             for name, box in config["geometry"]["native_boxes"].items()}
        result["expected_initial_mass_kg"] = config["initial_state"]["initial_mass_total_kg"]
        result["fluid_y_layers_min"] = min(box["fluid_y_layers"]
                                            for box in config["geometry"]["native_boxes"].values())
        if result["fluid_y_layers_min"] < 3:
            raise ValueError("fluid transverse layer count is unresolved")
    return result


def _parse_generated(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    if particles is None or constants is None:
        raise ValueError("generated GenCase XML lacks particles/constants")
    data2d = constants.find("data2d")
    fluid = []
    for node in particles.findall("fluid"):
        fluid.append({"mkfluid": int(node.get("mkfluid", "-1")),
                      "mk": int(node.get("mk", "-1")),
                      "count": int(node.get("count", "0"))})
    if not fluid or any(item["count"] <= 0 for item in fluid):
        raise ValueError("generated GenCase XML has no positive fluid blocks")
    positions = particles.find("./_summary/positions")
    mass_node = constants.find("massfluid")
    mass_value = float(mass_node.get("value", "nan")) if mass_node is not None else float("nan")
    position_bounds = None
    if positions is not None:
        position_bounds = {
            "min": {axis: float(positions.find("posmin").get(axis)) for axis in "xyz"},
            "max": {axis: float(positions.find("posmax").get(axis)) for axis in "xyz"},
        }
    result = {
        "path": str(Path(path).resolve()), "sha256": sha256(path),
        "total_particles": int(particles.get("np", "0")),
        "fixed_particles": int(particles.get("nb", "0")),
        "fluid_particles": sum(item["count"] for item in fluid),
        "fluid_blocks": fluid,
        "solver_dimension": "2D" if data2d is not None and data2d.get("value", "false").lower() == "true" else "3D",
        "particle_mass_kg": mass_value,
        "positions": position_bounds,
    }
    result["initial_mass_by_mkfluid_kg"] = {
        str(item["mkfluid"]): item["count"] * mass_value for item in fluid
    }
    if result["solver_dimension"] != "3D":
        raise ValueError("generated F4 mother is not an actual 3D case")
    if result["total_particles"] <= result["fixed_particles"] or result["fluid_particles"] <= 0:
        raise ValueError("generated F4 mother has no finite fluid mass")
    return result


def source_evidence() -> dict[str, Any]:
    """Audit the read-only official mothers and historical numerical recipe."""
    mothers = []
    for mechanism, paths in MOTHER_CASES.items():
        template = Path(paths["template"])
        generated = Path(paths["generated"])
        log = Path(paths["gencase_log"])
        generated_summary = _parse_generated(generated)
        mothers.append({
            "mechanism_id": mechanism,
            "case_name": paths["case_name"],
            "template": str(template), "template_sha256": sha256(template),
            "gencase_log": str(log), "gencase_log_sha256": sha256(log),
            "generated_xml": str(generated), "generated_xml_sha256": sha256(generated),
            "gencase": generated_summary,
            "finite_wall_semantics": {"closed_faces": CLOSED_FACES, "open_faces": OPEN_FACES,
                                       "inlet": False, "periodic": False},
            "read_only_source": True,
        })
    historical = []
    historical_root = SOURCE_LAB / "campaigns" / "v0.1-candidate" / "runs" / "r3-f4-3d-head-on"
    for label in ("coarse", "medium", "fine"):
        log = historical_root / f"{label}__tmax-0p55__tout-0p01" / "solver.stdout.log"
        run_csv = log.parent / "Run.csv"
        if not log.is_file() or not run_csv.is_file():
            continue
        text = log.read_text(errors="replace")
        run_csv_text = run_csv.read_text(errors="replace")
        def capture(pattern: str) -> str | None:
            match = re.search(pattern, text)
            return match.group(1) if match else None
        historical.append({
            "mechanism_id": "head_on_finite_columns_recipe_only",
            "resolution": label,
            "solver_stdout_log": str(log), "solver_stdout_sha256": sha256(log),
            "run_csv": str(run_csv), "run_csv_sha256": sha256(run_csv),
            "actual_3d": re.search(r"3D", run_csv_text) is not None,
            "total_particles": int(capture(r"CaseNp=([0-9,]+)").replace(",", "")) if capture(r"CaseNp=([0-9,]+)") else None,
            "fluid_particles": int(capture(r"CaseNfluid=([0-9,]+)").replace(",", "")) if capture(r"CaseNfluid=([0-9,]+)") else None,
            "dp_m": float(capture(r"Dp=([0-9.]+)")) if capture(r"Dp=([0-9.]+)") else None,
            "time_max_s": float(capture(r"TimeMax=([0-9.]+)")) if capture(r"TimeMax=([0-9.]+)") else None,
            "interpretation": "successful finite-column solver recipe; head-on evidence does not qualify the new oblique mechanism",
        })
    return {
        "schema": "ds02.f4.reference-evidence.v1",
        "source_root": str(SOURCE_LAB), "source_is_read_only": True,
        "mothers": mothers, "historical_recipe_evidence": historical,
        "registered_recipe_deltas": {
            "fluid_initialization": {
                "source": "raw inclusive drawbox",
                "registered": "balanced centre-lattice drawbox with native rho*dp^3 mass",
                "reason": "source coarse boxes over-count edge cells; no mass rescaling is applied",
            },
            "finite_drop_pool": {
                "pool_depth_source_m": 0.14, "pool_depth_registered_m": POOL_SIZE[2],
                "reason": "one registered cell-depth adjustment keeps all three native pool masses bounded",
            },
            "initial_velocity": {
                "source_drop": "mkfluid:0 rests implicitly",
                "registered_drop": "mkfluid:0 zero velocity is explicit",
            },
            "event_controls": {
                "source_time_max_s": {"finite_drop_pool": 0.6, "oblique_finite_columns": 0.55},
                "registered_time_max_s": TIME_MAX_S,
                "source_time_out_s": 0.05,
                "registered_time_out_s": OUTPUT_INTERVAL_S,
            },
        },
        "evidence_boundary": "GenCase mothers are actual 3D finite-mass evidence; new oblique/drop solver Q-N remains pending fresh runner receipts",
    }


def _registry_axis_records() -> dict[str, list[dict[str, Any]]]:
    drop_records = []
    for gap_m, x_offset_m, y_offset_m, speed in itertools.product(
            (0.18, 0.22, 0.24), (-0.08, 0.08), (-0.04, 0.04), (0.4, 0.6)):
        drop_records.append(drop_config("coarse", gap_m=gap_m, x_offset_m=x_offset_m,
                                        y_offset_m=y_offset_m, speed_m_per_s=speed,
                                        stage="nested48"))
    column_records = []
    for edge_gap, transverse, y_offset, length_x in itertools.product(
            (0.36, 0.52, 0.60), (0.20, 0.30), (-0.02, 0.02), (0.20, 0.22)):
        column_records.append(columns_config("coarse", edge_gap_m=edge_gap,
                                             transverse_speed_m_per_s=transverse,
                                             right_y_offset_m=y_offset,
                                             column_length_x_m=length_x,
                                             stage="nested48"))
    return {"finite_drop_pool": drop_records, "oblique_finite_columns": column_records}


def registry_records() -> list[dict[str, Any]]:
    """Return 48 independent physical groups with nested admission stages."""
    grouped = _registry_axis_records()
    records: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for rank, config in enumerate(grouped[mechanism]):
            stages = (["nested8", "nested24", "nested48"] if rank < 4
                      else ["nested24", "nested48"] if rank < 12
                      else ["nested48"])
            config = dict(config)
            config["admission_stages"] = stages
            config["axis_rank_within_background"] = rank
            config["registered_resolution_cells"] = [
                {"resolution": name, "dp_m": dp,
                 "case_id": f"{config['case_id']}_{name}"}
                for name, dp in RESOLUTIONS.items()
            ]
            config["production_artifact_status"] = "pre_registered_definition_only"
            records.append(config)
    return records


def split_plan(records: list[dict[str, Any]]) -> dict[str, Any]:
    splits: dict[str, list[str]] = {"train": [], "validation": [], "test": [], "extrapolation": []}
    for index, record in enumerate(records):
        rank = int(record["axis_rank_within_background"])
        if rank >= 12:
            split = "extrapolation"
        elif index % 5 == 0:
            split = "test"
        elif index % 3 == 0:
            split = "validation"
        else:
            split = "train"
        splits[split].append(record["case_id"])
    return {
        "schema": "ds02.f4.split-plan.v1",
        "split_rule": "deterministic background-local rank; rank 0..3 nested8, 0..11 nested24, 0..23 nested48",
        "endpoint_axes": {
            "finite_drop_pool": {"gap_m": [0.18, 0.24], "x_offset_m": [-0.08, 0.08],
                                  "y_offset_m": [-0.04, 0.04], "speed_m_per_s": [0.4, 0.6]},
            "oblique_finite_columns": {"edge_gap_m": [0.36, 0.60],
                                        "transverse_speed_m_per_s": [0.20, 0.30],
                                        "right_y_offset_m": [-0.02, 0.02],
                                        "column_length_x_m": [0.20, 0.22]},
        },
        "interior_values": {"finite_drop_pool": {"gap_m": 0.22},
                             "oblique_finite_columns": {"edge_gap_m": 0.52}},
        "counts": {name: len(ids) for name, ids in splits.items()},
        "case_ids": splits,
        "resolution_policy": "each physical case is evaluated at coarse/medium/fine; resolution copies share physical lineage",
    }


def integration_save_plan() -> dict[str, Any]:
    return {
        "schema": "ds02.f4.integration-save-plan.v1",
        "frozen_event_windows_s": {mechanism: TIME_MAX_S[mechanism] for mechanism in MECHANISMS},
        "scale_contract": {
            "finite_drop_pool": {"L_m": 0.16, "T_s": math.sqrt(0.16 / GRAVITY_M_S2),
                                  "event_time_budget_s": EVENT_TIME_ERROR_BUDGET * math.sqrt(0.16 / GRAVITY_M_S2)},
            "oblique_finite_columns": {"L_m": 0.16, "U_m_per_s": "sqrt(1^2+vy^2)",
                                        "T_s": "L/U", "event_time_budget_s": "0.02*T"},
        },
        "macro_error_budget_fraction": SPATIAL_ERROR_BUDGET,
        "event_time_relative_budget_fraction": EVENT_TIME_ERROR_BUDGET,
        "temporal_share_each_fraction": TEMPORAL_SHARE,
        "matrix": {
            "backgrounds": list(MECHANISMS), "resolutions": RESOLUTIONS,
            "native_integration": "CFL=0.2, adaptive Dt, TimeOut=0.001 s",
            "half_dt": "CFL=0.1, adaptive Dt, TimeOut=0.001 s",
            "half_save": "CFL=0.2, adaptive Dt, TimeOut=0.0005 s",
        },
        "sampling_justification": "At T≈0.128 s (drop) and T≈0.155 s (columns), half-frame at 0.001 s is below 20% of the 2% event-time budget; source 0.05 s is retained only as historical canary evidence.",
        "primary_observations": ["first_contact_time", "max_spread_or_deflection", "recontact_or_transport_time", "source_mass_fraction", "COM_and_momentum"],
        "secondary_observations": ["finite_plane_first_passage", "residence_time", "final_category", "unknown_mass"],
        "thresholds": {
            "spatial_region_min": "max(3*dp,0.02 m)",
            "event_contact": "first frame interval in which source support regions overlap at resolved scale; linear interval locator",
            "recontact": "separation followed by resolved overlap after first contact; censored if window ends",
            "mass_denominator": "native frame-zero fluid mass, source-wise, never survivor-renormalized",
        },
        "qualification_boundary": "This is a frozen plan. A case becomes Q-N-eligible only after actual GenCase and solver evidence for the exact recipe, geometry, controls, time window, observables and resolution.",
    }


def make_gencase_request(config: dict[str, Any], definition: Path, *, attempt_id: str | None = None) -> dict[str, Any]:
    definition = Path(definition).resolve()
    validate_definition(definition, config)
    mechanism = str(config["mechanism_id"])
    short = "drop_pool" if mechanism == "finite_drop_pool" else "oblique_columns"
    attempt = attempt_id or f"gencase-{short}-{config['resolution']}-nominal-v1"
    prefix = f"{{attempt_root}}/F4_{short}_{config['resolution']}"
    inputs = [definition, Path(MOTHER_CASES[mechanism]["template"]), SCRIPT_PATH]
    request = {
        "schema": "ds02.runner-request.v1",
        "family_id": "F4", "case_id": config["case_id"], "attempt_id": attempt,
        "kind": "cpu", "cpu_task_kind": "gencase",
        "command": [str(GENCASE), str(definition.with_suffix("")), prefix, "-save:all"],
        "cwd": str(BIN_ROOT), "max_wall_seconds": 300, "cpu_threads": 4,
        "estimated_storage_bytes": 96 * 1024 * 1024,
        "input_files": [str(path) for path in inputs],
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": _git_state()["commit"],
        "input_hashes": {str(path): sha256(path) for path in inputs},
        "expected": {
            "mechanism_id": mechanism, "resolution": config["resolution"],
            "solver_dimension": "3D", "finite_initial_mass": True,
            "minimum_fluid_y_layers": min(box["fluid_y_layers"] for box in config["geometry"]["native_boxes"].values()),
            "expected_native_fluid_particles": sum(box["counts"][0] * box["counts"][1] * box["counts"][2]
                                                    for box in config["geometry"]["native_boxes"].values()),
        },
        "source_read_only": True,
        "gpu_or_solver_started_by_generator": False,
    }
    return request


def make_qualification_request(config: dict[str, Any], receipt: Path, *, generated_prefix: Path | None = None,
                               attempt_id: str | None = None) -> dict[str, Any]:
    """Build a solver request bound to a real completed GenCase receipt."""
    receipt = Path(receipt).resolve()
    payload = json.loads(receipt.read_text())
    if payload.get("status") != "completed" or int(payload.get("returncode", -1)) != 0:
        raise ValueError("qualification requires a completed GenCase receipt")
    if int(payload.get("total_particles", 0)) <= 0 or int(payload.get("fluid_particles", 0)) <= 0:
        raise ValueError("qualification requires actual positive GenCase particle counts")
    output_root = Path(payload.get("output_root", ""))
    if generated_prefix is None:
        short = "drop_pool" if config["mechanism_id"] == "finite_drop_pool" else "oblique_columns"
        generated_prefix = output_root / f"F4_{short}_{config['resolution']}"
    generated_prefix = Path(generated_prefix).resolve()
    generated_xml = generated_prefix.with_suffix(".xml")
    if not generated_xml.is_file():
        raise FileNotFoundError(f"GenCase generated XML is missing: {generated_xml}")
    short = "drop_pool" if config["mechanism_id"] == "finite_drop_pool" else "oblique_columns"
    attempt = attempt_id or f"qualification-{short}-{config['resolution']}-fullwindow-v1"
    controls = config["controls"]
    inputs = [receipt, generated_xml]
    for suffix in (".bi4",):
        candidate = generated_prefix.with_suffix(suffix)
        if candidate.is_file():
            inputs.append(candidate)
    request = {
        "schema": "ds02.runner-request.v1",
        "family_id": "F4", "case_id": config["case_id"], "attempt_id": attempt,
        "kind": "qualification", "cpu_threads": 1,
        "command": [str(SOLVER), str(generated_prefix), "{attempt_root}/solver",
                     f"-tmax:{controls['time_max_s']:.9g}",
                     f"-tout:{controls['output_interval_s']:.9g}"],
        "cwd": str(BIN_ROOT), "max_wall_seconds": 300,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_gpu_mib": 4096,
        "input_files": [str(path) for path in inputs],
        "worktree_root": str(WORKTREE_ROOT),
        "gencase_receipt": str(receipt),
        "launch_commit": _git_state()["commit"],
        "input_hashes": {str(path): sha256(path) for path in inputs},
        "qualification_scope": {
            "recipe_id": config["recipe_id"], "mechanism_id": config["mechanism_id"],
            "resolution": config["resolution"], "time_window_s": controls["time_max_s"],
            "output_interval_s": controls["output_interval_s"],
            "observables": config["observables"],
            "status": "candidate_request_pending_solver_evidence",
        },
    }
    return request


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def register_family() -> dict[str, Any]:
    """Materialise family definitions, frozen plans, registry and CPU requests."""
    FAMILY_ROOT.mkdir(parents=True, exist_ok=True)
    evidence = source_evidence()
    records = registry_records()
    _write_json(FAMILY_ROOT / "family_card.json", {
        "schema": "ds02.f4.family-card.v1", "family_id": "F4",
        "status": "definition_and_gencase_request_ready",
        "mechanisms": MECHANISMS,
        "finite_initial_mass_core": True,
        "open_inlet_core": False,
        "wall_spec": {"tank": TANK, "closed_faces": CLOSED_FACES, "open_faces": OPEN_FACES},
        "resolutions": RESOLUTIONS, "event_windows_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "case_count": 48, "nested_counts": {"nested8": 8, "nested24": 24, "nested48": 48},
        "source_evidence_file": "reference_evidence.json",
        "qualified_recipe_file": "qualified_recipes.json",
        "generator": str(SCRIPT_PATH), "generator_sha256": sha256(SCRIPT_PATH),
        "qualification_boundary": "No Q-N or product claim follows from this registration alone.",
    })
    _write_json(FAMILY_ROOT / "reference_evidence.json", evidence)
    _write_json(FAMILY_ROOT / "integration_save_plan.json", integration_save_plan())
    _write_json(FAMILY_ROOT / "split_plan.json", split_plan(records))
    _write_jsonl(FAMILY_ROOT / "case_registry.jsonl", records)
    manifest_root = FAMILY_ROOT / "case_manifests"
    for record in records:
        manifest = {
            "schema": "ds02.f4.case-manifest.v1",
            "case_id": record["case_id"], "physical_case_id": record["physical_case_id"],
            "lineage_group_id": record["lineage_group_id"],
            "mechanism_id": record["mechanism_id"],
            "registered_resolution_cells": record["registered_resolution_cells"],
            "admission_stages": record["admission_stages"],
            "status": "pre_registered_definition_only",
            "hdf5_path": None, "hdf5_sha256": None, "solver_receipt": None,
            "unknown_mass_policy": "unknown is a reported category, never zero",
        }
        _write_json(manifest_root / f"{record['case_id']}.json", manifest)
    (FAMILY_ROOT / "labels").mkdir(exist_ok=True)
    (FAMILY_ROOT / "preview").mkdir(exist_ok=True)
    (FAMILY_ROOT / "labels" / "README.md").write_text(
        "# F4 labels\n\nLabels are pending real solver outputs. The frozen contract is in `integration_save_plan.json`; no metadata-only label is a production result.\n"
    )
    (FAMILY_ROOT / "preview" / "README.md").write_text(
        "# F4 previews\n\nPreview frames are pending shared-runner solver receipts.\n"
    )
    definition_dir = FAMILY_ROOT / "definitions"
    request_dir = FAMILY_ROOT / "requests"
    definition_records = {}
    for mechanism in MECHANISMS:
        config = (drop_config("coarse") if mechanism == "finite_drop_pool"
                  else columns_config("coarse"))
        for resolution in RESOLUTIONS:
            cfg = (drop_config(resolution) if mechanism == "finite_drop_pool"
                   else columns_config(resolution))
            target = definition_dir / f"{mechanism}_{resolution}_Def.xml"
            rendered = render_definition(cfg, target)
            validate_definition(target, cfg)
            definition_records[f"{mechanism}:{resolution}"] = rendered
        nominal = (drop_config("coarse") if mechanism == "finite_drop_pool"
                   else columns_config("coarse"))
        request = make_gencase_request(nominal, definition_dir / f"{mechanism}_coarse_Def.xml")
        _write_json(request_dir / f"gencase_{mechanism}_coarse.json", request)
    _write_json(FAMILY_ROOT / "definition_audit.json", definition_records)
    _write_json(FAMILY_ROOT / "qualified_recipes.json", {
        "schema": "ds02.f4.qualified-recipes.v1",
        "status": "pending_real_gencase_and_solver_receipts",
        "recipes": [{"recipe_id": f"F4_{mechanism}_native_dbc_v1",
                     "mechanism_id": mechanism,
                     "gencase_receipt": None, "solver_receipts": [],
                     "q_i": "not_assessed", "q_n": "not_assessed", "q_e": "not_assessed"}
                    for mechanism in MECHANISMS],
        "note": "Historical head-on logs are numerical recipe evidence only; they do not qualify new oblique/drop cases.",
    })
    handoff = {
        "schema": "ds02.f4.handoff.v1", "family_id": "F4",
        "status": "ready_for_shared_cpu_gencase",
        "next_executable_tasks": [
            "Run both requests/ gencase_*_coarse.json through shared ds_data02_runtime.py.",
            "Verify receipt total/fluid counts, Data2D=false, finite wall bounds, native source masses and y-layer counts.",
            "Bind each real receipt to a qualification request and let the primary dispatch GPU solver.",
            "Only after complete 1.2 s windows, 0.001 s outputs and independent CFL/output checks evaluate Q-I/Q-N.",
        ],
        "source_audit": "reference_evidence.json",
        "requests": ["requests/gencase_finite_drop_pool_coarse.json", "requests/gencase_oblique_finite_columns_coarse.json"],
        "no_gpu_started_by_generator": True,
        "no_product_or_qn_claim": True,
    }
    _write_json(FAMILY_ROOT / "FAMILY_HANDOFF.json", handoff)
    (FAMILY_ROOT / "FAMILY_HANDOFF.md").write_text(
        "# F4 handoff\n\n"
        "The two finite 3D mechanisms are materialized from the read-only official mothers and are ready for shared CPU GenCase. "
        "The source mothers are actual `Data2D=false` cases with finite fluid counts and five finite tank faces. "
        "New core definitions use a balanced centre-lattice initialization with native `rho*dp^3` mass and no mass rescaling. "
        "The frozen complete event window is 1.20 s and the reference output cadence is 0.001 s; 0.0005 s output and CFL=0.1 are independent controls. "
        "Run both JSON requests through the shared runner, then bind their real receipts to qualification requests. "
        "This handoff makes no Q-N or product claim.\n"
    )
    return {"family_root": str(FAMILY_ROOT), "records": len(records), "evidence": evidence,
            "definitions": definition_records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("register", help="write F4 family registration and requests")
    audit = sub.add_parser("audit", help="print read-only mother evidence")
    audit.add_argument("--json", action="store_true")
    render = sub.add_parser("render", help="render one definition")
    render.add_argument("mechanism", choices=MECHANISMS)
    render.add_argument("resolution", choices=list(RESOLUTIONS))
    render.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "audit":
        payload = source_evidence()
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
        return 0
    if args.action == "register":
        result = register_family()
        print(json.dumps({"family_root": result["family_root"], "records": result["records"]}, ensure_ascii=False, indent=2))
        return 0
    config = (drop_config(args.resolution) if args.mechanism == "finite_drop_pool"
              else columns_config(args.resolution))
    print(json.dumps(render_definition(config, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
