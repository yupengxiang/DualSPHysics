#!/usr/bin/env python3
"""Build a relocatable v25 graph with the v22 cold-cleanup supervisor.

v28's default constants are tied to the checkout that created the request.
That is useful for an ordinary build but makes a root worktree invocation
mistakenly compare the root's frozen v25 path with the consumer worktree's
path.  v29 accepts the explicitly supplied frozen v25/v26 request paths and
records those original provenance paths in the graph.  It does not rewrite
the nested requests or use a latest-file fallback.

The resulting v15/v22 contracts are fresh metadata files.  They remain
DEVELOPMENT/UNKNOWN and require the existing parent ledger, two filesystem
guard, OS open audit, and approved I/O slot.  The v22 wrapper is bound as the
actual outer entry and gives both the v14 child and v20 helper groups a 25 s
cold cleanup allowance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
LAB = SCRIPT_DIR.parents[0]
V25_DIR = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v25-consistent"
V26_DIR = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26-supervised-chain"
OUT_DIR = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v29-relocatable-chain"
V25_V13 = V25_DIR / "f2-s1-parent-supervised-launch-request-v13-012.json"
V26_V14 = V26_DIR / "f2-s1-parent-supervised-launch-request-v14-013.json"
V15_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v15.py"
V22_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v22.py"
V15_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v15-adapter-016.json"
V22_OUT = OUT_DIR / "f2-s1-external-supervisor-request-v22-016.json"
EXTERNAL = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
SUPERVISOR_ROOT = EXTERNAL / "f2-s1-v29-supervisor-001"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V15 = _load("ds02_parent_launcher_v15_for_v29", V15_PATH)
V22 = _load("ds02_external_supervisor_v22_for_v29", V22_PATH)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing existing v29 output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def _ref_path(item: Mapping[str, Any], key: str, parent: Path) -> Path:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"nested {key} path is missing in {parent}")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"nested request is missing: {path}")
    expected = item.get("sha256")
    nested = load(path)
    # Historical edges contain either canonical or file SHA; accept only an
    # explicit match to this exact file, never a path/name guess.
    if expected not in {nested.get("sha256"), _canonical(nested), sha256_file(path)}:
        raise ValueError(f"nested {key} SHA differs: {path}")
    return path


def _graph_from_v25(v25_path: Path) -> dict[str, dict[str, str]]:
    v13 = load(v25_path)
    if v13.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v13":
        raise ValueError("v25 source is not the expected v13 request")
    v12_path = _ref_path(v13["v12_launch"], "path", v25_path)
    v12 = load(v12_path)
    v11_path = _ref_path(v13["v11_launch"], "path", v25_path)
    v11 = load(v11_path)
    v10_path = _ref_path(v11["bridge_request"], "path", v11_path)
    v10 = load(v10_path)
    v7_path = _ref_path(v10["v7_request"], "path", v10_path)
    v7 = load(v7_path)
    command = v7.get("execution", {}).get("command", [])
    if not isinstance(command, list) or len(command) < 3:
        raise ValueError("v25 v7 command does not bind an engine")
    v7_engine = Path(str(command[2])).expanduser().resolve()
    if not v7_engine.is_file():
        raise ValueError(f"v25 v7 engine is missing: {v7_engine}")
    engine_binding = next((item for item in v7.get("source_bindings", [])
                           if isinstance(item, Mapping)
                           and item.get("role") == "portable_orchestrator_v7"), None)
    if not isinstance(engine_binding, Mapping) or Path(str(engine_binding.get("path", ""))).expanduser().resolve() != v7_engine:
        raise ValueError("v25 v7 command is not bound to its orchestrator source")
    v10_v7_ref = next((item for item in v10.get("source_bindings", [])
                       if isinstance(item, Mapping) and item.get("role") == "v7_request"), None)
    if not isinstance(v10_v7_ref, Mapping) or Path(str(v10_v7_ref.get("path", ""))).expanduser().resolve() != v7_path:
        raise ValueError("v25 v10 bridge does not load the bound v7 request")
    if Path(str(v12.get("v11_launch", {}).get("path", ""))).expanduser().resolve() != v11_path:
        raise ValueError("v25 v12/v11 graph is not continuous")
    nodes = {
        "v7_request": v7_path,
        "v10_bridge_request": v10_path,
        "v11_request": v11_path,
        "v12_request": v12_path,
        "v13_request": v25_path,
        "v7_engine": v7_engine,
    }
    return {role: {"path": str(path), "sha256": sha256_file(path),
                   "canonical_sha256": load(path).get("sha256") if path.suffix == ".json" else None}
            for role, path in nodes.items()}


def build(*, v25_v13: Path = V25_V13, v26_v14: Path = V26_V14,
          v15_output: Path = V15_OUT, v22_output: Path = V22_OUT,
          supervisor_root: Path = SUPERVISOR_ROOT) -> dict[str, Any]:
    v25 = v25_v13.expanduser().resolve()
    v26 = v26_v14.expanduser().resolve()
    if not v25.is_file() or not v26.is_file():
        raise ValueError("explicit v25/v26 requests must both exist")
    graph = _graph_from_v25(v25)
    v26_value = load(v26)
    if v26_value.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v14":
        raise ValueError("v26 source is not the expected v14 request")
    if Path(str(v26_value.get("forward_of", {}).get("path", ""))).expanduser().resolve() != v25:
        raise ValueError("v26 v14 request does not forward the supplied v25 v13 request")
    if v15_output.exists() or v22_output.exists() or supervisor_root.exists():
        raise ValueError("refusing existing v29 output namespace/request")
    v15 = V15.build_request(v26, v15_output)
    v22 = V22.build_request(v15_output, v22_output, output_root=supervisor_root,
                            max_wall_seconds=6000.0)
    value = load(v22_output)
    value["forward_graph_v29"] = {
        "authority": "explicit_frozen_v25_v26_paths",
        "v25_request": {"path": str(v25), "sha256": sha256_file(v25)},
        "v26_request": {"path": str(v26), "sha256": sha256_file(v26)},
        "nodes": copy.deepcopy(graph),
        "load_order": ["v22_supervisor", "v15_adapter", "v14_request",
                        "v13_request", "v12_request", "v11_request",
                        "v10_bridge_request", "v7_request", "v7_engine"],
        "no_latest_fallback": True,
        "relocation_policy": "original_uri_and_hash provenance are retained; actual bundle paths are overlay-bound by the parent",
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "v29 accepts explicit frozen request paths so root and consumer worktrees cannot be confused by a default absolute path.",
        "This build opens only JSON/source metadata; raw/HDF5/BI4 reading remains parent-slot gated.",
    ]
    value["sha256"] = V22.canonical_sha(value)
    # v22 created this new file for this builder; replace it only after adding
    # the v29 graph, while refusing any pre-existing destination.
    v22_output.unlink()
    _write_new(v22_output, value)
    return {"v15": v15, "v22": value, "graph": graph}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v25-v13", type=Path, default=V25_V13)
    parser.add_argument("--v26-v14", type=Path, default=V26_V14)
    parser.add_argument("--v15-output", type=Path, default=V15_OUT)
    parser.add_argument("--v22-output", type=Path, default=V22_OUT)
    parser.add_argument("--supervisor-root", type=Path, default=SUPERVISOR_ROOT)
    args = parser.parse_args(argv)
    value = build(v25_v13=args.v25_v13, v26_v14=args.v26_v14,
                  v15_output=args.v15_output, v22_output=args.v22_output,
                  supervisor_root=args.supervisor_root)
    print(json.dumps({"status": value["v22"].get("status"),
                      "v15": {"path": str(args.v15_output.resolve()),
                              "sha256": sha256_file(args.v15_output),
                              "canonical_sha256": value["v15"]["sha256"]},
                      "v22": {"path": str(args.v22_output.resolve()),
                              "sha256": sha256_file(args.v22_output),
                              "canonical_sha256": value["v22"]["sha256"]},
                      "graph": value["graph"]}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
