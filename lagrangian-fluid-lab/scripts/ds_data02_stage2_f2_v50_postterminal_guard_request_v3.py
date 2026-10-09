#!/usr/bin/env python3
"""V53-aware post-terminal hand-off with real runtime command paths.

V2 repaired the runtime-closure records but inherited V1's command operand,
which still named ``target/runtime/executor/...``.  V41/V45 materialize that
row below ``target/runtime/runtime/executor/...``.  V3 consumes a V53
executor request and emits a fresh post-terminal request whose command,
closure records, and V53 marker all identify the same materialized path.
This is metadata-only; terminal products, raw data, BI4, HDF5, and result
payloads remain deferred to a parent-reserved execution.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V2_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_v50_postterminal_guard_request_v2.py"
V53_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v53.py"
SCHEMA = "ds02.stage2.f2-v50-postterminal-parent-guard-request.v3"
FORWARD_SCHEMA = "ds02.stage2.f2-v50-postterminal-parent-guard-forward.v3"
V53_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v53-forward.v1"


class PostterminalV3Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PostterminalV3Error(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_SCRIPT, "ds02_bound_v50_postterminal_v2_for_v3")
V53 = _load(V53_SCRIPT, "ds02_bound_f2_executor_v53_for_postterminal_v3")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V2.canonical_sha(dict(value))


def _load_executor(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = V2.V1._json(path, "V53 executor request")
    marker = value.get("forward_v53")
    if not isinstance(marker, Mapping) or marker.get("schema") != V53_FORWARD_SCHEMA:
        raise PostterminalV3Error("postterminal V3 requires the V53 command-path marker")
    if value.get("sha256") != canonical_sha(value):
        raise PostterminalV3Error("V53 executor canonical SHA differs")
    return target, value


def _rewrite_command(value: dict[str, Any], target_root: Path) -> str:
    execution = value.get("execution")
    if not isinstance(execution, dict):
        raise PostterminalV3Error("postterminal execution binding is missing")
    command = execution.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise PostterminalV3Error("postterminal execution command is malformed")
    expected = str(target_root / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v51.py")
               or item.endswith("ds_data02_stage2_f2_portable_executor_v52.py")
               or item.endswith("ds_data02_stage2_f2_portable_executor_v53.py")]
    if len(matches) != 1:
        raise PostterminalV3Error("postterminal command has no unique V53 executor operand")
    command[matches[0]] = expected
    execution["command"] = command
    execution["command_materialization_policy"] = "target_root/runtime/<target_relative_path>"
    execution["executor_script_target_path"] = expected
    execution["source_path_fallback"] = "FORBIDDEN"
    return expected


def build_request(*, executor_request: Path | str, parent_request: Path | str,
                  v50_preflight: Path | str, output: Path | str,
                  target_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    executor_path, executor = _load_executor(executor_request)
    # V2 already performs the V1 request/parent/preflight/status checks and
    # emits the corrected V41/V45 runtime closure.  Reuse it on a new output,
    # then add only the V53 command-path and marker fields.
    result = V2.build_request(executor_request=executor_path, parent_request=parent_request,
                              v50_preflight=v50_preflight, output=output,
                              target_root=target_root, output_root=output_root)
    output_path = Path(result["request"])
    try:
        value = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PostterminalV3Error(f"cannot reopen V2 hand-off: {error}") from error
    if not isinstance(value, dict):
        raise PostterminalV3Error("V2 hand-off is not an object")
    target = Path(target_root)
    command_path = _rewrite_command(value, target)
    roles = value.get("runtime_closure", {}).get("roles")
    if not isinstance(roles, list):
        raise PostterminalV3Error("V2 runtime closure roles are missing")
    executor_rows = [row for row in roles
                     if isinstance(row, Mapping) and row.get("role") == "executor_v53"]
    if len(executor_rows) != 1:
        raise PostterminalV3Error("V53 executor is not present in copied runtime closure")
    if executor_rows[0].get("target_path") != command_path:
        raise PostterminalV3Error("V53 command path differs from runtime closure")
    value["schema"] = SCHEMA
    value["request_id"] = str(value.get("request_id", "")) + "-v53-command-path"
    value["forward_v53_postterminal"] = {
        "schema": FORWARD_SCHEMA,
        "v53_executor_request": {
            "path": str(executor_path),
            "physical_sha256": V2.V1.sha256_file(executor_path, limit=V2.V1.MAX_JSON_BYTES),
            "canonical_sha256": executor["sha256"],
        },
        "executor_role": "executor_v53",
        "executor_target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py",
        "executor_target_path": command_path,
        "worker_parent_relative_directory": "runtime/runtime/native",
        "command_materialization_policy": "target_root/runtime/<target_relative_path>",
        "source_path_fallback": "FORBIDDEN",
        "payload_read_during_build": False,
        "old_v2_postterminal_request": {
            "schema": V2.SCHEMA,
            "path": str(output_path),
        },
    }
    closure = value.get("runtime_closure")
    if not isinstance(closure, dict):
        raise PostterminalV3Error("runtime closure is missing")
    closure["schema"] = "ds02.stage2.f2-postterminal-runtime-closure.v3"
    closure["materialization_path_policy"] = "target_root/runtime/<target_relative_path>"
    value["runtime_closure"] = closure
    value["limitations"] = list(value.get("limitations", [])) + [
        "V53 command and executor closure use V41/V45 target_root/runtime materialization; terminal payload and static content hashes remain parent-after-reservation.",
    ]
    value["sha256"] = canonical_sha(value)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {
        "schema": SCHEMA,
        "status": value["status"],
        "request": str(output_path),
        "request_sha256": V2.V1.sha256_file(output_path, limit=V2.V1.MAX_JSON_BYTES),
        "executor_target_path": command_path,
        "payload_read": False,
        "qualification": dict(V2.V1.UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--executor-request", type=Path, required=True)
    parser.add_argument("--parent-request", type=Path, required=True)
    parser.add_argument("--v50-preflight", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_request(executor_request=args.executor_request, parent_request=args.parent_request,
                               v50_preflight=args.v50_preflight, target_root=args.target_root,
                               output_root=args.output_root, output=args.output)
    except (PostterminalV3Error, V2.PostterminalV2Error, V2.V1.PostterminalRequestError,
            V2.V52.PortableV52Error, OSError, TypeError,
            ValueError, json.JSONDecodeError) as error:
        print(f"V50 postterminal V3 request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
