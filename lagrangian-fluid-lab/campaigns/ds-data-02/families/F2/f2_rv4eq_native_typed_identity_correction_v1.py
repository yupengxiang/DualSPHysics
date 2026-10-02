#!/usr/bin/env python3
"""Correct typed ``Mk`` labels in an immutable RV4 native PartVTKOut report.

The first functional RV4 PartVTKOut report preserved all native rows and
positions, but its sidecar lookup used ``mkfluid`` (source ordinal) instead of
the generated XML's native ``mk`` value.  This producer rewrites only the
typed identity sidecar from the same immutable rows and XML.  It never reruns
PartVTKOut, touches the raw CSV/receipt, or changes exclusion/fate semantics.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds-data-02.f2.rv4eq-native-typed-identity-correction.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def binding(path: Path, role: str) -> dict[str, Any]:
    path = require(path, role)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def typed_ranges(xml: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError(f"no particles block: {xml}")
    ranges = []
    for tag, type_id in (("fixed", 0), ("moving", 1), ("fluid", 3)):
        for node in particles.findall(f"./{tag}"):
            begin = int(node.attrib["begin"])
            count = int(node.attrib["count"])
            # DualSPHysics native PartVTK Mk is the child `mk` value.  For a
            # fluid block `mkfluid` is only the source block ordinal.
            mk = int(node.attrib["mk"])
            ranges.append({"low": begin, "high": begin + count - 1, "type": type_id, "mk": mk, "source": tag})
    ranges.sort(key=lambda item: (item["low"], item["high"]))
    if not ranges or ranges[0]["low"] != 0 or any(a["high"] + 1 != b["low"] for a, b in zip(ranges, ranges[1:])):
        raise ValueError(f"typed XML ranges do not form a contiguous axis: {xml}")
    return ranges


def typed_identity(idp: int, ranges: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [item for item in ranges if item["low"] <= idp <= item["high"]]
    if len(matches) != 1:
        return {"status": "unknown", "idp": idp, "matching_ranges": matches}
    item = matches[0]
    return {"status": "resolved", "idp": idp, "type": item["type"], "mk": item["mk"], "source": item["source"], "range": item}


def case_xml(report_case: dict[str, Any]) -> Path:
    for entry in report_case.get("source_bindings", {}).values():
        path = Path(str(entry.get("path", "")))
        if path.name.endswith(".xml") and path.is_file():
            return path
    raise ValueError(f"report case has no generated XML binding: {report_case.get('case_id')}")


def build(source_report: Path, output: Path) -> dict[str, Any]:
    source_report = require(source_report, "v2 native PartVTKOut report")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_report.read_text(encoding="utf-8"))
    if source.get("schema") != "ds-data-02.f2.rv4eq-native-partvtkout-diagnostic.v2":
        raise ValueError(f"unexpected source report schema: {source.get('schema')!r}")
    corrected_cases = []
    for case in source.get("cases", []):
        xml = case_xml(case)
        ranges = typed_ranges(xml)
        records = []
        types: Counter[str] = Counter()
        mks: Counter[str] = Counter()
        for raw in case["partvtkout_exclusions"]["records"]:
            corrected = typed_identity(int(raw["idp"]), ranges)
            types[str(corrected.get("type", "unknown"))] += 1
            mks[str(corrected.get("mk", "unknown"))] += 1
            records.append({
                **raw,
                "prior_v2_typed_identity": raw.get("typed_identity"),
                "typed_identity": corrected,
                "typed_identity_correction": "generated_xml_child_mk_not_mkfluid_source_ordinal",
            })
        # The v2 report's JSONL is retained as immutable raw evidence.  Emit a
        # separate corrected JSONL so downstream owner/label requests never
        # silently point at rows whose typed identity still has source-block
        # ordinals (mkfluid=0/1/2) instead of native Mk values (1/2/3).
        corrected_records_path = output.parent / "corrected_records" / f"{case['case_id']}.jsonl"
        corrected_records_path.parent.mkdir(parents=True, exist_ok=True)
        with corrected_records_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        prior_enriched = case["partvtkout_exclusions"].get("enriched_records")
        corrected_enriched = binding(corrected_records_path, "corrected typed identity records")
        corrected_enriched["rows"] = len(records)
        corrected_cases.append({
            **case,
            "typed_identity_ranges": ranges,
            "partvtkout_exclusions": {
                **case["partvtkout_exclusions"],
                "prior_v2_enriched_records": prior_enriched,
                "enriched_records": corrected_enriched,
                "typed_type_totals": dict(sorted(types.items())),
                "typed_mk_totals": dict(sorted(mks.items())),
                "records": records,
                "corrected_records_are_same_native_rows": True,
            },
        })
    result = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_report": binding(source_report, "immutable v2 native PartVTKOut report"),
        "producer": binding(SCRIPT, "typed identity correction producer"),
        "cases": corrected_cases,
        "correction_scope": {
            "changed": ["typed_identity.range.mk", "typed_mk_totals", "typed_identity_ranges"],
            "preserved": ["Idp", "PartOut", "first_missing_time_s", "Motive", "position_m", "velocity_m_s", "density_kg_m3", "domain evidence", "finite geometry evidence", "raw PartVTKOut outputs"],
            "native_mk_definition": "generated XML particle child attribute mk; mkfluid is source block ordinal",
        },
        "status": "typed_identity_corrected_pending_scientific_review",
        "all_native_fate_unknown": True,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_report, args.output)
    print(json.dumps({"status": result["status"], "path": str(args.output.resolve()), "sha256": sha256(args.output.resolve()), "case_count": len(result["cases"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
