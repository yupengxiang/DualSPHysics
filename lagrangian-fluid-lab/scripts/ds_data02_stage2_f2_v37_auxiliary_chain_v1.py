#!/usr/bin/env python3
"""Metadata-only V37 auxiliary-sidecar to request/overlay chain.

The parent guard owns the expensive 401-frame plus four-auxiliary SHA pass.
After that pass this helper verifies the completed sidecar, calls the
immutable V37 builder, and records a fresh request/overlay binding.  It reads
JSON and ``stat`` records only: it never opens BI4/HDF5 payloads and never
copies or launches a worker.  The frozen 405-file manifest and expected tree
SHA are checked before and after the V37 build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V37_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v37.py"
CHAIN_SCHEMA = "ds02.stage2.f2-v37-auxiliary-chain.v1"
PREFLIGHT_SCHEMA = "ds02.stage2.f2-v37-auxiliary-chain-preflight.v1"
AUX_SCHEMA = "ds02.stage2.f2-raw-auxiliary-binding.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
OVERLAY_SCHEMA = "ds02.stage2.f2-native-raw-portable-overlay.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
FRAME_COUNT = 401
AUX_NAMES = ("PartInfo.ibi4", "PartMotionRef.ibi4", "PartOut_000.obi4", "Part_Head.ibi4")
EXPECTED_TREE = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
REQUIRED_EXECUTABLE_ROLES = {"native_bi4_decoder", "os_strace", "python_executable"}


class V37ChainError(RuntimeError):
    """Raised when the sidecar or fresh request chain is unsafe."""


def _load_v37() -> Any:
    if not V37_SCRIPT.is_file():
        raise V37ChainError(f"bound V37 builder is missing: {V37_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_stage2_f2_v37_bound", V37_SCRIPT)
    if spec is None or spec.loader is None:
        raise V37ChainError("cannot import bound V37 builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V37 = _load_v37()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=_json_default).encode("utf-8")).hexdigest()


def sha256_json(path: Path | str) -> str:
    """Hash a bound JSON sidecar; never call this for raw scientific files."""
    target = Path(path).expanduser().resolve()
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V37ChainError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise V37ChainError(f"JSON object required: {target}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise V37ChainError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")
    return target


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V37ChainError(f"{name} must be an absolute path")
    return Path(value).expanduser().resolve()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V37ChainError(f"{name} must be a lowercase SHA-256")
    return value


def _stat(path: Path, name: str) -> dict[str, int]:
    try:
        info = path.stat()
    except OSError as error:
        raise V37ChainError(f"{name} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise V37ChainError(f"{name} is not a regular file: {path}")
    return {
        "st_dev": int(info.st_dev), "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode), "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink), "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid), "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns), "st_ctime_ns": int(info.st_ctime_ns),
    }


def _same_stat(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(int(left.get(key, -1)) == int(right.get(key, -1)) for key in (
        "st_dev", "st_ino", "st_mode", "mode_bits", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_mtime_ns", "st_ctime_ns"))


def _validate_auxiliary_sidecar(path: Path | str) -> dict[str, Any]:
    """Validate a completed cdd8 sidecar without opening its raw files."""
    sidecar_path = Path(path).expanduser().resolve()
    sidecar = _load_json(sidecar_path)
    if sidecar.get("schema") != AUX_SCHEMA:
        raise V37ChainError("auxiliary sidecar schema is not V37-compatible")
    if sidecar.get("snapshot_schema") != "ds02.stage2.f2-raw-auxiliary-snapshot.v1":
        raise V37ChainError("auxiliary sidecar does not identify the snapshot worker")
    if sidecar.get("status") != "COMPLETE_PARENT_GUARDED":
        raise V37ChainError("auxiliary sidecar is not a completed parent-guard snapshot")
    if sidecar.get("role") != "DEVELOPMENT" or sidecar.get("qualification") != UNKNOWN:
        raise V37ChainError("auxiliary sidecar role/qualification is not conservative")
    if sidecar.get("content_read_during_build") is not False:
        raise V37ChainError("sidecar metadata build must state content_read_during_build=false")
    if sidecar.get("snapshot_content_read") is not True or sidecar.get("payload_hashes_computed") is not True:
        raise V37ChainError("sidecar lacks the parent-guarded payload hash evidence")
    if sidecar.get("execution_boundary", {}).get("hdf5_opened") is not False:
        raise V37ChainError("auxiliary snapshot must not open HDF5")
    if sidecar.get("sha256") != canonical_sha(sidecar):
        raise V37ChainError("auxiliary sidecar canonical SHA differs")

    expected = sidecar.get("expected_raw_tree")
    if not isinstance(expected, Mapping) or int(expected.get("file_count", -1)) != FRAME_COUNT + len(AUX_NAMES):
        raise V37ChainError("sidecar expected raw scope is not the frozen 405-file scope")
    expected_tree = _sha(expected.get("tree_sha256"), "sidecar expected_raw_tree.tree_sha256")
    if expected_tree != EXPECTED_TREE:
        raise V37ChainError("sidecar attempted to replace the frozen 405-file tree SHA")

    raw = sidecar.get("raw_manifest")
    files = raw.get("files") if isinstance(raw, Mapping) else None
    if not isinstance(raw, Mapping) or int(raw.get("file_count", -1)) != 405:
        raise V37ChainError("sidecar raw manifest file count is not 405")
    if _sha(raw.get("tree_sha256"), "sidecar raw_manifest.tree_sha256") != expected_tree:
        raise V37ChainError("sidecar observed tree SHA differs from frozen expected tree SHA")
    if not isinstance(files, list) or len(files) != 405:
        raise V37ChainError("sidecar raw manifest must contain all 405 files")
    expected_names = {*(f"Part_{index:04d}.bi4" for index in range(FRAME_COUNT)), *AUX_NAMES}
    file_by_path: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(files):
        if not isinstance(item, Mapping):
            raise V37ChainError(f"raw manifest entry {index} is malformed")
        relative = item.get("path")
        if not isinstance(relative, str) or relative not in expected_names or relative in file_by_path:
            raise V37ChainError(f"raw manifest contains an unexpected/duplicate path: {relative!r}")
        if any(part in {"", ".", ".."} for part in Path(relative).parts) or "/" in relative:
            raise V37ChainError(f"raw manifest path is not a top-level relative name: {relative!r}")
        if int(item.get("bytes", -1)) < 0:
            raise V37ChainError(f"raw manifest bytes are invalid: {relative}")
        _sha(item.get("sha256"), f"raw manifest SHA {relative}")
        file_by_path[relative] = item
    if set(file_by_path) != expected_names:
        raise V37ChainError("raw manifest does not equal the frozen 405-file name set")

    frozen = sidecar.get("frozen_frame_manifest")
    if not isinstance(frozen, list) or len(frozen) != FRAME_COUNT:
        raise V37ChainError("sidecar must preserve all 401 frozen frame records")
    for number, item in enumerate(frozen):
        if not isinstance(item, Mapping) or int(item.get("frame", -1)) != number:
            raise V37ChainError(f"frozen frame {number} is malformed")
        relative = f"Part_{number:04d}.bi4"
        if item.get("relative_path") != relative:
            raise V37ChainError(f"frozen frame {number} relative name differs")
        actual = file_by_path[relative]
        if item.get("sha256") != actual.get("sha256") or item.get("frozen_sha256") != actual.get("sha256"):
            raise V37ChainError(f"frozen frame {number} SHA does not match the joined raw manifest")

    entries = sidecar.get("entries")
    if not isinstance(entries, list) or len(entries) != len(AUX_NAMES):
        raise V37ChainError("sidecar must contain exactly four auxiliary entries")
    entry_names: set[str] = set()
    for item in entries:
        if not isinstance(item, Mapping) or item.get("filename") not in AUX_NAMES:
            raise V37ChainError("auxiliary entry filename is malformed")
        name = str(item["filename"])
        if name in entry_names:
            raise V37ChainError("auxiliary entry is duplicated")
        entry_names.add(name)
        if item.get("sha256") != file_by_path[name].get("sha256"):
            raise V37ChainError(f"auxiliary {name} SHA differs from the joined raw manifest")
    if entry_names != set(AUX_NAMES):
        raise V37ChainError("auxiliary entry set differs from the frozen four-file closure")

    stats = sidecar.get("stat_pre_post")
    if not isinstance(stats, Mapping) or stats.get("stable") is not True:
        raise V37ChainError("sidecar does not prove stable pre/post stats")
    pre, post = stats.get("files"), stats.get("post_hash_files")
    if not isinstance(pre, Mapping) or not isinstance(post, Mapping) or set(pre) != expected_names or set(post) != expected_names:
        raise V37ChainError("sidecar stat closure does not cover all 405 files")
    if any(not isinstance(pre[name], Mapping) or not isinstance(post[name], Mapping) or
           not _same_stat(pre[name], post[name]) for name in expected_names):
        raise V37ChainError("sidecar pre/post stats are not stable for every raw file")
    return {
        "path": str(sidecar_path), "sha256": sha256_json(sidecar_path),
        "expected_tree_sha256": expected_tree, "file_count": 405,
        "frame_count": FRAME_COUNT, "auxiliary_count": len(AUX_NAMES),
        "entry_names": sorted(entry_names), "raw_manifest_files": file_by_path,
    }


def _load_v36_metadata(request_path: Path | str, overlay_path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _load_json(request_path)
    overlay = _load_json(overlay_path)
    if request.get("schema") != V34_SCHEMA or request.get("sha256") != V37.canonical_sha(request):
        raise V37ChainError("V36 request is not canonical")
    if overlay.get("schema") != OVERLAY_SCHEMA or overlay.get("sha256") != V37.canonical_sha(overlay):
        raise V37ChainError("V36 overlay is not canonical")
    runtime = request.get("runtime_sources")
    if not isinstance(runtime, list):
        raise V37ChainError("V36 runtime_sources are missing")
    aliases: set[str] = set()
    observed_roles: set[str] = set()
    for item in runtime:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise V37ChainError("runtime source role is malformed")
        role = str(item["role"])
        observed_roles.add(role)
        target = item.get("target_relative_path")
        if not isinstance(target, str) or not target or target in aliases:
            raise V37ChainError(f"runtime target alias is missing/duplicated: {target!r}")
        aliases.add(target)
        path = _path(item.get("path"), f"runtime {role}.path")
        info = _stat(path, f"runtime {role}")
        expected = item.get("source_stat_expected")
        if isinstance(expected, Mapping) and not _same_stat(expected, info):
            raise V37ChainError(f"runtime {role} source stat differs")
        mode = int(item.get("source_mode_bits", info["mode_bits"]))
        required = bool(item.get("required_executable", False))
        if required != bool(mode & 0o111):
            raise V37ChainError(f"runtime {role} executable mode contract differs")
        if item.get("preserve_mode") is not True:
            raise V37ChainError(f"runtime {role} does not preserve mode")
        if role == "python_executable":
            invocation = item.get("invocation_path")
            if not isinstance(invocation, str) or not Path(invocation).is_absolute():
                raise V37ChainError("python executable literal invocation_path is missing")
            # The invocation string is deliberately retained; resolved_source_path
            # is provenance only and must never replace argv[0].
            if item.get("invocation_path") != invocation:
                raise V37ChainError("python executable invocation path was normalized")
    if "python_executable" not in observed_roles:
        raise V37ChainError("V36 request lacks literal python_executable binding")
    source_entries = request.get("source_entries")
    if not isinstance(source_entries, list):
        raise V37ChainError("V36 source_entries are missing")
    for item in source_entries:
        if not isinstance(item, Mapping):
            raise V37ChainError("V36 source entry is malformed")
        role = str(item.get("role", ""))
        if role in REQUIRED_EXECUTABLE_ROLES:
            mode = int(item.get("source_mode_bits", 0))
            if not mode & 0o111 or item.get("preserve_mode") is not True:
                raise V37ChainError(f"source executable role {role} lacks mode preservation")
    return request, overlay


def _output_binding(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    return {"path": str(path.resolve()), "sha256": sha256_json(path),
            "canonical_sha256": value.get("sha256"), "schema": value.get("schema")}


def _validate_v37_outputs(request_path: Path, overlay_path: Path, expected_tree: str) -> dict[str, Any]:
    request = _load_json(request_path)
    overlay = _load_json(overlay_path)
    if request.get("schema") != V34_SCHEMA or request.get("sha256") != V37.canonical_sha(request):
        raise V37ChainError("fresh V37 request is not canonical")
    if overlay.get("schema") != OVERLAY_SCHEMA or overlay.get("sha256") != V37.canonical_sha(overlay):
        raise V37ChainError("fresh V37 overlay is not canonical")
    marker = request.get("forward_v37")
    if not isinstance(marker, Mapping) or int(marker.get("expected_file_count", -1)) != 405:
        raise V37ChainError("fresh V37 request does not preserve the 405-file scope")
    if marker.get("expected_raw_tree_sha256") != expected_tree:
        raise V37ChainError("fresh V37 request changed the frozen raw tree SHA")
    if marker.get("raw_data_root_relative") != "raw" or marker.get("sources_directory_excluded_from_raw_manifest") is not True:
        raise V37ChainError("fresh V37 request raw scope/relative names are not isolated")
    source_entries = request.get("source_entries")
    raw = [item for item in source_entries if isinstance(item, Mapping)
           and isinstance(item.get("target_relative_path"), str)
           and item["target_relative_path"].startswith("raw/")]
    if len(raw) != 405:
        raise V37ChainError("fresh V37 request does not bind exactly 405 raw entries")
    expected_names = {*(f"Part_{index:04d}.bi4" for index in range(FRAME_COUNT)), *AUX_NAMES}
    names = {Path(str(item["target_relative_path"])).name for item in raw}
    if names != expected_names:
        raise V37ChainError("fresh V37 raw target names differ from the frozen closure")
    aux_roles = {str(item.get("role")) for item in raw if Path(str(item["target_relative_path"])).name in AUX_NAMES}
    if not {"raw_aux_partinfo", "raw_aux_partmotionref", "v2:native_partout", "raw_aux_part_head"}.issubset(aux_roles):
        raise V37ChainError("fresh V37 auxiliary role aliases are incomplete")
    return {"request": _output_binding(request_path), "overlay": _output_binding(overlay_path),
            "raw_entry_count": len(raw), "raw_target_names": sorted(names)}


def _chain_receipt(*, aux: Mapping[str, Any], v36_request: Path, v36_overlay: Path,
                   output_request: Path, output_overlay: Path, target_root: Path,
                   output_root: Path, output_summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": CHAIN_SCHEMA, "status": "READY_FOR_PARENT_V37_STAGE2_GUARD",
        "role": "DEVELOPMENT", "qualification": dict(UNKNOWN),
        "inputs": {
            "v36_request": {"path": str(v36_request), "sha256": sha256_json(v36_request)},
            "v36_overlay": {"path": str(v36_overlay), "sha256": sha256_json(v36_overlay)},
            "auxiliary_sidecar": {"path": aux["path"], "sha256": aux["sha256"]},
        },
        "outputs": output_summary,
        "fresh_roots": {"target_root": str(target_root), "output_root": str(output_root)},
        "raw_scope": {"file_count": 405, "frame_count": FRAME_COUNT,
                       "auxiliary_count": len(AUX_NAMES),
                       "expected_raw_tree_sha256": aux["expected_tree_sha256"],
                       "raw_data_root_relative": "raw",
                       "sources_directory_excluded_from_raw_manifest": True},
        "execution_boundary": {
            "content_read_during_build": False, "payload_hashes_computed_during_build": False,
            "hdf5_opened": False, "bi4_opened": False, "converter_invoked": False,
            "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        },
        "limitations": [
            "This chain only builds metadata request/overlay files; parent copy and raw conversion are pending.",
            "The successful auxiliary SHA sidecar came from a separate parent-guarded snapshot.",
            "Quality remains UNKNOWN and no native/label credit is granted.",
        ],
    }


def preflight(*, v36_request: Path | str, v36_overlay: Path | str,
              auxiliary_manifest: Path | str, output: Path | str) -> dict[str, Any]:
    v36, _ = _load_v36_metadata(v36_request, v36_overlay)
    aux = _validate_auxiliary_sidecar(auxiliary_manifest)
    report = {
        "schema": PREFLIGHT_SCHEMA, "status": "READY_FOR_PARENT_V37_BUILD",
        "v36_schema": v36.get("schema"), "auxiliary": aux,
        "expected_raw_tree_sha256": aux["expected_tree_sha256"],
        "raw_file_count": 405, "frame_count": FRAME_COUNT, "auxiliary_count": len(AUX_NAMES),
        "metadata_only": True, "payload_read": False, "hdf5_opened": False,
        "bi4_opened": False, "qualification": dict(UNKNOWN),
    }
    report["sha256"] = canonical_sha(report)
    _write_new(output, report)
    return report


def build(*, v36_request: Path | str, v36_overlay: Path | str,
          auxiliary_manifest: Path | str, output_request: Path | str,
          output_overlay: Path | str, target_root: Path | str,
          output_root: Path | str, receipt: Path | str) -> dict[str, Any]:
    v36_request_path = Path(v36_request).expanduser().resolve()
    v36_overlay_path = Path(v36_overlay).expanduser().resolve()
    target = _path(str(target_root), "target_root")
    output = _path(str(output_root), "output_root")
    _load_v36_metadata(v36_request_path, v36_overlay_path)
    aux = _validate_auxiliary_sidecar(auxiliary_manifest)
    result = V37.build_forward(
        v36_request=v36_request_path, v36_overlay=v36_overlay_path,
        auxiliary_manifest=Path(auxiliary_manifest).expanduser().resolve(),
        output_request=Path(output_request).expanduser().resolve(),
        output_overlay=Path(output_overlay).expanduser().resolve(),
        target_root=target, output_root=output,
    )
    output_request_path = Path(output_request).expanduser().resolve()
    output_overlay_path = Path(output_overlay).expanduser().resolve()
    outputs = _validate_v37_outputs(output_request_path, output_overlay_path,
                                    aux["expected_tree_sha256"])
    outputs["builder_result"] = dict(result)
    receipt_value = _chain_receipt(
        aux=aux, v36_request=v36_request_path, v36_overlay=v36_overlay_path,
        output_request=output_request_path, output_overlay=output_overlay_path,
        target_root=target, output_root=output, output_summary=outputs)
    receipt_value["sha256"] = canonical_sha(receipt_value)
    _write_new(receipt, receipt_value)
    return {"status": receipt_value["status"], "request": str(output_request_path),
            "overlay": str(output_overlay_path), "receipt": str(Path(receipt).expanduser().resolve()),
            "expected_raw_tree_sha256": aux["expected_tree_sha256"],
            "payload_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--v36-request", type=Path, required=True)
    common.add_argument("--v36-overlay", type=Path, required=True)
    common.add_argument("--auxiliary-manifest", type=Path, required=True)
    pre = sub.add_parser("preflight", parents=[common])
    pre.add_argument("--output", type=Path, required=True)
    build_parser = sub.add_parser("build", parents=[common])
    build_parser.add_argument("--output-request", type=Path, required=True)
    build_parser.add_argument("--output-overlay", type=Path, required=True)
    build_parser.add_argument("--target-root", type=Path, required=True)
    build_parser.add_argument("--output-root", type=Path, required=True)
    build_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            value = preflight(v36_request=args.v36_request, v36_overlay=args.v36_overlay,
                              auxiliary_manifest=args.auxiliary_manifest, output=args.output)
        else:
            value = build(v36_request=args.v36_request, v36_overlay=args.v36_overlay,
                          auxiliary_manifest=args.auxiliary_manifest,
                          output_request=args.output_request, output_overlay=args.output_overlay,
                          target_root=args.target_root, output_root=args.output_root,
                          receipt=args.receipt)
    except (V37ChainError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V37 auxiliary chain: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
