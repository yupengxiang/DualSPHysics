#!/usr/bin/env python3
"""Fresh195 F5 metadata-only storage cleanup audit.

This audit reads F5 JSON receipts, selected small text logs, and the current
F5 census metadata.  It uses directory entries and stat sizes for payload
files, but never opens, hashes, copies, or deletes BI4/H5/CSV/DAT/VTK/PNG
payloads.  Every deletion item is a parent-review candidate; this script
never declares a deletion safe and never changes shared state.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
F5_WORKTREE_HANDOFF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003"
)
INTEGRATION_HANDOFF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003"
)
CENSUS = F5_WORKTREE_HANDOFF / "root_followup_169_f5_full48_authoritative_census_v1/metadata/fresh169-census.json"

SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".vtu", ".png", ".gif", ".partial"}
SAFE_LOG_NAMES = {"stdout.log", "stderr.log", "Run.out"}
PACKAGE_NAME = "root_followup_195_f5_cleanup_audit_v1"


# These six entries are deliberately narrow review items.  The four one-frame
# solver attempts failed before the second saved frame, but their sole
# Part_0000 is the first/last diagnostic frame and is retained.  The two
# compact geometry checks have reports/logs and no current C082S1-48-row
# membership, but their raw CSVs remain protected because the recovery/source
# references have not been retired.  There is therefore no immediate delete
# candidate in this package.
CANDIDATE_SPECS = [
    {
        "id": "failed_solver_runup_coarse_055",
        "attempt_token": "root-compact-equilibrium-runup_coarse-full801-native-055",
        "case_id": "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050",
        "class": "failed_one_frame_solver",
        "expected_frames": 801,
        "delete_scope": "none_now; retain_the_sole_Part_0000_first_last_diagnostic_frame_and_all_receipt_provenance",
        "reason": "returncode 1; log says the solver reached only Part_0000 and could not open relative assets/f5_compact_packet_motion.dat; no current C082S1 48-row stage membership",
    },
    {
        "id": "failed_solver_runup_medium_055",
        "attempt_token": "root-compact-equilibrium-runup_medium-full801-native-055",
        "case_id": "F5_REF_RUNUP_DP0125_EQUILIBRIUM_ROOT050",
        "class": "failed_one_frame_solver",
        "expected_frames": 801,
        "delete_scope": "none_now; retain_the_sole_Part_0000_first_last_diagnostic_frame_and_all_receipt_provenance",
        "reason": "returncode 1; log says the solver reached only Part_0000 and could not open relative assets/f5_compact_packet_motion.dat; no current C082S1 48-row stage membership",
    },
    {
        "id": "failed_solver_weir_coarse_055",
        "attempt_token": "root-compact-equilibrium-weir_coarse-full801-native-055",
        "case_id": "F5_REF_WEIR_DP020_EQUILIBRIUM_ROOT053",
        "class": "failed_one_frame_solver",
        "expected_frames": 801,
        "delete_scope": "none_now; retain_the_sole_Part_0000_first_last_diagnostic_frame_and_all_receipt_provenance",
        "reason": "returncode 1; log says the solver reached only Part_0000 and could not open relative assets/f5_compact_packet_motion.dat; no current C082S1 48-row stage membership",
    },
    {
        "id": "failed_solver_a061_short_091",
        "attempt_token": "root-stage1-f5-explicit-bed-repair-a-short-event-native-091",
        "case_id": "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061",
        "class": "failed_one_frame_solver",
        "expected_frames": 51,
        "delete_scope": "none_now; retain_the_sole_Part_0000_first_last_diagnostic_frame_and_all_receipt_provenance",
        "reason": "returncode 1; short solver reached only Part_0000 and could not open relative assets/f5_compact_packet_motion.dat; the separate A061 093/131/typed negative chain is protected",
    },
    {
        "id": "compact_geometry_qa_052_payload",
        "attempt_token": "root-compact-equilibrium-two-mechanism-three-dp-full-native-geometry-qa-052",
        "case_id": "F5_COMPACT_EQUILIBRIUM_ACTUAL_COARSE_GEOMETRY_QA",
        "class": "historical_compact_geometry_csv",
        "expected_frames": None,
        "delete_scope": "none_now; retain_CSVs_until_parent_retires_all_recovery_and_source_references",
        "reason": "failed geometry QA is outside the current C082S1 48-row collection, but its CSVs remain recovery/source evidence and have historical request/binding references; report records the weir-solid overlap negative",
    },
    {
        "id": "compact_runup_geometry_qa_049_payload",
        "attempt_token": "root-compact-equilibrium-runup-coarse-full-native-geometry-qa-049",
        "case_id": "F5_COMPACT_EQUILIBRIUM_ACTUAL_COARSE_GEOMETRY_QA",
        "class": "historical_compact_geometry_csv",
        "expected_frames": None,
        "delete_scope": "none_now; retain_CSV_until_parent_retires_all_recovery_and_source_references",
        "reason": "failed geometry QA is outside the current C082S1 48-row collection, but its CSV remains recovery/source evidence and has historical request/binding references; report records below-bed/outside-bounds evidence",
    },
]


# These are explicit hold items.  Their failure or negative result is itself
# part of the F5 root-cause/recovery record, so a Q-N or precision failure is
# not treated as an erasure criterion.
PROTECTED_SPECS = [
    {
        "id": "a061_dynamic_penetration_negative",
        "attempt_tokens": [
            "root-stage1-f5-explicit-bed-repair-a-short-event-native-093",
            "root-stage1-f5-short51-actual-framewise-bed-audit-131",
            "root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065",
            "root-stage1-f5-short51-normal-dynamic-129",
        ],
        "reason": "A061 is the first genuine repaired-bed short event and its 131 report is the historical severe penetration negative; keep the native/typed/XMF evidence and receipts.",
    },
    {
        "id": "b071_dynamic_penetration_negative",
        "attempt_tokens": [
            "root-stage1-f5-b071-genuine-gencase-163",
            "root-stage1-f5-b071-initial-qa-output-root-binding-repair-175",
            "root-stage1-f5-b071-native-bed-marker-mapping-repair-185",
            "root-stage1-f5-b071-short-native-qualification-187",
            "root-stage1-f5-b071-short-native-typed-nvme-189",
            "root-stage1-f5-b071-short-native-xmf-190",
            "root-stage1-f5-b071-short-native-bed-audit-binding-repair-201",
        ],
        "reason": "B071 has the second genuine short dynamic bed failure (framewise 1DP/2DP penetration); its reports are direct historical evidence for rejecting the geometric repair. Keep its payload and metadata until Root explicitly archives it.",
    },
    {
        "id": "a061_initial_qa_negative",
        "attempt_tokens": [
            "root-stage1-f5-explicit-bed-repair-a-native-qa-081",
            "root-stage1-f5-explicit-bed-repair-a-native-qa-082",
        ],
        "reason": "A061 initial QA failures document the pre-dynamic support/identity diagnosis and remain part of the A/B repair history; not safe to infer uselessness from status=failed.",
    },
    {
        "id": "c082r1_precision_and_geometry_negative",
        "attempt_tokens": [
            "root-stage1-f5-c082r1-actual-native-initial-qa-zero-count-schema-repair-246",
            "root-stage1-f5-c082r1-voidfill-actual-native-initial-qa-292",
            "root-stage1-f5-c082r1-official-void-fill-genuine-gencase-265",
        ],
        "reason": "C082R1 records the exact-DP-lattice precision negative and the void-fill unique-Y=12 versus required 15 geometry negative; reports are required to explain why the recovery moved to C082S1.",
    },
    {
        "id": "c082s1_precision_negative",
        "attempt_tokens": [
            "root-stage1-f5-c082s1-solid-fluid-recovery-actual-initial-qa-306-actual-audit312",
            "root-stage1-f5-c082s1-solid-fluid-recovery-actual-initial-qa-306-actual-audit312-particlecsv314",
            "root-stage1-f5-c082s1-actual-perfluid-rounding-occupancy-diagnostic-264",
        ],
        "reason": "C082S1 placement succeeded but the exact DP-lattice residual exceeded the unchanged 1e-6 diagnostic threshold; this numerical negative is explicitly retained and is not a cleanup reason.",
    },
    {
        "id": "c082_thick_bed_geometry_negative",
        "attempt_tokens": ["root-stage1-f5-c082-analytic-thick-bed-genuine-gencase-208"],
        "reason": "The thick-bed fallback changed the producer population and failed its expected-fluid assertion; its generated geometry is the evidence that prevented an unsupported fallback claim.",
    },
    {
        "id": "a080_a120_terminated_render_provenance",
        "attempt_tokens": [
            "root-stage1-f5-c082s1-A080-full801-native-render-590-root610",
            "root-stage1-f5-c082s1-A120-full801-native-render-590-root610",
        ],
        "reason": "Root610 ended with SIGTERM/partial PNGs and is referenced by the later Root635 replacement/census; retain the failed-render provenance and do not delete merely because a successor exists.",
    },
    {
        "id": "failed_typed_preflight_no_payload",
        "attempt_tokens": ["root-stage1-f5-c082s1-m085_t080-full801-typed-nvme-127-root751"],
        "reason": "Root751 failed at the NumPy/h5py ABI import before science payload access and has no H5; it has negligible metadata-only size and is retained as failure provenance rather than proposed as a storage cleanup target.",
    },
]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def request_of(receipt: dict[str, Any]) -> dict[str, Any]:
    value = receipt.get("request")
    return value if isinstance(value, dict) else {}


def attempt_id_of(receipt: dict[str, Any], path: Path) -> str:
    req = request_of(receipt)
    return str(receipt.get("attempt_id") or req.get("attempt_id") or path.parent.name)


def case_id_of(receipt: dict[str, Any]) -> str | None:
    req = request_of(receipt)
    value = receipt.get("case_id") or req.get("case_id")
    return str(value) if value is not None else None


def output_root_of(receipt_path: Path, receipt: dict[str, Any]) -> Path:
    req = request_of(receipt)
    value = receipt.get("output_root") or req.get("output_root") or req.get("attempt_root")
    if value is None:
        return receipt_path.parent
    result = Path(str(value))
    return result if result.is_absolute() else receipt_path.parent / result


def status_of(receipt: dict[str, Any]) -> tuple[Any, Any]:
    return receipt.get("status"), receipt.get("returncode", receipt.get("return_code"))


def pid_snapshot(pid: Any) -> dict[str, Any]:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return {"pid": pid, "alive": False, "fd_count": None}
    proc = Path("/proc") / str(value)
    if not proc.exists():
        return {"pid": value, "alive": False, "fd_count": 0}
    try:
        fd_count = len(list((proc / "fd").iterdir()))
    except OSError:
        fd_count = None
    return {"pid": value, "alive": True, "fd_count": fd_count}


def stat_tree(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.exists(),
        "directory": path.is_dir(),
        "directory_bytes": None,
        "file_count": 0,
        "suffix_counts": {},
        "suffix_bytes": {},
        "payload_files": [],
    }
    if not path.exists():
        return result
    suffix_counts: collections.Counter[str] = collections.Counter()
    suffix_bytes: collections.Counter[str] = collections.Counter()
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            file_path = Path(root) / name
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            total += size
            result["file_count"] += 1
            suffix = file_path.suffix.lower()
            suffix_counts[suffix] += 1
            suffix_bytes[suffix] += size
            if suffix in SCIENCE_SUFFIXES:
                result["payload_files"].append(
                    {"path": str(file_path), "bytes": size, "suffix": suffix}
                )
    result["directory_bytes"] = total
    result["suffix_counts"] = dict(sorted(suffix_counts.items()))
    result["suffix_bytes"] = dict(sorted(suffix_bytes.items()))
    result["payload_files"].sort(key=lambda item: item["path"])
    return result


def read_log_evidence(receipt_path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in sorted(SAFE_LOG_NAMES):
        path = receipt_path.parent / name
        if not path.is_file() or path.stat().st_size > 200_000:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        matches = []
        for index, line in enumerate(lines, 1):
            if re.search(
                r"(?i)(error|fail|exception|assert|cannot open|terminated|signal|traceback|valueerror|keyerror|nameerror|residual|below|penetr)",
                line,
            ):
                matches.append({"line": index, "text": line[:800]})
        if matches:
            result.append({"file": str(path), "matches": matches[-12:]})
    return result


def receipt_paths() -> list[Path]:
    return sorted(DATA_ROOT.rglob("execution-receipt.json"))


def scan_reference_paths(token: str, own_receipt: Path) -> list[str]:
    """Search metadata JSON only; no payload suffix is opened or hashed."""
    roots = [DATA_ROOT, F5_WORKTREE_HANDOFF, INTEGRATION_HANDOFF]
    paths: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            if path == own_receipt:
                continue
            # Avoid self-referential output if this audit is run twice.
            if PACKAGE_NAME in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError):
                continue
            if token in text:
                paths.add(str(path))
    return sorted(paths)


def split_reference_paths(paths: list[str]) -> dict[str, list[str]]:
    return {
        "execution_receipt_paths": sorted(
            path for path in paths if path.endswith("/execution-receipt.json")
        ),
        "other_metadata_paths": sorted(
            path for path in paths if not path.endswith("/execution-receipt.json")
        ),
    }


def load_receipts() -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, str]]]:
    valid: list[tuple[Path, dict[str, Any]]] = []
    invalid: list[dict[str, str]] = []
    for path in receipt_paths():
        try:
            value = load_json(path)
            if not isinstance(value, dict):
                raise ValueError("receipt JSON is not an object")
            valid.append((path, value))
        except Exception as exc:  # metadata integrity only
            invalid.append({"receipt": str(path), "error": repr(exc)})
    return valid, invalid


def resolve_attempt(
    spec: dict[str, Any], receipts: list[tuple[Path, dict[str, Any]]]
) -> dict[str, Any]:
    matches = [
        (path, receipt)
        for path, receipt in receipts
        if attempt_id_of(receipt, path) == spec["attempt_token"]
    ]
    result = {**spec, "found": bool(matches), "matches": []}
    for path, receipt in matches:
        req = request_of(receipt)
        status, returncode = status_of(receipt)
        output_root = output_root_of(path, receipt)
        pid = receipt.get("pid") or req.get("pid")
        tree = stat_tree(output_root)
        references = scan_reference_paths(spec["attempt_token"], path)
        result["matches"].append(
            {
                "receipt": str(path),
                "attempt_id": attempt_id_of(receipt, path),
                "case_id": case_id_of(receipt),
                "status": status,
                "returncode": returncode,
                "kind": receipt.get("kind") or req.get("kind"),
                "cpu_task_kind": receipt.get("cpu_task_kind") or req.get("cpu_task_kind"),
                "pid": pid,
                "pid_snapshot": pid_snapshot(pid),
                "output_root": str(output_root),
                "expected_frames": spec.get("expected_frames"),
                "directory": tree,
                "log_evidence": read_log_evidence(path),
                "metadata_reference_paths": references,
                "reference_summary": split_reference_paths(references),
            }
        )
    return result


def resolve_protected(
    spec: dict[str, Any], receipts: list[tuple[Path, dict[str, Any]]]
) -> dict[str, Any]:
    result = {**spec, "matches": []}
    for token in spec["attempt_tokens"]:
        token_matches = [
            (path, receipt)
            for path, receipt in receipts
            if attempt_id_of(receipt, path) == token
        ]
        for path, receipt in token_matches:
            req = request_of(receipt)
            status, returncode = status_of(receipt)
            output_root = output_root_of(path, receipt)
            references = scan_reference_paths(token, path)
            result["matches"].append(
                {
                    "attempt_token": token,
                    "receipt": str(path),
                    "status": status,
                    "returncode": returncode,
                    "case_id": case_id_of(receipt),
                    "output_root": str(output_root),
                    "directory": stat_tree(output_root),
                    "metadata_reference_paths": references,
                    "reference_summary": split_reference_paths(references),
                }
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "metadata" / "fresh195-audit-report.json",
    )
    args = parser.parse_args()

    receipts, bad_json = load_receipts()
    status_counts: collections.Counter[str] = collections.Counter()
    current_running: list[dict[str, Any]] = []
    for path, receipt in receipts:
        status, returncode = status_of(receipt)
        status_counts[f"{status}/{returncode}"] += 1
        if status == "running":
            req = request_of(receipt)
            current_running.append(
                {
                    "attempt_id": attempt_id_of(receipt, path),
                    "case_id": case_id_of(receipt),
                    "receipt": str(path),
                    "pid": receipt.get("pid") or req.get("pid"),
                    "output_root": str(output_root_of(path, receipt)),
                    "pid_snapshot": pid_snapshot(receipt.get("pid") or req.get("pid")),
                }
            )

    census = None
    if CENSUS.is_file():
        raw_census = load_json(CENSUS)
        if isinstance(raw_census, dict):
            rows = raw_census.get("rows") if isinstance(raw_census.get("rows"), list) else []
            census = {
                "source": str(CENSUS),
                "schema": raw_census.get("schema"),
                "row_count": len(rows),
                "physical_case_ids": [row.get("physical_case_id") for row in rows if isinstance(row, dict)],
                "stage_completion_counts": raw_census.get("stage_completion_counts"),
                "scientific_payload_read_or_hashed_by_source_agent": raw_census.get(
                    "scientific_payload_read_or_hashed_by_source_agent"
                ),
            }

    try:
        ledger = load_json(LEDGER)
    except Exception as exc:
        ledger = {"read_error": repr(exc)}

    f5_attempts = []
    if isinstance(ledger, dict):
        raw_attempts = ledger.get("attempts", {})
        values = list(raw_attempts.values()) if isinstance(raw_attempts, dict) else list(raw_attempts or [])
        f5_attempts = [
            {
                key: value.get(key)
                for key in (
                    "id",
                    "kind",
                    "status",
                    "started_at_utc",
                    "finished_at_utc",
                    "pid",
                    "controller_pid",
                    "reservation_id",
                )
                if key in value
            }
            for value in values
            if isinstance(value, dict) and str(value.get("id", "")).startswith("F5/")
        ]

    try:
        sv = os.statvfs("/home/jade")
        home_free = sv.f_bavail * sv.f_frsize
    except OSError:
        home_free = None

    candidate_results = [resolve_attempt(spec, receipts) for spec in CANDIDATE_SPECS]
    protected_results = [resolve_protected(spec, receipts) for spec in PROTECTED_SPECS]

    report = {
        "schema": "ds02.f5.cleanup-audit.v2",
        "audit_at_utc": now_utc(),
        "scope": {
            "family": "F5",
            "data_root": str(DATA_ROOT),
            "read_json_receipts": True,
            "read_small_logs": True,
            "stat_directory_entries_and_payload_sizes": True,
            "read_science_payload_bytes": False,
            "hash_science_payload": False,
            "copy_science_payload": False,
            "delete_anything": False,
            "launch_anything": False,
            "modify_shared_state": False,
            "recursive_delegation": False,
        },
        "filesystem": {
            "home_path": "/home/jade",
            "home_free_bytes_at_audit": home_free,
            "ledger_home_min_free_bytes": ledger.get("limits", {}).get("home_min_free_bytes")
            if isinstance(ledger, dict)
            else None,
        },
        "receipt_inventory": {
            "receipt_count": len(receipt_paths()),
            "valid_json_receipt_count": len(receipts),
            "bad_json_receipts": bad_json,
            "status_counts": dict(sorted(status_counts.items())),
            "current_running": current_running,
        },
        "current_336_stage_membership_evidence": census,
        "ledger_metadata_snapshot": {
            "schema": ledger.get("schema") if isinstance(ledger, dict) else None,
            "campaign_id": ledger.get("campaign_id") if isinstance(ledger, dict) else None,
            "deadline_utc": ledger.get("deadline_utc") if isinstance(ledger, dict) else None,
            "f5_attempts": f5_attempts,
        },
        "cleanup_candidates": candidate_results,
        "protected_negative_or_recovery_evidence": protected_results,
        "decision": {
            "safe_to_delete_now": False,
            "immediate_deletion_candidates": [],
            "review_only_candidate_ids": [spec["id"] for spec in CANDIDATE_SPECS],
            "candidate_scope": "This package identifies review items only. No F5 payload is approved for deletion. If Root later authorizes cleanup, preserve the sole first/last diagnostic frame for each one-frame failure and all receipt/log/report/provenance files.",
            "why_not_qn_only": "A061/B071 dynamic penetration, C082R1/C082S1 precision and geometry negatives, and changed-bed comparisons are retained because they explain the recovery decisions. A failed receipt alone does not make a payload disposable.",
            "parent_actions_before_cleanup": [
                "freeze and reread the shared ledger/controller state",
                "verify candidate PID/fd state and absence of downstream references after this audit",
                "archive each receipt, stdout/Run.out, report and provenance JSON",
                "approve exact payload paths only; do not remove evidence files",
                "rerun fresh195 after any parent-controlled removal",
            ],
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "receipt_count": len(receipts),
                "status_counts": dict(sorted(status_counts.items())),
                "candidate_count": len(candidate_results),
                "protected_group_count": len(protected_results),
                "safe_to_delete_now": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
