#!/usr/bin/env python3
"""Source-only V58 interface inventory for a copied F2 worker graph.

This is deliberately separate from the frozen V57 executor/request.  It
reads only bounded Python and JSON metadata and delegates the path/inode/SHA
checks to V57.  The report distinguishes module-load imports from interfaces
that would open HDF5/BI4/PartVTK during a guarded payload stage.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V57_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v57.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
MAX_SOURCE_BYTES = 1_000_000
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class InventoryV58Error(RuntimeError):
    pass


def _load_v57() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_v57_inventory_v58", V57_SCRIPT)
    if spec is None or spec.loader is None:
        raise InventoryV58Error(f"cannot load V57: {V57_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V57 = _load_v57()


def _regular(value: Path | str, role: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise InventoryV58Error(f"{role} is not a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise InventoryV58Error(f"{role} exceeds source-only bound: {path}")
    return path.resolve()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def build_inventory(*, wrapper: Path | str, plain_worker: Path | str,
                    aliases: Mapping[str, Path | str], decoder: Path | str,
                    bundle_root: Path | str) -> dict[str, Any]:
    """Build an evidence-scoped report without invoking native/payload code."""
    base = V57.inventory_code_graph(wrapper=wrapper, plain_worker=plain_worker,
                                    aliases=aliases, decoder=decoder,
                                    bundle_root=bundle_root)
    wrapper_path = _regular(wrapper, "V4 wrapper")
    plain_path = _regular(plain_worker, "plain worker")
    alias_paths = {role: _regular(path, f"alias {role}")
                   for role, path in aliases.items()}
    texts = {role: _text(path) for role, path in alias_paths.items()}
    plain_text = _text(plain_path)
    wrapper_text = _text(wrapper_path)
    decoder_path = _regular(decoder, "native BI4 decoder")
    decoder_mode = stat.S_IMODE(decoder_path.stat().st_mode)

    interfaces = {
        "v4_wrapper": {
            "worker_lookup": "_worker_path() -> bundle/runtime/native/WORKER_NAME",
            "plain_worker_load": "_load_worker() uses importlib.spec_from_file_location",
            "source_sha": _sha(wrapper_path),
            "wrapper_contract_tokens_present": _contains(wrapper_text, "def _worker_path", "def _load_worker", "runtime", "native"),
        },
        "plain_worker_v2": {
            "module_load_imports": [name for name, present in (
                ("h5py", "import h5py" in plain_text),
                ("numpy", "import numpy as np" in plain_text),
            ) if present],
            "module_load_only": True,
            "module_load_opens_hdf5": False,
            "hdf5_interfaces": [
                "_validate_and_load_typed -> h5py.File(path, 'r')",
            ] if "h5py.File" in plain_text else [],
            "converter_interface": {
                "call": "converter.convert_direct",
                "decoder_argument": "decoder",
                "partvtk_argument": "None",
                "run_partvtk": False,
            },
            "label_interfaces": [
                "v15.replay_trajectory_v15",
                "v16.forward_result",
            ],
        },
        "raw_converter": {
            "module_load_imports": [name for name, present in (
                ("h5py", "import h5py" in texts["raw_converter"]),
                ("numpy", "import numpy as np" in texts["raw_converter"]),
            ) if present],
            "convert_direct_defined": "def convert_direct" in texts["raw_converter"],
            "decoder_process_interface": "subprocess" in texts["raw_converter"] and "decode_frame" in texts["raw_converter"],
            "hdf5_output_interface": "h5py.File" in texts["raw_converter"],
            "partvtk_is_optional_converter_interface": "run_partvtk" in texts["raw_converter"],
        },
        "v14_operator": {
            "module_load_imports": ["numpy"] if "import numpy as np" in texts["v14_operator"] else [],
            "hdf5_import_deferred": "import h5py" in texts["v14_operator"],
            "hdf5_open_interface": "h5py.File" in texts["v14_operator"],
            "approved_read_entrypoints": [name for name in ("read_hdf5_initial_frame", "read_hdf5_window")
                                           if f"def {name}" in texts["v14_operator"]],
        },
        "v15_operator": {
            "module_load_imports": ["numpy"] if "import numpy as np" in texts["v15_operator"] else [],
            "delegates_hdf5_reads_to_v14": "v14.read_hdf5_window" in texts["v15_operator"],
            "label_entrypoint": "def replay_trajectory_v15" in texts["v15_operator"],
        },
        "v16_operator": {
            "module_load_imports": ["numpy"] if "import numpy as np" in texts["v16_operator"] else [],
            "hdf5_import_present": "h5py" in texts["v16_operator"],
            "json_forward_entrypoint": "def forward_result" in texts["v16_operator"],
            "scope": "JSON/result post-processing; no trajectory HDF5 read in this operator",
        },
    }
    base.update({
        "schema": "ds02.stage2.f2-copied-dependency-inventory-v58.v1",
        "module_interfaces": interfaces,
        "executed_binary_and_interface_scope": {
            "source_only_cli": "inventory",
            "executed_by_this_report": [
                "V57 bounded source/path/inode/SHA checks",
                "Python source-token interface checks",
            ],
            "not_executed": [
                "native BI4 decoder binary",
                "converter.convert_direct",
                "converter.decode_frame",
                "h5py.File payload reads",
                "v15.replay_trajectory_v15",
                "v16.forward_result",
                "PartVTK executable",
            ],
            "decoder": {
                "path": str(decoder_path),
                "sha256": _sha(decoder_path),
                "mode_bits": decoder_mode,
                "bound_executable": bool(decoder_mode & 0o111),
                "executed": False,
            },
            "payload_read": False,
            "interpretation": (
                "The copied Python import graph and interfaces are identified; "
                "this report grants no native conversion, HDF5, label, or PartVTK credit."
            ),
        },
        "qualification": dict(UNKNOWN),
    })
    return base


def _parse_aliases(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        role, separator, path = item.partition("=")
        if not separator or not role or not path:
            raise InventoryV58Error("alias must be role=absolute-path")
        if role in result:
            raise InventoryV58Error(f"duplicate alias role: {role}")
        result[role] = path
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--plain-worker", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--alias", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_inventory(
            wrapper=args.wrapper, plain_worker=args.plain_worker,
            aliases=_parse_aliases(args.alias), decoder=args.decoder,
            bundle_root=args.bundle_root)
        V57._write_new(args.output, result)
    except (InventoryV58Error, V57.PortableV57Error, V57.V56.PortableV56Error,
            V57.V55.PortableV55Error, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"f2 copied dependency inventory v58: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
