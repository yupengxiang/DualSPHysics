#!/usr/bin/env bash
set -euo pipefail

# Extract only the official F1 MeasureTool CSV observations.  This worker never
# launches a solver and deliberately omits PartVTK/PartVTKOut products so a
# second full particle representation is not created beside the native run.
#
# Usage:
#   extract_reference_observations.sh SOLVER_ROOT OUTPUT_ROOT [BIN_ROOT]

if (($# < 2 || $# > 3)); then
  echo "usage: $0 SOLVER_ROOT OUTPUT_ROOT [BIN_ROOT]" >&2
  exit 2
fi

solver_root=$(realpath -- "$1")
output_root=$(realpath -m -- "$2")
bin_root=${3:-/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux}
bin_root=$(realpath -- "$bin_root")
script_root=$(realpath -- "$(dirname "$0")/../input")
data_root="$solver_root/data"

[[ -d "$data_root" ]] || { echo "missing solver data directory: $data_root" >&2; exit 1; }
compgen -G "$data_root/Part_*.bi4" >/dev/null || {
  echo "no native Part_*.bi4 files under $data_root" >&2
  exit 1
}
[[ ! -e "$output_root" ]] || { echo "output already exists: $output_root" >&2; exit 1; }
[[ -x "$bin_root/MeasureTool_linux64" ]] || {
  echo "missing executable: $bin_root/MeasureTool_linux64" >&2
  exit 1
}

mkdir -p "$output_root/measuretool"

# These filters and point definitions are copied from the unchanged official
# CaseDamBreak3D_mDBC script.  -threads:1 is the native MeasureTool option;
# OMP_NUM_THREADS alone does not constrain its interpolation workers.
"$bin_root/MeasureTool_linux64" \
  -dirdata "$data_root" \
  -points "$script_root/elevation.txt" \
  -onlytype:-all,+fluid \
  -elevation:0.5 \
  -threads:1 \
  -savecsv "$output_root/measuretool/_elevation"

"$bin_root/MeasureTool_linux64" \
  -dirdata "$data_root" \
  -points "$script_root/pressure.txt" \
  -onlytype:+all,+fluid \
  -vars:-all,+press \
  -kclimit:0.5 \
  -threads:1 \
  -savecsv "$output_root/measuretool/_pressure"

elevation_csv=$(find "$output_root/measuretool" -maxdepth 1 -type f -name '_elevation*.csv' -print -quit)
pressure_csv=$(find "$output_root/measuretool" -maxdepth 1 -type f -name '_pressure*.csv' -print -quit)
[[ -n "$elevation_csv" ]] || { echo "MeasureTool did not produce an elevation CSV" >&2; exit 1; }
[[ -n "$pressure_csv" ]] || { echo "MeasureTool did not produce a pressure CSV" >&2; exit 1; }

elevation_csv=$(realpath -- "$elevation_csv")
pressure_csv=$(realpath -- "$pressure_csv")
solver_receipt="$solver_root/execution-receipt.json"
[[ -f "$solver_receipt" ]] || { echo "missing solver receipt: $solver_receipt" >&2; exit 1; }

cat >"$output_root/postprocess-manifest.json" <<EOF
{
  "schema": "ds-data-02.upstream-first.f1-minimal-postprocess.v1",
  "family_id": "F1",
  "case_id": "UF_F1_MDBC_DAMBREAK3D",
  "upstream_case_id": "CaseDamBreak3D",
  "solver_root": "$solver_root",
  "native_data_root": "$data_root",
  "output_root": "$output_root",
  "official_bin_root": "$bin_root",
  "native_thread_option": "-threads:1",
  "input_points": {
    "elevation": "$script_root/elevation.txt",
    "pressure": "$script_root/pressure.txt"
  },
  "primary_observation_files": [
    "$elevation_csv",
    "$pressure_csv"
  ],
  "auxiliary_products": [],
  "native_data_policy": "read native Part_*.bi4 directly; no PartVTK/PartVTKOut duplicate",
  "time_policy": {
    "simulation_window_s": [0.0, 6.0],
    "comparison_rule": "interpolate SPHERIC histories only inside source brackets at actual MeasureTool times; never extrapolate, retime, or phase shift"
  },
  "source_hashes": {
    "solver_receipt_sha256": "$(sha256sum "$solver_receipt" | awk '{print $1}')",
    "elevation_points_sha256": "$(sha256sum "$script_root/elevation.txt" | awk '{print $1}')",
    "pressure_points_sha256": "$(sha256sum "$script_root/pressure.txt" | awk '{print $1}')",
    "extraction_script_sha256": "$(sha256sum "$0" | awk '{print $1}')",
    "measuretool_binary_sha256": "$(sha256sum "$bin_root/MeasureTool_linux64" | awk '{print $1}')"
  }
}
EOF

echo "$output_root/postprocess-manifest.json"
