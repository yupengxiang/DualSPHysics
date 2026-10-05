#!/usr/bin/env python3
"""Build the two F4 gap endpoint Definitions without invoking GenCase.

The builder is deliberately byte-preserving.  It verifies the hash of the
known centered DROP Definition, replaces exactly one z attribute in the mk=1
drop point, validates the resulting XML, and writes only source XML plus a
small JSON receipt.  It never creates BI4, particle arrays, CSV, H5, solver,
or rendering output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f4.drop-gap-source-builder-receipt.v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def changed_byte_positions(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise RuntimeError("source mutation changed byte length")
    return [index for index, (left, right) in enumerate(zip(before, after)) if left != right]


def build(plan_path: Path, output_dir: Path) -> dict[str, Any]:
    plan = load_json(plan_path)
    mother = plan["mother_binding"]
    mother_path = Path(mother["source_definition_xml"])
    if not mother_path.is_file():
        raise FileNotFoundError(mother_path)
    mother_bytes = mother_path.read_bytes()
    observed_mother_sha = sha256_bytes(mother_bytes)
    expected_mother_sha = mother["source_definition_xml_sha256"]
    if observed_mother_sha != expected_mother_sha:
        raise RuntimeError(
            f"mother Definition hash mismatch: {observed_mother_sha} != {expected_mother_sha}"
        )

    mutation = plan["mutation_contract"]
    old_literal = str(mutation["old_literal"]).encode("ascii")
    if mother_bytes.count(old_literal) != int(mutation["expected_old_literal_count"]):
        raise RuntimeError("mother does not contain exactly one expected drop z literal")

    records: list[dict[str, Any]] = []
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        new_literal = str(endpoint["drop_point_z_literal"]).encode("ascii")
        if len(new_literal) != len(old_literal):
            raise RuntimeError(f"endpoint literal length differs from mother: {endpoint_id}")
        output_path = output_dir / str(endpoint["source_definition_output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise FileExistsError(output_path)
        output_bytes = mother_bytes.replace(old_literal, new_literal, 1)
        if output_bytes.count(new_literal) != 1:
            raise RuntimeError(f"endpoint has unexpected replacement count: {endpoint_id}")
        changed = changed_byte_positions(mother_bytes, output_bytes)
        expected_changed = sum(left != right for left, right in zip(old_literal, new_literal))
        if len(changed) != expected_changed:
            raise RuntimeError(f"mutation changed bytes outside the target literal: {endpoint_id}")
        # Parse only for well-formedness.  ElementTree is never used to write
        # the endpoint, so whitespace and all non-target numeric bytes survive.
        ET.fromstring(output_bytes)
        output_path.write_bytes(output_bytes)
        records.append(
            {
                "endpoint_id": endpoint_id,
                "source_definition": str(output_path),
                "source_definition_sha256": sha256_bytes(output_bytes),
                "source_definition_bytes": len(output_bytes),
                "mother_definition_sha256": observed_mother_sha,
                "old_literal": old_literal.decode("ascii"),
                "new_literal": new_literal.decode("ascii"),
                "changed_byte_count": len(changed),
                "changed_byte_span": [min(changed), max(changed)] if changed else None,
                "binary_or_particle_outputs": [],
            }
        )

    receipt = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "mother_definition": str(mother_path),
        "mother_definition_sha256": observed_mother_sha,
        "endpoint_count": len(records),
        "endpoints": records,
        "mutation_policy": "one drop point z literal per endpoint; every other source byte is preserved",
        "tools_invoked": [],
        "gencase_invoked": False,
        "solver_invoked": False,
        "conversion_invoked": False,
        "rendering_invoked": False,
        "binary_or_particle_outputs": [],
        "launch_allowed": False,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
    }
    write_json(output_dir / "source-build-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    receipt = build(args.plan, args.output_dir)
    print(json.dumps({"scope_id": receipt["scope_id"], "endpoint_count": receipt["endpoint_count"], "gencase_invoked": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
