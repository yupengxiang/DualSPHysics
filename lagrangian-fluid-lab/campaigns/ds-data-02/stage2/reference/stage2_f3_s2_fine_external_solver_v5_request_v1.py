#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Prepare the F3-S2 ``dp=.003`` full-window external-v5 request.

This is a forward-only adapter around the consumed shared external-v5 request
writer.  The source-card mode closes the already completed ROOT102 GenCase
and ROOT104 support evidence using small reports/XML and ``stat(2)`` only.  It
does not hash or open the generated BI4/VTK/forcing payloads.  The request mode
is deliberately gated on a terminal ROOT162 receipt, its actual proof, and a
successful selected-native observer report; it also requires a BI4 SHA supplied
by the parent after its own reservation/fingerprint step.

The request is still development/UNKNOWN.  It preserves the 0--
8.350016881886734 s window and ``tout=.01``.  The planning envelope is at most
21600 s, two CPU threads and 64 GiB external product reservation; those are
parent-review values, not measured runtime or storage guarantees.  No solver
or payload read is performed by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
FAMILY = "F3"
SENTINEL = "F3-S2"
TMAX = 8.350016881886734
TOUT = 0.01
FORCING_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
SOURCE_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
OWNER_MASS_KG = 14.58
FINE_FLUID_COUNT = 540_000
FINE_TOTAL_COUNT = 976_104
FINE_SAMPLE_MASS_KG = 14.58
FINE_BI4_BYTES = 48_183_300
FINE_PROXY_BYTES = 35_971_428_340
EXTERNAL_RESERVE_BYTES = 64 * 1024**3
HOME_RECEIPT_RESERVE_BYTES = 16 * 1024**2
HEX64 = re.compile(r"^[0-9a-f]{64}$")

FINE_ROOT = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001"
FINE_RECEIPT = FINE_ROOT / "execution-receipt.json"
FINE_WORKER_REPORT = FINE_ROOT / "worker/f3_s2_commensurate_dp003_gencase_v1.json"
FINE_XML = FINE_ROOT / "worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED.xml"
FINE_BI4 = FINE_ROOT / "worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED.bi4"
FINE_FLUID_VTK = FINE_ROOT / "worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED_Fluid.vtk"
FINE_BOUND_VTK = FINE_ROOT / "worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED_Bound.vtk"
SOURCE_XML = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
SOURCE_CONTROL = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/CaseSloshingAccData.csv"
ROOT102_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP003_ACTUAL_GENCASE_INITIAL_MASS_ROOT_VERIFICATION_102.json"
ROOT104_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP003_ACTUAL_SOURCE_MASS_OWNER_SUPPORT_ROOT_VERIFICATION_104.json"
ROOT102_REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-commensurate-dp003-gencase-v1-root-forward-102-001.json"
ROOT102_RECEIPT = FINE_RECEIPT
ROOT104_REPORT = DATA_ROOT / "families/F3/F3_S2_DP003_ACTUAL_INITIAL_SUPPORT_QA_ROOT_104/f3-s2-dp003-initial-support-qa-v1-root-104-001-root-forward-030-001/f3-s2-dp003-initial-support-qa-v1.json"
ROOT104_RECEIPT = DATA_ROOT / "families/F3/F3_S2_DP003_ACTUAL_INITIAL_SUPPORT_QA_ROOT_104/f3-s2-dp003-initial-support-qa-v1-root-104-001-root-forward-030-001/execution-receipt.json"
V5_DELEGATE = Path(__file__).with_name("stage2_f3_s2_external_solver_v5_request.py")

DEFAULT_CARD = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-owner-centered-dp003-fine-source-card-v1.json"
DEFAULT_OUTPUT = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-owner-centered-dp003-full-cfd-fine-root-169-001.json"


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    if stat.st_size > 2 * 1024 * 1024:
        raise ValueError(f"{label} is not a bounded small input: {stat.st_size} bytes")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_metadata_hashed_by_builder",
        "content_read_by_builder": True,
    }


