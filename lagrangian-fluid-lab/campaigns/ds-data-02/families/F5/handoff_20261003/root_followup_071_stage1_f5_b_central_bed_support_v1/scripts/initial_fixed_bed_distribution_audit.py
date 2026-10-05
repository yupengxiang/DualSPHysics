#!/usr/bin/env python3
"""Read-only frame-zero fixed-bed distribution audit for actual F5 candidate B071.

This worker is prepared for a Root-authorized invocation against the already
completed A061 Gen075/fresh B initial QA/fresh B typed conversion/fresh B normal XDMF chain.  It does not launch
GenCase, DualSPHysics, PartVTK, or a converter.  ``--check`` uses only small
synthetic arrays.  A real invocation reads one selected frame (frame 0 by
default) from a typed HDF5 trajectory, the XDMF time metadata, and the actual
generated XML.  It never edits or masks the source arrays.

The report distinguishes three observations: (1) XML-range fixed support and
its actual spatial distribution, (2) exact profile/top-surface coverage, and
(3) frame-zero fluid/profile separation.  The generated ``mk=40`` range is a
namespace cohort and may include walls; its presence is therefore evidence
only and is never called a continuous bed proof.  If support is present in
frame zero but a later dynamic audit still penetrates, Root can assign the
remaining cause to boundary/solver behaviour; this worker itself assigns no
cause and authorizes no solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SCHEMA = "ds02.f5.stage1.fresh071.actual-initial-fixed-bed-distribution-audit.v1"
FIXED_TYPE = 0
FLUID_TYPE = 3
BED_MARKER = 40
DP_M = 0.02
BED_NODES_XZ_M = np.asarray(
    ((-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448),
     (3.9, 0.448), (4.4, 0.05), (4.8, 0.05)), dtype=np.float64
)
BED_X_BOUNDS_M = (float(BED_NODES_XZ_M[0, 0]), float(BED_NODES_XZ_M[-1, 0]))
BED_Y_BOUNDS_M = (-0.15, 0.15)
TIME_CANDIDATES = ("/time", "/times", "/Time")
POSITION_CANDIDATES = ("/position", "/positions", "/Position")
VALID_CANDIDATES = ("/valid", "/Valid")
TYPE_CANDIDATES = ("/type", "/initial_type", "/Type")
MASS_CANDIDATES = ("/mass", "/initial_mass", "/Mass")
ID_CANDIDATES = ("/particle_id", "/particle_ids", "/ParticleId")
ZONE_CANDIDATES = ("/particle_zone", "/zone", "/Zone")
MARKER_CANDIDATES = ("/mk", "/initial_mk", "/marker", "/marker_code")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_small_file(path: Path) -> str:
    """Hash only a bound metadata file; never pass the H5 array to this helper."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, expected_sha256: str, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} does not exist: {path}")
    actual_sha256 = sha256_small_file(path)
    require(actual_sha256 == expected_sha256,
            f"{label} SHA mismatch: {actual_sha256} != {expected_sha256}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} must contain a JSON object")
    return value


def _bound_file(binding: dict[str, Any], name: str) -> tuple[Path, str, str]:
    entry = binding.get("files", {}).get(name)
    require(isinstance(entry, dict), f"binding has no files.{name} entry")
    path = Path(str(entry.get("path", "")))
    expected_sha256 = str(entry.get("sha256", ""))
    kind = str(entry.get("kind", ""))
    require(path.is_file(), f"bound {name} does not exist: {path}")
    require(len(expected_sha256) == 64, f"bound {name} has no SHA-256 declaration")
    return path, expected_sha256, kind


def _metadata_hashes(binding: dict[str, Any]) -> dict[str, str]:
    """Verify small JSON/XML/XDMF inputs; H5 is existence-checked only."""
    observed: dict[str, str] = {}
    for name, entry in binding.get("files", {}).items():
        require(isinstance(entry, dict), f"binding files.{name} must be an object")
        path = Path(str(entry.get("path", "")))
        kind = str(entry.get("kind", ""))
        expected_sha256 = str(entry.get("sha256", ""))
        require(path.is_file(), f"bound {name} does not exist: {path}")
        require(len(expected_sha256) == 64, f"bound {name} has invalid SHA-256 declaration")
        if kind == "hdf5_array":
            # The audit reads H5 datasets only when Root explicitly runs this worker.
            # Its large-file digest is supplied by the completed conversion/receipt
            # chain and is never computed here.
            observed[name] = "declared_only_no_h5_rehash"
            continue
        observed[name] = sha256_small_file(path)
        require(observed[name] == expected_sha256,
                f"bound metadata SHA mismatch for {name}: {observed[name]} != {expected_sha256}")
    return observed


