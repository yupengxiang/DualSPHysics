#!/usr/bin/env python3
"""Build a conservative, evidence-bound v24 index for all seven families.

This is a metadata-only forward index.  It joins the immutable v23 family
cards, v14 raw-anchor plans, the v23 access/rights index, and the v13 reader
dependency index.  It records an effective physical split contract, replay
readiness, and rights/dependency gaps without inferring physical equivalence
or qualification.  QI/QN/QE and every unresolved control, geometry,
recovery, or window relation remain ``UNKNOWN``.

Only bounded JSON metadata and small evidence files are opened.  No HDF5,
BI4, raw array, JSONL, or solver output is read.  Existing cards and indexes
are never rewritten; each output is a new v24 file.
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
CARD_SCHEMA = "ds02.stage2.family-card.v24-effective-source-proof"
INDEX_SCHEMA = "ds02.stage2.seven-family-effective-split-rights-index.v24"
V23_SCHEMA = "ds02.stage2.seven-family-source-access-index.v23"
PLAN_SCHEMA = "ds02.stage2.family-raw-anchor-plan.v1"
LICENSE_INDEX_SCHEMA = "ds02.stage2.reader-dependency-license-index.v13"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_HASH_BYTES = 2 * 1024 * 1024


class FamilyCardV24Error(ValueError):
    """A malformed or over-promoted source-only family input."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({k: v for k, v in value.items()
                                     if k != "sha256"}).encode()).hexdigest()


