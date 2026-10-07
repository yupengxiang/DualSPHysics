#!/usr/bin/env python3
"""Register common physical query times for the 14 Stage2 sentinels.

This metadata-only tool binds each sentinel to its exact CURRENT row and
historical solver receipt.  It registers integer physical query times without
assuming that frame index equals time, and it makes interpolation/extrapolation
rules explicit for a future generic native/typed reader.  It never reads BI4,
H5, or a solver output stream and does not change any consumed manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
OUTPUT_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_common_physical_query_plan_v1.json"
SCHEMA = "ds02.stage2.common-physical-query-plan.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1].lower()


def values(root: ET.Element, element_tag: str, attribute: str) -> list[str]:
    return [element.attrib[attribute] for element in root.iter() if tag(element) == element_tag and attribute in element.attrib]


def params(root: ET.Element, key: str) -> list[str]:
    return [element.attrib["value"] for element in root.iter() if tag(element) == "parameter" and element.attrib.get("key") == key and "value" in element.attrib]


def one(values_: list[str]) -> str:
    values_ = list(dict.fromkeys(values_))
    return values_[0] if len(values_) == 1 else ("UNKNOWN" if not values_ else "UNKNOWN_CONFLICT")


def cli(command: list[str], prefix: str) -> str:
    return one([arg.split(":", 1)[1] for arg in command if isinstance(arg, str) and arg.startswith(prefix + ":")])


def load() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    rows = {row["sentinel_id"]: row for row in review["sentinels"]}
    if len(rows) != 14:
        raise ValueError(f"expected 14 review sentinels, found {len(rows)}")
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')}")
    return current, rows


def exact_row(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    rows = [row for row in current["cases"] if row.get("physical_case_id") == physical_case_id]
    if len(rows) != 1:
        raise ValueError(f"expected one exact CURRENT row for {physical_case_id}, found {len(rows)}")
    return rows[0]


def binding(row: dict[str, Any], key: str) -> tuple[Path, dict[str, Any]]:
    item = row["source_bindings"][key]
    path = Path(item["path"]).resolve()
    record = file_record(path)
    if record["sha256"] != item["sha256"]:
        raise ValueError(f"CURRENT digest mismatch for {path}")
    return path, record


def one_sentinel(sid: str, current: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    row = exact_row(current, review["source_physical_case_id"])
    if row["family_id"] != review["family"] or row["physical_case_id"] != review["source_physical_case_id"]:
        raise ValueError(f"physical identity mismatch for {sid}")
    generated_path, generated_record = binding(row, "generated_xml")
    solver_path, solver_record = binding(row, "solver_receipt")
    generated_root = ET.fromstring(generated_path.read_bytes())
    solver = json.loads(solver_path.read_text(encoding="utf-8"))
    command = solver.get("request", {}).get("command", [])
    end = float(row["actual_time_window_s"][1])
    integer_times = [float(i) for i in range(5) if float(i) <= end + 1e-12]
    # Every sentinel has 0 and 1 s in its exact source window; times beyond
    # the source end are represented as unavailable rather than extrapolated.
    endpoint = {"time_s": end, "status": "SOURCE_WINDOW_ENDPOINT", "frame_index": "UNKNOWN_UNTIL_GENERIC_READER"}
    return {
        "sentinel_id": sid,
        "family_id": review["family"],
        "physical_case_id": review["source_physical_case_id"],
        "current_identity": {
            "runtime_case_alias": row["runtime_case_alias"],
            "frames": row["frames"],
            "actual_time_window_s": row["actual_time_window_s"],
            "trajectory_producer_sha256": row["trajectory"]["producer_declared_sha256"],
            "trajectory_mtime_ns": row["trajectory"]["mtime_ns"],
            "raw_root": row["raw_root"],
        },
        "source_binding": {"generated_xml": generated_record, "solver_receipt": solver_record},
        "source_controls": {
            "xml_cflnumber": one(values(generated_root, "cflnumber", "value")),
            "xml_dp_m": one(values(generated_root, "definition", "dp")),
            "xml_DtMin": one(params(generated_root, "DtMin")),
            "xml_DtFixed": one(params(generated_root, "DtFixed")),
            "xml_TimeMax": one(params(generated_root, "TimeMax")),
            "xml_TimeOut": one(params(generated_root, "TimeOut")),
            "solver_cli_tmax_s": cli(command, "-tmax"),
            "solver_cli_tout_s": cli(command, "-tout"),
            "solver_command": command,
            "dt_or_clamp": "UNKNOWN_UNTIL_SOLVER_RUNTIME_RECEIPT",
        },
        "common_query_times_s": integer_times,
        "requested_4s_endpoint": {
            "time_s": 4.0,
            "status": "AVAILABLE_WITHIN_SOURCE_WINDOW" if end >= 4.0 else "UNAVAILABLE_BEYOND_SOURCE_WINDOW",
            "no_extrapolation": True,
        },
        "source_window_endpoint": endpoint,
        "review_spatial_grid_m": review.get("proposed_spacing_m", "UNKNOWN"),
        "review_dense_cadence_s": review.get("proposed_dense_cadence_s", "UNKNOWN"),
        "review_half_cfl": review.get("proposed_half_cfl", "UNKNOWN"),
        "reader_contract": {
            "query_time_is_physical_seconds": True,
            "frame_index_is_not_a_time_proxy": True,
            "saved_time_lookup": "generic reader must read exact saved times; if query is bracketed, interpolate inside adjacent saved times",
            "out_of_window": "UNKNOWN/UNAVAILABLE; reject extrapolation",
            "common_particle_ids_across_dp": "not required; compare macro/material/fraction/event observables",
            "typed_dimensions": "derive from typed metadata/output, never hardcode historical particle count or frame count",
            "phase": "same source recipe phase is an input property; cross-grid generated phase/count remains measured",
        },
    }


def build() -> dict[str, Any]:
    current, reviews = load()
    sentinels = [one_sentinel(row["sentinel_id"], current, row) for row in reviews.values()]
    sentinels.sort(key=lambda row: row["sentinel_id"])
    common = [0.0, 1.0]
    result = {
        "schema": SCHEMA,
        "status": "PRE_REGISTERED_QUERY_CONTRACT",
        "current_catalog": file_record(CURRENT_PATH),
        "review_matrix": file_record(REVIEW_PATH),
        "quality_label_split": file_record(QUALITY_PATH),
        "sentinel_count": len(sentinels),
        "global_common_query_times_s": common,
        "global_common_query_policy": "all 14 exact source windows contain 0 and 1 s; every later time is sentinel/window-specific",
        "cross_grid_comparison": {
            "spatial": "three registered dp candidates per review row; dp/h/mass/count/lattice phase are intentional variation",
            "temporal": "same-CFL and proposed half-CFL are separate controls; effective dt/clamp UNKNOWN until solver runtime evidence",
            "output": "review dense cadence is proposal metadata; actual saved timestamps and brackets required",
            "task_domain": "task/domain/region/event tolerances remain separate from time/output tolerances",
        },
        "error_budget_registration": {
            "position_macro_fraction_of_L": 0.02,
            "position_event_fraction_of_L": 0.05,
            "velocity_or_kinetic_energy_fraction_of_nonzero_scale": 0.05,
            "region_mass_fraction": 0.03,
            "event_time_fraction": 0.01,
            "time_and_output_each_fraction_of_total_gate": 0.25,
            "source": str(QUALITY_PATH),
        },
        "sentinels": sentinels,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "scientific_qualification": "UNKNOWN",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    output = args.output
    if output.exists():
        raise SystemExit(f"refuse to overwrite existing query plan: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(output), "sentinels": 14, "global_common_query_times_s": [0.0, 1.0]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
