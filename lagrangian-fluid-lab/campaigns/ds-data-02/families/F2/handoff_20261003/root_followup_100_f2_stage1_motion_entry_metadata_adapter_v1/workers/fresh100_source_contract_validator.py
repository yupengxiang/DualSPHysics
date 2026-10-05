#!/usr/bin/env python3
"""Validate fresh100 source/request closure without scientific inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SCIENCE = {".bi4", ".h5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
FORBIDDEN = ("mdbc", "noslip", "-mdbc", "-noslip")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    manifest = load(Path(args.manifest).resolve())
    errors: list[str] = []
    cases = manifest.get("cases", [])
    if len(cases) != 16:
        errors.append(f"case count is {len(cases)}, expected 16")
    for case in cases:
        cid = case["case_id"]
        for key in ("definition", "motion", "metadata", "binding", "owner"):
            path = Path(case[key]["path"]).resolve()
            if not path.is_file():
                errors.append(f"{cid}: missing {key} {path}")
        for kind, bound in case["requests"].items():
            path = Path(bound["path"]).resolve()
            if not path.is_file():
                errors.append(f"{cid}/{kind}: missing request {path}")
                continue
            request = load(path)
            for key, expected in (("disabled", True), ("source_only", True),
                                  ("execution_allowed", False), ("launch_allowed", False),
                                  ("launch", False)):
                if request.get(key) is not expected:
                    errors.append(f"{path.name}: {key}={request.get(key)!r}, expected {expected!r}")
            if request.get("launch_owner") != "root":
                errors.append(f"{path.name}: launch_owner is not root")
            if request.get("canonical_physical_binding_sha256") is not None:
                errors.append(f"{path.name}: canonical scope was prefilled")
            if request.get("production_claim") != "none" or request.get("qualification_claim") != "none":
                errors.append(f"{path.name}: approval claim was prefilled")
            if request.get("physical_condition_sha256") != case["physical_condition_sha256"]:
                errors.append(f"{path.name}: physical condition hash mismatch")
            if any(token in " ".join(map(str, request.get("command", []))).lower() for token in FORBIDDEN):
                errors.append(f"{path.name}: forbidden mdbc/noslip command option")
            for value in request.get("future_input_sha256", {}).values():
                if value is not None:
                    errors.append(f"{path.name}: future input hash is not null")
            for raw in request.get("input_files", []):
                path_value = Path(raw).resolve()
                if path_value.suffix.lower() in SCIENCE:
                    errors.append(f"{path.name}: science artifact listed as source input {path_value}")
                if not path_value.is_file():
                    errors.append(f"{path.name}: missing source input {path_value}")
                elif request.get("input_sha256", {}).get(str(path_value)) != sha(path_value):
                    errors.append(f"{path.name}: source input digest mismatch {path_value}")
        owner = load(Path(case["owner"]["path"]).resolve())
        binding = load(Path(case["binding"]["path"]).resolve())
        if owner.get("canonical_physical_binding_sha256") is not None or binding.get("canonical_physical_binding_sha256") is not None:
            errors.append(f"{cid}: canonical scope was prefilled")
        if owner.get("actual_converter_physical_condition_sha256") is not None:
            errors.append(f"{cid}: actual converter scope was prefilled")
        if "physical_binding" in owner:
            errors.append(f"{cid}: physical_binding must remain absent")
        if len(binding.get("assets", [])) != 1:
            errors.append(f"{cid}: motion asset count is not one")
        if binding.get("expected_fluid") is not None:
            errors.append(f"{cid}: expected fluid count was forced")
        gencase = load(Path(case["requests"]["gencase"]["path"]).resolve())
        if "f2_motion_prepared_gencase_worker.py" not in " ".join(gencase.get("command", [])):
            errors.append(f"{cid}: gencase bypasses staged motion worker")
        native = load(Path(case["requests"]["native"]["path"]).resolve())
        if not isinstance(native.get("gencase_receipt"), str):
            errors.append(f"{cid}: native gencase_receipt is not a string path")
    result = {"schema": "ds02.f2.stage1.fresh100.source-validator.v1",
              "status": "pass" if not errors else "fail",
              "case_count": len(cases), "errors": errors}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
