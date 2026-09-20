#!/usr/bin/env python3
"""Read-only audit of F5 v2 fixed/moving boundary count semantics."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
PREFLIGHT = ROOT / "preflight-v2/preflight.json"
OUTPUT = ROOT / "preflight-boundary-semantics-audit-v1.json"
RUNNER = LAB / "scripts/f5_wave_runup_preflight_v2.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build() -> dict[str, Any]:
    value = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    assert value["schema"] == "core.f5.third_t1.preflight.v1"
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    assert value["execution_controls"]["solver_invoked"] is False
    native = value["native"]
    generated = value["generated"]
    fixed = int(generated["fixed_particles"])
    total_bound = int(generated["boundary_particles"])
    moving = total_bound - fixed
    fluid = int(generated["fluid_particles"])
    total = int(generated["total_particles"])
    assert native["boundary_particles"] == fixed
    assert total_bound == fixed + moving
    assert total == fixed + moving + fluid
    return {
        "schema": "core.f5.third_t1.preflight_boundary_semantics_audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "read_only_semantics_audit_passed",
        "qualification_claim": "none",
        "source": bind(PREFLIGHT, "immutable F5 v2 CPU/native preflight"),
        "runner": bind(RUNNER, "F5 v2 preflight runner provenance"),
        "counts": {
            "generated_total_particles": total,
            "generated_boundary_particles_including_moving": total_bound,
            "generated_fixed_particles": fixed,
            "derived_moving_particles": moving,
            "generated_fluid_particles": fluid,
            "native_case_nfixed": int(native["boundary_particles"]),
            "identity_closure": total == fixed + moving + fluid,
            "native_fixed_semantics_match": int(native["boundary_particles"]) == fixed,
        },
        "interpretation": (
            "CaseNfixed/native boundary_particles counts fixed walls only; generated XML boundary count includes fixed and moving piston. "
            "The static preflight hard gate used fluid identity, finite arrays, mass metadata and geometry counts, so this semantic clarification "
            "does not change the preflight result or grant any T1 credit."
        ),
        "execution_controls": {
            "hdf5_opened": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
    }


def main() -> int:
    value = build()
    OUTPUT.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": rel(OUTPUT), "sha256": sha256(OUTPUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
