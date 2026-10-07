#!/usr/bin/env python3
"""Build substantive, conservative v16 domain cards from the 336 audit.

This is a metadata-only lineage pass.  It reads the immutable v15 small-source
closure request and the seven v13 family cards, never HDF5/BI4 content.  It
reports the actual source-role coverage per family and carries the observed
finite numeric support into seven new provisional cards.  A family card is
usable for planning and observer selection only; it never claims physical
equivalence, prospective split safety, recovery support, or QI/QN/QE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.current336-provisional-domain-audit.v16"
CARD_SCHEMA = "ds02.stage2.family-card.v16-provisional"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{index}" for index in range(1, 8))

MECHANISMS = {
    "F1": {
        "physical_mechanism": "eccentric lower-head / fallback gravity release",
        "candidate_observations": ["fluid mass/COM evolution", "obstacle interaction and free-surface response"],
    },
    "F2": {
        "physical_mechanism": "offset open-rim cup with prescribed rotation and spill/receiver interaction",
        "candidate_observations": ["finite receiver volume/aperture arrival", "mass-weighted front, flux and first-passage status"],
    },
    "F3": {
        "physical_mechanism": "two-axis acceleration / sloshing response",
        "candidate_observations": ["surface/COM motion", "forced-response timing and velocity/energy summaries"],
    },
    "F4": {
        "physical_mechanism": "finite drop impact into a pool",
        "candidate_observations": ["impact timing", "finite-region mass/front response"],
    },
    "F5": {
        "physical_mechanism": "compact runup with recovery and time/amplitude forcing",
        "candidate_observations": ["runup height/front", "recovery time and mass distribution"],
    },
    "F6": {
        "physical_mechanism": "angular rigid-body release with fluid/rigid coupling",
        "candidate_observations": ["fluid mass/COM response", "pose and linear/angular velocity only with explicit rigid telemetry"],
    },
    "F7": {
        "physical_mechanism": "quintic obstacle target with explicit wet base",
        "candidate_observations": ["obstacle/target interaction", "finite-region mass/front and arrival status"],
    },
}

ROLE_CATEGORIES = {
    "control": ("case:control_asset", "case:gencase_receipt", "case:solver_receipt"),
    "geometry": ("case:gencase_definition", "case:generated_xml", "case:manifest"),
    "initial_condition": ("case:owner_metadata", "case:manifest"),
    "solver_execution": ("case:solver_receipt", "case:run_out"),
}


class LineageV16Error(ValueError):
    """Raised when the source audit cannot support a conservative v16 card."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text())
    if not isinstance(value, dict):
        raise LineageV16Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise LineageV16Error(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _role_case_coverage(audit: Mapping[str, Any], family: str,
                        family_indices: set[int]) -> dict[str, Any]:
    rows = audit.get("input_roles")
    if not isinstance(rows, list):
        raise LineageV16Error("v15 input_roles is required")
    covered: dict[str, set[int]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("role"), str):
            continue
        case_indices = row.get("case_indices", [])
        if not isinstance(case_indices, list):
            continue
        overlap = family_indices.intersection(index for index in case_indices if isinstance(index, int))
        if overlap:
            role = str(row["role"])
            covered.setdefault(role, set()).update(overlap)
    return {role: len(indices) for role, indices in covered.items()}


def _card(v13: Mapping[str, Any], family: str, case_indices: list[int],
          role_counts: Mapping[str, int], *, output_root: Path) -> dict[str, Any]:
    support = v13.get("observed_support")
    if not isinstance(support, Mapping):
        raise LineageV16Error(f"v13 observed_support missing for {family}")
    mechanisms = MECHANISMS[family]
    case_count = len(case_indices)
    coverage: dict[str, Any] = {}
    for category, roles in ROLE_CATEGORIES.items():
        role_values = {role: int(role_counts.get(role, 0)) for role in roles}
        coverage[category] = {
            "case_count": case_count,
            "role_case_coverage": role_values,
            "all_cases_have_any_declared_role": any(value == case_count for value in role_values.values()),
            "semantic_interpretation": "source role coverage only; parsed source semantics still require per-case review",
        }
    card = {
        "schema": CARD_SCHEMA,
        "status": "PROVISIONAL_DOMAIN_CARD; QUALIFICATION_UNKNOWN",
        "family_id": family,
        "case_count": case_count,
        "case_indices": case_indices,
        "mechanism": mechanisms["physical_mechanism"],
        "candidate_observations": [
            {"name": value, "status": "candidate_development_observer_requires_source_bound_geometry_control"}
            for value in mechanisms["candidate_observations"]
        ],
        "source_role_coverage": coverage,
        "observed_finite_support": {
            "numeric_parameter_values": support.get("numeric_parameter_values", {}),
            "frame_counts": support.get("frame_counts", []),
            "time_window_range_s": support.get("time_window_range_s"),
            "particle_count_range": support.get("particle_count_range"),
            "resolution_dp_values": support.get("resolution_dp_values", []),
            "support_policy": "observed values only; no interpolation/extrapolation or cross-resolution equivalence",
        },
        "effective_condition": {
            "status": "PROVISIONAL_SOURCE_BOUND_CONDITION_CATEGORIES",
            "physical_condition": "owner/manifest/XML values are retained; validity outside listed support is UNKNOWN",
            "control": "receipt/XML/control assets are counted; control-family equivalence and acceleration/motion semantics require per-case review",
            "geometry": "definition/generated XML/manifest roles are counted; closed/open/destination equivalence is UNKNOWN",
            "initial_state": "owner/manifest source roles are counted; typed cohort and body/support mass semantics require exact case binding",
            "parameter_support": "finite observed support only",
            "resolution": "observed dp/header support only; resolution transfer is UNKNOWN",
            "window": "CURRENT frame/time support only; window comparability is UNKNOWN",
            "recovery": "no recovery equivalence inferred from receipt presence",
        },
        "lineage_and_split": {
            "conservative_group": f"family:{family}",
            "physical_condition_key": "provisional observed XML/control/initial categories; numerical/case/owner hashes are provenance",
            "shared_spectrum_or_template_links": "UNKNOWN_PENDING_SEMANTIC_CLOSURE",
            "recovery_resolution_window_group": "DEVELOPMENT_UNKNOWN",
            "split_safe": False,
            "split_status": "PROVISIONAL_ONLY; family group is not leakage-safe",
            "reason": "common control/template/physical-condition links and source semantics are not proven independent across cases",
        },
        "evidence_index": "CURRENT336-effective-lineage-audit-v16-provisional.json",
        "qualification": UNKNOWN,
        "unknown_scope": [
            "native raw-to-typed reconstruction and per-frame comparisons",
            "receiver/opening/destination semantics unless a source-bound geometry task proves them",
            "recovery/restart equivalence, cross-resolution transfer, and prospective split safety",
            "reference-result validity and QI/QN/QE",
        ],
    }
    card["sha256"] = canonical_sha(card)
    return card


def build(audit_path: Path | str, cards_root: Path | str, output_dir: Path | str) -> dict[str, Any]:
    audit_file = Path(audit_path).expanduser().resolve()
    card_root = Path(cards_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    audit = _load(audit_file)
    if audit.get("catalog_binding", {}).get("catalog_case_count") != 336:
        raise LineageV16Error("source audit is not the exact 336-case closure")
    links = audit.get("case_source_links")
    if not isinstance(links, list) or len(links) != 336:
        raise LineageV16Error("source audit must contain all 336 case links")
    family_indices: dict[str, list[int]] = {family: [] for family in FAMILIES}
    for link in links:
        if not isinstance(link, Mapping) or link.get("family_id") not in family_indices:
            raise LineageV16Error("case source link has an unknown family")
        family_indices[str(link["family_id"])].append(int(link["case_index"]))
    if any(len(values) != 48 for values in family_indices.values()):
        raise LineageV16Error(f"expected 48 cases per family: {family_indices}")

    cards: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        v13_path = card_root / "lineage" / "v13" / f"{family}-family-card-v13.json"
        v13 = _load(v13_path)
        counts = _role_case_coverage(audit, family, set(family_indices[family]))
        cards[family] = _card(v13, family, sorted(family_indices[family]), counts, output_root=output)

    report = {
        "schema": SCHEMA,
        "status": "PROVISIONAL_336_DOMAIN_CATEGORIES; SEMANTIC_CLOSURE_PENDING; QUALIFICATION_UNKNOWN",
        "audit_scope": {
            "case_count": 336,
            "family_case_counts": {family: len(values) for family, values in family_indices.items()},
            "source_audit": {
                "path": _relative(audit_file, output),
                "sha256": sha256_file(audit_file),
                "status": audit.get("status"),
            },
            "hdf5_or_bi4_read": False,
            "small_source_metadata_only": True,
        },
        "domain_categories": {
            "physical_condition": "provisional owner/manifest/XML numeric condition categories; finite support only",
            "control": "receipt/XML/control asset presence and declared signatures; effective motion/acceleration equivalence UNKNOWN",
            "geometry": "definition/generated XML/manifest source coverage; open/closed/receiver destination semantics UNKNOWN",
            "initial_state": "owner/manifest source coverage; exact type/MK/cohort/mass provenance remains case-bound",
            "parameter_support": "per-family finite observed numeric values; no validity envelope inferred",
            "resolution": "per-family observed dp/header values; no transfer equivalence",
            "recovery": "receipt presence does not prove restart/recovery equivalence; UNKNOWN",
            "window": "CURRENT frame/time windows retained; cross-window comparability UNKNOWN",
        },
        "split_policy": {
            "default_group": "family:F1..F7 conservative connected groups",
            "split_safe": False,
            "prospective_split_rule": "require source-supported physical/control/template/geometry condition closure and hold out complete connected components",
            "opaque_owner_or_case_hashes": "provenance only; never define physical identity",
        },
        "cards": {family: {
            "path": f"{family}-family-card-v16-provisional.json",
            "sha256": card["sha256"],
            "status": card["status"],
        } for family, card in cards.items()},
        "qualification": UNKNOWN,
        "limitations": [
            "This report reconciles source-role coverage and observed finite support; it is not a raw replay or scientific result.",
            "All seven cards remain development/provisional and split_safe=false.",
            "Unknown source semantics are preserved rather than collapsed into equivalence classes.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    output.mkdir(parents=True, exist_ok=False)
    report_path = output / "CURRENT336-effective-lineage-audit-v16-provisional.json"
    _write_new(report_path, report)
    for family, card in cards.items():
        _write_new(output / f"{family}-family-card-v16-provisional.json", card)
    return {"report": str(report_path), "cards": len(cards), "sha256": report["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-v15", type=Path, required=True)
    parser.add_argument("--cards-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.audit_v15, args.cards_root, args.output_dir)
    except (OSError, json.JSONDecodeError, LineageV16Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
