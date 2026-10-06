#!/usr/bin/env python3
"""Fresh162 F5 storage audit.

Metadata-only: reads JSON receipts/ledger and small text logs, and uses directory
entry/stat information. It never opens BI4/H5/CSV/DAT/VTK/PNG science payloads,
does not hash or delete files, and does not launch work.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
HOME = Path("/home/jade")

# Each item is a review candidate only. The audit never removes any of them.
CANDIDATE_SPECS = [
    {
        "id": "failed_solver_runup_coarse_055",
        "attempt_token": "root-compact-equilibrium-runup_coarse-full801-native-055",
        "category": "partial_solver_output",
        "expected_saved_frames": 801,
        "reason": "solver reached only initial Part_0000 then failed opening relative assets/f5_compact_packet_motion.dat",
        "recommendation": "payload_only_after_root_freeze",
    },
    {
        "id": "failed_solver_runup_medium_055",
        "attempt_token": "root-compact-equilibrium-runup_medium-full801-native-055",
        "category": "partial_solver_output",
        "expected_saved_frames": 801,
        "reason": "solver reached only initial Part_0000 then failed opening relative assets/f5_compact_packet_motion.dat",
        "recommendation": "payload_only_after_root_freeze",
    },
    {
        "id": "failed_solver_weir_coarse_055",
        "attempt_token": "root-compact-equilibrium-weir_coarse-full801-native-055",
        "category": "partial_solver_output",
        "expected_saved_frames": 801,
        "reason": "solver reached only initial Part_0000 then failed opening relative assets/f5_compact_packet_motion.dat",
        "recommendation": "payload_only_after_root_freeze",
    },
    {
        "id": "failed_solver_a061_short_091",
        "attempt_token": "root-stage1-f5-explicit-bed-repair-a-short-event-native-091",
        "category": "partial_solver_output",
        "expected_saved_frames": 51,
        "reason": "short solver reached only initial Part_0000 then failed opening relative assets/f5_compact_packet_motion.dat",
        "recommendation": "payload_only_after_root_freeze",
    },
    {
        "id": "terminated_render_a080_610",
        "attempt_token": "root-stage1-f5-c082s1-A080-full801-native-render-590-root610",
        "category": "incomplete_render_output",
        "expected_saved_frames": 801,
        "reason": "returncode -15; historical Root634 review attributes termination to reserved CPU budget, later Root635/793 replacement exists",
        "recommendation": "render_payload_after_root_freeze",
    },
    {
        "id": "terminated_render_a120_610",
        "attempt_token": "root-stage1-f5-c082s1-A120-full801-native-render-590-root610",
        "category": "incomplete_render_output",
        "expected_saved_frames": 801,
        "reason": "returncode -15; historical Root634 review attributes termination to reserved CPU budget, later replacement exists",
        "recommendation": "render_payload_after_root_freeze",
    },
    {
        "id": "failed_typed_a080_751",
        "attempt_token": "root-stage1-f5-c082s1-m085_t080-full801-typed-nvme-127-root751",
        "category": "failed_preflight_no_science_output",
        "expected_saved_frames": 801,
        "reason": "NumPy/h5py ABI import failure before scientific payload access; replacement Root753 completed",
        "recommendation": "attempt_directory_after_root_freeze",
    },
]

# Negative evidence is kept by default. The raw CSVs are intentionally listed
# for a parent-controlled, receipt/report-preserving decision, never auto-cleaned.
NEGATIVE_SPECS = [
    {
        "id": "compact_geometry_qa_052",
        "attempt_token": "root-compact-equilibrium-two-mechanism-three-dp-full-native-geometry-qa-052",
        "reason": "physical_geometry_pass false (weir_coarse native fluid inside weir solid=240); reports are historical geometry evidence",
        "recommendation": "retain_receipt_reports; parent_may_review_payload_after_archive",
    },
    {
        "id": "compact_runup_geometry_qa_049",
        "attempt_token": "root-compact-equilibrium-runup-coarse-full-native-geometry-qa-049",
        "reason": "physical_geometry_pass false; runup_coarse below continuous bed=10860 and outside initial bounds=300",
        "recommendation": "retain_receipt_reports; parent_may_review_payload_after_archive",
    },
    {
        "id": "a061_qa_081",
        "attempt_token": "root-stage1-f5-explicit-bed-repair-a-native-qa-081",
        "reason": "historical A061 initial QA failure; preserve alongside A061 repair evidence",
        "recommendation": "retain_negative_evidence",
    },
    {
        "id": "a061_qa_082",
        "attempt_token": "root-stage1-f5-explicit-bed-repair-a-native-qa-082",
        "reason": "historical A061 initial QA failure; preserve alongside A061 repair evidence",
        "recommendation": "retain_negative_evidence",
    },
    {
        "id": "c082r1_qa_246",
        "attempt_token": "root-stage1-f5-c082r1-actual-native-initial-qa-zero-count-schema-repair-246",
        "reason": "C082R1 exact-DP-lattice/initial QA negative evidence; numerical precision negative is not a cleanup criterion",
        "recommendation": "retain_negative_evidence",
    },
    {
        "id": "c082r1_qa_292",
        "attempt_token": "root-stage1-f5-c082r1-voidfill-actual-native-initial-qa-292",
        "reason": "C082R1 void-fill physical geometry failed uniqueY=12 versus required 15",
        "recommendation": "retain_negative_evidence",
    },
    {
        "id": "c082s1_qa_314",
        "attempt_token": "root-stage1-f5-c082s1-solid-fluid-recovery-actual-initial-qa-306-actual-audit312-particlecsv314",
        "reason": "C082S1 exact-DP-lattice residual negative; placement evidence is historical and must not be relabeled",
        "recommendation": "retain_negative_evidence",
    },
    {
        "id": "c082_initial_gencase_208",
        "attempt_token": "root-stage1-f5-c082-analytic-thick-bed-genuine-gencase-208",
        "reason": "thick-bed GenCase wrapper assertion expected fluid count versus actual producer count; preserve changed-geometry evidence",
        "recommendation": "retain_receipt_reports; parent_may_review_payload_after_archive",
    },
]

# The audit protects all completed/unknown outputs by default. These named
# patterns are additionally protected even when a downstream job is pending.
PROTECTED_PATTERNS = [
    "root-stage1-f5-c082s1-m085_t080-full801-native-qualification-125-root738",
    "root-stage1-f5-c082s1-m085_t080-full801-typed-nvme-127-root753",
    "root-stage1-f5-m085-t100-actual854-full801-N3-XMF-root953",
    "root-stage1-f5-m085-t100-actual953-full801-Mk50-bed-original138-root956",
    "root-stage1-f5-m085-t100-actual956-full801-grounded116-NVMe-hard2GiB-root960",
    "root-stage1-f5-next34-m086_t085-own848849-full801-native-root850",
    "root-stage1-f5-next34-m086_t085-own850-full801-typed-nvme-root864",
    "root-stage1-f5-m086-t085-actual864-full801-N3-XMF-root963",
    "root-stage1-f5-c082s1-m095_t080-genuine-gencase-118-root640",
    "root-stage1-f5-c082s1-m095_t080-actual-initial-placement-mk50-119-root661",
    "root-stage1-f5-c082s1-m095_t080-full801-native-release-131-root808",
    "root-stage1-f5-m095_t080-actual808-full801-typed157-NVMe4GiB-root939",
    "root-stage1-f5-next34-m095_t080-own824-genuine-gencase-root848",
    "root-stage1-f5-next34-m095_t080-own848-initial-placement-mk50-root849",
]

SAFE_TEXT_NAMES = {"stdout.log", "stderr.log", "Run.out"}
SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".png"}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def receipt_paths() -> list[Path]:
    # Find names only; receipt content is read individually below.
    p = subprocess.run(
        ["find", str(DATA_ROOT), "-type", "f", "-name", "execution-receipt.json", "-print"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(s) for s in p.stdout.splitlines() if s]


def request_of(receipt: dict[str, Any]) -> dict[str, Any]:
    return receipt.get("request") if isinstance(receipt.get("request"), dict) else {}


def attempt_id_of(receipt: dict[str, Any], path: Path) -> str:
    req = request_of(receipt)
    return str(receipt.get("attempt_id") or req.get("attempt_id") or path.parent.name)


def case_id_of(receipt: dict[str, Any]) -> str | None:
    req = request_of(receipt)
    value = receipt.get("case_id") or req.get("case_id")
    return str(value) if value is not None else None


def status_of(receipt: dict[str, Any]) -> tuple[str | None, Any]:
    return receipt.get("status"), receipt.get("returncode", receipt.get("return_code"))


def du_bytes(path: Path) -> int | None:
    try:
        p = subprocess.run(["du", "-sb", str(path)], check=True, capture_output=True, text=True)
        return int(p.stdout.split()[0])
    except (OSError, ValueError, subprocess.CalledProcessError, IndexError):
        return None


def stat_tree(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.exists(),
        "du_bytes": du_bytes(path) if path.exists() else None,
        "file_count": 0,
        "suffix_counts": {},
        "suffix_bytes": {},
        "bi4_names": [],
        "frame_png_names": [],
        "all_frame_png_names": [],
    }
    if not path.is_dir():
        return result
    counts: collections.Counter[str] = collections.Counter()
    sizes: collections.Counter[str] = collections.Counter()
    for root, _dirs, files in os.walk(path):
        for name in files:
            p = Path(root) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            result["file_count"] += 1
            suffix = p.suffix.lower()
            counts[suffix] += 1
            sizes[suffix] += size
            rel = str(p.relative_to(path))
            if name.endswith(".bi4") and name.startswith("Part_"):
                result["bi4_names"].append({"path": rel, "bytes": size})
            if name.startswith("frame_") and name.endswith(".png"):
                result["frame_png_names"].append({"path": rel, "bytes": size})
            if name.startswith("all_frames_") and name.endswith(".png"):
                result["all_frame_png_names"].append({"path": rel, "bytes": size})
    result["suffix_counts"] = dict(sorted(counts.items()))
    result["suffix_bytes"] = dict(sorted(sizes.items()))
    result["bi4_names"].sort(key=lambda x: x["path"])
    result["frame_png_names"].sort(key=lambda x: x["path"])
    result["all_frame_png_names"].sort(key=lambda x: x["path"])
    return result


def output_root_of(receipt_path: Path, receipt: dict[str, Any]) -> Path:
    req = request_of(receipt)
    value = receipt.get("output_root") or req.get("output_root") or req.get("attempt_root")
    if value:
        value_path = Path(str(value))
        if not value_path.is_absolute():
            value_path = receipt_path.parent / value_path
        return value_path
    return receipt_path.parent


def safe_log_evidence(receipt_path: Path) -> list[dict[str, Any]]:
    """Read only small text logs, never science suffixes."""
    out: list[dict[str, Any]] = []
    for name in SAFE_TEXT_NAMES:
        p = receipt_path.parent / name
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
            if size > 200_000:
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        matches = []
        for i, line in enumerate(lines, 1):
            if re.search(r"(?i)(error|fail|exception|assert|cannot open|terminated|signal|traceback|valueerror|keyerror|nameerror|residual|assets/)", line):
                matches.append({"line": i, "text": line[:800]})
        if matches:
            out.append({"file": str(p), "matches": matches[-8:]})
    return out


def pid_snapshot(pid: Any) -> dict[str, Any]:
    try:
        n = int(pid)
    except (TypeError, ValueError):
        return {"pid": pid, "alive": False, "fd_count": None}
    proc = Path("/proc") / str(n)
    if not proc.exists():
        return {"pid": n, "alive": False, "fd_count": 0}
    try:
        fd_count = len(list((proc / "fd").iterdir()))
    except OSError:
        fd_count = None
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")[:400]
    except OSError:
        cmdline = None
    return {"pid": n, "alive": True, "fd_count": fd_count, "cmdline": cmdline}


def find_by_token(paths: list[Path], token: str) -> list[Path]:
    return [p for p in paths if token in str(p)]


def compact_receipt(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    req = request_of(receipt)
    status, rc = status_of(receipt)
    return {
        "receipt": str(path),
        "attempt_id": attempt_id_of(receipt, path),
        "case_id": case_id_of(receipt),
        "status": status,
        "returncode": rc,
        "kind": receipt.get("kind") or req.get("kind"),
        "cpu_task_kind": receipt.get("cpu_task_kind") or req.get("cpu_task_kind"),
        "pid": receipt.get("pid") or req.get("pid"),
        "output_root": str(output_root_of(path, receipt)),
        "depends_on_attempts": req.get("depends_on_attempts"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=Path(__file__).resolve().parents[1] / "metadata" / "fresh162-audit-report.json")
    args = ap.parse_args()

    paths = receipt_paths()
    receipts: list[tuple[Path, dict[str, Any]]] = []
    bad_json: list[dict[str, str]] = []
    for path in paths:
        try:
            receipts.append((path, load_json(path)))
        except Exception as exc:  # metadata integrity issue, not a science read
            bad_json.append({"receipt": str(path), "error": repr(exc)})

    status_counts: collections.Counter[str] = collections.Counter()
    for path, receipt in receipts:
        status, rc = status_of(receipt)
        status_counts[f"{status}/{rc}"] += 1

    # All receipt JSON is metadata. This reference scan does not inspect any
    # BI4/H5/CSV/DAT/VTK/PNG content.
    serialized_receipts = [(p, json.dumps(r, ensure_ascii=False, sort_keys=True)) for p, r in receipts]

    def resolve_spec(spec: dict[str, Any]) -> dict[str, Any]:
        matches = [(p, r) for p, r in receipts if spec["attempt_token"] == attempt_id_of(r, p)]
        if not matches:
            return {**spec, "found": False, "matches": []}
        entries = []
        for rp, r in matches:
            req = request_of(r)
            root = output_root_of(rp, r)
            status, rc = status_of(r)
            pid = r.get("pid") or req.get("pid")
            refs = [str(op) for op, text in serialized_receipts if op != rp and spec["attempt_token"] in text]
            item = {
                "found": True,
                "receipt": str(rp),
                "attempt_id": attempt_id_of(r, rp),
                "case_id": case_id_of(r),
                "status": status,
                "returncode": rc,
                "kind": r.get("kind") or req.get("kind"),
                "pid": pid,
                "pid_snapshot": pid_snapshot(pid) if pid is not None else {"pid": None, "alive": False, "fd_count": 0},
                "output_root": str(root),
                "tree_stat": stat_tree(root),
                "depends_on_attempts": req.get("depends_on_attempts"),
                "downstream_receipt_references": refs,
                "log_evidence": safe_log_evidence(rp),
            }
            # Exact expected/observed frame summary for parent review.
            item["expected_saved_frames"] = spec.get("expected_saved_frames")
            item["observed_part_count"] = len(item["tree_stat"]["bi4_names"])
            item["observed_frame_png_count"] = len(item["tree_stat"]["frame_png_names"])
            entries.append(item)
        return {**spec, "found": True, "matches": entries}

    candidates = [resolve_spec(s) for s in CANDIDATE_SPECS]
    negatives = [resolve_spec(s) for s in NEGATIVE_SPECS]

    protected: list[dict[str, Any]] = []
    for token in PROTECTED_PATTERNS:
        matches = [(p, r) for p, r in receipts if token in attempt_id_of(r, p)]
        protected.append({
            "token": token,
            "matches": [compact_receipt(p, r) for p, r in matches],
        })

    # Resource ledger is metadata only. Keep only F5 entries and the active
    # reservations; do not copy charges or any scientific payload references.
    ledger: dict[str, Any] = load_json(LEDGER)
    attempts = ledger.get("attempts", {})
    attempt_values = list(attempts.values()) if isinstance(attempts, dict) else list(attempts)
    f5_attempts = [v for v in attempt_values if str(v.get("id", "")).startswith("F5/")]
    ledger_counts = collections.Counter((v.get("kind"), v.get("status")) for v in f5_attempts)
    f5_failed_ledger = [
        {k: v.get(k) for k in ("id", "kind", "status", "started_at_utc", "finished_at_utc", "pid", "controller_pid", "reservation_id")}
        for v in f5_attempts if v.get("status") == "failed"
    ]
    reservations = [
        {k: v.get(k) for k in ("id", "kind", "cpu_task_kind", "cpu_threads", "cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "reserved_at_utc", "launcher_pid")}
        for v in ledger.get("reservations", [])
        if str(v.get("id", "")).startswith("F5/")
    ]
    try:
        sv = os.statvfs(HOME)
        home_free = sv.f_bavail * sv.f_frsize
    except OSError:
        home_free = None

    report = {
        "schema": "ds02.f5.storage-audit.v1",
        "audit_at_utc": now_utc(),
        "scope": {
            "family": "F5",
            "data_root": str(DATA_ROOT),
            "ledger": str(LEDGER),
            "read_json_receipts": True,
            "read_small_logs": True,
            "stat_directory_and_file_names": True,
            "read_science_payload_bytes": False,
            "hash_science_payload": False,
            "delete_anything": False,
            "launch_anything": False,
            "modify_shared_state": False,
        },
        "filesystem": {
            "home_path": str(HOME),
            "home_free_bytes_at_audit": home_free,
            "ledger_home_min_free_bytes": ledger.get("limits", {}).get("home_min_free_bytes"),
        },
        "receipt_inventory": {
            "receipt_count": len(paths),
            "valid_json_receipt_count": len(receipts),
            "bad_json_receipts": bad_json,
            "status_counts": dict(sorted(status_counts.items())),
            "failed_receipt_count": sum(v for k, v in status_counts.items() if k.startswith("failed/")),
            "running_receipt_count": sum(v for k, v in status_counts.items() if k.startswith("running/")),
            "terminal_completed_zero_count": status_counts.get("completed/0", 0),
            "all_failed_receipts": [compact_receipt(p, r) for p, r in receipts if status_of(r)[0] == "failed"],
        },
        "ledger_snapshot": {
            "schema": ledger.get("schema"),
            "campaign_id": ledger.get("campaign_id"),
            "deadline_utc": ledger.get("deadline_utc"),
            "limits": ledger.get("limits"),
            "f5_attempt_counts_by_kind_status": {f"{k[0]}/{k[1]}": n for k, n in sorted(ledger_counts.items())},
            "f5_failed_attempts": f5_failed_ledger,
            "f5_production_attempt_count": sum(1 for v in f5_attempts if v.get("kind") == "production"),
            "f5_reservations": reservations,
        },
        "cleanup_review_candidates": candidates,
        "negative_evidence_to_retain": negatives,
        "protected_current_and_accepted_scope": {
            "named_patterns": protected,
            "rules": [
                "Protect every completed/0 receipt and its output tree by default.",
                "Protect status-unknown receipts (completed or failed without returncode) until Root reconciles them.",
                "Protect all accepted199/accepted_decisions/verified-stock related data; this pass does not delete or infer acceptance from directory names.",
                "Protect native0 stock and any current queue/dependency inputs; only a parent-controlled dependency check may release them.",
                "Protect M085 actual854/953/956/960, M086 actual850/864/963 plus fresh161, and M095 actual808/939 and their GenCase/QA producers.",
                "A numerical precision negative is not an automatic cleanup reason.",
            ],
            "active_root960_launcher": pid_snapshot(4022120),
        },
        "parent_action": {
            "safe_to_delete_now": False,
            "required_before_any_cleanup": [
                "freeze and re-read the shared ledger/controller state",
                "verify no active PID/fd and no receipt/request/downstream references",
                "archive receipt, stdout/Run.out, failure report and provenance metadata",
                "remove only explicitly approved payload components, never the protected source/receipt evidence",
                "re-run this audit after the parent changes storage",
            ],
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(args.report),
        "receipt_count": len(paths),
        "status_counts": dict(sorted(status_counts.items())),
        "candidate_count": len(candidates),
        "negative_evidence_count": len(negatives),
        "home_free_bytes": home_free,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
