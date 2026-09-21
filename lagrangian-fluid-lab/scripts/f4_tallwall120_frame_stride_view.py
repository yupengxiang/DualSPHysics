#!/usr/bin/env python3
"""Create an exact frame-stride H5 view of a terminal F4 trajectory.

The view copies saved rows selected by ``frame_index % stride == 0``.  It
never interpolates particle positions, velocities, or any other field.  The
parent trajectory remains immutable; the output binds its parent SHA, stride,
and selected source indices in HDF5 attributes and a sidecar manifest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


SCHEMA = "core.cfd.frame_stride_view.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_attrs(source, target):
    for key, value in source.attrs.items():
        target.attrs[key] = value


def _create_frame_dataset(source, target, indices: np.ndarray):
    shape = (len(indices),) + source.shape[1:]
    kwargs = {}
    if source.chunks is not None:
        chunks = (min(source.chunks[0], len(indices)),) + source.chunks[1:]
        kwargs["chunks"] = chunks
    if source.compression is not None:
        kwargs["compression"] = source.compression
        if source.compression_opts is not None:
            kwargs["compression_opts"] = source.compression_opts
    if source.shuffle:
        kwargs["shuffle"] = source.shuffle
    if source.fletcher32:
        kwargs["fletcher32"] = source.fletcher32
    target = target.create_dataset(source.name.rsplit("/", 1)[-1], shape=shape,
                                   dtype=source.dtype, **kwargs)
    for out_index, source_index in enumerate(indices):
        target[out_index] = source[int(source_index)]
    _copy_attrs(source, target)
    return target


def build_view(source: Path, output: Path, *, stride: int,
               expected_source_sha256: str | None = None) -> dict:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if stride < 1 or isinstance(stride, bool):
        raise ValueError("stride must be a positive integer")
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(output)
    source_sha256 = sha256(source)
    if expected_source_sha256 is not None and source_sha256 != expected_source_sha256:
        raise ValueError("source SHA256 does not match the frozen parent binding")

    with h5py.File(source, "r") as src:
        if "time" not in src or src["time"].ndim != 1:
            raise ValueError("source must provide a one-dimensional time dataset")
        source_frame_count = int(src["time"].shape[0])
        indices = np.arange(0, source_frame_count, stride, dtype=np.int64)
        if len(indices) < 2 or indices[-1] != source_frame_count - 1:
            raise ValueError("exact stride view must retain the terminal source frame")
        frame_names = {
            name for name, dataset in src.items()
            if isinstance(dataset, h5py.Dataset)
            and dataset.ndim >= 1
            and dataset.shape[0] == source_frame_count
        }
        if "position" not in frame_names or "velocity" not in frame_names or "valid" not in frame_names:
            raise ValueError("source frame contract is incomplete")
        output.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(output, "x") as dst:
            _copy_attrs(src, dst)
            dst.attrs["view_schema"] = SCHEMA
            dst.attrs["view_source_sha256"] = source_sha256
            dst.attrs["view_source_path"] = str(source)
            dst.attrs["view_stride"] = int(stride)
            dst.attrs["view_selection_rule"] = "source_frame_index % stride == 0"
            dst.attrs["view_exact_rows_no_interpolation"] = True
            dst.attrs["view_source_frame_count"] = source_frame_count
            dst.attrs["view_frame_count"] = int(len(indices))
            dst.attrs["view_source_time_start_s"] = float(src["time"][0])
            dst.attrs["view_source_time_end_s"] = float(src["time"][-1])
            dst.attrs["view_native_output_interval_s"] = float(np.median(np.diff(src["time"])))
            dst.attrs["view_nominal_output_interval_s"] = float(
                np.median(np.diff(src["time"][indices]))
            )
            index_dataset = dst.create_dataset(
                "view_source_frame_index", data=indices, dtype=np.int64
            )
            index_dataset.attrs["selection_rule"] = "source_frame_index % stride == 0"
            for name, dataset in src.items():
                if not isinstance(dataset, h5py.Dataset):
                    continue
                if name in frame_names:
                    _create_frame_dataset(src[name], dst, indices)
                else:
                    src.copy(name, dst, name=name)
            dst.flush()

    output_sha256 = sha256(output)
    manifest = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(source), "sha256": source_sha256, "bytes": source.stat().st_size},
        "view": {
            "path": str(output),
            "sha256": output_sha256,
            "bytes": output.stat().st_size,
            "stride": int(stride),
            "selection_rule": "source_frame_index % stride == 0",
            "exact_rows_no_interpolation": True,
            "source_frame_count": source_frame_count,
            "view_frame_count": int(len(indices)),
            "source_frame_indices": indices.tolist(),
        },
        "scientific_status": "derived_reference_view; not an independent CFD run and not T2 qualification",
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_result = dict(manifest)
    manifest_result["manifest"] = {
        "path": str(manifest_path),
        "sha256": sha256(manifest_path),
        "bytes": manifest_path.stat().st_size,
    }
    return manifest_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stride", required=True, type=int)
    parser.add_argument("--expected-source-sha256")
    args = parser.parse_args()
    print(json.dumps(build_view(
        args.source, args.output, stride=args.stride,
        expected_source_sha256=args.expected_source_sha256,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