def _h5_hash_declarations(*, conversion_report: dict[str, Any], normal_manifest: dict[str, Any],
                          normal_receipt: dict[str, Any], trajectory_h5: Path,
                          declared_sha256: str) -> dict[str, Any]:
    """Cross-check the published H5 digest declarations without hashing H5."""
    conversion_sha = conversion_report.get("output_sha256")
    conversion_path = conversion_report.get("output_hdf5")
    manifest_sha = normal_manifest.get("trajectory_h5_sha256")
    manifest_source_sha = normal_manifest.get("source_h5_sha256")
    launch_hashes = normal_receipt.get("input_hashes_at_launch") or {}
    after_hashes = normal_receipt.get("input_hashes_after_run") or {}
    receipt_launch_sha = launch_hashes.get(str(trajectory_h5))
    receipt_after_sha = after_hashes.get(str(trajectory_h5))
    declarations = {
        "declared_h5_sha256": declared_sha256,
        "conversion_report_output_sha256": conversion_sha,
        "conversion_report_output_hdf5": conversion_path,
        "normal_manifest_trajectory_h5_sha256": manifest_sha,
        "normal_manifest_source_h5_sha256": manifest_source_sha,
        "normal_receipt_input_hash_at_launch": receipt_launch_sha,
        "normal_receipt_input_hash_after_run": receipt_after_sha,
        "digest_computed_by_worker": False,
    }
    for label, value in (
        ("conversion_report.output_sha256", conversion_sha),
        ("normal manifest trajectory_h5_sha256", manifest_sha),
        ("normal manifest source_h5_sha256", manifest_source_sha),
        ("normal receipt launch H5 hash", receipt_launch_sha),
        ("normal receipt after-run H5 hash", receipt_after_sha),
    ):
        require(value == declared_sha256,
                f"H5 digest declaration mismatch at {label}: {value} != {declared_sha256}")
    require(Path(str(conversion_path)) == trajectory_h5,
            f"conversion report H5 path mismatch: {conversion_path} != {trajectory_h5}")
    return declarations


