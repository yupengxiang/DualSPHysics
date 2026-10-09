#!/usr/bin/env python3
"""V52-aware source-only post-terminal hand-off.

V1 of the post-terminal request is retained for the V51 ``sources/*`` plan.
V52 moves the four native module bindings into ``target/runtime/native`` so
V38's ``worker.parent`` alias guard can accept them.  This wrapper reuses V1's
bounded request/accounting/command construction while replacing only its
module-plan function with the V52 worker-parent plan.  It then emits a new
schema and an explicit V52 provenance marker.  No payload is opened or
hashed, and no old failure/product/proof is promoted.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_v50_postterminal_guard_request_v1.py"
V52_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v52.py"
SCHEMA = "ds02.stage2.f2-v50-postterminal-parent-guard-request.v2"
FORWARD_SCHEMA = "ds02.stage2.f2-v50-postterminal-parent-guard-forward.v2"
V52_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v52-forward.v1"


class PostterminalV2Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PostterminalV2Error(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "ds02_bound_v50_postterminal_v1_for_v2")
V52 = _load(V52_SCRIPT, "ds02_bound_f2_executor_v52_for_postterminal_v2")


def canonical_sha(value: dict[str, Any]) -> str:
    return V1.canonical_sha(value)


def _load_executor(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = V1._json(path, "V52 executor request")
    marker = value.get("forward_v52")
    if not isinstance(marker, dict) or marker.get("schema") != V52_FORWARD_SCHEMA:
        raise PostterminalV2Error("postterminal V2 requires the V52 worker-parent forward marker")
    if value.get("sha256") != canonical_sha(value):
        raise PostterminalV2Error("V52 executor canonical SHA differs")
    return target, value


def build_request(*, executor_request: Path | str, parent_request: Path | str,
                  v50_preflight: Path | str, output: Path | str,
                  target_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    executor_path, executor = _load_executor(executor_request)
    # V1 performs all bounded V50/V51 status, parent, preflight, namespace,
    # literal-venv and pending-artifact checks.  Its module plan is the only
    # part that must change for V52.
    old_plan = V1._module_plan
    V1._module_plan = V52.module_rebinding_plan
    try:
        result = V1.build_request(executor_request=executor_path, parent_request=parent_request,
                                  v50_preflight=v50_preflight, output=output,
                                  target_root=target_root, output_root=output_root)
    finally:
        V1._module_plan = old_plan
    output_path = Path(result["request"])
    try:
        value = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PostterminalV2Error(f"cannot reopen V1 hand-off: {error}") from error
    if not isinstance(value, dict):
        raise PostterminalV2Error("V1 hand-off is not an object")
    module_plan = V52.module_rebinding_plan(executor, Path(target_root))
    value["schema"] = SCHEMA
    value["request_id"] = str(value.get("request_id", "")) + "-v52-worker-parent"
    value["forward_v52_postterminal"] = {
        "schema": FORWARD_SCHEMA,
        "v52_executor_request": {"path": str(executor_path),
                                  "physical_sha256": V1.sha256_file(executor_path, limit=V1.MAX_JSON_BYTES),
                                  "canonical_sha256": executor["sha256"]},
        "module_rebinding": module_plan,
        "worker_parent_relative_directory": "runtime/runtime/native",
        "source_path_fallback": "FORBIDDEN",
        "payload_read_during_build": False,
        "old_v1_postterminal_request": {"schema": V1.SCHEMA, "path": str(output_path)},
    }
    contract = dict(value.get("copied_module_import_contract", {}))
    contract.update({"schema": FORWARD_SCHEMA, "worker_parent_alias_directory": str(Path(target_root) / "runtime/runtime/native"),
                     "module_paths": module_plan, "source_path_fallback": "FORBIDDEN"})
    value["copied_module_import_contract"] = contract
    value["runtime_closure"]["schema"] = "ds02.stage2.f2-postterminal-runtime-closure.v2"
    value["limitations"] = list(value.get("limitations", [])) + [
        "V52 aliases are expected under target/runtime/native so V38 worker.parent can verify them; parent must still hash targets after reservation.",
    ]
    value["sha256"] = canonical_sha(value)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {"schema": SCHEMA, "status": value["status"], "request": str(output_path),
            "request_sha256": V1.sha256_file(output_path, limit=V1.MAX_JSON_BYTES),
            "module_roles": sorted(module_plan), "payload_read": False,
            "qualification": dict(V1.UNKNOWN)}


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
    except (PostterminalV2Error, V1.PostterminalRequestError, V52.PortableV52Error,
            OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V50 postterminal V2 request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
