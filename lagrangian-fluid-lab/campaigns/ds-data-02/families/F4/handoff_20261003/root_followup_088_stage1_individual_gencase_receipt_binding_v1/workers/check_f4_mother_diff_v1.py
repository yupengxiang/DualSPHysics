#!/usr/bin/env python3
"""Prove the six fresh087 Definitions differ from the mother at one z token."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = load(args.plan)
    mother_path = Path(plan["mother_binding"]["source_definition_xml"])
    mother = mother_path.read_bytes()
    if sha256_bytes(mother) != plan["mother_binding"]["source_definition_xml_sha256"]:
        raise ValueError("mother Definition digest drift")
    old = plan["mutation_contract"]["old_literal"].encode("ascii")
    if mother.count(old) != 1:
        raise ValueError("mother does not contain exactly one permitted old z literal")
    rows = []
    for endpoint in plan["endpoints"]:
        source_path = args.plan.parent / endpoint["source_definition_output"]
        source = source_path.read_bytes()
        new = endpoint["drop_point_z_literal"].encode("ascii")
        expected = mother.replace(old, new, 1)
        if source != expected:
            raise ValueError(f"{endpoint['endpoint_id']}: source is not an exact one-token mother mutation")
        rows.append({
            "endpoint_id": endpoint["endpoint_id"],
            "source_definition": str(source_path),
            "source_definition_sha256": sha256_bytes(source),
            "source_bytes": len(source),
            "mother_sha256": sha256_bytes(mother),
            "old_literal": old.decode("ascii"),
            "new_literal": new.decode("ascii"),
            "old_literal_count_in_source": source.count(old),
            "new_literal_count_in_source": source.count(new),
            "changed_byte_count": sum(left != right for left, right in zip(mother, source)),
            "only_drop_point_z_changed": True,
            "science_outputs_read": False,
        })
    result = {
        "schema": "ds02.f4.fresh087-mother-diff-evidence.v1",
        "status": "completed",
        "mother_definition": str(mother_path),
        "mother_sha256": sha256_bytes(mother),
        "case_count": len(rows),
        "cases": rows,
        "native_or_solver_outputs_read": False,
        "independent_case_count_increment": 0,
        "claim_boundary": "Committed source byte evidence only; no GenCase, native QA, solver, visual, precision, Q-N, or production claim.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"schema": result["schema"], "status": "completed", "cases": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