def sha256_file(path: Path, *, maximum: int | None = None) -> str:
    if not path.is_file() or path.is_symlink():
        raise FamilyCardV24Error(f"expected a regular non-symlink file: {path}")
    if maximum is not None and path.stat().st_size > maximum:
        raise FamilyCardV24Error(f"file exceeds bounded hash limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, *, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise FamilyCardV24Error(f"missing JSON metadata: {target}")
    if target.stat().st_size > maximum:
        raise FamilyCardV24Error(f"JSON metadata exceeds bounded limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FamilyCardV24Error(f"cannot read JSON metadata {target}: {error}") from error
    if not isinstance(value, dict):
        raise FamilyCardV24Error(f"JSON object required: {target}")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FamilyCardV24Error(f"refusing to overwrite v24 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise FamilyCardV24Error(f"{role} is not a lowercase SHA-256")
    return value


def _path_from_repo(repo_root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise FamilyCardV24Error("repository-relative path is missing")
    path = Path(value).expanduser()
    return path if path.is_absolute() else repo_root / path


def _small_evidence_binding(item: Mapping[str, Any], *, repo_root: Path,
                            family: str) -> tuple[dict[str, Any], list[str]]:
    path_value = item.get("path")
    if not isinstance(path_value, str) or not path_value.startswith("/"):
        raise FamilyCardV24Error(f"{family} evidence path is not absolute")
    expected = _sha(item.get("sha256"), f"{family}.{item.get('id')}.sha256")
    path = Path(path_value).expanduser()
    result = {
        "id": item.get("id"), "path": str(path), "declared_sha256": expected,
        "declared_status": item.get("status"), "scope": item.get("scope"),
        "provenance_only_external_root": item.get("provenance_only_external_root") is True,
        "qualification": dict(UNKNOWN),
    }
    gaps: list[str] = []
    if not path.is_file() or path.is_symlink():
        result["availability"] = "MISSING_AT_BUILD_STAT_ONLY"
        gaps.append(f"evidence_missing:{item.get('id')}")
    else:
        stat = path.stat()
        result["observed_bytes"] = int(stat.st_size)
        if stat.st_size <= MAX_EVIDENCE_HASH_BYTES:
            observed = sha256_file(path, maximum=MAX_EVIDENCE_HASH_BYTES)
            result["observed_sha256"] = observed
            result["sha_match"] = observed == expected
            result["availability"] = "PRESENT_AND_HASHED"
            if observed != expected:
                gaps.append(f"evidence_sha_mismatch:{item.get('id')}")
        else:
            result["availability"] = "PRESENT_STAT_ONLY_BOUNDED_HASH_DEFERRED"
            gaps.append(f"evidence_hash_deferred:{item.get('id')}")
    return result, gaps


def _verify_conservative_card(card: Mapping[str, Any], family: str) -> None:
    if card.get("schema") != "ds02.stage2.family-card.v23-source-proof":
        raise FamilyCardV24Error(f"{family} is not a v23 source-proof card")
    if card.get("family_id") != family or card.get("case_count") != 48:
        raise FamilyCardV24Error(f"{family} card family/count differs")
    if card.get("sha256") != canonical_sha(card):
        raise FamilyCardV24Error(f"{family} v23 card canonical SHA differs")
    if card.get("qualification") != UNKNOWN:
        raise FamilyCardV24Error(f"{family} card overclaims qualification")
    split = card.get("development_split")
    if not isinstance(split, Mapping) or split.get("split_safe") is not False:
        raise FamilyCardV24Error(f"{family} card does not preserve split_safe=false")
    if card.get("model_invoked") is not False or card.get("cfd_invoked") is not False:
        raise FamilyCardV24Error(f"{family} card is not model/CFD-free")
    if "UNKNOWN" not in str(card.get("status", "")):
        raise FamilyCardV24Error(f"{family} card status is not conservative")


def _plan_summary(plan: Mapping[str, Any], family: str, *, repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("family_id") != family:
        raise FamilyCardV24Error(f"{family} raw-anchor plan schema/family differs")
    if plan.get("case_count") != 48 or plan.get("qualification") != UNKNOWN:
        raise FamilyCardV24Error(f"{family} raw-anchor plan is not 48/UNKNOWN")
    if plan.get("cfd_invoked") is not False or plan.get("model_invoked") is not False:
        raise FamilyCardV24Error(f"{family} raw-anchor plan invokes CFD/model")
    anchor = plan.get("anchor_case")
    raw = plan.get("raw_anchor")
    if not isinstance(anchor, Mapping) or not isinstance(raw, Mapping):
        raise FamilyCardV24Error(f"{family} raw-anchor metadata is incomplete")
    current_index = anchor.get("current_index")
    if not isinstance(current_index, int) or not 0 <= current_index < 336:
        raise FamilyCardV24Error(f"{family} anchor CURRENT index is invalid")
    raw_root = raw.get("raw_root")
    if not isinstance(raw_root, str) or not raw_root.startswith("/"):
        raise FamilyCardV24Error(f"{family} raw root is not an explicit absolute path")
    gaps = [
        "raw_to_typed_execution_requires_parent_guard",
        "raw_pre_post_content_sha_is_not_available_to_this_source_only_build",
    ]
    if raw.get("raw_root_exists") is not True:
        gaps.append("declared_raw_root_not_proven_present")
    actual_exists = Path(raw_root).expanduser().is_dir()
    if not actual_exists:
        gaps.append("raw_root_missing_at_build")
    summary = {
        "plan_path": None,
        "plan_schema": plan.get("schema"),
        "status": plan.get("status"),
        "parent_guard_required": True,
        "raw_read_status": "NONE_BY_THIS_BUILD",
        "anchor_current_index": current_index,
        "physical_case_id": anchor.get("physical_case_id"),
        "runtime_case_alias": anchor.get("runtime_case_alias"),
        "frame_count_expected": raw.get("frame_count_expected"),
        "actual_time_window_s": anchor.get("actual_time_window_s"),
        "particle_count_declared": anchor.get("particles"),
        "raw_root": raw_root,
        "raw_root_declared_exists": raw.get("raw_root_exists"),
        "raw_root_stat_exists": actual_exists,
        "required_source_arrays": list(raw.get("required_source_arrays", [])),
        "content_sha_policy": raw.get("content_sha_policy"),
        "selection_policy": dict(plan.get("selection_policy", {})),
        "typed_comparison_contract": dict(plan.get("typed_comparison_contract", {})),
        "plan_unknown_scope": list(plan.get("unknown_scope", [])),
    }
    return summary, gaps


def _rights_dependency(index: Mapping[str, Any], *, repo_root: Path,
                       dependency_path: Path) -> tuple[dict[str, Any], list[str]]:
    deps = index.get("dependencies_and_licenses")
    if not isinstance(deps, Mapping):
        raise FamilyCardV24Error("v23 dependency/license index is missing")
    gaps: list[str] = []
    reader = deps.get("reader_dependency_license_index_v13")
    reader_path = None
    if isinstance(reader, Mapping):
        reader_path = _path_from_repo(repo_root, reader.get("repo_relative_path"))
        reader_sha = _sha(reader.get("sha256"), "reader dependency index SHA")
    else:
        raise FamilyCardV24Error("v13 reader dependency index binding is missing")
    reader_result: dict[str, Any] = {
        "path": str(reader_path), "declared_sha256": reader_sha,
        "schema": LICENSE_INDEX_SCHEMA, "availability": "MISSING_AT_BUILD_STAT_ONLY",
    }
    if reader_path.is_file() and not reader_path.is_symlink():
        reader_result["observed_bytes"] = reader_path.stat().st_size
        if reader_path.stat().st_size <= MAX_JSON_BYTES:
            reader_value = read_json(reader_path)
            if reader_value.get("schema") != LICENSE_INDEX_SCHEMA:
                raise FamilyCardV24Error("reader dependency index schema differs")
            # v13's embedded digest is the historical digest of its
            # canonicalized producer record; the v23 access index carries
            # the actual file SHA used for this join.  Do not reinterpret
            # the former as a canonical digest for the latter.
            observed = sha256_file(reader_path, maximum=MAX_JSON_BYTES)
            reader_result.update({"availability": "PRESENT_AND_HASHED",
                                  "observed_sha256": observed,
                                  "sha_match": observed == reader_sha})
            if observed != reader_sha:
                gaps.append("reader_dependency_index_sha_mismatch")
    else:
        gaps.append("reader_dependency_index_missing")

    license_spec = deps.get("repository_license")
    license_path = _path_from_repo(repo_root, license_spec.get("repo_relative_path")) if isinstance(license_spec, Mapping) else None
    license_result: dict[str, Any] = {"path": str(license_path) if license_path else None,
                                      "declared_sha256": license_spec.get("sha256") if isinstance(license_spec, Mapping) else None,
                                      "status": "REPOSITORY_LICENSE_ONLY"}
    if license_path is None or not license_path.is_file():
        gaps.append("repository_license_missing")
    else:
        license_result["observed_bytes"] = license_path.stat().st_size
        license_result["observed_sha256"] = sha256_file(license_path, maximum=MAX_JSON_BYTES)
        if license_result["declared_sha256"] != license_result["observed_sha256"]:
            gaps.append("repository_license_sha_mismatch")

    official = deps.get("official_solver_library")
    official_root = official.get("root") if isinstance(official, Mapping) else None
    official_result = {"root": official_root, "binding": official.get("binding") if isinstance(official, Mapping) else None,
                       "status": "CONTENT_NOT_READ_BY_SOURCE_ONLY_BUILD"}
    if not isinstance(official_root, str) or not Path(official_root).expanduser().is_dir():
        gaps.append("official_solver_library_root_missing")

    interpreter = deps.get("runtime_interpreter")
    interpreter_result = dict(interpreter) if isinstance(interpreter, Mapping) else {"status": "MISSING"}
    interpreter_result["status"] = "PINNED_ENVIRONMENT_EXCEPTION_CONTENT_NOT_READ"
    gaps.append("pinned_interpreter_ABI_and_third_party_runtime_require_guarded_smoke")

    result = {
        "reader_dependency_license_index_v13": reader_result,
        "repository_license": license_result,
        "official_solver_library": official_result,
        "runtime_interpreter": interpreter_result,
        "access_policy": {
            "exact_paths_only": True,
            "original_path_fallback": "REJECT",
            "parent_guard_required_for_raw_or_H5_content": True,
            "redistribution": "NOT_GRANTED_BY_THIS_INDEX",
        },
        "scientific_rights_status": "DEVELOPMENT_REPOSITORY_ACCESS_INDEX_ONLY",
    }
    return result, gaps


def build(*, stage2_root: Path | str, output_dir: Path | str,
          access_index: Path | str | None = None,
          cards_dir: Path | str | None = None,
          plans_dir: Path | str | None = None,
          dependency_index: Path | str | None = None,
          repo_root: Path | str | None = None) -> dict[str, Any]:
    stage2 = Path(stage2_root).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    repository = Path(repo_root).expanduser().resolve() if repo_root else stage2.parents[3]
    access = Path(access_index).expanduser().resolve() if access_index else stage2 / "lineage/v23-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V23.json"
    cards = Path(cards_dir).expanduser().resolve() if cards_dir else stage2 / "lineage/v23-source-proof"
    plans = Path(plans_dir).expanduser().resolve() if plans_dir else stage2 / "lineage/v14/raw-anchor-plans"
    dep = Path(dependency_index).expanduser().resolve() if dependency_index else stage2 / "replay/v13/READER_DEPENDENCY_LICENSE_INDEX_v13.json"

    source_index = read_json(access)
    if source_index.get("schema") != V23_SCHEMA or source_index.get("qualification") != UNKNOWN:
        raise FamilyCardV24Error("v23 source access index is not conservative")
    if source_index.get("sha256") != canonical_sha(source_index):
        raise FamilyCardV24Error("v23 source access index canonical SHA differs")
    current = source_index.get("current_binding")
    if not isinstance(current, Mapping) or current.get("case_count") != 336:
        raise FamilyCardV24Error("v23 CURRENT binding is incomplete")
    current_sha = _sha(current.get("sha256"), "CURRENT336 declared SHA")
    dep_value = read_json(dep)
    if dep_value.get("schema") != LICENSE_INDEX_SCHEMA:
        raise FamilyCardV24Error("v13 reader dependency index schema differs")
    rights, rights_gaps = _rights_dependency(source_index, repo_root=repository, dependency_path=dep)

    family_cards: dict[str, dict[str, Any]] = {}
    card_values: dict[str, dict[str, Any]] = {}
    all_gaps: dict[str, list[str]] = {}
    plans_by_family: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        card_path = cards / f"{family}-family-card-v23-source-proof.json"
        card = read_json(card_path)
        _verify_conservative_card(card, family)
        plan_path = plans / f"{family}-raw-anchor-plan-v1.json"
        plan = read_json(plan_path)
        plan_summary, plan_gaps = _plan_summary(plan, family, repo_root=repository)
        plan_summary["plan_path"] = str(plan_path)
        plans_by_family[family] = plan_summary

        evidence: list[dict[str, Any]] = []
        gaps = list(plan_gaps) + list(rights_gaps)
        for item in card.get("evidence", []):
            if not isinstance(item, Mapping):
                raise FamilyCardV24Error(f"{family} evidence entry is not an object")
            bound, evidence_gaps = _small_evidence_binding(item, repo_root=repository, family=family)
            evidence.append(bound)
            gaps.extend(evidence_gaps)

        # A card's declared split and source closure are deliberately carried
        # forward, then made executable as an explicit *unsafe* split plan.
        split = card.get("development_split", {})
        effective_split = {
            "split_safe": False,
            "method": split.get("grouping"),
            "source_supported_components_only": True,
            "anchor_current_index": plan_summary["anchor_current_index"],
            "physical_case_id": plan_summary["physical_case_id"],
            "identity_key": plan.get("typed_comparison_contract", {}).get("identity_key"),
            "held_out_dimensions": {
                "control": "UNKNOWN_UNLESS_EACH_SOURCE_BOUND",
                "geometry": "UNKNOWN_UNLESS_EXACT_ASSET_BOUND",
                "recovery": "UNKNOWN",
                "window": "UNKNOWN",
                "resolution": "VARIATION_NOT_PHYSICAL_IDENTITY",
                "continuous_transfer": "UNKNOWN",
            },
            "owner_case_hashes_are_identity": False,
            "claim_boundary": "development_source_split_only; no qualification or leakage safety",
        }
        replay = {
            "raw_anchor_plan": str(plan_path),
            "raw_anchor_plan_sha256": sha256_file(plan_path, maximum=MAX_JSON_BYTES),
            "status": "PARENT_GUARD_REQUIRED",
            "source_selection": plan.get("selection_policy", {}).get("source"),
            "run_out_policy": plan.get("source_bindings", [{}])[-1].get("role") if plan.get("source_bindings") else None,
            "family_specific_replay_request": "NONE_BOUND_IN_V23_INDEX",
            "portable_credit": "NOT_CLAIMED",
            "no_original_path_fallback": True,
        }
        if family == "F2":
            replay["family_specific_replay_request"] = "F2 native raw-to-typed evidence only; portable replay pending"
        if family == "F7":
            replay["family_specific_replay_request"] = "F7 initial-QA/request-builder evidence only; solver replay pending"

        gaps.extend([
            "qualification_QI_QN_QE_UNKNOWN",
            "prospective_split_safety_UNKNOWN",
            "semantic_control_geometry_recovery_window_closure_PENDING",
        ])
        # Stable ordering keeps the generated cards reproducible and makes a
        # gap review straightforward.
        gaps = sorted(set(str(item) for item in gaps))
        value: dict[str, Any] = {
            "schema": CARD_SCHEMA,
            "status": "DEVELOPMENT_ONLY; SOURCE_BOUND; QUALIFICATION_UNKNOWN",
            "role": "DEVELOPMENT_SOURCE_INDEX",
            "family_id": family,
            "case_count": 48,
            "qualification": dict(UNKNOWN),
            "model_invoked": False,
            "cfd_invoked": False,
            "source_card": {
                "path": str(card_path), "file_sha256": sha256_file(card_path, maximum=MAX_JSON_BYTES),
                "embedded_sha256": card["sha256"], "schema": card["schema"],
            },
            "current_binding": {
                "repo_relative_path": current.get("repo_relative_path"),
                "sha256": current_sha, "case_count": 336,
                "selection": current.get("selection"),
                "anchor_current_index": plan_summary["anchor_current_index"],
                "physical_case_id": plan_summary["physical_case_id"],
            },
            "effective_physical_split": effective_split,
            "raw_anchor": plan_summary,
            "evidence": evidence,
            "rights_and_dependencies": rights,
            "replay_delivery": replay,
            "task_subsets": card.get("task_subsets", []),
            "observer_contract": card.get("observer_contract", []),
            "unknown_scope": sorted(set(list(card.get("unknown_scope", [])) + [
                "rights and redistribution scope is repository/environment metadata only",
                "raw content, H5/BI4 arrays, and solver outputs were not opened",
            ])),
            "gaps": gaps,
            "read_scope": {
                "card_json_opened": True, "raw_plan_json_opened": True,
                "source_access_index_opened": True, "dependency_index_opened": True,
                "evidence_large_json_opened": False, "hdf5_opened": False,
                "bi4_opened": False, "raw_arrays_opened": False,
                "jsonl_opened": False, "solver_output_opened": False,
            },
        }
        value["sha256"] = canonical_sha(value)
        card_out = out / f"{family}-family-card-v24-effective-source-proof.json"
        write_new(card_out, value)
        family_cards[family] = {
            "path": str(card_out), "file_sha256": sha256_file(card_out, maximum=MAX_JSON_BYTES),
            "embedded_sha256": value["sha256"], "case_count": 48,
            "split_safe": False, "qualification": dict(UNKNOWN),
            "gap_count": len(gaps),
        }
        card_values[family] = value
        all_gaps[family] = gaps

    report: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "status": "DEVELOPMENT_SOURCE_BOUND_INDEX_ONLY",
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "current_binding": {
            "repo_relative_path": current.get("repo_relative_path"),
            "sha256": current_sha, "case_count": 336,
            "family_counts": {family: 48 for family in FAMILIES},
            "selection": current.get("selection"),
        },
        "versioned_from": {
            "path": str(access), "file_sha256": sha256_file(access, maximum=MAX_JSON_BYTES),
            "embedded_sha256": source_index["sha256"], "immutable": True,
        },
        "family_cards": family_cards,
        "effective_physical_split": {
            "split_safe": False, "family_count": 7,
            "unknown_control_geometry_recovery_window": True,
            "owner_hashes_not_identity": True,
            "qualification": dict(UNKNOWN),
        },
        "rights_and_dependencies": rights,
        "replay_delivery": {
            "families": plans_by_family,
            "all_parent_guard_required": True,
            "raw_read_status": "NONE_BY_THIS_BUILD",
            "portable_credit": "NOT_CLAIMED",
        },
        "gaps_by_family": all_gaps,
        "read_scope": {
            "v23_cards_opened": True, "v14_raw_plans_opened": True,
            "dependency_index_opened": True, "license_stat_or_hash_only": True,
            "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
            "jsonl_opened": False, "solver_output_opened": False,
        },
        "limitations": [
            "All seven cards remain DEVELOPMENT_ONLY with QI/QN/QE UNKNOWN.",
            "split_safe remains false; no physical equivalence or leakage safety is inferred.",
            "Raw anchor plans are source-bound plans and still require a parent guard.",
            "Rights/dependency records describe repository/environment access only; redistribution is not granted.",
            "Missing or mismatched evidence is retained as an explicit gap and never promoted.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    index_out = out / "SEVEN_FAMILY_EFFECTIVE_SPLIT_RIGHTS_INDEX_V24.json"
    write_new(index_out, report)
    return {
        "index": str(index_out), "index_sha256": sha256_file(index_out, maximum=MAX_JSON_BYTES),
        "cards": {family: entry["path"] for family, entry in family_cards.items()},
        "gaps_by_family": all_gaps,
        "qualification": dict(UNKNOWN),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--access-index", type=Path)
    parser.add_argument("--cards-dir", type=Path)
    parser.add_argument("--plans-dir", type=Path)
    parser.add_argument("--dependency-index", type=Path)
    parser.add_argument("--repo-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build(stage2_root=args.stage2_root, output_dir=args.output_dir,
                       access_index=args.access_index, cards_dir=args.cards_dir,
                       plans_dir=args.plans_dir, dependency_index=args.dependency_index,
                       repo_root=args.repo_root)
    except (FamilyCardV24Error, OSError, ValueError) as error:
        print(f"family cards v24: {error}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
