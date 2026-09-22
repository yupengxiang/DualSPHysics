#!/usr/bin/env python3
"""Write the no-side-effect root decision packet for a possible F8 r002.

F8 r001 is an immutable retained hard failure.  This packet neither changes
that scope nor creates an r002 input: it gives the user a precise choice about
whether a *new* scope may be considered after the r001 closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
R001 = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001"
OUTPUT = R001 / "r002-continuation-decision-v1/packet.json"
PLAN = Path("/home/jade/.codex/attachments/ece07836-13f3-4e3a-9dd4-55120224dcee/PLAN.md")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = str(path.relative_to(LAB))
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build_packet() -> dict[str, Any]:
    postrun = R001 / "cpu-native-preflight-postrun-audit-v1/receipt.json"
    preflight = R001 / "cpu-native-preflight-v1/receipt.json"
    ruling = R001 / "root-scope-ruling-v1/receipt.json"
    for path in (postrun, preflight, ruling, PLAN):
        if not path.is_file():
            raise FileNotFoundError(path)
    audit = json.loads(postrun.read_text(encoding="utf-8"))
    if audit.get("status") != "retained_hard_failure_no_retry_zero_credit":
        raise ValueError("F8 r001 is not the retained no-retry hard failure")
    return {
        "schema": "core.cfd.f8.r002_continuation_decision_packet.v1",
        "status": "awaiting_user_r002_continuation_ruling",
        "closed_scope": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "proposed_new_scope": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002",
        "question": "May Core open a new F8 r002 scope after the closed r001 hard failure, with fresh inputs and a fresh static review?",
        "evidence": [
            ref(PLAN, "adopted Core plan"),
            ref(ruling, "user-accepted F8 mechanism-family ruling for r001"),
            ref(preflight, "one-shot r001 CPU/native preflight receipt"),
            ref(postrun, "read-only r001 hard-failure closure"),
        ],
        "r001_retained_failure": {
            "status": audit["status"],
            "fixed_boundary_particle_count": audit["retained_failure_facts"]["fixed_boundary_particle_count"],
            "boundary_normal_file": audit["retained_failure_facts"]["decoded_boundary_normal_file"],
            "control_copy_warning": audit["retained_failure_facts"]["control_csv_copy_warning"],
            "same_input_retry_forbidden": audit["failure_closure"]["same_input_retry_forbidden"],
            "qualification_credit": 0,
        },
        "options": {
            "open_new_r002_scope": {
                "label": "Authorize a fresh F8 r002 scope",
                "effect": "permits only a new root/static design review; it does not permit input writing or runtime execution",
                "mandatory_invariants": [
                    "r001 files and raw evidence remain immutable and are never rerun",
                    "r002 uses a separate directory, scope ID, Definition hash, control hash, and output namespace",
                    "static review must prove GenCase-realizable fixed z-wall particles and a resolvable control-file path before any CPU authorization",
                    "the next CPU/native preflight requires its own immutable one-shot authorization",
                    "solver, GPU, queue, registry, ledger, qualification, and training remain unauthorized",
                ],
                "qualification_credit": 0,
            },
            "close_f8_after_r001": {
                "label": "Do not open r002; retain F8 as closed after r001",
                "effect": "F8 supplies no third T1 family and Core must choose another family",
                "qualification_credit": 0,
            },
        },
        "execution_controls": {
            "r002_definition_written": False,
            "r002_control_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "no_implicit_selection": True,
    }


def write_packet(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r002 decision packet: {path}")
    packet = build_packet()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    packet = write_packet(args.output)
    print(json.dumps({key: packet[key] for key in ("status", "closed_scope", "proposed_new_scope")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
