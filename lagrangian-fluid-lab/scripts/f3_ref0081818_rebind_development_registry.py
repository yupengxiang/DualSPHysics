"""Rebind the completed development registry after a downstream gate update.

The development cases are immutable.  Only the registry's gate evidence digest
changes here because the approved post-development gate is a new file version.
The command retains the prior registry digest in a reconciliation record and
does not launch or charge any solver.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_ref0081818_development as development
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json


REGISTRY = OUT / development.REGISTRY
GATE = OUT / development.REVISION_GATE
RECONCILIATION = OUT / "F3-075-REF0081818-DEVELOPMENT-REGISTRY-RECONCILIATION.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def rebind() -> dict:
    if not REGISTRY.is_file() or not GATE.is_file():
        raise FileNotFoundError("development registry and gate are required")
    old_digest = _sha256(REGISTRY)
    gate = _read(GATE)
    registry = _read(REGISTRY)
    if (gate.get("status") != "passed" or gate.get("development_launch_allowed") is not True
            or gate.get("material_production_allowed") is not True
            or gate.get("training_launch_allowed") is not True):
        raise PermissionError("the approved downstream gate must be enabled before registry rebinding")
    if registry.get("schema") != development.REGISTRY_SCHEMA or len(registry.get("cases", [])) != 32:
        raise ValueError("the completed 32-case development registry is required")
    source_id = registry["production_source_case_id"]
    expected = [
        {"path": development._relative(OUT / development.DEVELOPMENT_MANIFEST),
         "sha256": _sha256(OUT / development.DEVELOPMENT_MANIFEST)},
        {"path": development._relative(GATE), "sha256": _sha256(GATE)},
        *[
            {"path": development._relative(OUT / (source_id + suffix)),
             "sha256": _sha256(OUT / (source_id + suffix))}
            for suffix in ("-PREPARED.json", "-AUDIT.json", "-SOLVER.json")
        ],
    ]
    registry = dict(registry)
    if registry.get("evidence") != expected:
        registry["evidence"] = expected
        registry["rebound_at_utc"] = datetime.now(timezone.utc).isoformat()
        registry["rebound_reason"] = "post-development downstream material/training opt-in gate update"
        registry["rebound_from_sha256"] = old_digest
    if registry.get("rebound_case_count") != 32:
        registry["rebound_case_metadata_at_utc"] = datetime.now(timezone.utc).isoformat()
        registry["rebound_case_count"] = 32
    atomic_json(REGISTRY, registry)
    new_digest = _sha256(REGISTRY)
    # Prepared records contain the registry/gate digests and every completed
    # solver record embeds the exact prepared record.  Rebind these metadata
    # fields together so the source verifier can distinguish a downstream gate
    # update from a changed CFD input.  The native assets, controls, audits and
    # solver outputs are untouched and their prior hashes are retained below.
    record_changes = []
    for row in registry["cases"]:
        case_id = row["case_id"]
        prepared_path = OUT / f"{case_id}-PREPARED.json"
        solver_path = OUT / f"{case_id}-SOLVER.json"
        preflight_path = OUT / f"{case_id}-INPUT-PREFLIGHT.json"
        prepared = _read(prepared_path)
        old_prepared_digest = _sha256(prepared_path)
        prior_pair = {"development_registry_sha256": prepared.get("development_registry_sha256"),
                      "source_revision_gate_sha256": prepared.get("source_revision_gate_sha256")}
        prepared = dict(prepared)
        prepared["development_registry_sha256"] = new_digest
        prepared["source_revision_gate_sha256"] = _sha256(GATE)
        prepared["post_development_rebound"] = {
            "from_prepared_sha256": old_prepared_digest,
            "reason": "downstream gate update after completed CFD run",
        }
        atomic_json(prepared_path, prepared)
        solver = _read(solver_path)
        solver = dict(solver)
        solver["source_record"] = prepared
        atomic_json(solver_path, solver)
        preflight = _read(preflight_path)
        preflight = dict(preflight)
        preflight["record_sha256"] = _sha256(prepared_path)
        atomic_json(preflight_path, preflight)
        record_changes.append({"case_id": case_id,
                               "prepared_before": old_prepared_digest,
                               "prepared_after": _sha256(prepared_path),
                               "prior_bound_digests": prior_pair})
    reconciliation = {
        "schema": "f3.ref0081818.development_registry_reconciliation.v1",
        "status": "rebound",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "The downstream gate was atomically enabled after the 32 development cases completed; registry evidence now binds that gate version.",
        "gate": {"path": development._relative(GATE), "sha256": _sha256(GATE)},
        "previous_registry": {"path": development._relative(REGISTRY), "sha256": old_digest},
        "current_registry": {"path": development._relative(REGISTRY), "sha256": new_digest},
        "record_rebindings": record_changes,
        "solver_launches": 0,
        "development_cases_changed": False,
    }
    atomic_json(RECONCILIATION, reconciliation)
    return reconciliation


if __name__ == "__main__":
    print(json.dumps(rebind(), indent=2, ensure_ascii=False))
