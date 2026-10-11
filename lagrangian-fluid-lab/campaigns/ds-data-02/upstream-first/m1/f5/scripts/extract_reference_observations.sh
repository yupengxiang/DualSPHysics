#!/usr/bin/env bash
set -euo pipefail

# Extract the official CasePistonBeach_REG observation products after the
# shared runner has completed the solver.  This script never launches a
# solver and never edits the native data directory.
#
# Usage:
#   extract_reference_observations.sh SOLVER_ROOT OUTPUT_ROOT [BIN_ROOT]
#
# SOLVER_ROOT is the runner output directory that contains data/Part_*.bi4.
# OUTPUT_ROOT must be a new directory on the approved NAS output filesystem.

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
for tool in PartVTK_linux64 PartVTKOut_linux64 MeasureTool_linux64 IsoSurface_linux64; do
  [[ -x "$bin_root/$tool" ]] || { echo "missing executable: $bin_root/$tool" >&2; exit 1; }
done

mkdir -p "$output_root/particles" "$output_root/measuretool" "$output_root/surface"

# Preserve the official script's filters and measurement definitions.  The
# CSV files are the comparison inputs; VTK is retained for visual/geometry QA.
"$bin_root/PartVTK_linux64" \
  -dirdata "$data_root" \
  -savevtk "$output_root/particles/PartFluid" \
  -onlytype:-all,+fluid

"$bin_root/PartVTK_linux64" \
  -dirdata "$data_root" \
  -savevtk "$output_root/particles/PartPiston" \
  -onlytype:-all,+moving

"$bin_root/PartVTKOut_linux64" \
  -dirdata "$data_root" \
  -savevtk "$output_root/particles/PartFluidOut" \
  -SaveResume "$output_root/particles/_ResumeFluidOut"

"$bin_root/MeasureTool_linux64" \
  -dirdata "$data_root" \
  -points "$script_root/elevation.txt" \
  -onlytype:-all,+fluid \
  -elevation:0.4 \
  -savecsv "$output_root/measuretool/_elevation" \
  -savevtk "$output_root/measuretool/elevation"

"$bin_root/MeasureTool_linux64" \
  -dirdata "$data_root" \
  -points "$script_root/velocity.txt" \
  -onlytype:-all,+fluid \
  -vars:-all,+vel \
  -savecsv "$output_root/measuretool/_velocity" \
  -savevtk "$output_root/measuretool/velocity"

# Keep a surface slice for the visual check of the elevation extraction.  It
# is auxiliary and is not substituted for the MeasureTool CSV observations.
"$bin_root/IsoSurface_linux64" \
  -dirdata "$data_root" \
  -saveslice "$output_root/surface/Slices"

cat >"$output_root/postprocess-manifest.json" <<EOF
{
  "schema": "ds-data-02.upstream-first.f5-postprocess.v1",
  "upstream_case_id": "CasePistonBeach_REG",
  "solver_root": "$solver_root",
  "native_data_root": "$data_root",
  "output_root": "$output_root",
  "official_bin_root": "$bin_root",
  "input_points": {
    "elevation": "$script_root/elevation.txt",
    "velocity": "$script_root/velocity.txt"
  },
  "primary_observation_files": [
    "$output_root/measuretool/_elevation.csv",
    "$output_root/measuretool/_velocity.csv"
  ],
  "auxiliary_products": [
    "$output_root/particles/PartFluid",
    "$output_root/particles/PartPiston",
    "$output_root/particles/PartFluidOut",
    "$output_root/surface/Slices"
  ],
  "time_policy": {
    "simulation_window_s": [0.0, 30.0],
    "startup_report_window_s": [0.0, 2.0],
    "primary_acceptance_window_s": [2.0, 30.0],
    "theory_window_s": [0.0, 40.0],
    "comparison_rule": "interpolate theory only inside brackets at actual MeasureTool times; never extrapolate"
  }
}
EOF
