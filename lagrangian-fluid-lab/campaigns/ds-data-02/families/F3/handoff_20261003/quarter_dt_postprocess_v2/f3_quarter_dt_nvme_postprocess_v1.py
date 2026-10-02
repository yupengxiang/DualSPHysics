#!/usr/bin/env python3
"""Run F3 quarter labels and HALF comparison on a verified NVMe HDF5 copy.

The terminal converter output remains read-only.  The wrapper verifies the
conversion receipt/report and the HDF5 digest while copying it once to a
private NVMe scratch directory, runs the unchanged native-label and transport
comparison producers against that copy, then records the original source
path/digest in small output sidecars.  It never starts a solver or converter
and does not turn a numerical unknown into a physical exit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def signature(path: Path) -> tuple[int, int, int, int]:
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load producer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not Path(path).is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def verified_copy(source: Path, target: Path, expected_sha256: str) -> str:
    before = signature(source)
    digest_value = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(16 * 1024 * 1024), b""):
            digest_value.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    actual = digest_value.hexdigest()
    if signature(source) != before:
        raise ValueError("quarter H5 source changed during verified copy")
    if actual != expected_sha256:
        raise ValueError(f"quarter H5 digest mismatch: expected {expected_sha256}, got {actual}")
    target.chmod(0o400)
    return actual


def run(config_path: Path, output_dir: Path, scratch_parent: Path, particle_chunk: int = 65536) -> dict[str, Any]:
    config = read_json(config_path, "NVMe postprocess config")
    output_dir = Path(output_dir).expanduser().resolve()
    scratch_parent = Path(scratch_parent).expanduser().resolve()
    if output_dir.exists():
        runtime_files = {"execution-receipt.json", "stdout.log"}
        unexpected = [
            path.name
            for path in output_dir.iterdir()
            if path.name not in runtime_files and not path.name.startswith("execution-receipt.json.")
        ]
        if unexpected:
            raise FileExistsError(f"postprocess output is not fresh: {output_dir}; found {unexpected}")
    output_dir.mkdir(parents=True, exist_ok=True)

    source = require_file(Path(config["source_hdf5"]), "terminal quarter H5")
    receipt_path = require_file(Path(config["terminal_conversion_receipt"]), "terminal conversion receipt")
    report_path = require_file(Path(config["terminal_conversion_report"]), "terminal conversion report")
    receipt = read_json(receipt_path, "terminal conversion receipt")
    report = read_json(report_path, "terminal conversion report")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"terminal conversion receipt is not successful: {receipt.get('status')}/{receipt.get('returncode')}")
    expected_sha = str(config["source_hdf5_sha256"])
    if digest(receipt_path) != config["terminal_conversion_receipt_sha256"]:
        raise ValueError("terminal conversion receipt binding changed")
    if digest(report_path) != config["terminal_conversion_report_sha256"]:
        raise ValueError("terminal conversion report binding changed")
    if report.get("conversion_status") != "completed" or report.get("output_sha256") != expected_sha:
        raise ValueError("terminal report does not bind the expected completed H5")
    if report.get("frames") != config["expected_frames"] or report.get("solver_dimension", {}).get("solver_dimension") != 3:
        raise ValueError("terminal report does not meet the expected 3D/full-window shape")
    if source.stat().st_size != config["source_hdf5_bytes"]:
        raise ValueError("terminal H5 byte count changed")

    source_before = signature(source)
    scratch_parent.mkdir(parents=True, exist_ok=True)
    free_bytes = os.statvfs(scratch_parent).f_bavail * os.statvfs(scratch_parent).f_frsize
    if free_bytes < source.stat().st_size + 100 * 1024**3:
        raise ValueError("NVMe scratch requires source H5 plus 100 GiB free")

    labels_producer = require_file(Path(config["native_labels_producer"]), "native labels producer")
    compare_producer = require_file(Path(config["transport_compare_producer"]), "transport comparison producer")
    labels_config_path = require_file(Path(config["transport_config"]), "transport config")
    labels_config = read_json(labels_config_path, "transport config")
    half_labels = require_file(Path(config["half_labels"]), "HALF labels")
    if digest(half_labels) != config["half_labels_sha256"]:
        raise ValueError("HALF labels binding changed")

    label_path = output_dir / "typed-transport-labels.h5"
    comparison_path = output_dir / "quarter-vs-half-transport-comparison.json"
    source_contract_path = output_dir / "source-contract.json"

    with tempfile.TemporaryDirectory(prefix="ds02-f3-quarter-", dir=scratch_parent) as scratch:
        transient_h5 = Path(scratch) / "trajectory.h5"
        copied_sha = verified_copy(source, transient_h5, expected_sha)
        labels_module = load_module(labels_producer, "ds_data02_native_labels_quarter_v2")
        labels_result = labels_module.materialize(transient_h5, label_path, labels_config, particle_chunk=particle_chunk)

        # Keep the label payload produced by the unchanged operator, while
        # replacing only the transient source pathname with its immutable
        # original.  The source digest remains the verified H5 digest.
        import h5py

        with h5py.File(label_path, "r+") as labels_h5:
            labels_h5.attrs["source_hdf5"] = str(source)
            labels_h5.attrs["source_hdf5_sha256"] = copied_sha
            labels_h5.attrs["nvme_copy_verified"] = True
            labels_h5.attrs["nvme_original_stat_unchanged"] = True

        compare_module = load_module(compare_producer, "ds_data02_f3_transport_compare_quarter_v2")
        comparison_result = compare_module.compare(
            half_labels,
            [label_path],
            output=comparison_path,
            particle_chunk=particle_chunk,
        )

    if signature(source) != source_before:
        raise ValueError("terminal quarter H5 changed during NVMe postprocess")
    label_sha = digest(label_path)
    comparison_sha = digest(comparison_path)
    source_contract = {
        "schema": "ds02.f3.quarter-nvme-postprocess-source-contract.v1",
        "source_hdf5": str(source),
        "source_hdf5_sha256": copied_sha,
        "source_hdf5_bytes": source.stat().st_size,
        "terminal_conversion_receipt": str(receipt_path),
        "terminal_conversion_receipt_sha256": digest(receipt_path),
        "terminal_conversion_report": str(report_path),
        "terminal_conversion_report_sha256": digest(report_path),
        "copy_protocol": "single sequential SHA-verified private NVMe copy; original read-only and stat unchanged",
        "scientific_reader": str(labels_producer),
        "labels_path": str(label_path),
        "labels_sha256": label_sha,
        "comparison_path": str(comparison_path),
        "comparison_sha256": comparison_sha,
        "q_i_status": "labels/comparison evidence produced; full Q-I review remains separate",
        "q_n_status": "not_assessed",
        "production_approval": "none",
    }
    source_contract_path.write_text(json.dumps(source_contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema": "ds02.f3.quarter-nvme-postprocess.v1",
        "config": str(config_path.resolve()),
        "config_sha256": digest(config_path),
        "source_contract": str(source_contract_path),
        "source_contract_sha256": digest(source_contract_path),
        "source_hdf5": str(source),
        "source_hdf5_sha256": copied_sha,
        "copy_verified_before_scientific_read": True,
        "original_stat_unchanged": True,
        "private_scratch_removed": True,
        "labels": {"path": str(label_path), "sha256": label_sha, "producer_result": labels_result},
        "comparison": {"path": str(comparison_path), "sha256": comparison_sha, "producer_result": comparison_result},
        "q_i_status": "labels/comparison evidence produced; Q-I verdict pending contract review",
        "q_n_status": "not_assessed",
        "production_approval": "none",
    }
    (output_dir / "nvme-postprocess.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scratch-parent", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    args = parser.parse_args()
    result = run(args.config, args.output_dir, args.scratch_parent, args.particle_chunk)
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "labels_sha256": result["labels"]["sha256"], "comparison_sha256": result["comparison"]["sha256"], "q_n_status": "not_assessed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