def validate_binding(binding_path: Path) -> dict[str, Any]:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    require(isinstance(binding, dict), "binding must contain a JSON object")
    require(binding.get("schema") == "ds02.f5.stage1.fresh071.actual-initial-fixed-bed-distribution-binding.v1",
            f"unexpected binding schema: {binding.get('schema')}")
    metadata_hashes = _metadata_hashes(binding)
    generated_xml, generated_xml_sha256, generated_xml_kind = _bound_file(binding, "generated_xml")
    gencase_receipt_path, gencase_receipt_sha256, _ = _bound_file(binding, "gencase_receipt")
    qa_receipt_path, _, _ = _bound_file(binding, "initial_qa_receipt")
    qa_report_path, _, _ = _bound_file(binding, "initial_qa_report")
    typed_receipt_path, _, _ = _bound_file(binding, "typed_receipt")
    native_receipt_path, _, _ = _bound_file(binding, "native_receipt")
    conversion_report_path, _, _ = _bound_file(binding, "conversion_report")
    normal_manifest_path, _, _ = _bound_file(binding, "normal_manifest")
    normal_receipt_path, _, _ = _bound_file(binding, "normal_receipt")
    xdmf_path, _, _ = _bound_file(binding, "xdmf")
    trajectory_h5, trajectory_h5_sha256, h5_kind = _bound_file(binding, "trajectory_h5")
    require(generated_xml_kind == "small_xml", "generated_xml must be a small_xml binding")
    require(h5_kind == "hdf5_array", "trajectory_h5 must be an hdf5_array binding")

    gencase_receipt = _load_json(gencase_receipt_path, expected_sha256=gencase_receipt_sha256,
                                 label="genuine Gen075 receipt")
    qa_receipt = _load_json(qa_receipt_path,
                            expected_sha256=binding["files"]["initial_qa_receipt"]["sha256"],
                            label="fresh B initial QA receipt")
    qa_report = _load_json(qa_report_path,
                           expected_sha256=binding["files"]["initial_qa_report"]["sha256"],
                           label="fresh B initial QA report")
    typed_receipt = _load_json(typed_receipt_path,
                               expected_sha256=binding["files"]["typed_receipt"]["sha256"],
                               label="fresh B typed conversion receipt")
    native_receipt = _load_json(native_receipt_path,
                                expected_sha256=binding["files"]["native_receipt"]["sha256"],
                                label="native093 receipt")
    conversion_report = _load_json(conversion_report_path,
                                   expected_sha256=binding["files"]["conversion_report"]["sha256"],
                                   label="fresh B typed conversion conversion report")
    normal_manifest = _load_json(normal_manifest_path,
                                 expected_sha256=binding["files"]["normal_manifest"]["sha256"],
                                 label="fresh B normal XDMF manifest")
    normal_receipt = _load_json(normal_receipt_path,
                                expected_sha256=binding["files"]["normal_receipt"]["sha256"],
                                label="fresh B normal XDMF receipt")
    xml = _xml_provenance(generated_xml)
    require(xml["sha256"] == binding["files"]["generated_xml"]["sha256"],
            "generated XML SHA changed after metadata binding")
    require(gencase_receipt.get("status") == "completed" and gencase_receipt.get("returncode") == 0,
            "genuine Gen075 receipt is not completed/zero")
    require(qa_receipt.get("status") == "completed" and qa_receipt.get("returncode") == 0,
            "fresh B initial QA receipt is not completed/zero")
    require(qa_report.get("status") == "actual_native_qa" and qa_report.get("all_actual_checks_pass") is True,
            "fresh B initial QA report is not the passed actual-native QA report")
    checks = qa_report.get("checks")
    require(isinstance(checks, dict) and all(value is True for value in checks.values()),
            "fresh B initial QA report contains a false or missing check")
    require(typed_receipt.get("status") == "completed" and typed_receipt.get("returncode") == 0,
            "fresh B typed conversion receipt is not completed/zero")
    require(native_receipt.get("status") == "completed" and native_receipt.get("returncode") == 0,
            "native093 receipt is not completed/zero")
    require(conversion_report.get("conversion_status") == "completed" and
            conversion_report.get("frames") == int(binding["actual_counts"]["frames"]) and
            conversion_report.get("particles") == int(binding["actual_counts"]["total_particles"]),
            "conversion report does not match bound actual frame/particle counts")
    require(normal_manifest.get("bound_status") == "root-bound-after-actual-nvme-conversion" and
            normal_manifest.get("diagnostic_only") is True and
            normal_manifest.get("full16_authorized") is False,
            "fresh B normal XDMF manifest is not a bound diagnostic-only product")
    require(normal_receipt.get("status") == "completed" and normal_receipt.get("returncode") == 0,
            "fresh B normal XDMF receipt is not completed/zero")
    for manifest_key in ("gencase_receipt", "initial_qa_receipt", "initial_qa_report",
                         "typed_receipt", "native_receipt", "conversion_report", "trajectory_h5", "xdmf"):
        bound_path, bound_sha256, _ = _bound_file(binding, manifest_key)
        require(normal_manifest.get(manifest_key) == str(bound_path),
                f"fresh B normal XDMF manifest {manifest_key} path does not match fresh071 binding")
        require(normal_manifest.get(f"{manifest_key}_sha256") == bound_sha256,
                f"fresh B normal XDMF manifest {manifest_key} SHA does not match fresh071 binding")
    receipt_total = int(gencase_receipt["total_particles"])
    receipt_fluid = int(gencase_receipt["fluid_particles"])
    declared_counts = binding["actual_counts"]
    require(receipt_total == int(declared_counts["total_particles"]), "Gen075 total differs from binding")
    require(receipt_fluid == int(declared_counts["fluid_particles"]), "Gen075 fluid count differs from binding")
    require(xml["actual_total_particles"] == receipt_total,
            f"generated XML np {xml['actual_total_particles']} != Gen075 receipt total {receipt_total}")
    h5_declarations = _h5_hash_declarations(conversion_report=conversion_report,
                                             normal_manifest=normal_manifest,
                                             normal_receipt=normal_receipt,
                                             trajectory_h5=trajectory_h5,
                                             declared_sha256=trajectory_h5_sha256)
    xdmf_times = _parse_times(xdmf_path)
    require(len(xdmf_times) == int(declared_counts["frames"]),
            "fresh B normal XDMF XDMF frame count differs from bound actual count")
    return {
        "binding": binding,
        "binding_sha256": sha256_small_file(binding_path),
        "metadata_hashes": metadata_hashes,
        "generated_xml": generated_xml,
        "gencase_receipt": gencase_receipt,
        "qa_receipt": qa_receipt,
        "qa_report": qa_report,
        "typed_receipt": typed_receipt,
        "native_receipt": native_receipt,
        "conversion_report": conversion_report,
        "normal_manifest": normal_manifest,
        "normal_receipt": normal_receipt,
        "xdmf": xdmf_path,
        "xdmf_times": xdmf_times,
        "trajectory_h5": trajectory_h5,
        "trajectory_h5_sha256": trajectory_h5_sha256,
        "h5_digest_declarations": h5_declarations,
        "xml": xml,
        "actual_counts": {"total_particles": receipt_total, "fluid_particles": receipt_fluid,
                          "frames": int(declared_counts["frames"]),
                          "solver_dimension": int(declared_counts["solver_dimension"])},
    }


