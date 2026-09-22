#!/usr/bin/env python3
"""Version the third-family frontier audit with the current F8 oracle closure.

The v1 frontier receipt remains immutable.  This adapter adds the current
F8 analytic reference contract as evidence while preserving every closed
route, zero-credit decision, and non-mutating execution control from v1.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import core_third_t1_frontier_audit_v1 as _legacy


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260922-v2.json"
ORACLE_CONTRACT = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "reference-oracle-v1/contract.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def build_audit() -> dict[str, Any]:
    value = copy.deepcopy(_legacy.build_audit())
    contract_path = LAB / ORACLE_CONTRACT
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract["status"] != "static_reference_only_no_admission":
        raise ValueError("F8 oracle contract is not static-only")
    if contract["qualification_credit"] != 0:
        raise ValueError("F8 oracle contract cannot carry qualification credit")
    for name in ("implementation", "test"):
        binding = contract["bindings"][name]
        path = LAB / binding["path"]
        if path.stat().st_size != binding["bytes"] or sha256(path) != binding["sha256"]:
            raise ValueError(f"F8 oracle {name} binding is stale")

    value["schema"] = "core.third_t1.frontier_audit.v2"
    value["route_decisions"]["F8"]["reference_oracle"] = {
        "path": str(ORACLE_CONTRACT),
        "schema": contract["schema"],
        "status": contract["status"],
        "qualification_credit": contract["qualification_credit"],
        "admission_granted": False,
    }
    value["evidence"].append(bind(
        ORACLE_CONTRACT,
        "F8 static Womersley reference oracle contract"))
    value["execution_controls"]["reference_oracle_materialized"] = True
    value["execution_controls"]["definition_written"] = False
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
