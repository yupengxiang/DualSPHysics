#!/usr/bin/env python3
"""Bind completed XMF JSON/XML metadata into a fresh108 bed-audit copy.

This helper reads JSON/XML metadata only.  It never opens H5/BI4/CSV/VTK/DAT
and never launches the bed worker; Root runs the resulting disabled audit
request only after reviewing the actual XMF receipt.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HEX = set("0123456789abcdefABCDEF")

def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)

def load(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata required: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value

def sha(path: Path) -> str:
    require(path.suffix.lower() in {".json", ".xml", ".xmf", ".md", ".py", ".txt", ".log"}, f"payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--xdmf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binding = load(args.binding)
    manifest = load(args.manifest)
    require(binding.get("schema") == "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh108.v1", "fresh108 bed binding schema")
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "XMF manifest schema")
    require(manifest.get("case_id") == binding.get("case_id"), "XMF manifest case mismatch")
    require(manifest.get("physical_case_id") == binding.get("physical_case_id"), "XMF manifest physical case mismatch")
    require(manifest.get("frames") == 51 and manifest.get("particles") == 194427, "XMF dimensions mismatch")
    require(manifest.get("canonical_physical_condition_sha256") == binding.get("physical_condition_sha256"), "canonical owner mismatch")
    require(manifest.get("source_h5_physical_condition_sha256") == binding.get("source_h5_physical_condition_sha256"), "legacy H5 scope mismatch")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"), "producer H5 SHA mismatch")
    require(args.xdmf.is_file() and args.manifest.is_file(), "completed XMF metadata missing")
    xdmf_sha = sha(args.xdmf)
    require(manifest.get("xdmf") == str(args.xdmf) and manifest.get("xdmf_sha256") == xdmf_sha, "XMF path/SHA mismatch")
    updated = dict(binding)
    updated["xmf_manifest"] = str(args.manifest)
    updated["xmf_manifest_sha256"] = sha(args.manifest)
    updated["xmf"] = str(args.xdmf)
    updated["xmf_sha256"] = xdmf_sha
    updated["xdmf"] = str(args.xdmf)
    updated["xdmf_sha256"] = xdmf_sha
    updated["xmf_binding_provenance"] = {"manifest": str(args.manifest), "manifest_sha256": updated["xmf_manifest_sha256"], "xdmf": str(args.xdmf), "xdmf_sha256": xdmf_sha, "source_agent_read_science_payload": False}
    updated["future_output_hashes"] = {"typed_h5_sha256": binding.get("trajectory_h5_sha256"), "xmf_manifest_sha256": updated["xmf_manifest_sha256"], "bed_audit_report_sha256": None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "bound_xmf_metadata_only", "binding": str(args.output), "xmf_manifest_sha256": updated["xmf_manifest_sha256"], "xdmf_sha256": xdmf_sha}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