def uid_digest(ids: np.ndarray) -> str:
    values = np.asarray(ids, dtype="<u8").reshape(-1)
    return hashlib.sha256(np.sort(values, kind="stable").tobytes()).hexdigest()


def fraction(a: int, b: int) -> float | None:
    return float(a) / float(b) if b else None


def bed_profile_z(x: np.ndarray) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    flat = values.reshape(-1)
    result = np.full(flat.shape, np.nan, dtype=np.float64)
    inside = (flat >= BED_X_BOUNDS_M[0]) & (flat <= BED_X_BOUNDS_M[1])
    result[inside] = np.interp(flat[inside], BED_NODES_XZ_M[:, 0], BED_NODES_XZ_M[:, 1])
    return result.reshape(values.shape)


def _dataset(handle: Any, names: Sequence[str], required: bool = True) -> tuple[Any | None, str | None]:
    for name in names:
        if name in handle:
            return handle[name], name
    if required:
        raise ValueError(f"none of the required datasets exists: {names}")
    return None, None


def _frame_array(dataset: Any, frame: int, particle_count: int) -> np.ndarray:
    shape = tuple(int(value) for value in dataset.shape)
    if len(shape) == 1:
        values = np.asarray(dataset[...])
    elif len(shape) >= 2 and shape[0] > frame:
        values = np.asarray(dataset[frame, ...])
    else:
        raise ValueError(f"dataset cannot provide frame {frame}: shape={shape}")
    return values.reshape(-1)[:particle_count]


def _parse_times(xdmf: Path) -> list[float]:
    root = ET.parse(xdmf).getroot()
    values: list[float] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "time" and "Value" in node.attrib:
            values.append(float(node.attrib["Value"]))
    require(values, f"XDMF contains no Time/@Value: {xdmf}")
    return values


