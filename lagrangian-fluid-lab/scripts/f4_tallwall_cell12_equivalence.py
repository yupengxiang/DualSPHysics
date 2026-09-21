#!/usr/bin/env python3
"""Reproduce the read-only F4 tall-wall cell-12 input equivalence check.

The matrix cell is intentionally not solved again.  This utility decodes the
two already generated initial BI4 files with the pinned official decoder and
compares native particle arrays, mDBC normals, and the generated geometry
assets.  It produces provenance that can be consumed by the qualification
evaluator without changing the frozen matrix or its canary result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _prepared(path: Path) -> dict:
    value = json.loads(Path(path).read_text())
    if value.get("preflight_pass") is not True:
        raise ValueError(f"prepared input failed preflight: {path}")
    for key in ("generated_prefix", "decoder", "decoder_sha256"):
        if key not in value:
            raise ValueError(f"prepared input lacks {key}: {path}")
    decoder = Path(value["decoder"])
    if digest(decoder) != value["decoder_sha256"]:
        raise ValueError(f"decoder hash mismatch: {decoder}")
    return value


def _asset_by_suffix(prefix: Path, suffix: str) -> Path:
    matches = sorted(prefix.parent.glob(prefix.name + suffix))
    if len(matches) != 1:
        raise ValueError(f"expected one {suffix} asset for {prefix}, found {len(matches)}")
    return matches[0]


def _asset_comparison(reference_prefix: Path, matrix_prefix: Path) -> dict:
    suffixes = ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk", "_hdp_Actual.vtk")
    result = {}
    for suffix in suffixes:
        reference = _asset_by_suffix(reference_prefix, suffix)
        matrix = _asset_by_suffix(matrix_prefix, suffix)
        result[suffix] = {
            "reference": str(reference.resolve()),
            "matrix": str(matrix.resolve()),
            "reference_sha256": digest(reference),
            "matrix_sha256": digest(matrix),
            "byte_equal": reference.read_bytes() == matrix.read_bytes(),
        }
    return result


def _max_abs(first: np.ndarray, second: np.ndarray) -> float:
    if first.shape != second.shape:
        raise ValueError(f"array shape mismatch: {first.shape} vs {second.shape}")
    return float(np.max(np.abs(first.astype(np.float64) - second.astype(np.float64)), initial=0.0))


def compare(reference: Path, matrix: Path, output: Path) -> dict:
    reference = Path(reference).resolve()
    matrix = Path(matrix).resolve()
    ref = _prepared(reference)
    candidate = _prepared(matrix)
    ref_prefix = Path(ref["generated_prefix"]).resolve()
    matrix_prefix = Path(candidate["generated_prefix"]).resolve()
    ref_bi4 = ref_prefix.with_suffix(".bi4")
    matrix_bi4 = matrix_prefix.with_suffix(".bi4")
    if not ref_bi4.is_file() or not matrix_bi4.is_file():
        raise FileNotFoundError("one or both generated BI4 files are missing")
    if ref["decoder"] != candidate["decoder"] or ref["decoder_sha256"] != candidate["decoder_sha256"]:
        raise ValueError("reference and matrix do not use the same pinned decoder")

    with tempfile.TemporaryDirectory(prefix="f4-tallwall-cell12-equivalence-") as folder:
        root = Path(folder)
        ref_ids, ref_pos, ref_vel, ref_rho, ref_meta, ref_info, ref_arrays = core_cfd.native_frame(
            ref_bi4, root / "reference", Path(ref["decoder"])
        )
        mat_ids, mat_pos, mat_vel, mat_rho, mat_meta, mat_info, mat_arrays = core_cfd.native_frame(
            matrix_bi4, root / "matrix", Path(candidate["decoder"])
        )
        ref_normals_path = ref_arrays / "BoundNor.bin"
        mat_normals_path = mat_arrays / "BoundNor.bin"
        ref_normals = np.fromfile(ref_normals_path, dtype=np.float32)
        mat_normals = np.fromfile(mat_normals_path, dtype=np.float32)
        # The decoder workspace is temporary, so retain the hashes while the
        # files still exist and carry only the arrays beyond this context.
        ref_normals_sha256 = digest(ref_normals_path)
        mat_normals_sha256 = digest(mat_normals_path)

    native = {
        "ids_exact": bool(np.array_equal(ref_ids, mat_ids)),
        "position_shape_equal": ref_pos.shape == mat_pos.shape,
        "velocity_shape_equal": ref_vel.shape == mat_vel.shape,
        "density_shape_equal": ref_rho.shape == mat_rho.shape,
        "position_max_abs_m": _max_abs(ref_pos, mat_pos),
        "velocity_max_abs_m_s": _max_abs(ref_vel, mat_vel),
        "density_max_abs_kg_m3": _max_abs(ref_rho, mat_rho),
        "counts_equal": len(ref_ids) == len(mat_ids),
    }
    normals = {
        "shape_equal": ref_normals.shape == mat_normals.shape,
        "array_exact": bool(np.array_equal(ref_normals, mat_normals)),
        "max_abs": _max_abs(ref_normals, mat_normals),
        "reference_count": int(ref_normals.size // 3),
        "matrix_count": int(mat_normals.size // 3),
        "finite": bool(np.isfinite(ref_normals).all() and np.isfinite(mat_normals).all()),
        "reference_sha256": ref_normals_sha256,
        "matrix_sha256": mat_normals_sha256,
    }
    assets = _asset_comparison(ref_prefix, matrix_prefix)
    code = Path(__file__).resolve()
    command = [
        str(LAB_ROOT / ".venv/bin/python"),
        str(code),
        "--reference-prepared", str(reference),
        "--matrix-prepared", str(matrix),
        "--output", str(Path(output).resolve()),
    ]
    report = {
        "schema": "core.f4.tallwall120.canary_cell12_equivalence.v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "solver_launched": False,
        "matrix_cell_new_bi4_executed": False,
        "qualification_claim": "none",
        "scope_id": candidate["config"]["scope_id"],
        "revision_id": candidate["config"]["revision_id"],
        "reproducibility": {
            "command": command,
            "command_shell": " ".join(command),
            "equivalence_code": str(code),
            "equivalence_code_sha256": digest(code),
            "core_cfd_code": str(Path(core_cfd.__file__).resolve()),
            "core_cfd_code_sha256": digest(Path(core_cfd.__file__)),
            "decoder": str(Path(candidate["decoder"]).resolve()),
            "decoder_sha256": candidate["decoder_sha256"],
        },
        "reference_canary_input": {
            "prepared": str(reference),
            "prepared_sha256": digest(reference),
            "bi4": str(ref_bi4),
            "bi4_sha256": digest(ref_bi4),
            "scope_id": ref["config"]["scope_id"],
            "case_id": ref["config"]["case_id"],
        },
        "matrix_cell_12_input": {
            "prepared": str(matrix),
            "prepared_sha256": digest(matrix),
            "bi4": str(matrix_bi4),
            "bi4_sha256": digest(matrix_bi4),
            "scope_id": candidate["config"]["scope_id"],
            "case_id": candidate["config"]["case_id"],
        },
        "raw_bi4_bytes_equal": ref_bi4.read_bytes() == matrix_bi4.read_bytes(),
        "native_decode_comparison": native,
        "mdbc_normal_array_comparison": normals,
        "geometry_asset_comparison": assets,
        "semantic_config_equal": {
            key: ref["config"].get(key) == candidate["config"].get(key)
            for key in (
                "pool", "drop", "dp_m", "cfl", "time_max_s", "output_interval_s",
                "wall_bounds", "container_height_m", "physical_kinematic_viscosity_m2_s",
                "viscosity_formulation", "closed_faces", "open_faces", "recipe",
                "solver_arguments",
            )
        },
        "limits": [
            "The reference trajectory is the only executed canary; it does not qualify the 15-cell range.",
            "The new matrix cell-12 BI4 is an unexecuted input-equivalence check; its raw bytes may differ in case metadata.",
            "Qualification must retain cell 12 in the 15-cell denominator and use the canary output only as the explicitly registered reuse record.",
        ],
    }
    report["native_decode_comparison"]["all_exact"] = bool(
        native["ids_exact"] and native["position_shape_equal"] and native["velocity_shape_equal"]
        and native["density_shape_equal"] and native["position_max_abs_m"] == 0.0
        and native["velocity_max_abs_m_s"] == 0.0 and native["density_max_abs_kg_m3"] == 0.0
        and native["counts_equal"]
    )
    report["mdbc_normal_array_comparison"]["all_exact"] = bool(
        normals["shape_equal"] and normals["array_exact"] and normals["finite"]
    )
    report["geometry_asset_comparison"]["all_exact"] = all(
        item["byte_equal"] for item in assets.values()
    )
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-prepared", type=Path, required=True)
    parser.add_argument("--matrix-prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.reference_prepared, args.matrix_prepared, args.output)
    print(json.dumps({
        "native_decode_all_exact": report["native_decode_comparison"]["all_exact"],
        "mdbc_normal_array_all_exact": report["mdbc_normal_array_comparison"]["all_exact"],
        "geometry_assets_all_exact": report["geometry_asset_comparison"]["all_exact"],
        "qualification_claim": report["qualification_claim"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
