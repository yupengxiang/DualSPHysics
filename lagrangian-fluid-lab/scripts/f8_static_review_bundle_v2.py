#!/usr/bin/env python3
"""Version the F8 static review bundle with startup and parser closures."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_static_review_bundle_v1 as _legacy


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "static-review-bundle-v2/bundle.json")
SCHEMA = "core.cfd.f8.static_review_bundle.v2"
EXTENSIONS = {
    "startup_oracle_contract": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v2/contract.json"),
    "startup_oracle_implementation": Path("scripts/f8_womersley_oracle_v2.py"),
    "startup_oracle_test": Path("tests/test_f8_womersley_oracle_v2.py"),
    "observation_parser_contract": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/observation-parser-v1/contract.json"),
    "observation_parser_implementation": Path("scripts/f8_observation_parser_v1.py"),
    "observation_parser_test": Path("tests/test_f8_observation_parser_v1.py"),
    "extension_contract_test": Path("tests/test_f8_reference_contracts_v2.py"),
}


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


def build_bundle() -> dict[str, Any]:
    bundle = copy.deepcopy(_legacy.build_bundle())
    for relative in EXTENSIONS.values():
        if not (LAB / relative).is_file():
            raise FileNotFoundError(LAB / relative)
    bundle["schema"] = SCHEMA
    bundle["status"] = "static_review_bundle_v2_pending_root_decision"
    bundle["parser_contract"]["status"] = "implemented_static_parser_no_source_present"
    bundle["transient_boundary"].update({
        "startup_oracle_available": True,
        "startup_oracle_steady_limit_tested": True,
        "steady_oracle_supports_startup_decay": False,
        "cfd_weakly_compressible_startup_evidence_required": True,
    })
    bundle["bindings"].extend(
        bind(path, f"F8 v2 static extension: {role}")
        for role, path in EXTENSIONS.items())
    bundle["execution_controls"]["definition_written"] = False
    bundle["execution_controls"]["control_written"] = False
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