def payload_stat(path: Path, label: str, expected_sha: str | None, *, authority: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    if expected_sha is not None and not HEX64.fullmatch(expected_sha):
        raise ValueError(f"{label} expected SHA must be lowercase SHA-256")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha,
        "sha256_computed_by_builder": False,
        "content_scope": "parent_after_reservation_pre_post_hash",
        "content_read_by_builder": False,
        "sha_authority": authority,
    }


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def validate_initial_evidence() -> dict[str, Any]:
    proof102 = load_json(ROOT102_PROOF, "ROOT102 GenCase proof")
    proof104 = load_json(ROOT104_PROOF, "ROOT104 support proof")
    report102 = load_json(FINE_WORKER_REPORT, "ROOT102 GenCase report")
    report104 = load_json(ROOT104_REPORT, "ROOT104 support report")
    if proof102.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError("ROOT102 proof schema changed")
    if proof102.get("status") != "VERIFIED_ACTUAL_F3_DP003_GENCASE_INITIAL_XML_PREFERRED_SUPPORT_PENDING":
        raise ValueError("ROOT102 proof is not the completed dp003 initial proof")
    if proof104.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError("ROOT104 proof schema changed")
    if proof104.get("status") != "VERIFIED_ACTUAL_F3_DP003_SOURCE_MASS_OWNER_SUPPORT_CPU_DELTA_PENDING":
        raise ValueError("ROOT104 proof is not the completed dp003 support proof")
    if report102.get("status") != "COMPLETED_F3_S2_COMMENSURATE_DP003_GENCASE":
        raise ValueError("ROOT102 GenCase report status changed")
    if report104.get("status") != "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED":
        raise ValueError("ROOT104 support report status changed")
    for value, label in ((proof102, "ROOT102 proof"), (proof104, "ROOT104 proof"), (report102, "ROOT102 report"), (report104, "ROOT104 report")):
        if value.get("physical_case_id") not in (None, PHYSICAL_CASE_ID):
            raise ValueError(f"{label} physical identity changed")
    if proof102.get("actual_sample_mass_kg") != OWNER_MASS_KG or proof102.get("mass_gate") != "PREFERRED":
        raise ValueError("ROOT102 does not close the preferred 14.58 kg initial mass gate")
    if proof104.get("actual_mass_kg") != OWNER_MASS_KG:
        raise ValueError("ROOT104 support proof does not close the 14.58 kg initial mass")
    source = report104.get("source", {})
    if source.get("control", {}).get("sha256") != FORCING_SHA:
        raise ValueError("ROOT104 source control SHA is not the frozen 9a776... forcing")
    if source.get("xml", {}).get("sha256") != SOURCE_XML_SHA:
        raise ValueError("ROOT104 source XML SHA changed")
    candidate = report104.get("candidate", {})
    candidate_summary = candidate.get("generated_xml_summary_actual", {})
    candidate_counts = candidate_summary.get("counts", {}) if isinstance(candidate_summary, dict) else {}
    if candidate_counts.get("fluid") != FINE_FLUID_COUNT or candidate_summary.get("sample_fluid_mass_kg") != OWNER_MASS_KG:
        raise ValueError("ROOT104 candidate count/mass no longer matches the fine source")
    fingerprint = proof102.get("generated_bi4_worker_fingerprint")
    if not isinstance(fingerprint, dict) or fingerprint.get("bytes") != FINE_BI4_BYTES or not HEX64.fullmatch(str(fingerprint.get("sha256", ""))):
        raise ValueError("ROOT102 does not expose the historical BI4 fingerprint needed for parent review")
    return {"proof102": proof102, "proof104": proof104, "report102": report102, "report104": report104, "historical_bi4_fingerprint": fingerprint}