def _xml_provenance(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    require(particles is not None, "generated XML has no execution/particles")
    np_total = int(particles.attrib["np"])
    ranges: list[dict[str, Any]] = []
    for node in particles:
        if node.tag not in {"fixed", "moving", "fluid", "floating"}:
            continue
        begin = int(node.attrib.get("begin", "-1"))
        count = int(node.attrib.get("count", "0"))
        ranges.append({"kind": node.tag, "begin": begin, "count": count,
                       "end_exclusive": begin + count, "mk": node.attrib.get("mk"),
                       "mkbound": node.attrib.get("mkbound"),
                       "refmotion": node.attrib.get("refmotion")})
    summary = particles.find("./_summary")
    summary_counts: dict[str, int] = {}
    if summary is not None:
        for node in summary:
            if node.tag in {"fixed", "moving", "fluid", "floating"} and "count" in node.attrib:
                summary_counts[node.tag] = int(node.attrib["count"])
    bed_ranges = [item for item in ranges if item["kind"] == "fixed" and item["mk"] == str(BED_MARKER)]
    return {
        "path": str(xml_path), "sha256": sha256_small_file(xml_path), "actual_total_particles": np_total,
        "ranges": ranges, "bed_mk40_ranges": bed_ranges,
        "summary_counts": summary_counts,
        "bed_range_count": sum(item["count"] for item in bed_ranges),
        "bed_cohort_is_mixed_boundary_namespace": True,
    }


def _range_mask(ids: np.ndarray, ranges: Sequence[dict[str, Any]]) -> np.ndarray:
    mask = np.zeros(ids.shape[0], dtype=bool)
    for item in ranges:
        lo, hi = int(item["begin"]), int(item["end_exclusive"])
        mask |= (ids >= lo) & (ids < hi)
    return mask


def _coordinate_summary(points: np.ndarray) -> dict[str, Any]:
    if points.size == 0:
        return {"count": 0, "min_m": None, "max_m": None}
    return {"count": int(points.shape[0]),
            "min_m": [float(value) for value in np.min(points, axis=0)],
            "max_m": [float(value) for value in np.max(points, axis=0)]}


def _surface_counts(mask: np.ndarray, positions: np.ndarray, profile: np.ndarray,
                    denominator: int) -> dict[str, Any]:
    evaluable = mask & np.isfinite(profile) & np.isfinite(positions).all(axis=1)
    distance = positions[:, 2] - profile
    out: dict[str, Any] = {"evaluable_count": int(evaluable.sum()),
                           "fraction_of_support_evaluable": fraction(int(evaluable.sum()), denominator)}
    for tol in (0.5 * DP_M, DP_M, 2.0 * DP_M):
        near = evaluable & (np.abs(distance) <= tol)
        above = evaluable & (distance >= -tol) & (distance <= tol)
        key = f"{tol:.3f}m"
        out[key] = {"near_surface_count": int(near.sum()),
                    "near_surface_fraction": fraction(int(near.sum()), int(evaluable.sum())),
                    "within_band_and_on_or_above_profile_count": int(above.sum()),
                    "max_abs_distance_m": float(np.max(np.abs(distance[evaluable]))) if evaluable.any() else None}
    return out


def _segment_surface(mask: np.ndarray, positions: np.ndarray, profile: np.ndarray) -> list[dict[str, Any]]:
    finite = mask & np.isfinite(profile) & np.isfinite(positions).all(axis=1)
    distance = positions[:, 2] - profile
    records: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(BED_NODES_XZ_M[:-1, 0], BED_NODES_XZ_M[1:, 0])):
        in_segment = finite & (positions[:, 0] >= left)
        in_segment &= positions[:, 0] < right if index < len(BED_NODES_XZ_M) - 2 else positions[:, 0] <= right
        near = in_segment & (np.abs(distance) <= 0.5 * DP_M)
        mid_y = near & (np.abs(positions[:, 1]) <= 0.5 * DP_M)
        y_values = positions[in_segment, 1]
        records.append({"segment_index": index, "x_min_m": float(left), "x_max_m": float(right),
                        "support_evaluable_count": int(in_segment.sum()),
                        "surface_half_dp_count": int(near.sum()),
                        "surface_half_dp_fraction": fraction(int(near.sum()), int(in_segment.sum())),
                        "surface_half_dp_mid_y_count": int(mid_y.sum()),
                        "surface_half_dp_mid_y_fraction": fraction(int(mid_y.sum()), int(near.sum())),
                        "y_level_count": int(np.unique(y_values).size) if y_values.size else 0,
                        "y_min_m": float(np.min(y_values)) if y_values.size else None,
                        "y_max_m": float(np.max(y_values)) if y_values.size else None,
                        "y_levels_m": sorted(float(v) for v in np.unique(y_values))[:31]})
    return records


def _pairwise_duplicate_summary(positions: np.ndarray, groups: dict[str, np.ndarray]) -> dict[str, Any]:
    finite = np.isfinite(positions).all(axis=1)
    rounded = np.round(positions[finite], decimals=10)
    _, inverse, counts = np.unique(rounded, axis=0, return_inverse=True, return_counts=True)
    duplicate_rows = int(np.sum(counts[inverse] > 1)) if inverse.size else 0
    out: dict[str, Any] = {"all_finite_coordinate_duplicate_rows": duplicate_rows,
                            "group_pair_overlap_rows": {}}
    names = list(groups)
    for i, left in enumerate(names):
        li = np.flatnonzero(groups[left] & finite)
        if not li.size:
            for right in names[i + 1:]:
                out["group_pair_overlap_rows"][f"{left}__{right}"] = 0
            continue
        lkeys = {tuple(row) for row in np.round(positions[li], decimals=10)}
        for right in names[i + 1:]:
            ri = np.flatnonzero(groups[right] & finite)
            rkeys = {tuple(row) for row in np.round(positions[ri], decimals=10)}
            out["group_pair_overlap_rows"][f"{left}__{right}"] = len(lkeys & rkeys)
    out["all_group_pairs_zero_overlap"] = all(value == 0 for value in out["group_pair_overlap_rows"].values())
    return out


