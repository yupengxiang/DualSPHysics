#!/usr/bin/env python3
"""Forward v35 path-contract builder and v34-compatible executor shim.

The consumed v34 request copied BI4 frames as ``sources/0038-Part_0000.bi4``.
The native v2 worker deliberately requires a data root whose immediate
children are exactly ``Part_0000.bi4``, ``Part_0001.bi4``, ... .  This module
creates a new metadata-only request/overlay with that layout and delegates
execution to the immutable v34 implementation through the compatibility
envelope required by the consumed parent-v3 guard.

``build-forward`` reads JSON and small runtime metadata only.  It does not
open or hash HDF5, BI4, or raw source content.  The compatibility envelope is
intentional: parent-v3 still validates the executor schema as v34.  The
``forward_v35`` record makes the additive path contract explicit and lets a
future parent-v4 consume the same request without silently treating it as the
old v34 artifact.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V34_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v34.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v35-forward.v1"
BOUND_V34_SHA256 = "506477a0feb24a9e6b58af82499bf242f37a3cd768bc39cd6dbaa73d1dead989"
RAW_FRAME_RE = re.compile(r"^Part_(\d{4,})\.bi4$")
HEX64 = set("0123456789abcdef")


class PortableV35Error(RuntimeError):
    """Raised when a v35 metadata/path contract is incomplete."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV35Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV35Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableV35Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise PortableV35Error(f"{name} must be a lowercase SHA-256")
    return value


def _validate_envelope(request: Mapping[str, Any], *, name: str) -> None:
    if request.get("schema") != V34_SCHEMA:
        raise PortableV35Error(f"{name} must use the parent-v3 v34 compatibility schema")
    if request.get("sha256") != canonical_sha(request):
        raise PortableV35Error(f"{name} canonical SHA differs")
    if request.get("role") == "PRODUCTION" or request.get("qualification") not in ({
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"
    }, None):
        raise PortableV35Error(f"{name} must remain DEVELOPMENT/UNKNOWN")


