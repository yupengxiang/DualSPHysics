#!/usr/bin/env python3
"""Build a source-only plan for the three-sentinel reference studies.

This module deliberately stops before a parent reservation.  It reads only
small JSON/XML/source files and file metadata.  GenCase products, BI4/VTK
payloads, solver outputs, receipts, and observer sidecars are represented as
parent-after-reservation records.  The generated plan is therefore useful to
the root scheduler without turning a source plan into scientific evidence.

The plan has three layers:

* the nine already prepared GenCase producer rows (three grids for F2-S2,
  F3-S1, and F5-S1);
* the gated F3-S1 solver studies (spatial, CFL/integration, and output
  sampling), together with the F5 support-only and F2 owner-blocked states;
* a concrete native observer command and a small next-parent map for the
  remaining sentinel cases.

No function in this file opens a declared forcing file or a generated BI4,
VTK, H5, or native Part file.  ``--self-test`` uses only manufactured data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "ds02.stage2.three-sentinel.actual-solver-plan.v1"
SMALL_LIMIT = 10 * 1024 * 1024
HEX64 = set("0123456789abcdef")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {
        "bytes": int(s.st_size),
        "device": int(s.st_dev),
        "inode": int(s.st_ino),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
    }


def _record_small(path: Path, *, declared_sha: str | None = None) -> dict[str, Any]:
    """Record a small source file, reading its bytes exactly once."""

    path = path.expanduser().absolute()
    st = _stat(path)
    if st["bytes"] > SMALL_LIMIT:
        raise ValueError(f"source file exceeds metadata cap: {path} ({st['bytes']})")
    before = _stat(path)
    data = path.read_bytes()
    after = _stat(path)
    digest = _sha256_bytes(data)
    if before != after:
        raise ValueError(f"source changed while read: {path}")
    if declared_sha is not None and digest != declared_sha:
        raise ValueError(f"source SHA mismatch for {path}: {digest} != {declared_sha}")
    return {
        "path": str(path),
        "sha256": digest,
        "stat_before": before,
        "stat_after": after,
        "read_scope": "bounded_small_source",
    }


def _record_stat_only(path: Path, *, declared_sha: str | None = None, reason: str) -> dict[str, Any]:
    """Record a deferred payload without opening it."""

    path = path.expanduser().absolute()
    st = _stat(path)
    if declared_sha is not None and (len(declared_sha) != 64 or set(declared_sha) - HEX64):
        raise ValueError(f"invalid declared SHA for deferred file: {path}")
    return {
        "path": str(path),
        "sha256": declared_sha,
        "stat_at_prepare": st,
        "payload_read": False,
        "read_scope": "stat_only_deferred_parent_after_reservation",
        "reason": reason,
    }


def _load_json_small(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = _record_small(path)
    return json.loads(path.read_text(encoding="utf-8")), rec


def _path_from_repo(repo: Path, value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return repo / p


def _find_literal_venv(repo: Path) -> dict[str, Any]:
    """Bind the literal venv argv0 and its resolved interpreter provenance."""

    candidates = [
        # Production requests deliberately use the original vendor checkout's
        # literal venv.  A worktree-local venv is only a fallback for a
        # manufactured test and must never replace this argv0 in a parent q.
        Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"),
        repo / "lagrangian-fluid-lab/.venv/bin/python",
        repo / "lagrangian-fluid-lab/campaigns/ds-data-02/.venv/bin/python",
    ]
    literal = next((p for p in candidates if p.exists()), None)
    if literal is None:
        raise FileNotFoundError("literal stage2 venv python not found")
    resolved = literal.resolve()
    cfg = literal.parent.parent / "pyvenv.cfg"
    if not cfg.exists():
        raise FileNotFoundError(f"pyvenv.cfg not found for {literal}")
    result = {
        "argv0_literal": str(literal),
        "argv0_must_remain_literal": True,
        "resolved_interpreter": str(resolved),
        "resolved_interpreter_record": _record_small(resolved),
        "pyvenv_cfg_record": _record_small(cfg),
        "system_python_fallback_allowed": False,
    }
    return result


def _source_closure(repo: Path) -> dict[str, Any]:
    ref = repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
    candidates = [
        "stage2_f3_s2_external_solver_v5_request.py",
        "stage2_f3_s2_external_solver_v5_materialize.py",
        "stage2_native_physical_observer_v2.py",
        "stage2_native_physical_observer_enforcer_v2.py",
        "stage2_three_sentinel_refstudy_contract_v1.json",
        "stage2_three_sentinel_refstudy_worker_v1.py",
        "stage2_three_sentinel_refstudy_request_v1.py",
        "stage2_three_sentinel_refstudy_verify_v1.py",
    ]
    records = []
    for name in candidates:
        path = ref / name
        if not path.exists():
            raise FileNotFoundError(path)
        records.append(_record_small(path))

    runtime = repo / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
    if runtime.exists():
        records.append(_record_small(runtime))
    else:
        # Some source checkouts keep the runtime in the stage2 reference tree.
        fallback = ref / "ds_data02_runtime_v8.py"
        if not fallback.exists():
            raise FileNotFoundError("runtime v8 source not found")
        records.append(_record_small(fallback))
    return {
        "records": records,
        "imports_must_be_bound_transitively": True,
        "payload_read": False,
        "runtime_contract": "external-solver-request.v5 plus native observer V2/enforcer V2",
    }


def _producer_rows(manifest: dict[str, Any], repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in manifest.get("producer_requests", []):
        request_path = Path(item["path"])
        request, request_record = _load_json_small(request_path)
        # The source manifest's digest is a producer binding, not a suggestion.
        if request_record["sha256"] != item["sha256"]:
            raise ValueError(f"producer request SHA mismatch: {request_path}")
        output = request.get("output", {})
        products = output.get("products", []) if isinstance(output, dict) else []
        if not products:
            products = [
                {"path": "{attempt_root}/generated.xml", "kind": "generated_xml"},
                {"path": "{attempt_root}/generated_Fluid.vtk", "kind": "fluid_vtk"},
                {"path": "{attempt_root}/generated_Bound.vtk", "kind": "bound_vtk"},
                {"path": "{attempt_root}/generated.bi4", "kind": "generated_bi4"},
                {"path": "{attempt_root}/execution-receipt.json", "kind": "execution_receipt"},
            ]
        rows.append(
            {
                "row_key": item["row_key"],
                "namespace": item["namespace"],
                "producer_request": request_record,
                "producer_request_sha256": request_record["sha256"],
                "producer_request_contract": {
                    "schema": request.get("schema"),
                    "family_id": request.get("family_id"),
                    "sentinel_id": request.get("sentinel_id"),
                    "grid_label": request.get("grid_label"),
                    "case_id": request.get("case_id"),
                    "physical_case_id": request.get("physical_case_id"),
                    "cpu_task_kind": request.get("cpu_task_kind"),
                    "cpu_threads": request.get("cpu_threads"),
                    "max_wall_seconds": request.get("max_wall_seconds"),
                    "max_memory_bytes": request.get("max_memory_bytes"),
                    "max_storage_bytes": request.get("max_storage_bytes"),
                    "command": request.get("command"),
                    "execution_allowed": request.get("execution_allowed"),
                    "source_only": request.get("source_only"),
                    "solver_launch": request.get("solver_launch"),
                    "gencase_launch": request.get("gencase_launch"),
                },
                "products": [
                    {
                        "kind": x.get("kind", "unknown") if isinstance(x, dict) else "unknown",
                        "path": x.get("path") if isinstance(x, dict) else str(x),
                        "sha256": None,
                        "stat": None,
                        "source": "PARENT_AFTER_RESERVATION_REQUIRED",
                    }
                    for x in products
                ],
                "receipt_join_required": [
                    "receipt.request_sha256 equals actual request file-byte SHA",
                    "receipt.request equals request file document",
                    "receipt family/case/attempt/output root exact join",
                    "all four generated products are present and stable",
                ],
                "scientific_status": "NO_PRODUCT_OR_SUPPORT_RESULT_YET",
            }
        )
    return rows


def _study_plan() -> dict[str, Any]:
    return {
        "admission_order": [
            "serial nine GenCase producers",
            "initial XML/Fluid/Bound/native-header support audit for every row",
            "F3-S1 spatial ladder only if owner/support joins pass",
            "F3-S1 integration or output-sampling pair, one changed control at a time",
            "selected native observer and independent refstudy verifier",
        ],
        "common_control": {
            "source_control_id": "F3-S1-owner-grid-source-v3",
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "cfl_number": 0.05,
            "coef_dt_min": 0.005,
            "time_max_s": 8.35,
            "time_out_s": 0.01,
            "verlets": 40,
            "pointref_m": [0.003, 0.003, 0.003],
            "forcing": {
                "path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005/root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056/prepared/CaseSloshingAccData.csv",
                "sha256": "a4afb8a99ba1e7404b2892b84a2d2b293b11653d792a118867abfaec6593fb48",
                "bytes": 14919771,
                "payload_read": False,
                "hash_basis": "declared source record; parent rechecks after reservation",
            },
        },
        "F3-S1": {
            "admission_status": "PENDING_NINE_GENCASE_SUPPORT_AND_OWNER_L",
            "source_primitive_mass_kg": 13.066704,
            "source_primitive_is_not_owner_truth": True,
            "spatial": {
                "dimension": "spatial",
                "grid_dp_m": [0.0075, 0.006, 0.0048],
                "change_set": ["definition@dp"],
                "required_actual_inputs": [
                    "three completed GenCase receipts/products",
                    "generated XML role/count/geometry join",
                    "Fluid and Bound VTK finite/support/overlap audit",
                    "native frame-0 Idp roles and MassFluid/MassBound/Dp header",
                    "owner L and mass authority, still UNKNOWN until source/native join",
                ],
                "solver": "external_solver_v5_parent_guard_only",
                "output_window_s": 8.350016881886734,
                "output_interval_s": 0.01,
                "observer_queries_s": [0.0, 2.0, 4.0, 6.0, 8.0],
                "interpolation": False,
                "neighbor_grid_truth": False,
            },
            "integration": {
                "dimension": "integration",
                "baseline_dp_m": 0.006,
                "baseline_cfl": 0.05,
                "variant_cfl": 0.025,
                "output_interval_s": 0.01,
                "only_changed_input": "CFL number",
                "required_trace": ["actual DtInfo/RunPARTs", "DtMin/CoedDtMin clamp counts", "exact saved times"],
                "admission_status": "BLOCKED_UNTIL_BASELINE_TERMINAL_AND_SUPPORT_PASS",
            },
            "output_sampling": {
                "dimension": "output_sampling",
                "baseline_dp_m": 0.006,
                "cfl": 0.05,
                "baseline_output_interval_s": 0.01,
                "variant_output_interval_s": 0.005,
                "only_changed_input": "output interval",
                "required_trace": ["RunPARTs saved-time rows", "actual native query rows", "no interpolation"],
                "admission_status": "BLOCKED_UNTIL_BASELINE_TERMINAL_AND_SUPPORT_PASS",
            },
        },
        "F5-S1": {
            "admission_status": "SUPPORT_ONLY_NO_SOLVER",
            "continuous_owner_mass_kg": 287.736,
            "source_region": "box [0.01,-0.14,0.01]+size [3.42,0.28,0.38], retained z>=0.28*(x-2)",
            "discrete_sample_mass_kg": 254.4779834119572,
            "raw_envelope_mass_kg": 363.888,
            "mass_rescale": False,
            "required_next_parent": [
                "new representation-only GenCase output",
                "Fluid/Bound support and overlap",
                "native Idp roles and MassFluid/MassBound when present",
                "same source motion/control closure",
            ],
            "scientific_status": "QI_QN_QE_UNKNOWN",
        },
        "F2-S2": {
            "admission_status": "OWNER_UNVERIFIED_CROSS_SENTINEL_TARGET",
            "owner_mass_kg": None,
            "do_not_import_f2_s1_mass": True,
            "required_next_parent": [
                "source-specific owner region derivation",
                "exact S2 XML/Def/control identity",
                "three GenCase support audits only after owner source closes",
            ],
            "solver_status": "BLOCKED_UNTIL_SOURCE_OWNER_CLOSED",
        },
    }


def _observer_entry(repo: Path, venv: dict[str, Any]) -> dict[str, Any]:
    ref = repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
    observer = _record_small(ref / "stage2_native_physical_observer_v2.py")
    enforcer = _record_small(ref / "stage2_native_physical_observer_enforcer_v2.py")
    return {
        "producer": "stage2_native_physical_observer_v2 plus enforcer_v2",
        "observer_source": observer,
        "enforcer_source": enforcer,
        "command_template": [
            venv["argv0_literal"],
            str(ref / "stage2_native_physical_observer_v2.py"),
            "--raw-root", "{actual_solver_output_data}",
            "--runparts", "{actual_RunPARTs_csv}",
            "--generated-xml", "{actual_generated_xml}",
            "--decoder", "{official_decoder}",
            "--decoder-source", "{decoder_source_record}",
            "--output", "{attempt_root}/observer/native-physical-observer-v2.json",
            "--scratch-root", "{attempt_root}/observer/scratch",
            "--expected-frame-count", "{actual_frame_count}",
            "--expected-final-time-s", "{actual_final_time_s}",
            "--final-time-tolerance-s", "{registered_final_time_tolerance_s}",
            "--frames", "{actual_selected_frame_ids}",
            "--query-times", "0", "2", "4", "6", "8",
        ],
        "read_contract": {
            "selected_frames_only": True,
            "no_interpolation": True,
            "native_mass_header_required": True,
            "xml_mass_fallback": False,
            "fluid_and_bound_roles_separate": True,
            "all_raw_input_sha_stat": "pre/decode/post by parent worker",
            "Q_status": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "sidecar_adapter": {
            "required": True,
            "reason": "refstudy worker consumes normalized native sidecars; observer V2 alone is not a solver result",
            "native_mass_basis": "parent native-header probe only; never XML-derived",
            "status": "PARENT_SOURCE_ADAPTER_REQUIRED",
        },
    }


def _remaining_sentinels(index: dict[str, Any], repo: Path) -> dict[str, Any]:
    index_path = repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_fourteen_actual_evidence_readiness_v7.json"
    index_record = _record_small(index_path)
    result: dict[str, Any] = {
        "index": index_record,
        "scientific_credit": 0,
        "policy": "actual diagnostic terminal != QI/QN/QE qualification; no neighbor truth or interpolation",
        "rows": [],
    }
    for row in index.get("sentinels", []):
        sid = row.get("sentinel_id")
        if sid in {"F2-S2", "F3-S1", "F5-S1"}:
            continue
        nxt = row.get("next_parent", {})
        result["rows"].append(
            {
                "sentinel_id": sid,
                "family_id": row.get("family_id"),
                "physical_case_id": row.get("physical_case_id"),
                "actual_evidence": [
                    {
                        "kind": ev.get("kind"),
                        "path": ev.get("path"),
                        "sha256": ev.get("sha256"),
                        "bytes": ev.get("bytes"),
                        "claim_scope": ev.get("claim_scope"),
                    }
                    for ev in row.get("actual_evidence", [])
                ],
                "next_parent_kind": nxt.get("kind"),
                "next_action": nxt.get("action"),
                "source_prerequisite": nxt.get("source_prerequisite"),
                "resource_estimate": nxt.get("resource_estimate"),
                "success_condition": nxt.get("success_condition"),
                "recovery_if_gate_fails": row.get("recovery_if_gate_fails"),
                "admission": "PARENT_REQUEST_REQUIRED; no source-only status is a result",
                "resource": "root chooses after source/support gate; no reservation in this plan",
                "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            }
        )
    return result


def _recent_root310_update(repo: Path) -> dict[str, Any]:
    """Bind the small ROOT310 snapshot proof when it is present.

    The selected Part files are represented only by the proof/report metadata;
    this helper never opens a native file.
    """

    checkpoint = repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json"
    if not checkpoint.exists():
        return {"status": "NOT_PRESENT_IN_SOURCE_CHECKOUT"}
    proof, proof_record = _load_json_small(checkpoint)
    report = Path(proof["report"])
    report_record = _record_small(report)
    if report_record["sha256"] != proof.get("report_sha256"):
        raise ValueError("ROOT310 proof/report source SHA mismatch")
    return {
        "status": "ACTUAL_SOURCE_SNAPSHOT_METADATA_BOUND_NO_NATIVE_DECODE",
        "proof": proof_record,
        "proof_sha256": proof_record["sha256"],
        "report": report_record,
        "request_path": proof.get("request"),
        "request_sha256": proof.get("request_sha256"),
        "selected_file_count": proof.get("selected_file_count"),
        "selected_native_total_bytes": proof.get("selected_native_total_bytes"),
        "source_sha_list_digest": proof.get("source_sha_list_digest"),
        "payload_read": proof.get("root_payload_content_read"),
        "next_entry": {
            "builder": "stage2_f1_s2_root279_source_package_v1.py",
            "command": "literal venv python stage2_f1_s2_root279_source_package_v1.py --primary-root {primary_root} --output-dir {primary_stage2}/requests/root279-pair-native-source-v6-prepared-001",
            "status": "SOURCE_ONLY_WAITING_PARENT_NATIVE_DECODE",
        },
    }


def build_plan(repo: Path, admission_manifest_path: Path, owner_report_path: Path) -> dict[str, Any]:
    admission_manifest, admission_record = _load_json_small(admission_manifest_path)
    owner_report, owner_record = _load_json_small(owner_report_path)
    if admission_manifest.get("schema") != "ds02.stage2.root-nine-gencase-admission-source.v3":
        raise ValueError("unexpected nine-producer admission manifest schema")
    if admission_manifest.get("actual_gencase_count") != 0:
        raise ValueError("plan input already claims a GenCase result")

    venv = _find_literal_venv(repo)
    closure = _source_closure(repo)
    source_ref = repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
    contract = _record_small(source_ref / "stage2_three_sentinel_refstudy_contract_v1.json")
    readiness_path = source_ref / "stage2_fourteen_actual_evidence_readiness_v7.json"
    readiness, _ = _load_json_small(readiness_path)

    # These are small source reports.  They establish the plan's source
    # values, while their generated/native products remain out of scope.
    f3_result = source_ref / "stage2_f3_s1_source_closure_v1_result.json"
    f5_result = source_ref / "stage2_f5_s1_continuous_owner_geometry_v2_result.json"
    f3_source = _record_small(f3_result)
    f5_source = _record_small(f5_result)

    return {
        "schema": SCHEMA,
        "status": "SOURCE_PLAN_ONLY_PARENT_REBIND_REQUIRED",
        "created_by": "stage2_three_sentinel_actual_solver_plan_v1.py",
        "scientific_credit": 0,
        "qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "No GenCase product, native observer, solver receipt, or continuous-owner support result is claimed by this plan.",
        },
        "source_inputs": {
            "nine_gencase_admission_manifest": admission_record,
            "owner_source_report": owner_record,
            "f3_source_closure": f3_source,
            "f5_continuous_owner_geometry": f5_source,
            "refstudy_contract": contract,
            "runtime_and_observer_closure": closure,
            "literal_venv": venv,
        },
        "dependency_chain": {
            "source_admission_manifest": {
                "path": str(admission_manifest_path),
                "sha256": admission_record["sha256"],
                "actual_gencase_count": admission_manifest.get("actual_gencase_count"),
                "required_status": "SOURCE_METADATA_PREFLIGHTED_PENDING_ACTUAL_NATIVE321",
            },
            "root345_product_handoff": {
                "expected_path": str(repo / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/three-sentinel-owner-grid-actual-gencase-products-v2-root345-001/owner-grid-actual-gencase-product-map-v2.json"),
                "required_before_solver": True,
                "required_fields": [
                    "exact producer request file-byte SHA",
                    "actual GenCase execution receipt/proof SHA",
                    "generated.xml/generated.bi4/Fluid.vtk/Bound.vtk path and parent-after-reservation SHA/stat",
                    "staged F3 forcing/control copy SHA and cwd closure",
                ],
                "status": "NOT_BOUND_IN_THIS_SOURCE_PLAN",
            },
            "root274_to_root345": {
                "role": "historical dependency chain retained by root; this plan consumes only its source manifest and exact handoff when available",
                "no_implicit_terminal_claim": True,
            },
        },
        "nine_gencase_producers": _producer_rows(admission_manifest, repo),
        "study_plan": _study_plan(),
        "native_observer": _observer_entry(repo, venv),
        "recent_actual_source_updates": {
            "F1-S2_ROOT310": _recent_root310_update(repo),
            "F1-S2_ROOT277_ROOT278": {
                "terminal_proofs": [
                    {"path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_DP020_SAME_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_277.json", "sha256": "026b2d326c2d65869dc16c6a0d062056ca31d720642dbb715bd3d13d787115d8"},
                    {"path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_DP020_HALF_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_278.json", "sha256": "b357afa839d78bf8a8e14626e459f79c08afd77c739c078e2f13573ee3871629"},
                ],
                "role": "terminal solver lineage only; QI/QN/QE remain UNKNOWN",
            },
        },
        "source_only_commands": {
            "gencase": {
                "description": "Use each bound producer request through shared runtime V8; do not invoke this template directly.",
                "argv": [
                    "{official_GenCase_linux64}",
                    "{candidate_Def_stem_without_xml}",
                    "{attempt_root}/generated",
                    "-save:all",
                    "-threads:1",
                ],
                "cwd": "{attempt_root}/inputs/{sentinel}/{grid}",
                "outputs": [
                    "{attempt_root}/generated.xml",
                    "{attempt_root}/generated_Fluid.vtk",
                    "{attempt_root}/generated_Bound.vtk",
                    "{attempt_root}/generated.bi4",
                    "{attempt_root}/execution-receipt.json",
                ],
                "admission": "PARENT_RUNTIME_V8_AFTER_RESERVATION_ONLY",
            },
            "external_solver_v5": {
                "request_builder": "stage2_f3_s2_external_solver_v5_request.py",
                "materializer": "stage2_f3_s2_external_solver_v5_materialize.py",
                "status": "ROOT_REBINDS_GPU_UUID_AND_ATTEMPT_AFTER_SUPPORT_PASS",
                "argv0_rule": "materializer command[0] remains literal venv script; resolved interpreter is provenance only",
                "planned_control": "F3-S1 dp=0.006, CFL=0.05, TimeMax=8.35, TimeOut=0.01",
                "not_launchable_from_this_file": True,
            },
            "refstudy": {
                "worker": "stage2_three_sentinel_refstudy_worker_v1.py",
                "verifier": "stage2_three_sentinel_refstudy_verify_v1.py",
                "input": "parent-after-reservation normalized observer sidecars",
                "query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0],
                "no_interpolation": True,
                "no_neighbor_grid_truth": True,
            },
        },
        "resource_plan": {
            "gen_case_serial": {
                "rows": 9,
                "cpu_threads": 1,
                "max_wall_seconds_per_row": 1800,
                "memory_bytes": 4 * 1024**3,
                "max_storage_bytes_per_row": 8 * 1024**3,
                "gpu": False,
                "storage_basis": "source request upper bounds; actual products measured by parent",
            },
            "f3_solver_canary": {
                "rows": 1,
                "runner": "external_solver_v5",
                "cpu_threads": 2,
                "max_wall_seconds": 7200,
                "memory_bytes": 8 * 1024**3,
                "external_storage_bytes": 64 * 1024**3,
                "home_storage_bytes": 512 * 1024**2,
                "gpu_uuid": "ROOT_SELECTS_AT_ADMISSION",
                "basis": "planning ceiling, not a measured run cost",
            },
            "selected_native_observer": {
                "cpu_threads": 1,
                "max_wall_seconds": 3600,
                "memory_bytes": 4 * 1024**3,
                "scratch_bytes": 2 * 1024**3,
                "raw_part_read_passes": 4,
                "basis": "parent wrapper prehash + decoder + posthash + decoder input read; actual bytes from parent stat",
            },
        },
        "gate_contract": {
            "producer_products": "all nine products and execution receipts must be present, stable, and exact-joined before solver",
            "support": "Fluid/Bound finite support, Idp roles, overlap, and native MassFluid/MassBound/Dp are actual parent observations",
            "owner": "F2-S2 owner remains unresolved; F3 source primitive is not owner mass; F5 287.736 kg is geometric target only",
            "forcing": "14,919,771-byte F3 source is deferred and must be copied/hash-checked inside the reserved attempt",
            "observer": "native header and role fields come from the decoder/producer; XML mass fallback is forbidden",
            "science": "spatial, integration, output sampling, and lifecycle results stay separate; QI/QN/QE remain UNKNOWN until their registered task gates are met",
        },
        "remaining_sentinel_next_parents": _remaining_sentinels(readiness, repo),
        "read_scope": {
            "small_source_json_xml_code": True,
            "forcing_payload": False,
            "generated_bi4_vtk_h5_native_part": False,
            "solver_launch": False,
            "gpu_lease": False,
            "ledger_mutation": False,
        },
    }


def _self_test() -> None:
    # The self-test deliberately does not touch a campaign source or payload.
    with __import__("tempfile").TemporaryDirectory() as td:
        p = Path(td) / "tiny.json"
        p.write_text('{"schema":"tiny"}\n', encoding="utf-8")
        rec = _record_small(p)
        assert rec["sha256"] == _sha256_bytes(p.read_bytes())
        deferred = _record_stat_only(p, declared_sha=rec["sha256"], reason="fixture")
        assert deferred["payload_read"] is False
        assert deferred["sha256"] == rec["sha256"]
    plan = _study_plan()
    assert plan["F3-S1"]["integration"]["variant_cfl"] == 0.025
    assert plan["F3-S1"]["output_sampling"]["variant_output_interval_s"] == 0.005
    assert plan["F5-S1"]["continuous_owner_mass_kg"] == 287.736
    assert plan["F5-S1"]["discrete_sample_mass_kg"] != plan["F5-S1"]["continuous_owner_mass_kg"]
    print("stage2_three_sentinel_actual_solver_plan_v1: self-test PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--owner-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    if not all((args.repo_root, args.admission_manifest, args.owner_report, args.output)):
        parser.error("generation requires --repo-root, --admission-manifest, --owner-report, and --output")
    plan = build_plan(args.repo_root, args.admission_manifest, args.owner_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": plan["status"], "output": str(args.output), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