def frame_zero_report(*, positions: np.ndarray, valid: np.ndarray, types: np.ndarray,
                      masses: np.ndarray, ids: np.ndarray, markers: np.ndarray | None,
                      xml: dict[str, Any], actual_fluid: int) -> dict[str, Any]:
    n = positions.shape[0]
    finite = np.isfinite(positions).all(axis=1)
    valid = valid.astype(bool, copy=False)
    fixed = valid & (types == FIXED_TYPE)
    moving = valid & (types == 1)
    fluid = valid & (types == FLUID_TYPE)
    support = _range_mask(ids, xml["bed_mk40_ranges"]) & fixed
    x = positions[:, 0]
    y = positions[:, 1]
    profile = bed_profile_z(x)
    footprint = support & finite & np.isfinite(profile) & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1]) & (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    fluid_footprint = fluid & finite & np.isfinite(profile) & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1]) & (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    below = fluid_footprint & (positions[:, 2] < profile)
    layers = np.rint((positions[:, 2] - profile) / DP_M)
    layer_values, layer_counts = np.unique(layers[footprint].astype(np.int64), return_counts=True) if footprint.any() else (np.asarray([], dtype=np.int64), np.asarray([], dtype=np.int64))
    marker_summary = None
    if markers is not None:
        marker_summary = {str(int(v)): int((fixed & np.isfinite(markers) & (markers == v)).sum()) for v in np.unique(markers[fixed & np.isfinite(markers)])}
    return {
        "particle_axis_count": int(n), "valid_count": int(valid.sum()),
        "finite_position_count": int(finite.sum()), "nonfinite_position_count": int((~finite).sum()),
        "unique_particle_id_count": int(np.unique(ids).size), "particle_id_uid_digest": uid_digest(ids),
        "type_counts_valid": {"type0_fixed": int(fixed.sum()), "type1_moving": int(moving.sum()), "type3_fluid": int(fluid.sum())},
        "actual_fluid_count_from_genuine_gencase_receipt": int(actual_fluid),
        "fluid_count_matches_genuine_gencase_receipt": int(fluid.sum()) == int(actual_fluid),
        "bed_support": {
            "source": "generated_xml_fixed_mk40_particle_id_ranges_and_type0",
            "range_count": len(xml["bed_mk40_ranges"]), "range_particle_count": xml["bed_range_count"],
            "valid_type0_count": int(support.sum()), "finite_count": int((support & finite).sum()),
            "outside_exact_x_domain_count": int((support & finite & ~((x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1]))).sum()),
            "outside_exact_y_domain_count": int((support & finite & ~((y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1]))).sum()),
            "uid_digest": uid_digest(ids[support]),
            "coordinate_extrema": _coordinate_summary(positions[support & finite]),
            "surface_counts": _surface_counts(support, positions, profile, int(support.sum())),
            "segments": _segment_surface(support, positions, profile),
            "relative_layers_dp": [{"layer": int(layer), "count": int(count)} for layer, count in zip(layer_values, layer_counts)],
            "marker_counts_if_present": marker_summary,
            "mixed_boundary_cohort_warning": True,
            "bed_only_claim": False,
        },
        "fluid_initial_profile_separation": {
            "exact_bed_footprint_count": int(fluid_footprint.sum()),
            "below_profile_count": int(below.sum()),
            "below_profile_fraction": fraction(int(below.sum()), int(fluid.sum())),
            "minimum_profile_distance_m": float(np.min(positions[fluid_footprint, 2] - profile[fluid_footprint])) if fluid_footprint.any() else None,
            "no_initial_fluid_below_profile": not bool(below.any()),
        },
        "uid_and_finite": {"all_ids_unique": int(np.unique(ids).size) == n,
                            "nonfinite_position_count": int((~finite).sum()),
                            "nonfinite_mass_count": int((~np.isfinite(masses)).sum()),
                            "mass_sum_finite_kg": float(masses[np.isfinite(masses)].sum())},
        "spatial_overlap": _pairwise_duplicate_summary(positions, {"fixed": fixed, "moving": moving, "fluid": fluid}),
        "interpretation": "diagnostic only; no root cause or solver approval",
    }


