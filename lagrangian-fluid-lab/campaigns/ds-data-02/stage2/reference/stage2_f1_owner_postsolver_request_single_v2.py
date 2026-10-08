#!/usr/bin/env python3
"""Emit one additive F1 owner post-solver request after a terminal receipt.

This is a forward wrapper around the consumed v1 builder.  It intentionally
handles one run so that a late terminal receipt (currently dp0025/half-CFL)
does not regenerate or touch the three already-consumed v1 request bundles.
The builder only reads text metadata and ``stat`` information for selected
native Part files; it does not read or hash native payload bytes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f1_owner_postsolver_requests_v1.py"
SCHEMA = "ds02.stage2.f1.owner-postsolver-request-builder.v2.single-forward"


def load_v1():
    spec = importlib.util.spec_from_file_location("stage2_f1_owner_postsolver_v1_frozen", V1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load consumed v1 builder: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(payload)


def add_builder_binding(value: dict[str, Any], v1: Any, wrapper: Path) -> None:
    """Record this wrapper in the request closure without changing v1 source."""
    wrapper = wrapper.resolve()
    files = value.setdefault("input_files", [])
    hashes = value.setdefault("input_hashes", {})
    if str(wrapper) not in files:
        files.append(str(wrapper))
    hashes[str(wrapper)] = v1.sha256_file(wrapper)


def build(dp: str, mode: str, out: Path) -> dict[str, str]:
    v1 = load_v1()
    receipt_path = v1.run_receipt(dp, mode)
    if receipt_path is None:
        raise RuntimeError(f"no completed terminal receipt for {dp}/{mode}")

    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    observer, snapshot, dt_request, _ = v1.make_observer(dp, mode, receipt_path, out)
    wrapper = Path(__file__).resolve()

    stem = f"f1_s1_owner_{dp}_{mode}"
    observer_path = out / f"{stem}_selected_native_observer_v2.json"
    snapshot_path = out / f"{stem}_selected_native_snapshot_v2.json"
    dt_path = out / f"{stem}_savedt_metadata_v2.json"

    # Rebind only the emitted paths/identity.  The source, decoder, controls,
    # query brackets, and deferred selected-Part policy come from frozen v1.
    observer["schema"] = "ds02.request.v1"
    observer["case_id"] = f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SELECTED_NATIVE_OBSERVER_V2"
    observer["attempt_id"] = f"f1-s1-owner-{dp}-{mode}-selected-native-observer-v2-root-forward-001"
    observer["qualification_stage"] = "stage2_f1_owner_postsolver_selected_native_pending_parent_cpu_guard_v2"
    observer["source_binding"]["schema"] = SCHEMA
    observer["output"]["path"] = f"{{attempt_root}}/observer/{observer_path.name}"
    observer["command"][observer["command"].index("--output") + 1] = observer["output"]["path"]
    add_builder_binding(observer, v1, wrapper)

    snapshot["case_id"] = f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SELECTED_NATIVE_SNAPSHOT_V2"
    snapshot["attempt_id"] = f"f1-s1-owner-{dp}-{mode}-selected-native-snapshot-v2-root-forward-001"
    snapshot["output"]["path"] = f"{{attempt_root}}/snapshot/{snapshot_path.name}"
    snapshot["command"][snapshot["command"].index("--observer-request") + 1] = str(observer_path)
    snapshot["command"][snapshot["command"].index("--output") + 1] = snapshot["output"]["path"]
    snapshot["input_files"] = [str(observer_path) if p == str(out / f"f1_s1_owner_{dp}_{mode}_selected_native_observer_v1.json") else p for p in snapshot["input_files"]]
    add_builder_binding(snapshot, v1, wrapper)
    snapshot["input_hashes"].pop(str(out / f"f1_s1_owner_{dp}_{mode}_selected_native_observer_v1.json"), None)
    snapshot["input_hashes"][str(observer_path)] = "REQUEST_HASH_AFTER_EMISSION"
    snapshot["source_binding"]["observer_request"] = {"path": str(observer_path), "sha256": "REQUEST_HASH_AFTER_EMISSION"}

    dt_request["case_id"] = f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SAVEDT_METADATA_V2"
    dt_request["attempt_id"] = f"f1-s1-owner-{dp}-{mode}-savedt-metadata-v2-root-forward-001"
    dt_request["output"]["path"] = f"{{attempt_root}}/savedt/{dt_path.name}"
    dt_request["command"][dt_request["command"].index("--output") + 1] = dt_request["output"]["path"]
    add_builder_binding(dt_request, v1, wrapper)

    atomic_json(observer_path, observer)
    snapshot["input_hashes"][str(observer_path)] = v1.sha256_file(observer_path)
    snapshot["source_binding"]["observer_request"] = v1.record(observer_path)
    atomic_json(snapshot_path, snapshot)
    atomic_json(dt_path, dt_request)
    return {"observer": str(observer_path), "snapshot": str(snapshot_path), "savedt": str(dt_path), "receipt": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dp", choices=("dp005", "dp0025"), required=True)
    parser.add_argument("--mode", choices=("same_cfl", "half_cfl"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"status": "PASS_REQUESTS_EMITTED", **build(args.dp, args.mode, args.output_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