def build_source_card(output: Path) -> dict[str, Any]:
    evidence = validate_initial_evidence()
    card: dict[str, Any] = {
        "schema": "ds02.stage2.f3.s2.fine-external-v5-source-card.v1",
        "status": "SOURCE_READY_PENDING_ROOT162_TERMINAL_AND_ROOT169_BI4_FINGERPRINT",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": "F3_S2_OWNER_CENTERED_DP003_FULL_CFD_FINE_ROOT_169",
        "scope": {
            "purpose": "Source-bound fine dp=.003 same-CFL full-window solver preparation after actual middle terminal and a fresh parent BI4 fingerprint.",
            "builder_reads": "ROOT102/104 small JSON, generated XML and stat metadata only",
            "builder_reads_bi4": False,
            "builder_reads_vtk": False,
            "builder_reads_forcing_payload": False,
            "solver_started": False,
            "gpu_started": False,
            "hdf5_opened": False,
            "mass_rescale": False,
        },
        "owner_contract": {
            "continuous_owner_low_m": [-0.45, -0.09, 0.0],
            "continuous_owner_size_m": [0.9, 0.18, 0.09],
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "preferred_initial_mass_gate": "<=1% from 14.58 kg",
            "hard_initial_mass_gate": ">2% is a hard failure",
        },
        "source_control": {
            "source_xml": small_record(SOURCE_XML, "F3 current source XML"),
            "source_forcing": payload_stat(SOURCE_CONTROL, "F3 current forcing CSV", FORCING_SHA, authority="ROOT102/ROOT104 source report; parent must recheck after reservation"),
            "forcing_sha256": FORCING_SHA,
            "time_window_s": [0.0, TMAX],
        },
        "fine_gencase": {
            "request": small_record(ROOT102_REQUEST, "ROOT102 GenCase request"),
            "receipt": small_record(FINE_RECEIPT, "ROOT102 GenCase receipt"),
            "proof": small_record(ROOT102_PROOF, "ROOT102 GenCase proof"),
            "report": small_record(FINE_WORKER_REPORT, "ROOT102 GenCase report"),
            "generated_xml": small_record(FINE_XML, "ROOT102 generated XML"),
            "generated_bi4": payload_stat(FINE_BI4, "ROOT102 generated BI4", evidence["historical_bi4_fingerprint"]["sha256"], authority="ROOT102 worker fingerprint; final ROOT169 parent guard must recompute"),
            "fluid_vtk": payload_stat(FINE_FLUID_VTK, "ROOT102 generated Fluid VTK", None, authority="ROOT104 worker report; final parent guard must recheck"),
            "bound_vtk": payload_stat(FINE_BOUND_VTK, "ROOT102 generated Bound VTK", None, authority="ROOT104 worker report; final parent guard must recheck"),
            "fluid_count": FINE_FLUID_COUNT,
            "total_count": FINE_TOTAL_COUNT,
            "sample_mass_kg": FINE_SAMPLE_MASS_KG,
            "mass_rescale": False,
        },
        "support": {
            "proof": small_record(ROOT104_PROOF, "ROOT104 support proof"),
            "report": small_record(ROOT104_REPORT, "ROOT104 support report"),
            "receipt": small_record(ROOT104_RECEIPT, "ROOT104 support receipt"),
            "status": "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED",
            "scope": "finite/count and owner-envelope support only; no no-penetration, flux or particle-fate credit",
            "support_parent_full_vtk_hash": "UNKNOWN_NOT_CLAIMED_BY_ROOT104_PROOF",
        },
        "planning_cost": {
            "estimated_total_particles": FINE_TOTAL_COUNT,
            "native_receipt_proxy_bytes": FINE_PROXY_BYTES,
            "native_receipt_proxy_gib": FINE_PROXY_BYTES / 1024**3,
            "proxy_basis": "ROOT706 same-forcing 836-frame receipt scaled by actual dp003 total count; planning only",
            "actual_middle_cost_basis": "PENDING_ROOT162_TERMINAL_RECEIPT_AND_PROOF",
            "not_a_wall_or_frame_guarantee": True,
        },
        "planned_resource_envelope": {
            "cpu_threads": 2,
            "max_wall_seconds": 21600,
            "external_product_reserve_bytes": EXTERNAL_RESERVE_BYTES,
            "home_receipt_reserve_bytes": HOME_RECEIPT_RESERVE_BYTES,
            "status": "PLANNING_ONLY_PARENT_REVIEW_REQUIRED",
            "actual_gpu_uuid": "UNKNOWN_UNTIL_PARENT_FRESH_INVENTORY",
        },
        "release_gates": [
            "ROOT162 terminal receipt with actual RunPARTs/Run.out/DtAllInfo and closed external cost",
            "ROOT162 terminal proof and successful selected-native observer report",
            "ROOT169 parent-after-reservation generated BI4 SHA/stat pre/post closure",
            "ROOT102/104 source identity, 14.58 kg mass and support evidence remain unchanged",
            "fresh parent UUID/storage lease and attempt-contained materialization",
        ],
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "Initial source/support only; no full fine solver or temporal/output qualification has run.",
        },
    }
    card["sha256"] = canonical(card)
    write_once(output, card)
    return {"status": card["status"], "output": str(output.resolve()), "sha256": card["sha256"], "solver_started": False, "payload_read": False}