def run_worker(*, binding_path: Path, output_dir: Path, frame: int = 0) -> dict[str, Any]:
    import h5py
    metadata = validate_binding(binding_path)
    trajectory_h5 = metadata["trajectory_h5"]
    xdmf = metadata["xdmf"]
    xml = metadata["xml"]
    times = metadata["xdmf_times"]
    require(0 <= int(frame) < len(times), f"frame {frame} outside XDMF time axis of {len(times)}")
    with h5py.File(trajectory_h5, "r") as handle:
        position_ds, position_path = _dataset(handle, POSITION_CANDIDATES)
        shape = tuple(int(v) for v in position_ds.shape)
        if len(shape) == 2 and shape[1] == 3:
            frame_count, n = 1, shape[0]
        elif len(shape) >= 3 and shape[-1] == 3:
            frame_count, n = shape[0], shape[1]
        else:
            raise ValueError(f"positions must be (N,3) or (frames,N,3), got {shape}")
        require(frame_count == len(times),
                f"H5 frame count {frame_count} != XDMF frame count {len(times)}")
        require(frame_count == int(metadata["actual_counts"]["frames"]),
                f"H5 frame count {frame_count} != bound actual frame count {metadata['actual_counts']['frames']}")
        require(n == xml["actual_total_particles"], f"H5 particle axis {n} != generated XML np {xml['actual_total_particles']}")
        valid_ds, valid_path = _dataset(handle, VALID_CANDIDATES)
        type_ds, type_path = _dataset(handle, TYPE_CANDIDATES)
        mass_ds, mass_path = _dataset(handle, MASS_CANDIDATES)
        id_ds, id_path = _dataset(handle, ID_CANDIDATES, required=False)
        zone_ds, zone_path = _dataset(handle, ZONE_CANDIDATES, required=False)
        marker_ds, marker_path = _dataset(handle, MARKER_CANDIDATES, required=False)
        time_ds, time_path = _dataset(handle, TIME_CANDIDATES, required=False)
        ids = np.asarray(id_ds[...] if id_ds is not None else np.arange(n, dtype=np.uint64)).reshape(-1)
        require(ids.size == n, "particle_id axis does not match positions")
        positions = np.asarray(position_ds[...]) if frame_count == 1 else np.asarray(position_ds[frame, ...])
        valid = _frame_array(valid_ds, frame, n); types = _frame_array(type_ds, frame, n); masses = _frame_array(mass_ds, frame, n)
        markers = _frame_array(marker_ds, frame, n) if marker_ds is not None else None
        actual_times = np.asarray(time_ds[...], dtype=np.float64).reshape(-1) if time_ds is not None else np.asarray(times, dtype=np.float64)
        require(actual_times.size in {1, frame_count}, f"time axis size {actual_times.size} inconsistent with frame_count {frame_count}")
        frame_report = frame_zero_report(positions=positions, valid=valid, types=types, masses=masses,
                                         ids=ids, markers=markers, xml=xml,
                                         actual_fluid=metadata["actual_counts"]["fluid_particles"])
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": SCHEMA, "status": "completed_worker_output_pending_root_review", "diagnostic_only": True,
        "case_id": metadata["binding"]["case_id"],
        "repair_success": "unknown_until_root_initial_distribution_review", "production_approval": "none",
        "q_n_status": "not_granted", "full_solver_authorized": False,
        "source_arrays_modified": False, "source_arrays_dropped_or_masked": False,
        "source": {"binding": str(binding_path), "binding_sha256": metadata["binding_sha256"],
                   "trajectory_h5": str(trajectory_h5),
                   "trajectory_h5_sha256": metadata["trajectory_h5_sha256"],
                   "trajectory_h5_digest_computed_by_worker": False,
                   "trajectory_h5_digest_declarations": metadata["h5_digest_declarations"],
                   "xdmf": str(xdmf), "xdmf_sha256": sha256_small_file(xdmf),
                   "generated_xml": str(metadata["generated_xml"]),
                   "generated_xml_sha256": xml["sha256"],
                   "gencase_receipt": str(_bound_file(metadata["binding"], "gencase_receipt")[0]),
                   "gencase_receipt_sha256": _bound_file(metadata["binding"], "gencase_receipt")[1],
                   "initial_qa_receipt": str(_bound_file(metadata["binding"], "initial_qa_receipt")[0]),
                   "initial_qa_report": str(_bound_file(metadata["binding"], "initial_qa_report")[0]),
                   "typed_receipt": str(_bound_file(metadata["binding"], "typed_receipt")[0]),
                   "native_receipt": str(_bound_file(metadata["binding"], "native_receipt")[0]),
                   "conversion_report": str(_bound_file(metadata["binding"], "conversion_report")[0]),
                   "normal_manifest": str(_bound_file(metadata["binding"], "normal_manifest")[0]),
                   "normal_receipt": str(_bound_file(metadata["binding"], "normal_receipt")[0]),
                   "dataset_paths": {"position": position_path, "valid": valid_path, "type": type_path,
                                     "mass": mass_path, "particle_id": id_path, "particle_zone": zone_path,
                                     "marker": marker_path, "time": time_path}},
        "metadata_binding": {"validated_small_metadata_sha256": metadata["metadata_hashes"],
                              "actual_counts_from_genuine_gen075": metadata["actual_counts"],
                              "qa083_all_actual_checks_pass": metadata["qa_report"]["all_actual_checks_pass"],
                              "fresh B typed conversion_conversion_status": metadata["conversion_report"]["conversion_status"],
                              "fresh B normal XDMF_full16_authorized": metadata["normal_manifest"]["full16_authorized"]},
        "time_provenance": {"xdmf_count": len(times), "frame_count": frame_count,
                             "audited_frame_index": int(frame),
                             "audited_frame_time_s": float(times[frame]),
                             "actual_xdmf_time_values_preserved": True,
                             "uniform_spacing_assumption": False},
        "generated_xml_provenance": xml,
        "gencase_receipt_summary": {key: metadata["gencase_receipt"].get(key) for key in
                                     ("status", "returncode", "total_particles", "fluid_particles",
                                      "solver_dimension_from_gencase", "output_root")},
        "frame_zero": frame_report,
        "audit_contract": {"frame_indices": [0], "dp_m": DP_M, "profile_nodes_xz_m": BED_NODES_XZ_M.tolist(),
                           "bed_y_bounds_m": list(BED_Y_BOUNDS_M), "bed_marker_mk": BED_MARKER,
                           "support_identity": "(particle_id in generated XML fixed mk40 ranges, type==0)",
                           "mk40_mixed_cohort_warning": True, "surface_bands_m": [0.5*DP_M, DP_M, 2*DP_M],
                           "no_initial_fluid_below_profile_required": True},
        "interpretation_boundary": {"mk40_range_is_not_bed_only": True, "initial_support_does_not_prove_dynamic_no_penetration": True,
                                     "dynamic_solver_cause_unassigned": True, "no_threshold_relaxation": True,
                                     "no_full16_authorization": True, "root_manual_review_required": True},
    }
    out = output_dir / "b071-initial-fixed-bed-distribution-audit.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _check() -> None:
    positions = np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 0.0, -0.02], [1.0, 0.0, 0.02]], dtype=float)
    ids = np.arange(4, dtype=np.uint64)
    xml = {"actual_total_particles": 4, "bed_mk40_ranges": [{"begin": 0, "count": 3, "end_exclusive": 3, "mk": "40"}], "bed_range_count": 3}
    out = frame_zero_report(positions=positions, valid=np.ones(4, dtype=bool), types=np.asarray([0,0,0,3]), masses=np.ones(4), ids=ids, markers=None, xml=xml, actual_fluid=1)
    assert out["bed_support"]["valid_type0_count"] == 3
    assert out["fluid_initial_profile_separation"]["below_profile_count"] == 0
    assert out["type_counts_valid"]["type3_fluid"] == 1
    assert out["fluid_count_matches_genuine_gencase_receipt"] is True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--frame", type=int, default=0)
    args = parser.parse_args(argv)
    if args.check:
        _check(); print("source-only fresh071 initial audit synthetic checks passed"); return 0
    required = (args.binding, args.output_dir)
    if any(value is None for value in required):
        parser.error("--binding and --output-dir are required")
    run_worker(binding_path=args.binding, output_dir=args.output_dir, frame=args.frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
