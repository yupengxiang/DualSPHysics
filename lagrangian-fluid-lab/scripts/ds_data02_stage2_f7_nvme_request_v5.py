#!/usr/bin/env python3
"""Build an additive F7 v5 native-solver request.

The v4 request and its failed receipt are immutable evidence.  This builder
copies only the declared metadata and SHA map, then adds the v5 runner and
the official native shared-library bindings.  It does not open HDF5/BI4
payloads, run a solver, or overwrite an existing request.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
V5_RUNNER = SCRIPT_DIR / "ds_data02_stage2_external_solver_v5.py"
OFFICIAL_LIBRARY_ROOT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "vendor/official/DualSPHysics_v5.4/bin/linux"
)
DEFAULT_SOURCE = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-nvme-counterpart-v4/f7-s2-same-cfl-nvme-request-v4-001.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, default=str).encode()).hexdigest()


def _file_binding(path: Path, *, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"bound file is missing: {path}")
    return {"role": role, "path": str(path), "sha256": sha256_file(path),
            "bytes": path.stat().st_size}


def _worktree_root(path: Path) -> Path | None:
    current = path.expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def build(source: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError(f"refusing to overwrite request: {output}")
    value = json.loads(source.read_text(encoding="utf-8"))
    if value.get("schema") != "ds02.stage2.external-solver-request.v4":
        raise ValueError("source must be the immutable v4 request")
    if value.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("source v4 request is not ready")

    result = copy.deepcopy(value)
    result["schema"] = "ds02.stage2.external-solver-request.v5"
    result["attempt_id"] = "f7-s2-a065-same-cfl-dense-savedt-v5-001"
    result["storage_scope"] = dict(result.get("storage_scope", {}))
    result["storage_scope"]["output_root"] = (
        "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
        "f7-s2-a065-same-cfl-dense-savedt-v5-001"
    )
    old_attempt = str(value["attempt_id"])
    result["forward_of"] = {
        "request_path": str(source.resolve()),
        "request_sha256": sha256_file(source),
        "old_attempt_id": old_attempt,
        "immutable_failure_preserved": True,
        "failure_scope": "v4 missing libdsphchrono.so before CFD initialization",
    }
    result["v4_runner_binding"] = dict(value["v4_runner_binding"])
    result["v5_runner_binding"] = _file_binding(V5_RUNNER, role="f7_v5_runner")
    result["official_library_binding"] = {
        "root": str(OFFICIAL_LIBRARY_ROOT),
        "path_policy": "official_bin_first_then_inherited",
        "required_by_native_launch": ["libdsphchrono.so"],
        "files": [
            _file_binding(OFFICIAL_LIBRARY_ROOT / "libdsphchrono.so", role="libdsphchrono.so"),
            _file_binding(OFFICIAL_LIBRARY_ROOT / "libChronoEngine.so", role="libChronoEngine.so"),
        ],
    }
    result["launch_environment_contract"] = {
        "LD_LIBRARY_PATH": "official_library_binding.root + inherited_parent_value",
        "official_root_precedes_inherited": True,
        "actual_environment_recorded_in_receipt": True,
        "original_path_fallback": "FORBIDDEN",
    }
    result["execution"] = dict(result.get("execution", {}))
    result["execution"].update({
        "runner_schema": "ds02.stage2.external-solver-request.v5",
        "runner_script": str(V5_RUNNER),
        "native_shared_library_binding": "official_library_binding",
        "actual_launch_argv_and_environment_recorded": True,
        "model_invoked": False,
        "cfd_invoked": False,
    })
    worktree_root = _worktree_root(Path(str(result.get("cwd", ""))))
    if worktree_root is not None:
        result["worktree_root"] = str(worktree_root)
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["role"] = "DEVELOPMENT"
    result["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    result["launch_allowed"] = True
    result["model_invoked"] = False
    result["cfd_invoked"] = False

    paths = list(result.get("input_files", []))
    hashes = dict(result.get("input_sha256", {}))
    scopes = dict(result.get("input_content_scope", {}))
    additions = [V5_RUNNER,
                 OFFICIAL_LIBRARY_ROOT / "libdsphchrono.so",
                 OFFICIAL_LIBRARY_ROOT / "libChronoEngine.so"]
    for path in additions:
        text = str(path)
        if text not in paths:
            paths.append(text)
        hashes[text] = sha256_file(path)
        scopes[text] = "post_reservation_hash"
    result["input_files"] = paths
    result["input_sha256"] = hashes
    result["input_content_scope"] = scopes
    result["source_provenance"] = dict(result.get("source_provenance", {}))
    result["source_provenance"]["v5_library_fix"] = {
        "official_library_root": str(OFFICIAL_LIBRARY_ROOT),
        "library_sha256s": {item["role"]: item["sha256"] for item in result["official_library_binding"]["files"]},
        "actual_ld_library_path_required": True,
    }
    result["sha256"] = canonical_sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