def load_delegate():
    path = regular(V5_DELEGATE, "shared external-v5 request writer")
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_external_solver_v5_request_fine_delegate", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load shared external-v5 request writer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_middle_terminal(receipt_path: Path, proof_path: Path, observer_path: Path) -> dict[str, Any]:
    receipt = load_json(receipt_path, "ROOT162 terminal receipt")
    proof = load_json(proof_path, "ROOT162 terminal proof")
    observer = load_json(observer_path, "ROOT167 selected observer report")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0", "completed_development_unknown"}:
        raise ValueError("ROOT162 receipt is not terminal")
    if receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT162 receipt has a nonzero return code")
    if int(receipt.get("bytes", 0) or 0) <= 0:
        raise ValueError("ROOT162 receipt has no positive terminal charge bytes")
    proof_status = str(proof.get("status", ""))
    allowed_proof_schema = {
        "ds02.stage2.root-actual-verification.v1",
        "ds02.stage2.root-actual-external-solver-verification.v1",
    }
    runparts_summary = proof.get("RunPARTs_summary")
    if proof.get("schema") not in allowed_proof_schema or "ACTUAL" not in proof_status or int(proof.get("actual_output_bytes", 0) or 0) <= 0:
        raise ValueError("ROOT162 proof is not an actual solver terminal proof")
    if not isinstance(runparts_summary, dict) or int(runparts_summary.get("rows", 0) or 0) < 2:
        raise ValueError("ROOT162 proof has no terminal RunPARTs evidence")
    if proof.get("parent_source_prepost_full_sha_equal") is not True:
        raise ValueError("ROOT162 proof does not close materialized source pre/post SHA")
    proof_receipt_path = proof.get("receipt")
    if proof_receipt_path is not None and Path(str(proof_receipt_path)).expanduser().resolve() != receipt_path.expanduser().resolve():
        raise ValueError("ROOT162 proof receipt path does not match the supplied terminal receipt")
    proof_receipt_sha = proof.get("receipt_sha256")
    if proof_receipt_sha is not None and proof_receipt_sha != sha256(receipt_path):
        raise ValueError("ROOT162 proof receipt SHA does not match the supplied terminal receipt")
    observer_status = str(observer.get("status", ""))
    if not observer_status.startswith("PASS_MIDDLE_SELECTED_NATIVE_FIELDS"):
        raise ValueError("ROOT167 selected observer is not a successful native-field report")
    if observer.get("scope", {}).get("typed_conversion") not in (None, "NOT_PERFORMED"):
        raise ValueError("ROOT167 observer scope unexpectedly includes typed conversion")
    return {"receipt": receipt, "proof": proof, "observer": observer}