def _frame_number(item: Mapping[str, Any], *, index: int) -> int:
    if item.get("role") != "raw_frame_input":
        raise PortableV35Error(f"source entry {index} is not a raw_frame_input")
    path_value = item.get("path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise PortableV35Error(f"raw source entry {index} has no absolute path")
    match = RAW_FRAME_RE.fullmatch(Path(path_value).name)
    if match is None:
        raise PortableV35Error(f"raw source entry {index} is not named Part_####.bi4")
    return int(match.group(1))


def _raw_layout(source_entries: Sequence[Mapping[str, Any]], overlay_entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sources = [item for item in source_entries if item.get("role") == "raw_frame_input"]
    if len(sources) < 2:
        raise PortableV35Error("at least two raw frame source entries are required")
    numbers = [_frame_number(item, index=index) for index, item in enumerate(sources)]
    if numbers != list(range(len(numbers))):
        raise PortableV35Error(f"raw frame source numbers are not contiguous from zero: {numbers[:5]}")
    overlay_by_original = {
        str(Path(item.get("original_path", "")).expanduser().resolve()): item
        for item in overlay_entries if item.get("role") == "raw_frame_input"
    }
    if len(overlay_by_original) != len(sources):
        raise PortableV35Error("overlay raw frame entries do not match source entries")
    rewritten: list[dict[str, Any]] = []
    for number, source in enumerate(sources):
        original = str(Path(str(source["path"])).expanduser().resolve())
        item = overlay_by_original.get(original)
        if item is None:
            raise PortableV35Error(f"overlay is missing raw frame: {original}")
        value = dict(item)
        value["bundle_relative_path"] = f"Part_{number:04d}.bi4"
        rewritten.append(value)
    return {"count": len(sources), "frame_numbers": numbers, "entries": rewritten}


def build_forward(*, v34_request: Path | str, v5_overlay: Path | str,
                  output_request: Path | str, output_overlay: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    """Create v35 path-correct metadata without reading scientific content."""
    request = load_json(v34_request)
    overlay = load_json(v5_overlay)
    _validate_envelope(request, name="v34 request")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise PortableV35Error("v5 overlay canonical SHA differs")
    bundle = request.get("v5_bundle")
    overlay_binding = request.get("v5_overlay_template")
    if not isinstance(bundle, Mapping) or not isinstance(overlay_binding, Mapping):
        raise PortableV35Error("v34 request lacks bundle/overlay bindings")
    if overlay.get("bundle", {}).get("canonical_sha256") != bundle.get("canonical_sha256"):
        raise PortableV35Error("overlay does not bind the v34 bundle")
    source_entries = request.get("source_entries")
    overlay_entries = overlay.get("entries")
    if not isinstance(source_entries, list) or not isinstance(overlay_entries, list):
        raise PortableV35Error("source_entries and overlay.entries are required")
    layout = _raw_layout(source_entries, overlay_entries)
    raw_by_original = {
        str(Path(item["original_path"]).expanduser().resolve()): item
        for item in layout["entries"]
    }

    new_overlay = copy.deepcopy(overlay)
    new_overlay["forward_v35"] = {
        "schema": FORWARD_SCHEMA,
        "raw_data_root_layout": "target_root immediate children Part_0000.bi4..Part_N.bi4",
        "frame_count": layout["count"],
        "frame_indices": layout["frame_numbers"],
        "source_content_hashes_unchanged": True,
        "scientific_scope": "path contract only; no raw/H5 content read",
        "original_path_fallback": "FORBIDDEN",
    }
    rewritten_overlay_entries = []
    for item in overlay_entries:
        value = dict(item)
        if value.get("role") == "raw_frame_input":
            original = str(Path(str(value.get("original_path", ""))).expanduser().resolve())
            replacement = raw_by_original.get(original)
            if replacement is None:
                raise PortableV35Error(f"overlay raw entry has no source match: {original}")
            value["bundle_relative_path"] = replacement["bundle_relative_path"]
        rewritten_overlay_entries.append(value)
    new_overlay["entries"] = rewritten_overlay_entries
    new_overlay["status"] = "READY_FOR_PARENT_COPY; V35_TOP_LEVEL_RAW_FRAME_LAYOUT"
    new_overlay["sha256"] = canonical_sha(new_overlay)
    overlay_path = write_new(output_overlay, new_overlay)

    new_request = copy.deepcopy(request)
    new_request["forward_v35"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "overlay_sha256": new_overlay["sha256"],
        "raw_data_root_layout": "target_root immediate children Part_0000.bi4..Part_N.bi4",
        "frame_count": layout["count"],
        "frame_indices": layout["frame_numbers"],
        "content_read_during_build": False,
        "original_path_fallback": "FORBIDDEN",
    }
    for item in new_request["source_entries"]:
        if item.get("role") == "raw_frame_input":
            item["target_relative_path"] = f"Part_{_frame_number(item, index=0):04d}.bi4"
    runtime_sources = new_request.get("runtime_sources")
    if not isinstance(runtime_sources, list):
        raise PortableV35Error("v34 runtime_sources are required")
    if not any(isinstance(item, Mapping) and item.get("role") == "executor_v35"
               for item in runtime_sources):
        stat = SCRIPT.stat()
        runtime_sources.append({
            "role": "executor_v35",
            "path": str(SCRIPT),
            "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": sha256_file(SCRIPT),
            "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v35.py",
            "forward_only": True,
        })
    compatibility_sha = next(
        (item.get("sha256") for item in runtime_sources
         if isinstance(item, Mapping) and item.get("role") == "executor_v34"),
        BOUND_V34_SHA256,
    )
    _require_sha(compatibility_sha, "executor_v34 compatibility SHA")
    new_request["forward_v35"]["compatibility_executor_sha256"] = compatibility_sha
    new_request["v5_overlay_template"] = {
        "canonical_sha256": new_overlay["sha256"],
        "path": str(overlay_path),
        "sha256": sha256_file(overlay_path),
    }
    old_roots = request.get("fresh_roots")
    if not isinstance(old_roots, Mapping):
        raise PortableV35Error("v34 fresh_roots are required")
    old_target = str(old_roots.get("target_root", ""))
    old_output = str(old_roots.get("output_root", ""))
    derived_target = old_target.replace("v34-executor-050", "v35-executor-051")
    derived_output = old_output.replace("v34-executor-050", "v35-executor-051")
    new_target = str(Path(target_root or derived_target).expanduser())
    new_output = str(Path(output_root or derived_output).expanduser())
    if not new_target or not new_output or new_target == new_output:
        raise PortableV35Error("fresh target/output roots must be distinct")
    new_request["fresh_roots"] = {"target_root": new_target, "output_root": new_output}
    new_request["storage_scope"] = dict(new_request.get("storage_scope", {}),
                                         new_namespace_absent_before_run=True,
                                         external_output_root=new_output)
    # Keep the exact v34 readiness token because parent-v3 validates it
    # strictly.  The additive forward_v35 record carries the new contract.
    new_request["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    new_request["sha256"] = canonical_sha(new_request)
    request_path = write_new(output_request, new_request)
    return {
        "status": "READY_FOR_PARENT_V35_METADATA_ONLY",
        "request": str(request_path),
        "request_sha256": sha256_file(request_path),
        "overlay": str(overlay_path),
        "overlay_sha256": sha256_file(overlay_path),
        "raw_frame_count": layout["count"],
        "raw_frame_layout": "top-level Part_0000.bi4 contiguous",
        "content_read": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _load_v34():
    if not V34_SCRIPT.is_file():
        raise PortableV35Error(f"immutable v34 executor is missing: {V34_SCRIPT}")
    if sha256_file(V34_SCRIPT) != BOUND_V34_SHA256:
        raise PortableV35Error("immutable v34 executor SHA differs from the forward binding")
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v34", V34_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV35Error("cannot load immutable v34 executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v34-request", type=Path, required=True)
    build.add_argument("--v5-overlay", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--output-overlay", type=Path, required=True)
    build.add_argument("--target-root", type=Path)
    build.add_argument("--output-root", type=Path)
    # Actual execution remains delegated to the consumed v34 implementation
    # behind the explicit compatibility envelope.  Parent-v3 can therefore
    # run a fresh v35 request without changing any consumed byte.
    for name in ("preflight", "run", "evaluate"):
        delegated = sub.add_parser(name)
        delegated.add_argument("--request", type=Path, required=True)
        if name == "preflight":
            delegated.add_argument("--output", type=Path, required=True)
        elif name == "run":
            delegated.add_argument("--io-slot-approved", action="store_true")
            delegated.add_argument("--parent-pid", type=int)
            delegated.add_argument("--evaluator-proof", type=Path)
            delegated.add_argument("--max-wall-seconds", type=float)
        elif name == "evaluate":
            delegated.add_argument("--evaluator-proof", type=Path, required=True)
            delegated.add_argument("--parent-pid", type=int)
            delegated.add_argument("--max-wall-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            value = build_forward(v34_request=args.v34_request, v5_overlay=args.v5_overlay,
                                  output_request=args.output_request, output_overlay=args.output_overlay,
                                  target_root=args.target_root, output_root=args.output_root)
        else:
            impl = _load_v34()
            forwarded = list(argv if argv is not None else sys.argv[1:])
            value = impl.main(forwarded)
            # The delegated v34 CLI prints its own JSON and returns an exit
            # code.  Do not print a second object or hide a semantic failure.
            return int(value)
    except (PortableV35Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v35: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
