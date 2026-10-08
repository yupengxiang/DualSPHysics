#!/usr/bin/env python3
"""Audit the minimal recovery closure for the historical F1-S2 SaveDt request.

This forward-only audit does not edit the consumed request or its builder.  It
proves which commit supplies the missing builder and records the historical
input_files schema issue for the parent guard to normalize in a new request.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
TARGET = "4020d4f518443edb209d0c016a1a45543754037b"
BUILDER_COMMIT = "a440a616da4b6dad61f3715e6cea91ea33688eaa"
BUILDER_PARENT = "964eeea956ae09e6f4319826d1fd503286997d3d"
BUILDER_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s2_coarse_savedt_v1.py"
REQUEST_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s2-reference-v6/f1_s2_coarse_dp0p0225_same_cfl_savedt_full4s.json"
OUTPUT = REFERENCE / "stage2_f1_s2_coarse_savedt_dependency_audit_v2.json"


def run(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=REPO).returncode == 0


def main() -> None:
    builder_blob = subprocess.run(["git", "show", f"{BUILDER_COMMIT}:{BUILDER_REL}"], cwd=REPO, check=True, capture_output=True).stdout
    target_request = json.loads(run("show", f"{TARGET}:{REQUEST_REL}"))
    target_files = set(run("ls-tree", "-r", "--name-only", TARGET, "--", "lagrangian-fluid-lab/campaigns/ds-data-02/stage2").splitlines())
    builder_diff = run("diff", "--name-status", f"{BUILDER_COMMIT}^", BUILDER_COMMIT).splitlines()
    request_input_files = target_request.get("input_files", [])
    input_types = sorted({type(item).__name__ for item in request_input_files})
    request_path = REPO / REQUEST_REL
    report = {
        "schema": "ds02.stage2.f1-s2-coarse-savedt-dependency-audit.v2",
        "status": "MINIMAL_BUILDER_RECOVERY_CLOSED_WITH_HISTORICAL_SCHEMA_WARNING",
        "generated_at_commit": run("rev-parse", "HEAD"),
        "target": {
            "commit": TARGET,
            "request_path": REQUEST_REL,
            "request_exists_in_target_tree": REQUEST_REL in target_files,
            "request_kind": target_request.get("kind"),
            "request_schema": target_request.get("schema"),
            "launch_disabled": target_request.get("launch_disabled"),
        },
        "minimal_recovery": {
            "builder_commit": BUILDER_COMMIT,
            "builder_parent": BUILDER_PARENT,
            "builder_path": BUILDER_REL,
            "builder_bytes": len(builder_blob),
            "builder_sha256": sha256_bytes(builder_blob),
            "builder_commit_is_direct_parent_of_target": is_ancestor(BUILDER_COMMIT, TARGET) and run("rev-parse", f"{TARGET}^") == BUILDER_COMMIT,
            "builder_diff_from_parent": builder_diff,
            "recovery_order": [f"cherry-pick {BUILDER_COMMIT}", f"cherry-pick {TARGET}"],
            "no_consumed_request_mutation": True,
        },
        "other_lineage": {
            "builder_parent_is_only_builder_dependency": builder_diff == [f"A\t{BUILDER_REL}"],
            "forensics_3ab618f4a_required": False,
            "forensics_d28e75826_required": False,
            "v5_contract_and_calibration_are_ancestral": all(is_ancestor(c, BUILDER_COMMIT) for c in ("9a2804d5487d6ab342b7936a545705cf7c2d17a4", "125113340cb31de9d1abc583857da9941d37c94b")),
        },
        "historical_request_schema_observation": {
            "input_files_type_set": input_types,
            "input_files_are_dict_records": all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in request_input_files),
            "shared_guard_ready_string_list": False,
            "kind_is_shared_guard_qualification": target_request.get("kind") == "qualification",
            "action": "preserve historical request bytes; normalize input_files to strings and use kind=qualification only in a new forward request",
            "request_path_in_current_worktree": str(request_path.resolve()),
        },
        "scope": {
            "solver_started": False,
            "gpu_started": False,
            "hdf5_read": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    atomic_json(OUTPUT, report)
    print(json.dumps({"status": report["status"], "output": str(OUTPUT), "builder_commit": BUILDER_COMMIT}, ensure_ascii=False))


if __name__ == "__main__":
    main()
