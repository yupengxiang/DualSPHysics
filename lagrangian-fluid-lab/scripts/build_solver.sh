#!/usr/bin/env bash
set -euo pipefail

lab_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_dir="$lab_root/vendor/src/source"
log_dir="$lab_root/reports/runtime"
mkdir -p "$log_dir"

make -C "$source_dir" -j"${BUILD_JOBS:-8}" \
  CUDA=00 \
  DIRTOOLKIT=/usr/local/cuda \
  COMPILE_MOORDYNPLUS=NO \
  'GENCODE=-gencode=arch=compute_89,code=sm_89' \
  2>&1 | tee "$log_dir/build-solver.log"
