#!/usr/bin/env python3
"""Forward raw-to-label bundle with an explicit solver Run.out binding.

The v1 bundle remains immutable.  This additive version retains the v1
source/report/label checks and adds the exact Run.out selected by the solver
receipt command/output scope.  A portable raw reconstruction cannot rely on a
neighboring log: the native converter parses this log while decoding BI4.
The resulting v2 manifest is consumed by the v1 loader and remains
DEVELOPMENT with UNKNOWN qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import ds_data02_stage2_f2_native_raw_to_label_bundle_v1 as v1


BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class RawToLabelBundleV2Error(ValueError):
    """Raised when the v2 Run.out binding cannot be established."""


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RawToLabelBundleV2Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RawToLabelBundleV2Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RawToLabelBundleV2Error(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def _resolve_run_out(manifest: Mapping[str, Any]) -> tuple[Path, str, str]:
    sources = manifest.get("source_bindings")
    if not isinstance(sources, list):
        raise RawToLabelBundleV2Error("bundle source_bindings are required")
    receipts = [item for item in sources if isinstance(item, Mapping)
                and (item.get("role") == "v2:solver_receipt" or str(item.get("role", "")).endswith(":solver_receipt"))]
    if len(receipts) != 1:
        raise RawToLabelBundleV2Error("exactly one solver receipt binding is required")
    receipt_path = Path(str(receipts[0].get("original_path", ""))).expanduser().resolve()
    receipt = _load(receipt_path)
    command = receipt.get("command")
    output_root_value = receipt.get("output_root")
    if not isinstance(command, list) or not command or not isinstance(output_root_value, str):
        raise RawToLabelBundleV2Error("solver receipt command/output_root is required")
    candidates: list[Path] = []
    for value in command:
        if isinstance(value, str) and ("solver_output" in value or value.endswith("output")):
            candidate = Path(value).expanduser()
            if candidate.is_dir():
                candidates.append(candidate / "Run.out")
    output_root = Path(output_root_value).expanduser()
    candidates.extend([output_root / "solver_output" / "Run.out", output_root / "Run.out"])
    unique: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in unique:
            unique.append(candidate)
    present = [candidate for candidate in unique if candidate.is_file()]
    if len(present) != 1:
        raise RawToLabelBundleV2Error(
            "exact solver command output Run.out is missing or ambiguous; "
            f"checked {[str(item) for item in unique]}")
    run_out = present[0]
    role_matches = [item for item in sources if isinstance(item, Mapping)
                    and Path(str(item.get("original_path", ""))).expanduser().resolve() == run_out]
    if role_matches:
        raise RawToLabelBundleV2Error("solver Run.out is already present under an ambiguous source role")
    return run_out, str(receipts[0]["role"]), str(receipt_path)


def _run_out_binding(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": "solver_run_out",
        "original_path": str(path.resolve()),
        "bundle_relative_path": "sources/solver_run_out/Run.out",
        "bytes": int(stat.st_size),
        "original_mtime_ns": int(stat.st_mtime_ns),
        "content_sha256": v1.sha256_file(path),
        "content_hash_status": "VERIFIED_NOW",
        "replay_actionable": True,
        "receipt_output_scope": "exact solver receipt command/output_root; no neighboring fallback",
    }


def build_bundle_manifest_v2(request_path: Path | str, report_path: Path | str,
                             anchor_index_path: Path | str) -> dict[str, Any]:
    base = v1.build_bundle_manifest(request_path, report_path, anchor_index_path)
    run_out, receipt_role, receipt_path = _resolve_run_out(base)
    manifest = dict(base)
    manifest["schema"] = BUNDLE_SCHEMA
    source_bindings = [dict(item) for item in base["source_bindings"]]
    source_bindings.append(_run_out_binding(run_out))
    manifest["source_bindings"] = source_bindings
    manifest["runtime_access_bindings"] = {
        "solver_receipt_role": receipt_role,
        "solver_receipt_original_path": receipt_path,
        "solver_run_out_role": "solver_run_out",
        "raw_converter_run_out_policy": "exact receipt command output only",
        "python_audit_hook_scope": "Python opens only; parent strace required for HDF5/native C opens",
        "license_and_import_closure": "bound by inherited v4 import_closure and shared guard roles",
    }
    replay_contract = dict(manifest.get("replay_contract", {}))
    replay_contract["solver_run_out_role"] = "solver_run_out"
    replay_contract["loader"] = "ds_data02_stage2_f2_native_raw_to_label_loader_v1.py"
    manifest["replay_contract"] = replay_contract
    manifest["sha256"] = v1.canonical_sha(manifest)
    if manifest["qualification"] != UNKNOWN:
        raise RawToLabelBundleV2Error("qualification must remain UNKNOWN")
    return manifest


def prepare_bundle_v2(request_path: Path | str, report_path: Path | str,
                      anchor_index_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise RawToLabelBundleV2Error(f"refusing to overwrite existing bundle root: {target}")
    manifest = build_bundle_manifest_v2(request_path, report_path, anchor_index_path)
    target.mkdir(parents=True, exist_ok=False)
    _write_new(target / "bundle-manifest-v2.json", manifest)
    template = v1._path_map_template(manifest)
    template["schema"] = "ds02.stage2.f2-native-raw-to-label-path-map.v2"
    template["required_role"] = "solver_run_out"
    _write_new(target / "path-map-template-v2.json", template)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--anchor-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_bundle_v2(args.request, args.report, args.anchor_index, args.output_dir)
    except (OSError, RawToLabelBundleV2Error, v1.RawToLabelBundleError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "sha256": result["sha256"], "qualification": result["qualification"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