def _add_small_input(request: dict[str, Any], path: Path, label: str) -> None:
    item = small_record(path, label)
    text_path = str(Path(item["path"]).resolve())
    request.setdefault("input_files", []).append(text_path)
    request.setdefault("input_sha256", {})[text_path] = item["sha256"]
    request.setdefault("input_content_scope", {})[text_path] = item["content_scope"]


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    card = load_json(args.source_card, "fine source card")
    if card.get("status") != "SOURCE_READY_PENDING_ROOT162_TERMINAL_AND_ROOT169_BI4_FINGERPRINT":
        raise ValueError("fine source card status is not the immutable pending source card")
    if card.get("physical_case_id") != PHYSICAL_CASE_ID or card.get("family_id") != FAMILY or card.get("sentinel_id") != SENTINEL:
        raise ValueError("fine source card physical identity changed")
    if card.get("sha256") != canonical(card):
        raise ValueError("fine source card canonical SHA is invalid")
    evidence = validate_initial_evidence()
    middle = validate_middle_terminal(args.middle_terminal_receipt, args.middle_proof, args.middle_observer_report)
    if not HEX64.fullmatch(args.generated_bi4_sha256):
        raise ValueError("--generated-bi4-sha256 must be a lowercase SHA-256")
    if args.generated_bi4_sha256 != evidence["historical_bi4_fingerprint"]["sha256"]:
        raise ValueError("fine BI4 SHA differs from the ROOT102 fingerprint; parent must provide the actual bound source SHA")

    delegate = load_delegate()
    delegate.ROOT120_CASE = "F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102"
    delegate.ROOT120_RECEIPT_ROOT = FINE_ROOT
    delegate.DEFAULT_SOURCE_XML = SOURCE_XML
    delegate.DEFAULT_SOURCE_CONTROL = SOURCE_CONTROL
    delegate.COST_BASIS_RECEIPT = args.middle_terminal_receipt.expanduser().resolve()
    delegate.TMAX = repr(TMAX)
    delegate.TOUT = repr(TOUT)
    delegate.ESTIMATED_NATIVE_FRAMES = "UNKNOWN_UNTIL_TERMINAL_RUNPARTS"

    def support_status(_report: dict[str, Any]) -> str:
        return "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED"

    delegate._actual_support_status = support_status
    captured: dict[str, Any] = {}
    delegate.write_new = lambda _path, value: captured.setdefault("request", value)
    delegated_args = SimpleNamespace(
        gencase_request=ROOT102_REQUEST,
        receipt=FINE_RECEIPT,
        generated_xml=FINE_XML,
        generated_bi4=FINE_BI4,
        generated_bi4_sha256=args.generated_bi4_sha256,
        source_xml=SOURCE_XML,
        source_control=SOURCE_CONTROL,
        support_report=ROOT104_REPORT,
        cost_basis_receipt=args.middle_terminal_receipt,
        launch_commit=args.launch_commit,
        case_id=args.case_id,
        attempt_id=args.attempt_id,
        external_filesystem=args.external_filesystem,
        external_reserve_bytes=args.external_reserve_bytes,
        home_receipt_reserve_bytes=args.home_receipt_reserve_bytes,
        max_wall_seconds=args.max_wall_seconds,
        output=args.output,
    )
    delegated = delegate.build(delegated_args)
    request = captured.get("request")
    if not isinstance(request, dict):
        raise RuntimeError("shared external-v5 writer did not produce an in-memory request")
    _add_small_input(request, args.source_card, "F3 dp003 fine source card")
    _add_small_input(request, Path(__file__), "F3 dp003 fine request adapter")
    _add_small_input(request, V5_DELEGATE, "shared external-v5 request writer")
    _add_small_input(request, ROOT102_PROOF, "ROOT102 fine GenCase proof")
    _add_small_input(request, ROOT104_PROOF, "ROOT104 fine support proof")
    _add_small_input(request, args.middle_proof, "ROOT162 middle terminal proof")
    _add_small_input(request, args.middle_observer_report, "ROOT167 middle selected observer report")
    request["input_files"] = sorted(set(request["input_files"]))
    request["input_sha256"] = {path: request["input_sha256"][path] for path in request["input_files"]}
    request["input_content_scope"] = {path: request["input_content_scope"][path] for path in request["input_files"]}
    request.setdefault("source_provenance", {})["fine_source_card"] = str(args.source_card.expanduser().resolve())
    request["source_provenance"]["root102_proof"] = str(ROOT102_PROOF.resolve())
    request["source_provenance"]["root104_proof"] = str(ROOT104_PROOF.resolve())
    request["source_provenance"]["middle_terminal_receipt"] = str(args.middle_terminal_receipt.expanduser().resolve())
    request["source_provenance"]["middle_terminal_proof"] = str(args.middle_proof.expanduser().resolve())
    request["source_provenance"]["middle_selected_observer"] = str(args.middle_observer_report.expanduser().resolve())
    request["source_provenance"]["fine_bi4_sha256_parent_bound"] = args.generated_bi4_sha256
    request["source_provenance"]["fine_bi4_sha256_source"] = "ROOT169 parent after-reservation fingerprint required"
    request["timing_contract"]["max_wall_seconds_planned"] = args.max_wall_seconds
    request["storage_scope"]["external_product_reserved_bytes"] = args.external_reserve_bytes
    request["storage_scope"]["planning_proxy_bytes"] = FINE_PROXY_BYTES
    request["storage_scope"]["planning_proxy_is_not_terminal_cost"] = True
    request["middle_terminal_cost_basis"] = {
        "receipt": str(args.middle_terminal_receipt.expanduser().resolve()),
        "proof": str(args.middle_proof.expanduser().resolve()),
        "observer": str(args.middle_observer_report.expanduser().resolve()),
        "terminal_bytes": int(middle["receipt"].get("bytes", 0) or 0),
        "terminal_cost_bound_only_after_root162_and_root167": True,
    }
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "fine source/support and middle terminal provenance only; fine solver/temporal/output qualification pending"}
    request["sha256"] = canonical(request)
    write_once(args.output, request)
    return {"status": "PASS_FINE_EXTERNAL_V5_REQUEST_BUILT", "output": str(args.output.resolve()), "request_sha256": request["sha256"], "delegated_status": delegated.get("status"), "solver_started": False, "native_payload_read": False}


