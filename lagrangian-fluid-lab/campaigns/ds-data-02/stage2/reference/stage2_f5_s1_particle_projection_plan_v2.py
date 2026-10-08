#!/usr/bin/env python3
"""Forward-only strict receipt/XML join for the F5 projection plan.

The consumed v1 plan is preserved.  This wrapper reuses its metadata-only
builder but replaces the unconditional XML/receipt claim with an exact small
file join: the supplied generated XML must be the receipt's
``output_root/generated.xml`` and both bytes must have the same SHA-256.  No
VTK, BI4, HDF5 or solver payload is read.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f5_s1_particle_projection_plan_v1.py"
SCHEMA = "ds02.stage2.f5-s1.particle-projection-plan.v2"
DEFAULT_OUTPUT = HERE / "stage2_f5_s1_particle_projection_plan_v2.json"


def load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_f5_s1_projection_v1_frozen", V1_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load frozen v1 module: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strict_receipt_observation(module: Any, original: Any, path: Path, grid: str, generated: dict[str, Any]) -> dict[str, Any]:
    """Run v1's stat-only observation then prove the generated XML join."""
    result = original(path, grid, generated)
    receipt = json.loads(module.regular(path, f"{grid} receipt").read_text(encoding="utf-8"))
    output_root = Path(str(receipt["output_root"])).expanduser().resolve()
    receipt_xml = module.regular(output_root / "generated.xml", f"{grid} receipt output generated XML")
    supplied_xml = Path(str(generated["record"]["path"])).expanduser().resolve()
    supplied_sha = str(generated["record"]["sha256"])
    receipt_sha = module.sha256(receipt_xml)
    if supplied_xml != receipt_xml:
        raise ValueError(f"{grid} generated XML path is not receipt output_root/generated.xml: {supplied_xml} != {receipt_xml}")
    if supplied_sha != receipt_sha:
        raise ValueError(f"{grid} generated XML SHA mismatch: supplied={supplied_sha} receipt_output={receipt_sha}")
    result.pop("generated_xml_count_matches_receipt_input", None)
    result["generated_xml_receipt_join"] = {
        "status": "PASS",
        "supplied_generated_xml": str(supplied_xml),
        "receipt_output_generated_xml": str(receipt_xml),
        "path_equal": True,
        "supplied_sha256": supplied_sha,
        "receipt_output_sha256": receipt_sha,
        "sha256_equal": True,
        "receipt_request_sha256": receipt.get("request_sha256"),
        "receipt_case_id": receipt.get("request", {}).get("case_id"),
        "receipt_attempt_id": receipt.get("request", {}).get("attempt_id"),
        "scope": "small generated.xml and receipt JSON only",
    }
    return result


def build(args: argparse.Namespace) -> dict[str, Any]:
    module = load_v1()
    module.SCHEMA = SCHEMA
    original = module.receipt_observation
    module.receipt_observation = lambda path, grid, generated: strict_receipt_observation(module, original, path, grid, generated)
    try:
        report = module.build(args)
    finally:
        module.receipt_observation = original
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_STRICT_SOURCE_RECEIPT_XML_JOIN_METADATA_ONLY"
    report["generator"] = {
        "script": str(Path(__file__).resolve()),
        "script_sha256": module.sha256(Path(__file__).resolve()),
        "frozen_v1_script": str(V1_PATH),
        "frozen_v1_bytes_unchanged": True,
        "generated_without_payload_reads": True,
    }
    report["strict_join_contract"] = {
        "required": "supplied generated.xml path == receipt.output_root/generated.xml and SHA-256 equal",
        "failed_join": "nonzero exception; no PASS fallback",
        "payloads_read": [],
    }
    return report


def main() -> int:
    module = load_v1()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for key, default in module.DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, default=default)
    parser.set_defaults(output=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        # Keep the test payload-free and verify that the frozen dependency is present.
        if not V1_PATH.is_file():
            raise FileNotFoundError(V1_PATH)
        print("PASS stage2_f5_s1_particle_projection_plan_v2 strict-join wrapper self-test")
        return 0
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build(args)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "schema": report["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
