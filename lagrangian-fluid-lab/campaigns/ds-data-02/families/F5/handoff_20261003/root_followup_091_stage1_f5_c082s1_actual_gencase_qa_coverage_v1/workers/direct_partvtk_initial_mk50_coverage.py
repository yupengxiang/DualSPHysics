#!/usr/bin/env python3
"""Read-only frame-zero Type-0/native-Mk50 coverage diagnostic for C082S1.

Root binds the actual GenCase/initial-QA producer and CSV.  This worker uses
actual producer counts only; Mk50 is filtered separately from source mkbound40
because the native Mk40 cohort includes other fixed geometry.  Coverage is a
diagnostic and never authorizes the short solver by itself.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "ds02.f5.c082s1.initial-mk50-coverage-binding.fresh091.v1"
RESULT_SCHEMA = "ds02.f5.c082s1.initial-mk50-coverage.fresh091.v1"
FIELDS = ["Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
          "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
          "Rhop [kg/m^3]", "Press [Pa]"]
TYPE_FIXED, TYPE_FLUID = 0, 3
DP = 0.02
PROFILE = np.asarray([[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448],
                      [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]], dtype=np.float64)
BED_Y = (-0.22, 0.22)
FLUID_Y = (-0.14, 0.14)


def require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load(path: Path, digest: str, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    require(sha256_file(path) == digest, f"{label} SHA mismatch")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def profile_z(x: np.ndarray) -> np.ndarray:
    return np.interp(np.asarray(x, dtype=np.float64), PROFILE[:, 0], PROFILE[:, 1])


def read_csv(path: Path) -> np.ndarray:
    header = None
    header_line = -1
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        for index, row in enumerate(csv.reader(stream)):
            row = [item.strip() for item in row]
            if "Pos.x [m]" in row and "Idp" in row and "Type" in row:
                header, header_line = row, index
                break
    require(header is not None and all(field in header for field in FIELDS),
            "official CSV header/fields are incomplete")
    rows = np.loadtxt(path, delimiter=",", skiprows=header_line + 1,
                      usecols=[header.index(field) for field in FIELDS], ndmin=2)
    rows = np.asarray(rows, dtype=np.float64)
    require(rows.ndim == 2 and rows.shape[1] == len(FIELDS), f"CSV shape is {rows.shape}")
    return rows


def xml_counts(path: Path) -> tuple[int, dict[str, int]]:
    root = ET.parse(path).getroot()
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and data2d.get("value", "true").lower() == "false", "producer XML is not 3-D")
    particles = root.find("./execution/particles")
    require(particles is not None, "producer XML particle metadata is missing")
    names = ("fixed", "moving", "floating", "fluid")
    counts = {name: sum(int(node.get("count", "-1")) for node in particles.findall(name)) for name in names}
    total = int(particles.get("np", "-1"))
    require(total == sum(counts.values()), "producer XML counts do not sum")
    return total, counts


def unresolved_root_binding(ref: dict[str, Any]) -> bool:
    """Recognize an explicit disabled-request placeholder, never a runtime input."""
    return (isinstance(ref.get("path"), str)
            and ref["path"].startswith("<root-bind:")
            and ref.get("sha256") in (None, ""))


def validate_binding(binding: dict[str, Any]) -> None:
    require(binding.get("schema") == SCHEMA, "C082S1 Mk50 binding schema mismatch")
    require(binding.get("case_id") == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1", "case identity mismatch")
    require(isinstance(binding.get("gencase_attempt_id"), str) and isinstance(binding.get("coverage_attempt_id"), str),
            "GenCase/coverage identities are required")
    require(binding["gencase_attempt_id"] != binding["coverage_attempt_id"], "attempt identities collapsed")
    counts = binding.get("actual_counts")
    require(isinstance(counts, dict) and all(isinstance(counts.get(k), int) for k in
                                             ("total_particles", "fixed_particles", "moving_particles",
                                              "floating_particles", "fluid_particles")),
            "actual producer counts are not bound")
    require(binding.get("source_mkbound") == 40 and binding.get("native_bed_mk") == 50,
            "source/native Mk mapping is missing")
    files = binding.get("files")
    require(isinstance(files, dict), "coverage files are missing")
    for key in ("actual_gencase_binding", "gencase_receipt", "prepared_input_report",
                "qa_provenance", "gencase_output_root", "generated_xml", "official_csv"):
        ref = files.get(key)
        require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"],
                f"coverage files.{key}.path is missing")
        if key in {"qa_provenance", "official_csv"} and unresolved_root_binding(ref):
            continue
        if key not in {"gencase_output_root"}:
            require(isinstance(ref.get("sha256"), str) and len(ref["sha256"]) == 64,
                    f"coverage files.{key}.sha256 is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    validate_binding(binding)
    files = binding["files"]
    require(not unresolved_root_binding(files["qa_provenance"]),
            "initial QA provenance must be resolved before coverage execution")
    require(not unresolved_root_binding(files["official_csv"]),
            "official CSV must be resolved before coverage execution")
    counts = binding["actual_counts"]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    producer = load(Path(files["actual_gencase_binding"]["path"]), files["actual_gencase_binding"]["sha256"], "actual GenCase binding")
    receipt = load(Path(files["gencase_receipt"]["path"]), files["gencase_receipt"]["sha256"], "GenCase receipt")
    prepared = load(Path(files["prepared_input_report"]["path"]), files["prepared_input_report"]["sha256"], "prepared report")
    qa = load(Path(files["qa_provenance"]["path"]), files["qa_provenance"]["sha256"], "initial QA provenance")
    require(producer.get("gencase_attempt_id", producer.get("attempt_id")) == binding["gencase_attempt_id"], "producer GenCase attempt mismatch")
    require(producer.get("case_id") == binding["case_id"], "producer case mismatch")
    require(producer.get("actual_counts", {}).get("total_particles") == counts["total_particles"], "producer total mismatch")
    require(producer.get("actual_counts", {}).get("fluid_particles") == counts["fluid_particles"], "producer fluid mismatch")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "GenCase receipt is not completed/zero")
    nested = receipt.get("request", {})
    require(nested.get("case_id") == binding["case_id"] and nested.get("attempt_id") == binding["gencase_attempt_id"], "nested receipt identity mismatch")
    require(receipt.get("solver_dimension_from_gencase") == 3, "GenCase is not 3-D")
    require(int(receipt.get("total_particles", -1)) == counts["total_particles"] and int(receipt.get("fluid_particles", -1)) == counts["fluid_particles"], "receipt counts mismatch")
    require(Path(str(receipt.get("output_root", ""))).resolve() == Path(files["gencase_output_root"]["path"]).resolve(), "receipt output root mismatch")
    total, xcounts = xml_counts(Path(files["generated_xml"]["path"]))
    require(sha256_file(Path(files["generated_xml"]["path"])) == files["generated_xml"]["sha256"], "generated XML SHA mismatch")
    require(total == counts["total_particles"], "XML total mismatch")
    prepared_counts = prepared.get("generated_xml_particle_counts", {})
    require({key: int(prepared_counts.get(key, 0)) for key in xcounts} == xcounts, "prepared/XML counts mismatch")
    require(qa.get("all_actual_checks_pass") is True, "initial QA did not pass")
    csv_path = Path(files["official_csv"]["path"])
    require(csv_path.is_file() and sha256_file(csv_path) == files["official_csv"]["sha256"], "bound official CSV missing/SHA mismatch")
    rows = read_csv(csv_path)
    require(rows.shape == (counts["total_particles"], len(FIELDS)), "official CSV axis differs from actual producer")
    require(np.isfinite(rows).all(), "official CSV contains nonfinite rows")
    ids = rows[:, 4].astype(np.int64)
    require(np.array_equal(np.sort(ids), np.arange(counts["total_particles"])), "Idp is not unique/consecutive")
    types = np.rint(rows[:, 5]).astype(np.int64)
    mks = np.rint(rows[:, 6]).astype(np.int64)
    fixed_mk50 = (types == TYPE_FIXED) & (mks == 50)
    fluid = types == TYPE_FLUID
    x, y, z = rows[:, 0], rows[:, 1], rows[:, 2]
    bed = profile_z(np.clip(x, PROFILE[0, 0], PROFILE[-1, 0]))
    profile_domain = (x >= PROFILE[0, 0]) & (x <= PROFILE[-1, 0])
    bed_footprint = fluid & profile_domain & (y >= BED_Y[0]) & (y <= BED_Y[1])
    below = bed_footprint & (z < bed - 2e-7)
    require(not below.any(), "initial fluid is below continuous source bed profile")
    bins = []
    segments = [(-0.2, 2.0), (2.0, 3.0), (3.0, 3.6), (3.6, 3.9), (3.9, 4.4), (4.4, 4.8)]
    distance = z - bed
    for index, (left, right) in enumerate(segments):
        segment = fixed_mk50 & (x >= left)
        segment &= x <= right if index == len(segments) - 1 else x < right
        surface = segment & (np.abs(distance) <= 0.5 * DP + 1e-8)
        central = surface & (np.abs(y) <= 0.01)
        bins.append({"x_bounds_m": [left, right], "support_count": int(segment.sum()),
                     "surface_half_dp_count": int(surface.sum()),
                     "central_abs_y_le_0p01_surface_half_dp_count": int(central.sum())})
    result = {
        "schema": RESULT_SCHEMA,
        "status": "completed_initial_mk50_coverage_diagnostic",
        "diagnostic_only": True,
        "all_actual_checks_pass": True,
        "full_solver_authorized": False,
        "full16_authorized": False,
        "q_n_status": "not_granted",
        "actual_counts": counts,
        "gencase_attempt_id": binding["gencase_attempt_id"],
        "coverage_attempt_id": binding["coverage_attempt_id"],
        "source_marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50,
                                  "native_filter": "Type==0 and Mk==50"},
        "checks": {"actual_gencase_completed": True, "initial_qa_pass_bound": True,
                   "csv_total_matches_actual_producer": True, "all_rows_finite": True,
                   "uid_unique_consecutive": True, "fluid_initial_below_profile_zero": True,
                   "native_type0_mk50_present": bool(fixed_mk50.any())},
        "support": {"native_type0_mk50_support_count": int(fixed_mk50.sum()),
                    "six_segment_bins": bins, "central_half_dp_global_count": int(sum(x["central_abs_y_le_0p01_surface_half_dp_count"] for x in bins)),
                    "profile_nodes_xz_m": PROFILE.tolist(), "bed_y_bounds_m": list(BED_Y),
                    "fluid_y_bounds_m": list(FLUID_Y),
                    "support_is_patchiness_diagnostic": True,
                    "mk40_mixed_geometry_not_used_as_bed_proof": True},
        "fluid_initial_geometry": {"footprint_count": int(bed_footprint.sum()),
                                    "below_profile_count": int(below.sum()),
                                    "all_fluid_below_profile_zero": bool(not below.any())},
        "review_boundary": {"short_event_requires_explicit_root_review": True,
                             "no_uniform_dense_bed_claim": True,
                             "no_dynamic_acceptance": True,
                             "no_full801_authorization": True},
        "inputs": files,
        "arrays_opened_by_source_agent": False,
    }
    (out / "c082s1-direct-native-initial-fixed-bed-coverage.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "completed", "native_type0_mk50_support_count": int(fixed_mk50.sum()),
                      "central_half_dp_global_count": result["support"]["central_half_dp_global_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