def self_test() -> dict[str, Any]:
    if str(VENV_PYTHON) != "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise AssertionError("literal venv path changed")
    if TMAX != 8.350016881886734 or TOUT != 0.01:
        raise AssertionError("F3 physical window/output cadence changed")
    if OWNER_MASS_KG != 14.58 or FINE_FLUID_COUNT != 540000:
        raise AssertionError("fine source mass/count contract changed")
    return {"status": "PASS", "schema": "ds02.stage2.external-solver-request.v5", "dp_m": 0.003, "window_s": [0.0, TMAX], "tout_s": TOUT, "planning_max_wall_seconds": 21600, "planning_external_reserve_bytes": EXTERNAL_RESERVE_BYTES, "payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-source-card", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-card", type=Path, default=DEFAULT_CARD)
    parser.add_argument("--middle-terminal-receipt", type=Path)
    parser.add_argument("--middle-proof", type=Path)
    parser.add_argument("--middle-observer-report", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP003_FULL_CFD_FINE_ROOT_169")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp003-full-cfd-fine-root-169-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=EXTERNAL_RESERVE_BYTES)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=HOME_RECEIPT_RESERVE_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=21600.0)
    args = parser.parse_args()
    try:
        if args.self_test:
            print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
        if args.build_source_card:
            result = build_source_card(args.output)
        else:
            required = (args.middle_terminal_receipt, args.middle_proof, args.middle_observer_report, args.generated_bi4_sha256, args.launch_commit)
            if any(value is None for value in required):
                parser.error("--build-request requires ROOT162 receipt/proof, ROOT167 observer report, BI4 SHA and --launch-commit")
            result = build_request(args)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_FINE_EXTERNAL_V5_PREPARATION", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
