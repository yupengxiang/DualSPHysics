#!/usr/bin/env python3
"""Archive Terra High's read-only review of the F8 R008 provenance design v2."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
DESIGN_V1 = Path("reports/F8-R008-PER-CASE-PROVENANCE-DESIGN-PROPOSAL-2026-09-24.zh-CN.md")
DESIGN_V2 = Path("reports/F8-R008-PER-CASE-PROVENANCE-DESIGN-PROPOSAL-V2-2026-09-24.zh-CN.md")
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_per_case_provenance_design_review_v2.py")
OUTPUT = LAB / ROOT / "t1-per-case-provenance-design-review-v2/receipt.json"
SCHEMA = "core.cfd.f8.r008_per_case_provenance_design_review.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": absolute.relative_to(LAB).as_posix(),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_receipt() -> dict[str, Any]:
    from scripts import f8_r008_execution_readiness_audit_v4 as audit

    current_audit = audit.verify_audit()
    if current_audit.get("readiness_pass") is not False or current_audit.get("qualification_credit") != 0:
        raise ValueError("the current F8 R008 audit must remain blocked and zero-credit")
    evidence = [
        binding(DESIGN_V1, "Terra High REVISE design draft v1"),
        binding(DESIGN_V2, "Terra High PASS design proposal v2"),
        binding(Path("scripts/f8_r008_t1_metric_adapter_v1.py"), "current F8 R008 adapter reviewed as an input to the design"),
        binding(Path("tests/test_f8_r008_t1_metric_adapter_v1.py"), "current F8 R008 adapter regression tests"),
        binding(Path("scripts/f8_r008_definition_control_pack_v1.py"), "Definition/control row validator referenced by the design"),
        binding(Path("tests/test_f8_r008_definition_control_pack_v1.py"), "Definition/control row and cadence contract tests"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"), "frozen R008 qualification scope and comparison contract"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json"), "frozen 15+32 Definition/control bindings"),
        binding(Path("scripts/f8_r008_execution_readiness_audit_v4.py"), "current zero-credit readiness audit implementation"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v4/receipt.json"), "current immutable readiness audit receipt"),
        binding(Path("scripts/core_cfd.py"), "existing BI4/native frame conversion path inspected during review"),
        binding(Path("campaigns/l1-resume/artifacts/bi4_dump"), "native BI4 decoder binary; hash-bound but not executed or reverse-engineered"),
        binding(SCRIPT, "parent-authored review archive builder"),
        binding(TEST, "review archive contract tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-per-case-provenance-design-review-v2",
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_design_review_passed_implementation_prerequisites_open",
        "reviewer": {
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "agent_id": "01a0d167-4db5-7f90-aee2-94547602a273",
            "verdict": "PASS",
            "review_mode": "read_only_static_design_review",
            "review_thread_note": "Follow-up by the same Terra High agent after its v1 REVISE; not represented as a newly independent second reviewer.",
            "reviewer_ran_tests": False,
            "reviewer_execution_or_evidence_mutation": False,
        },
        "reviewed_proposal": {
            "path": DESIGN_V2.as_posix(),
            "sha256": sha256(LAB / DESIGN_V2),
            "bytes": (LAB / DESIGN_V2).stat().st_size,
        },
        "findings": [
            {"topic": "prelaunch admission versus post-run consumed namespace", "verdict": "PASS", "detail": "Separate contracts require an absent target before launch and an existing, consumed target for post-run verification."},
            {"topic": "adapter/table provenance schema", "verdict": "PASS", "detail": "Requires a new table/adapter schema and rejects v1, GenCase-only, and synthetic provenance at qualification entry."},
            {"topic": "raw solver/decode lineage", "verdict": "PASS", "detail": "Defines solver output manifests, decoder input-output mapping, per-frame raw arrays and full-axis to table/window binding."},
            {"topic": "Definition/control case binding", "verdict": "PASS", "detail": "Requires the XML-to-CSV reference, exact hashes and validation of row-specific CFL, TimeMax, TimeOut and cadence controls."},
            {"topic": "provenance versus T1 boundary", "verdict": "PASS", "detail": "Keeps provenance, native integrity, metric/comparison gates and final T1 adjudication as distinct stages."},
        ],
        "remaining_prerequisites": [
            "Statically freeze the complete BI4/bi4_dump output layout, byte order, metadata semantics and exact output manifest before implementing B/C/D verifiers; no runtime probe is authorized.",
            "If hard-link substitution is prohibited, the implementation must explicitly require st_nlink == 1 in addition to no-follow regular-file checks.",
            "A design review PASS does not authorize GenCase, native decode, solver, worker, GPU, queue, registry, ledger or qualification work.",
        ],
        "parent_validation": {
            "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_definition_control_pack_v1.py",
            "passed": 15,
            "failed": 0,
            "scope_note": "Supporting static Definition/control validation only; no native tools invoked.",
        },
        "qualification_credit": 0,
        "execution_authority": {
            "gencase": False,
            "native_decode": False,
            "solver": False,
            "worker": False,
            "gpu": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_receipt():
        raise ValueError("F8 R008 provenance design review receipt no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 provenance design review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable review receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
