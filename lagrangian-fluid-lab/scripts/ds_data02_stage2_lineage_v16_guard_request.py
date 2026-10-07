#!/usr/bin/env python3
"""Freeze a metadata-only guard request for the v16 provisional domain cards.

The request binds the actual 336-case audit and seven generated card files by
content SHA, plus the generator's small-source inputs and test.  It records
the seven-family raw stream plan as *planned* evidence separately, so a
metadata guard cannot be mistaken for raw/typed reconstruction.  No HDF5 or
BI4 file is an input to this request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "ds02.request.v1"
REQUEST_KIND = "ds02.stage2.current336-provisional-domain-audit.v16-guard"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{index}" for index in range(1, 8))


class V16GuardRequestError(ValueError):
    """Raised when the generated v16 request is not source closed."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise V16GuardRequestError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise V16GuardRequestError(f"JSON object required: {path}")
    return value


def bind(path: Path, role: str, *, status: str = "ACTUAL") -> dict[str, Any]:
    if not path.is_file():
        raise V16GuardRequestError(f"source is missing: {role}: {path}")
    stat = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "status": status,
    }


def build(report_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    report_file = Path(report_path).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()
    report = load(report_file)
    if report.get("schema") != "ds02.stage2.current336-provisional-domain-audit.v16":
        raise V16GuardRequestError("report is not the v16 provisional domain audit")
    if report.get("status") != "PROVISIONAL_336_DOMAIN_CATEGORIES; SEMANTIC_CLOSURE_PENDING; QUALIFICATION_UNKNOWN":
        raise V16GuardRequestError("report status is not the conservative v16 status")
    if report.get("audit_scope", {}).get("case_count") != 336 or report.get("audit_scope", {}).get("hdf5_or_bi4_read") is not False:
        raise V16GuardRequestError("v16 report must be the 336-case metadata-only result")
    cards = report.get("cards")
    if not isinstance(cards, dict) or set(cards) != set(FAMILIES):
        raise V16GuardRequestError("v16 report must bind exactly seven family cards")
    bindings = [bind(report_file, "v16_domain_audit_report")]
    for family in FAMILIES:
        item = cards[family]
        if not isinstance(item, dict) or item.get("status") != "PROVISIONAL_DOMAIN_CARD; QUALIFICATION_UNKNOWN":
            raise V16GuardRequestError(f"{family} card status is not provisional/unknown")
        path = (report_file.parent / str(item.get("path"))).resolve()
        card_doc = load(path)
        if card_doc.get("sha256") != item.get("sha256"):
            raise V16GuardRequestError(f"{family} card canonical SHA differs from report")
        actual = bind(path, f"{family}_family_card")
        actual["canonical_sha256"] = card_doc.get("sha256")
        bindings.append(actual)
    source_audit = report.get("audit_scope", {}).get("source_audit")
    if not isinstance(source_audit, dict):
        raise V16GuardRequestError("v15 source audit binding is missing")
    audit_path = (report_file.parent / str(source_audit.get("path"))).resolve()
    source_binding = bind(audit_path, "immutable_v15_small_source_audit")
    if source_binding["sha256"] != source_audit.get("sha256"):
        raise V16GuardRequestError("v15 source audit SHA differs from v16 report")
    bindings.append(source_binding)
    script = Path(__file__).resolve().with_name("ds_data02_stage2_lineage_v16_provisional_domains.py")
    test = Path(__file__).resolve().parents[1] / "tests/test_ds_data02_stage2_lineage_v16_provisional_domains.py"
    bindings.extend([bind(script, "v16_domain_card_generator"), bind(test, "v16_domain_card_test")])
    lineage_root = report_file.parent.parent
    v13_inputs = []
    for family in FAMILIES:
        v13 = lineage_root / "v13" / f"{family}-family-card-v13.json"
        v13_inputs.append(bind(v13, f"{family}_immutable_v13_card"))
    bindings.extend(v13_inputs)
    plan = report_file.parent / "seven-family-raw-anchor-stream-plan-v1.json"
    planned = [{
        "role": "seven_family_raw_anchor_stream_plan",
        "path": str(plan.resolve()),
        "sha256": sha256_file(plan) if plan.is_file() else None,
        "status": "PLANNED_ONLY; NOT_EXECUTED; RAW_BI4_NOT_READ_BY_THIS_REQUEST",
    }]
    actual_roles = {item["role"] for item in bindings}
    if any(item["status"] != "ACTUAL" for item in bindings):
        raise V16GuardRequestError("actual source output binding has a non-actual status")
    request = {
        "schema": SCHEMA,
        "request_id": "current336-provisional-domain-audit-v16-guard-001",
        "orchestration_schema": REQUEST_KIND,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "source_hashes_preverified_by_parent": False,
        "input_files": [item["path"] for item in bindings],
        "input_hashes": {item["path"]: item["sha256"] for item in bindings},
        "source_bindings": bindings,
        "actual_source_worker_outputs": {
            "report": next(item for item in bindings if item["role"] == "v16_domain_audit_report"),
            "cards": [item for item in bindings if item["role"].endswith("_family_card")],
            "status": "ACTUAL_METADATA_OUTPUTS; NO_H5_OR_BI4_READ",
        },
        "planned_followups": planned,
        "execution_contract": {
            "read_scope": "JSON/source-card/generator/test metadata only",
            "hdf5_or_bi4_read": False,
            "raw_reconstruction": "NOT_EXECUTED",
            "typed_comparison": "NOT_EXECUTED",
            "family_labels": "NOT_EXECUTED",
            "model_invoked": False,
            "cfd_invoked": False,
            "source_worker_card_sha_policy": "exact hashes above; no status promotion from planned to actual",
        },
        "lineage_scope": {
            "case_count": 336,
            "family_case_counts": {family: 48 for family in FAMILIES},
            "split_safe": False,
            "semantic_closure": "PENDING",
            "qualification": UNKNOWN,
        },
        "resource_request": {
            "cpu": 1,
            "max_wall_seconds": 900,
            "max_rss_bytes": 2 * 1024**3,
            "storage_bytes": sum(item["bytes"] for item in bindings),
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "Cards are provisional source-role/domain categories, not effective physical equivalence closure",
            "Family groups are not prospective split-safe; recovery/resolution/window equivalence remains UNKNOWN",
            "The raw anchor plan is explicitly planned-only and cannot supply actual reconstruction credit",
        ],
    }
    request["sha256"] = canonical_sha(request)
    if output_file.exists():
        raise V16GuardRequestError(f"refusing to overwrite output: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {"path": str(output_file), "sha256": request["sha256"], "input_roles": len(actual_roles), "planned_roles": len(planned)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.report, args.output)
    except (OSError, V16GuardRequestError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
