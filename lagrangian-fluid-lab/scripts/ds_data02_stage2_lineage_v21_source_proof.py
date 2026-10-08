#!/usr/bin/env python3
"""Bind the development cards to the independent v23/all118 evidence.

This forward-only index consumes small JSON proofs and the existing v20 card
summaries.  It hashes the two actual proof files and the all118 output/receipt
they name, but never opens trajectory HDF5, Part_*.bi4, or solver arrays.  The
independent evidence is scoped by family and remains observational: every
card stays DEVELOPMENT_ONLY with QI/QN/QE UNKNOWN and split_safe=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


FAMILIES = tuple(f"F{i}" for i in range(1, 8))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V20_PROOF_SCHEMA = "ds02.stage2.current336-source-proof.v20"
PROOF_SCHEMA = "ds02.stage2.current336-source-proof.v21"
CARD_SCHEMA = "ds02.stage2.family-card.v21-source-proof"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
IMPACT_SCHEMA = "ds02.stage2.all118-impact-v8-independent-verification.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 32 * 1024 * 1024


class SourceProofV21Error(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise SourceProofV21Error(f"missing JSON source: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise SourceProofV21Error(f"JSON source exceeds bounded proof size: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceProofV21Error(f"cannot read JSON source {target}: {error}") from error
    if not isinstance(value, dict):
        raise SourceProofV21Error(f"JSON object required: {target}")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise SourceProofV21Error(f"refusing to overwrite proof output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise SourceProofV21Error(f"{name} must be a lowercase SHA-256")
    return value


def _read_v20_card(proof_dir: Path, family: str) -> tuple[dict[str, Any], str]:
    path = proof_dir / f"{family}-family-card-v20-source-proof.json"
    card = read_json(path)
    if card.get("schema") != "ds02.stage2.family-card.v20-source-proof":
        raise SourceProofV21Error(f"{family} is not a v20 source-proof card")
    if card.get("sha256") != canonical_sha(card):
        raise SourceProofV21Error(f"{family} v20 card canonical SHA differs")
    if card.get("family_id") != family or card.get("source_link_count") != 48:
        raise SourceProofV21Error(f"{family} v20 card count/family binding differs")
    if (card.get("qualification") != UNKNOWN
            or card.get("raw_anchor_policy", {}).get("split_safe") is not False):
        raise SourceProofV21Error(f"{family} v20 card is not conservative")
    return card, file_sha256(path)


def _proof_file_binding(path: Path, expected_schema: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proof = read_json(path)
    if proof.get("schema") != expected_schema:
        raise SourceProofV21Error(f"proof schema differs: {path}")
    return proof, {"path": str(path), "file_sha256": file_sha256(path),
                   "schema": expected_schema}


def _verify_scientific_audit(path: Path, current_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    audit, binding = _proof_file_binding(path, AUDIT_SCHEMA)
    if audit.get("distinct_completed_cases") != 336 or audit.get("by_family") != {family: 48 for family in FAMILIES}:
        raise SourceProofV21Error("scientific v23 proof is not all 336 / 7x48")
    if audit.get("current_catalog", {}).get("sha256") != current_sha:
        raise SourceProofV21Error("scientific v23 proof is bound to another CURRENT catalog")
    if audit.get("goal_complete") is not False:
        raise SourceProofV21Error("scientific v23 proof has an unsafe completion claim")
    if audit.get("verification_scope", "").find("No extra root H5 content scan") < 0:
        raise SourceProofV21Error("scientific v23 proof scope is missing the no-extra-H5 boundary")
    binding.update({
        "distinct_completed_cases": 336,
        "by_family": dict(audit["by_family"]),
        "newly_verified_count": audit.get("newly_verified_count"),
        "current_catalog": dict(audit["current_catalog"]),
        "goal_complete": False,
        "large_array_read": False,
    })
    return audit, binding


def _verify_impact(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    impact, binding = _proof_file_binding(path, IMPACT_SCHEMA)
    if impact.get("status") != "PASS_NATIVE_CAUSE_SOURCE_MASS_CENSORING_ACCOUNTING_ONLY":
        raise SourceProofV21Error("all118 impact proof status is not the accepted observational status")
    coverage = impact.get("coverage")
    if not isinstance(coverage, Mapping) or coverage.get("full_source_case_count") != 118:
        raise SourceProofV21Error("all118 impact proof lacks full source coverage")
    if coverage.get("family_counts") != {"F2": 48, "F4": 22, "F6": 48}:
        raise SourceProofV21Error("all118 impact family coverage differs")
    if impact.get("root_h5_or_raw_read") is not False or impact.get("goal_complete") is not False:
        raise SourceProofV21Error("all118 proof has an unsafe raw-read/completion claim")
    causes = impact.get("cause_counts")
    if not isinstance(causes, Mapping) or set(causes) != {"NUMERICAL_POSITION_EXCLUSION", "NUMERICAL_DENSITY_EXCLUSION"}:
        raise SourceProofV21Error("all118 native cause accounting is incomplete")
    output = impact.get("output")
    receipt = impact.get("receipt")
    if not isinstance(output, Mapping) or not isinstance(receipt, Mapping):
        raise SourceProofV21Error("all118 output/receipt binding is missing")
    for role, item in (("output", output), ("receipt", receipt)):
        target = Path(str(item.get("path", ""))).expanduser().resolve()
        expected = _sha(item.get("sha256"), f"impact.{role}.sha256")
        if not target.is_file() or file_sha256(target) != expected:
            raise SourceProofV21Error(f"all118 {role} content SHA differs or is missing")
    binding.update({
        "status": impact["status"],
        "coverage": dict(coverage),
        "cause_counts": dict(causes),
        "output": {"path": str(output["path"]), "sha256": output["sha256"]},
        "receipt": {"path": str(receipt["path"]), "sha256": receipt["sha256"]},
        "root_h5_or_raw_read": False,
        "claim_boundary": dict(impact.get("claim_boundary", {})),
        "goal_complete": False,
    })
    return impact, binding


def build(current_path: Path | str, v20_dir: Path | str, output_dir: Path | str,
          *, scientific_audit: Path | str, impact_proof: Path | str) -> dict[str, Any]:
    current_path = Path(current_path).expanduser().resolve()
    v20_dir = Path(v20_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    current = read_json(current_path)
    if current.get("schema") != "ds02.stage2.current336.v1" or len(current.get("cases", [])) != 336:
        raise SourceProofV21Error("CURRENT336 schema/count is not exact")
    current_sha = file_sha256(current_path)
    base = read_json(v20_dir / "CURRENT336-source-proof-v20.json")
    if base.get("schema") != V20_PROOF_SCHEMA or base.get("sha256") != canonical_sha(base):
        raise SourceProofV21Error("v20 source proof is not canonical")
    if base.get("current_binding", {}).get("sha256") != current_sha:
        raise SourceProofV21Error("v20 proof is bound to another CURRENT336")
    if base.get("qualification") != UNKNOWN or base.get("split_policy", {}).get("split_safe") is not False:
        raise SourceProofV21Error("v20 proof is not conservative")
    _, scientific = _verify_scientific_audit(Path(scientific_audit).expanduser().resolve(), current_sha)
    _, impact = _verify_impact(Path(impact_proof).expanduser().resolve())

    cards: dict[str, dict[str, Any]] = {}
    card_paths: dict[str, str] = {}
    for family in FAMILIES:
        card, file_digest = _read_v20_card(v20_dir, family)
        actual_scope = {
            "scientific_audit_v23": {
                "status": "ALL336_FIELD_SOURCE_VERIFIED; QI_DYNAMICS_NOT_ASSESSED",
                "case_count": 48,
                "proof_file_sha256": scientific["file_sha256"],
            },
            "impact_v8_all118": {
                "status": "DIRECT_NATIVE_CAUSE_EVIDENCE" if family in {"F2", "F4", "F6"} else "NOT_IN_SCOPE",
                "case_count": {"F2": 48, "F4": 22, "F6": 48}.get(family, 0),
                "proof_file_sha256": impact["file_sha256"],
            },
        }
        proof = {
            "schema": CARD_SCHEMA,
            "status": "DEVELOPMENT_ONLY; PROVISIONAL; QUALIFICATION_UNKNOWN",
            "family_id": family,
            "qualification": dict(UNKNOWN),
            "model_invoked": False,
            "cfd_invoked": False,
            "current_path": str(current_path),
            "current_sha256": current_sha,
            "base_card_path": str(v20_dir / f"{family}-family-card-v20-source-proof.json"),
            "base_card_file_sha256": file_digest,
            "base_card_embedded_sha256": card["sha256"],
            "source_link_count": 48,
            "source_closure": card.get("source_closure"),
            "physical_mechanism": card.get("physical_mechanism"),
            "effective_condition": card.get("effective_condition"),
            "task_subsets": card.get("task_subsets"),
            "observer_contract": card.get("observer_contract"),
            "actual_evidence_scope": actual_scope,
            "raw_anchor_policy": {"hidden": False, "exact_current_row": True,
                                   "arbitrary_latest_or_glob": False, "split_safe": False},
            "unknown_scope": list(card.get("unknown_scope", [])) + [
                "scientific v23 field verification does not award dynamics QI/QN/QE",
                "all118 impact evidence covers native numerical causes/mass censoring only; it is not physical outflow or dynamical error",
            ],
        }
        proof["sha256"] = canonical_sha(proof)
        cards[family] = {"path": str(output_dir / f"{family}-family-card-v21-source-proof.json"),
                         "sha256": proof["sha256"], "case_count": 48,
                         "split_safe": False, "qualification": dict(UNKNOWN)}
        card_paths[family] = str(output_dir / f"{family}-family-card-v21-source-proof.json")
        # Keep the in-memory proof for the write pass below.
        cards[family]["_proof"] = proof

    report: dict[str, Any] = {
        "schema": PROOF_SCHEMA,
        "status": "DEVELOPMENT_SOURCE_PROOF_BOUND_WITH_V23_AND_IMPACT_V8",
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "current_binding": {"path": str(current_path), "sha256": current_sha,
                             "schema": current["schema"], "case_count": 336,
                             "family_counts": {family: 48 for family in FAMILIES}},
        "forward_of": {"path": str(v20_dir / "CURRENT336-source-proof-v20.json"),
                        "sha256": base["sha256"], "immutable": True},
        "evidence_bindings": {"scientific_audit_v23": scientific, "impact_v8_all118": impact},
        "family_cards": {family: {key: value for key, value in card.items() if key != "_proof"}
                         for family, card in cards.items()},
        "split_policy": {"prospective_only": True, "split_safe": False,
                          "unknown_recovery_window_transfer": True,
                          "numerical_resolution_not_physical_identity": True,
                          "cross_family_template_equivalence": "UNREVIEWED"},
        "read_scope": {"current_json_opened": True, "v20_cards_opened": True,
                        "scientific_proof_json_opened": True, "impact_output_and_receipt_hashed": True,
                        "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False},
        "limitations": [
            "Scientific v23 verifies CURRENT/source/field/lifecycle bindings but does not award dynamics QI.",
            "Impact v8 covers 118 native numerical cause/source/mass/censoring records; it does not prove physical fate, legal flux, or dynamical error.",
            "Recovery, cross-resolution/window transfer, and prospective split safety remain UNKNOWN.",
            "All cards remain DEVELOPMENT_ONLY and QI/QN/QE UNKNOWN.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    for family, card in cards.items():
        write_new(output_dir / f"{family}-family-card-v21-source-proof.json", card["_proof"])
    report_path = output_dir / "CURRENT336-source-proof-v21.json"
    write_new(report_path, report)
    return {"report": str(report_path), "sha256": report["sha256"],
            "cards": card_paths, "current_sha256": current_sha,
            "hdf5_opened": False, "bi4_opened": False, "qualification": dict(UNKNOWN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--v20-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scientific-audit", type=Path, required=True)
    parser.add_argument("--impact-proof", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.current, args.v20_dir, args.output_dir,
                       scientific_audit=args.scientific_audit, impact_proof=args.impact_proof)
    except (OSError, SourceProofV21Error, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
