#!/usr/bin/env bash
set -euo pipefail

host_name="${1:?usage: prepare_host.sh ada|h200 [bundle-code-root]}"
bundle_code_root="${2:-}"
case "$host_name" in
  ada|h200) ;;
  *) echo "host must be ada or h200" >&2; exit 2 ;;
esac

lab_root="$(cd "$(dirname "$0")/../../../.." && pwd)"
env_root="$lab_root/campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1"
prefix="$env_root/runtime/$host_name"
source_prefix="/home/jade/.conda/envs/neural_lagrangian_solver_torch212"
record="$env_root/records/$host_name-import.json"
freeze="$env_root/records/$host_name.freeze.txt"
explicit="$env_root/records/$host_name.conda-explicit.txt"
if [[ -z "$bundle_code_root" ]]; then
  bundle_code_root="$lab_root/campaigns/core-v1/reproduction/ada-identical-h200-bundle-v3/code"
fi

if [[ ! -x "$source_prefix/bin/python" ]]; then
  echo "source environment is unavailable: $source_prefix" >&2
  exit 3
fi
if [[ -e "$prefix" ]]; then
  echo "refusing to overwrite existing prefix: $prefix" >&2
  exit 4
fi

mkdir -p "$env_root/records"
/opt/anaconda3/condabin/conda create --prefix "$prefix" \
  --clone "$source_prefix" --copy --yes

CUDA_VISIBLE_DEVICES= "$prefix/bin/python" -m pip install \
  --no-deps --only-binary=:all: numpy==2.2.6 scipy==1.15.3

CUDA_VISIBLE_DEVICES= "$prefix/bin/python" -m pip freeze --all > "$freeze"
/opt/anaconda3/condabin/conda list --explicit -p "$prefix" > "$explicit"
CUDA_VISIBLE_DEVICES= "$prefix/bin/python" \
  "$lab_root/scripts/core_cross_host_environment_probe.py" \
  --output "$record" \
  --host-label "$host_name" \
  --bundle-code-root "$bundle_code_root"

echo "prepared $host_name at $prefix"
echo "freeze: $freeze"
echo "record: $record"
