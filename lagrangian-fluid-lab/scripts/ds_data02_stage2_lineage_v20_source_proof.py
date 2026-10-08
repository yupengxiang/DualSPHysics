#!/usr/bin/env python3
"""Rebind the seven development cards to one immutable CURRENT336 audit.

This is an additive, metadata-only proof index.  It verifies the canonical
SHA of the v19 audit and all seven cards, checks that all 336 links retain
their family/physical identity and explicit Run.out role, and records the
conservative split/qualification limits.  It never opens trajectory HDF5 or
Part_*.bi4 arrays and never turns metadata closure into QI/QN/QE evidence.

An optional F7 v4 request is checked as an independent source-bound request:
the dense SaveDt=.01 predecessor and full window must be present, while the
reference H5/XMF remain provenance-only.  The generated proof cards contain
source hashes and scope summaries rather than copying the large audit.
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
AUDIT_SCHEMA = "ds02.stage2.current336-effective-lineage.v19-source-closure"
PROOF_SCHEMA = "ds02.stage2.current336-source-proof.v20"
CARD_SCHEMA = "ds02.stage2.family-card.v20-source-proof"
MAX_JSON_BYTES = 32 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SourceProofError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items() if key != "sha256"}).encode()).hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise SourceProofError(f"missing JSON source: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise SourceProofError(f"JSON source exceeds bounded proof size: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceProofError(f"cannot read JSON source {target}: {error}") from error
    if not isinstance(value, dict):
        raise SourceProofError(f"JSON object required: {target}")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise SourceProofError(f"refusing to overwrite proof output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _unknown(value: Any) -> bool:
    return isinstance(value, Mapping) and dict(value) == UNKNOWN


def _contains_forbidden_selector(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False).lower()
    return any(token in text for token in ("latest glob", "glob(" , "rglob(", "hidden test"))


def _verify_embedded_sha(path: Path, payload: Mapping[str, Any], role: str) -> str:
    expected = payload.get("sha256")
    if not isinstance(expected, str) or not HEX64.fullmatch(expected):
        raise SourceProofError(f"{role} has no lowercase canonical SHA")
    actual = canonical_sha(payload)
    if actual != expected:
        raise SourceProofError(f"{role} embedded SHA differs")
    file_digest = file_sha256(path)
    return file_digest


def _verify_f7_request(path: Path) -> dict[str, Any]:
    request = read_json(path)
    if request.get("schema") != "ds02.stage2.external-solver-request.v4":
        raise SourceProofError("F7 proof request is not external-solver v4")
    if request.get("sha256") != canonical_sha(request):
        raise SourceProofError("F7 proof request canonical SHA differs")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False:
        raise SourceProofError("F7 proof request is not DEVELOPMENT/UNKNOWN/model-free")
    inputs = request.get("input_files")
    if not isinstance(inputs, list) or not inputs:
        raise SourceProofError("F7 proof request has no actionable source closure")
    if any(str(item).lower().endswith((".h5", ".xmf")) for item in inputs):
        raise SourceProofError("F7 provenance H5/XMF leaked into actionable input_files")
    provenance = request.get("provenance_reference_files")
    if not isinstance(provenance, list) or not {Path(str(item.get("path", ""))).suffix.lower() for item in provenance} >= {".h5", ".xmf"}:
        raise SourceProofError("F7 H5/XMF provenance references are incomplete")
    source = request.get("source_provenance")
    dense = source.get("dense_predecessor") if isinstance(source, Mapping) else None
    if not isinstance(dense, Mapping) or dense.get("save_interval_s") != 0.01 or dense.get("scientific_credit") != "NONE_CROPPED_TIMEOUT":
        raise SourceProofError("F7 dense predecessor credit/save cadence is not conservative")
    if request.get("source_provenance", {}).get("native_save_interval_s") != 0.01:
        raise SourceProofError("F7 v4 request is not SaveDt=.01")
    return {"path": str(path), "sha256": file_sha256(path), "input_count": len(inputs),
            "actionable_input_bytes": sum(Path(str(item)).stat().st_size for item in inputs),
            "provenance_reference_count": len(provenance), "native_save_interval_s": 0.01,
            "full_window_s": source.get("native_time_window_s"),
            "scientific_credit": dense.get("scientific_credit")}


def _verify_observer_profile(path: Path, current_sha: str) -> dict[str, Any]:
    """Bind the preregistered no-model observer contract without raw reads."""
    profile = read_json(path)
    if profile.get("schema") not in {"ds02.stage2.f2-s1-observer-profile.v14",
                                     "ds02.stage2.reference-observer-profile.v9"}:
        raise SourceProofError("observer profile schema is not a supported frozen development profile")
    if profile.get("sha256") != canonical_sha(profile):
        raise SourceProofError("observer profile canonical SHA differs")
    if profile.get("model_invoked") not in (None, False):
        raise SourceProofError("observer profile is not model-free")
    if profile.get("current_binding_sha256") != current_sha:
        source = profile.get("source_binding", {})
        if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != current_sha:
            raise SourceProofError("observer profile is bound to a different CURRENT336")
    status = str(profile.get("scientific_status", profile.get("quality_label_split", {}).get("status", "")))
    if "UNKNOWN" not in status and status != "DEVELOPMENT_ONLY":
        raise SourceProofError("observer profile overclaims scientific status")
    if profile.get("frozen_before_reference") is False:
        raise SourceProofError("observer profile was not frozen before reference result")
    budget = profile.get("scientific_error_budget", {})
    if not isinstance(budget, Mapping) or any(float(value) > 0.25 for value in budget.values()):
        raise SourceProofError("observer scientific budget exceeds preregistered one-quarter bound")
    names = profile.get("observable_names")
    if not isinstance(names, list) or not names:
        names = profile.get("observation_contract", {}).get("fixed_observation_names", [])
    if not isinstance(names, list) or not names:
        raise SourceProofError("observer profile has no fixed observation names")
    label_split = profile.get("quality_label_split", {})
    return {
        "path": str(path), "file_sha256": file_sha256(path),
        "embedded_sha256": profile["sha256"], "profile_id": profile.get("profile_id"),
        "schema": profile.get("schema"), "current_sha256": current_sha,
        "frozen_before_reference": profile.get("frozen_before_reference", profile.get("frozen", False)),
        "scientific_status": status, "query_times_s": profile.get("query_times_s", profile.get("observation_contract", {}).get("query_times_s")),
        "observable_names": names, "scientific_error_budget": dict(budget),
        "quality_label_states": label_split.get("first_passage_states", []),
        "qualification": dict(UNKNOWN), "raw_content_read": False,
    }


def build(current_path: Path | str, audit_dir: Path | str, output_dir: Path | str,
          *, f7_request: Path | str | None = None,
          observer_profile: Path | str | None = None) -> dict[str, Any]:
    current_path = Path(current_path).expanduser().resolve()
    audit_dir = Path(audit_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    current = read_json(current_path)
    if current.get("schema") != "ds02.stage2.current336.v1" or len(current.get("cases", [])) != 336:
        raise SourceProofError("CURRENT336 schema/count is not exact")
    current_sha = file_sha256(current_path)
    audit_path = audit_dir / "CURRENT336-effective-lineage-audit-v19-source-closure.json"
    audit = read_json(audit_path)
    if audit.get("schema") != AUDIT_SCHEMA or audit.get("qualification") != UNKNOWN:
        raise SourceProofError("base lineage audit is not v19 development/UNKNOWN")
    audit_file_sha = _verify_embedded_sha(audit_path, audit, "v19 audit")
    catalog_binding = audit.get("catalog_binding", {})
    if catalog_binding.get("catalog_case_count") != 336 or catalog_binding.get("current_json_sha256") != current_sha:
        raise SourceProofError("v19 audit is bound to a different CURRENT336")
    links = audit.get("case_source_links")
    if not isinstance(links, list) or len(links) != 336:
        raise SourceProofError("v19 audit does not contain exactly 336 source links")
    families = {family: [] for family in FAMILIES}
    indexes: set[int] = set()
    for link in links:
        if not isinstance(link, Mapping) or link.get("family_id") not in families:
            raise SourceProofError("case source link has an unknown family")
        index = link.get("case_index")
        if not isinstance(index, int) or index in indexes or not 0 <= index < 336:
            raise SourceProofError("case source link index is not a unique CURRENT index")
        indexes.add(index)
        if link.get("physical_case_id") != link.get("identity", {}).get("physical_case_id"):
            raise SourceProofError("source link physical identity is not preserved")
        if link.get("source_closure", {}).get("closure_status") != "CONTENT_PENDING_PARENT_GUARD":
            raise SourceProofError("source link is over-promoted beyond parent content guard")
        run_out = link.get("source_closure", {}).get("solver_run_out", {})
        if run_out.get("status") != "EXACT_EXPLICIT_RUN_OUT":
            raise SourceProofError("source link Run.out is not an explicit receipt/argv binding")
        families[str(link["family_id"])].append(link)
    if indexes != set(range(336)) or any(len(items) != 48 for items in families.values()):
        raise SourceProofError("family/source link cardinality differs from CURRENT336")
    if audit.get("read_scope", {}).get("hdf5_opened") is not False or audit.get("read_scope", {}).get("bi4_opened") is not False:
        raise SourceProofError("base audit claims a forbidden large-array read")
    cards: dict[str, dict[str, Any]] = {}
    card_proofs: dict[str, dict[str, Any]] = {}
    family_refs = audit.get("family_cards", {})
    if set(family_refs) != set(FAMILIES):
        raise SourceProofError("base audit does not reference all seven cards")
    for family in FAMILIES:
        ref = family_refs[family]
        card_path = (audit_dir / str(ref.get("path", ""))).resolve()
        try:
            card_path.relative_to(audit_dir)
        except ValueError as error:
            raise SourceProofError(f"{family} card path escapes audit directory") from error
        card = read_json(card_path)
        card_file_sha = _verify_embedded_sha(card_path, card, f"{family} card")
        if ref.get("sha256") != card.get("sha256") or card.get("case_count") != 48:
            raise SourceProofError(f"{family} card hash/count does not match audit")
        if card.get("qualification") != UNKNOWN or card.get("status") != "DEVELOPMENT_ONLY; PROVISIONAL; QUALIFICATION_UNKNOWN":
            raise SourceProofError(f"{family} card is not conservative development status")
        split = card.get("development_split", {})
        if split.get("split_safe") is not False:
            raise SourceProofError(f"{family} card overclaims split safety")
        raw = card.get("raw_anchor", {})
        selection = raw.get("plan", {}).get("selection_policy", {})
        if raw.get("hidden") is not False or selection.get("source") != "exact CURRENT336 row and physical_case_id predicate":
            raise SourceProofError(f"{family} raw anchor policy is not exact CURRENT-bound")
        if _contains_forbidden_selector(selection):
            raise SourceProofError(f"{family} raw anchor policy contains a banned selector")
        cards[family] = {"path": str(card_path), "sha256": card_file_sha,
                         "embedded_sha256": card["sha256"], "case_count": 48,
                         "split_safe": False, "qualification": dict(UNKNOWN)}
        card_proofs[family] = {
            "schema": CARD_SCHEMA, "family_id": family, "status": "DEVELOPMENT_ONLY; PROVISIONAL; QUALIFICATION_UNKNOWN",
            "qualification": dict(UNKNOWN), "base_card_path": str(card_path),
            "base_card_sha256": card["sha256"], "base_audit_sha256": audit["sha256"],
            "current_path": str(current_path), "current_sha256": current_sha,
            "source_link_count": len(families[family]),
            "source_closure": card.get("source_closure"),
            "physical_mechanism": card.get("physical_mechanism"),
            "effective_condition": card.get("effective_condition"),
            "task_subsets": card.get("task_subsets"),
            "observer_contract": card.get("observer_contract"),
            "raw_anchor_policy": {"hidden": False, "exact_current_row": True,
                                   "arbitrary_latest_or_glob": False, "split_safe": False},
            "unknown_scope": card.get("unknown_scope", []),
            "model_invoked": False, "cfd_invoked": False,
        }
        card_proofs[family]["sha256"] = canonical_sha(card_proofs[family])
    f7_binding = _verify_f7_request(Path(f7_request).expanduser().resolve()) if f7_request else None
    observer_binding = (_verify_observer_profile(Path(observer_profile).expanduser().resolve(), current_sha)
                        if observer_profile else None)
    report: dict[str, Any] = {
        "schema": PROOF_SCHEMA, "status": "DEVELOPMENT_SOURCE_PROOF_BOUND",
        "role": "DEVELOPMENT", "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "current_binding": {"path": str(current_path), "sha256": current_sha,
                             "schema": current.get("schema"), "case_count": 336,
                             "family_counts": {family: len(items) for family, items in families.items()}},
        "base_audit": {"path": str(audit_path), "file_sha256": audit_file_sha,
                        "embedded_sha256": audit["sha256"], "schema": audit["schema"]},
        "family_cards": cards, "family_card_proofs": {family: f"{family}-family-card-v20-source-proof.json" for family in FAMILIES},
        "read_scope": {"current_json_opened": True, "small_audit_and_cards_opened": True,
                        "hdf5_opened": False, "bi4_opened": False, "large_source_rehashed": False},
        "split_policy": {"prospective_only": True, "split_safe": False,
                          "unknown_recovery_window_transfer": True,
                          "numerical_resolution_not_physical_identity": True,
                          "cross_family_template_equivalence": "UNREVIEWED"},
        "f7_dense_request": f7_binding,
        "observer_profile": observer_binding,
        "limitations": [
            "This proof binds CURRENT and small source/audit evidence only; it does not prove raw trajectory content.",
            "Every family remains DEVELOPMENT_ONLY with QI/QN/QE UNKNOWN.",
            "Recovery, cross-resolution/window transfer, and prospective split safety remain UNKNOWN.",
            "Explicit Run.out paths are provenance roles; no neighboring/latest output is selected.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    for family, proof in card_proofs.items():
        write_new(output_dir / f"{family}-family-card-v20-source-proof.json", proof)
    report_path = output_dir / "CURRENT336-source-proof-v20.json"
    write_new(report_path, report)
    return {"report": str(report_path), "sha256": report["sha256"],
            "cards": {family: str(output_dir / f"{family}-family-card-v20-source-proof.json") for family in FAMILIES},
            "current_sha256": current_sha, "hdf5_opened": False, "qualification": dict(UNKNOWN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--f7-request", type=Path)
    parser.add_argument("--observer-profile", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build(args.current, args.audit_dir, args.output_dir, f7_request=args.f7_request,
                       observer_profile=args.observer_profile)
    except (OSError, SourceProofError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
