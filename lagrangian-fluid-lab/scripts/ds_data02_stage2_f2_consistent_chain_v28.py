#!/usr/bin/env python3
"""Build the parent-scheduled v25→v15→v21 F2 launch graph.

The v25 request is the authority for the portable v7 graph that the bridge
actually opens.  Earlier forward builders produced the v14/v15/v21 requests,
but the graph relationship was only implicit in the inherited JSON.  This
additive builder verifies every nested request and records the exact v7,
v10, v11, v12, v13, v14, v15 and v21 hashes in a fresh v21 request.  It does
not rewrite a consumed request, create the output namespace, or open a raw
dataset.  The resulting request is still DEVELOPMENT/UNKNOWN and requires
the existing parent ledger and both Home/external filesystem guards.
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
OUT_DIR = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v28-supervised-chain"
V25_V13 = V25_DIR / "f2-s1-parent-supervised-launch-request-v13-012.json"
V26_V14 = V26_DIR / "f2-s1-parent-supervised-launch-request-v14-013.json"
V15_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v15.py"
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
V15_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v15-adapter-015.json"
V21_OUT = OUT_DIR / "f2-s1-external-supervisor-request-v21-015.json"
EXTERNAL = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
SUPERVISOR_ROOT = EXTERNAL / "f2-s1-v28-supervisor-001"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V15 = _load("ds02_parent_launcher_v15_for_v28", V15_PATH)
V21 = _load("ds02_external_supervisor_v21_for_v28", V21_PATH)


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
    if path.exists():
        raise ValueError(f"refusing to overwrite v28 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def _request_sha(path: Path) -> str:
    value = load(path)
    declared = value.get("sha256")
    if declared != _canonical(value):
        raise ValueError(f"noncanonical nested request: {path}")
    if not isinstance(declared, str) or sha256_file(path) == "":
        raise ValueError(f"missing request SHA: {path}")
    return str(declared)


def _ref_path(item: Mapping[str, Any], key: str, parent: Path) -> Path:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"nested {key} path is missing in {parent}")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"nested request is missing: {path}")
    expected = item.get("sha256")
    nested = load(path)
    # Some historical request edges bind the canonical JSON SHA while the
    # v10 bridge edge binds the file SHA.  Both are explicit provenance; a
    # missing/third value is rejected.
    if expected not in {nested.get("sha256"), _canonical(nested), sha256_file(path)}:
        raise ValueError(f"nested {key} SHA differs: {path}")
    return path


def _graph_from_v25() -> dict[str, dict[str, str]]:
    """Resolve the exact request graph opened by the v10 bridge."""
    v13 = load(V25_V13)
    if v13.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v13":
        raise ValueError("v25 source is not the expected v13 request")
    v12_path = _ref_path(v13["v12_launch"], "path", V25_V13)
    v12 = load(v12_path)
    v11_path = _ref_path(v13["v11_launch"], "path", V25_V13)
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
    v7_engine_binding = next((item for item in v7.get("source_bindings", [])
                              if isinstance(item, Mapping)
                              and item.get("role") == "portable_orchestrator_v7"), None)
    if not isinstance(v7_engine_binding, Mapping) or Path(str(v7_engine_binding.get("path", ""))).expanduser().resolve() != v7_engine:
        raise ValueError("v25 v7 command is not bound to its orchestrator source")
    v10_v7_ref = next((item for item in v10.get("source_bindings", [])
                       if isinstance(item, Mapping) and item.get("role") == "v7_request"), None)
    if not isinstance(v10_v7_ref, Mapping) or Path(str(v10_v7_ref.get("path", ""))).expanduser().resolve() != v7_path:
        raise ValueError("v25 v10 bridge does not load the bound v7 request")
    nodes = {
        "v7_request": v7_path,
        "v10_bridge_request": v10_path,
        "v11_request": v11_path,
        "v12_request": v12_path,
        "v13_request": V25_V13,
        "v7_engine": v7_engine,
    }
    # The v12 object is deliberately traversed above; this explicit check
    # catches an alias that jumps from v13 to an unrelated v11/v10 graph.
    v12_v11 = v12.get("v11_launch", {})
    if Path(str(v12_v11.get("path", ""))).expanduser().resolve() != v11_path:
        raise ValueError("v25 v12/v11 graph is not continuous")
    return {role: {"path": str(path), "sha256": sha256_file(path),
                   "canonical_sha256": load(path).get("sha256") if path.suffix == ".json" else None}
            for role, path in nodes.items()}


def _add_graph_binding(v21: dict[str, Any], graph: Mapping[str, Mapping[str, str]],
                       *, home_receipt_path: str | None) -> dict[str, Any]:
    value = copy.deepcopy(v21)
    v14 = load(Path(str(value["v14_request"]["path"])))
    v14_storage = v14.get("storage_scope", {})
    external_roots = list(v14_storage.get("external_roots", []))
    value["forward_graph"] = {
        "authority": "v25_v13_request_and_transitive_v7_bridge_graph",
        "immutable": True,
        "builder": {"path": str(Path(__file__).resolve()),
                     "sha256": sha256_file(Path(__file__).resolve())},
        "nodes": copy.deepcopy(dict(graph)),
        "load_order": ["v21_supervisor", "v15_adapter", "v14_request",
                        "v13_request", "v12_request", "v11_request",
                        "v10_bridge_request", "v7_request", "v7_engine"],
        "all_nested_paths_are_explicit": True,
    }
    value["same_parent_filesystems"] = {
        "ledger_path": value["parent_resource_binding"]["ledger_path"],
        "storage_policy": value["parent_resource_binding"]["storage_policy"],
        "home_receipt": {
            "path": home_receipt_path,
            "floor_bytes": value["parent_resource_binding"].get("home_min_free_bytes"),
            "charged_under_parent_ledger": True,
        },
        "external_output": {
            "filesystem": value["storage_scope"]["external_filesystem"],
            "roots": external_roots,
            "floor_bytes": value["storage_scope"].get("external_min_free_bytes"),
            "charged_under_parent_ledger": True,
        },
        "new_data_root_or_ledger": False,
        "symlink_bypass": "FORBIDDEN",
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "v28 records and validates the complete v25 v7/v10/v11/v12/v13 graph before the v15/v21 requests are written.",
        "The outer parent must still supply the shared ledger lease, Home floor, external filesystem floor, and approved I/O slot.",
        "No raw/HDF5/BI4 source is opened by this builder; all qualification fields remain UNKNOWN.",
    ]
    value["sha256"] = V21.canonical_sha(value)
    return value


def build(*, v25_v13: Path = V25_V13, v26_v14: Path = V26_V14,
          v15_output: Path = V15_OUT, v21_output: Path = V21_OUT,
          supervisor_root: Path = SUPERVISOR_ROOT) -> dict[str, Any]:
    if v25_v13.resolve() != V25_V13.resolve() or v26_v14.resolve() != V26_V14.resolve():
        raise ValueError("v28 only accepts the frozen v25/v26 graph paths")
    graph = _graph_from_v25()
    v26 = load(v26_v14)
    if v26.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v14":
        raise ValueError("v26 source is not the expected v14 request")
    if Path(str(v26.get("forward_of", {}).get("path", ""))).expanduser().resolve() != v25_v13.resolve():
        raise ValueError("v26 v14 request is not a forward of the frozen v25 v13 request")
    if v15_output.exists() or v21_output.exists() or supervisor_root.exists():
        raise ValueError("refusing existing v28 output namespace/request")
    v15 = V15.build_request(v26_v14, v15_output)
    v21 = V21.build_request(v15_output, v21_output, output_root=supervisor_root,
                            max_wall_seconds=6000.0)
    home_receipt_path = load(v15_output).get("accounting", {}).get("home_receipt_path")
    v21 = _add_graph_binding(v21, graph, home_receipt_path=home_receipt_path)
    # build_request has already written the v21 file.  It is safe to replace
    # this newly-created file inside the same atomic builder; consumed files
    # are never touched.  Use a temporary sibling so a partial rewrite cannot
    # leave a canonical request with stale bytes.
    temp = v21_output.with_name(v21_output.name + ".forwarding")
    _write_new(temp, v21)
    v21_output.unlink()
    temp.replace(v21_output)
    return {"v15": v15, "v21": v21, "graph": graph}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v25-v13", type=Path, default=V25_V13)
    parser.add_argument("--v26-v14", type=Path, default=V26_V14)
    parser.add_argument("--v15-output", type=Path, default=V15_OUT)
    parser.add_argument("--v21-output", type=Path, default=V21_OUT)
    parser.add_argument("--supervisor-root", type=Path, default=SUPERVISOR_ROOT)
    args = parser.parse_args(argv)
    value = build(v25_v13=args.v25_v13, v26_v14=args.v26_v14,
                  v15_output=args.v15_output, v21_output=args.v21_output,
                  supervisor_root=args.supervisor_root)
    print(json.dumps({"status": value["v21"]["status"],
                      "v15": {"path": str(args.v15_output), "sha256": sha256_file(args.v15_output),
                              "canonical_sha256": value["v15"]["sha256"]},
                      "v21": {"path": str(args.v21_output), "sha256": sha256_file(args.v21_output),
                              "canonical_sha256": value["v21"]["sha256"]},
                      "graph": value["graph"]}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
