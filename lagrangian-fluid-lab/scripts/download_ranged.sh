#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 URL OUTPUT [CONNECTIONS]" >&2
  exit 2
fi

download_url=$1
output_path=$2
connections=${3:-16}

mkdir -p "$(dirname "$output_path")"
parts_dir="${output_path}.parts"
mkdir -p "$parts_dir"

headers=$(curl -L -sS --fail -D - -o /dev/null --range 0-0 "$download_url")
total_bytes=$(printf '%s\n' "$headers" | awk -F/ 'tolower($1) ~ /^content-range:/ {gsub("\r", "", $2); print $2}' | tail -n 1)
if [[ ! "$total_bytes" =~ ^[0-9]+$ ]]; then
  echo "could not determine remote size" >&2
  exit 1
fi

chunk_bytes=$(( (total_bytes + connections - 1) / connections ))
pids=()
for ((part_index=0; part_index<connections; part_index++)); do
  start_byte=$((part_index * chunk_bytes))
  (( start_byte < total_bytes )) || break
  end_byte=$((start_byte + chunk_bytes - 1))
  (( end_byte < total_bytes )) || end_byte=$((total_bytes - 1))
  part_path=$(printf '%s/part-%04d' "$parts_dir" "$part_index")
  expected_bytes=$((end_byte - start_byte + 1))
  (
    current_bytes=0
    [[ -f "$part_path" ]] && current_bytes=$(stat -c %s "$part_path")
    if (( current_bytes != expected_bytes )); then
      tmp_path="${part_path}.tmp"
      [[ -f "$tmp_path" ]] || truncate -s 0 "$tmp_path"
      current_bytes=$(stat -c %s "$tmp_path")
      (( current_bytes <= expected_bytes )) || {
        truncate -s 0 "$tmp_path"
        current_bytes=0
      }
      while (( current_bytes < expected_bytes )); do
        resume_byte=$((start_byte + current_bytes))
        curl -L -sS --fail --retry 8 --retry-delay 3 \
          --connect-timeout 30 --range "${resume_byte}-${end_byte}" \
          "$download_url" >> "$tmp_path" || true
        next_bytes=$(stat -c %s "$tmp_path")
        if (( next_bytes <= current_bytes )); then
          sleep 5
        fi
        current_bytes=$next_bytes
        (( current_bytes <= expected_bytes )) || {
          echo "part ${part_index}: server returned too many bytes" >&2
          exit 1
        }
      done
      actual_bytes=$current_bytes
      if (( actual_bytes != expected_bytes )); then
        echo "part ${part_index}: expected ${expected_bytes}, got ${actual_bytes}" >&2
        exit 1
      fi
      mv "${part_path}.tmp" "$part_path"
    fi
  ) &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
(( failed == 0 )) || exit 1

assembled="${output_path}.assembling"
truncate -s 0 "$assembled"
for part_path in "$parts_dir"/part-*; do
  cat "$part_path" >> "$assembled"
done

assembled_bytes=$(stat -c %s "$assembled")
if (( assembled_bytes != total_bytes )); then
  echo "assembled file: expected ${total_bytes}, got ${assembled_bytes}" >&2
  exit 1
fi
mv "$assembled" "$output_path"
echo "downloaded ${output_path} (${total_bytes} bytes)"
