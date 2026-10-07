#!/usr/bin/env python3
"""Build the immutable F6 fresh193 personal visual-review handoff.

Only JSON/XML/XMF metadata and already-published PNG visualizations are read.
This builder never opens, copies, or hashes H5/BI4/CSV/DAT/VTK payloads and
never starts a job.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")

CASE = "F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT090"
CANON = "7d7c2dc27d0a3c8eaa297a3c48dc4cec27bf075003e2933591a537c755f69e23"
LEGACY = "a5892c54ca3899cc592df4ea831290e1baef0ffbee453ea6e1700a41e39e6148"
QI_SHA = "0e0d0055b6de0da7ea46d2b012dd815eb14acc46f7f6ee1df7086c444a0f8aca"

CASE_ROOT = DATA / "families/F2" / CASE
NATIVE_ATTEMPT = CASE_ROOT / (
    "root-stage1-f2-f2_stage1_first48_expansion_rx063_ry014_fill080_rot090_dp010_"
    "spatial_reference_save010-full401-native-source801-qa809-root812"
)
GEN_ATTEMPT = CASE_ROOT / (
    "root-stage1-f2-f2_stage1_first48_expansion_rx063_ry014_fill080_rot090_dp010_"
    "spatial_reference_save010-actual-gencase-source801-root804"
)
QA_ATTEMPT = CASE_ROOT / (
    "root-stage1-f2-f2_stage1_first48_expansion_rx063_ry014_fill080_rot090_dp010_"
    "spatial_reference_save010-actual804-initial-qa105-root809"
)
TYPED_ATTEMPT = CASE_ROOT / (
    "root-stage1-f2-f2_stage1_first48_expansion_rx063_ry014_fill080_rot090_dp010_"
    "spatial_reference_save010-actual812-full401-typed157-home4gib-source140-root1013"
)
XMF_ATTEMPT = CASE_ROOT / "root-stage1-f2-rx063-rot090-actual1013-full401-N3-xmf108-root1117"
RENDER_ATTEMPT = CASE_ROOT / (
    "root-stage1-f2-rx063-rot090-actual1117-full401-116-023-nvme-hard2gib-root1143"
)
RENDER_DIR = RENDER_ATTEMPT / "render"
QI = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F2_RX063ROT090_actual1143_full401_UID_N3_times_nativecanonical_"
    "typedlegacy_fifteen_fluid_omissions_actual_plan_namespaces_previsual_QI_1366/"
    "actual1143-full401-own-QI-UID-N3-native-typed-role-fifteen-fluid-omissions-previsual-proof.json"
)
RENDER_HANDOFF = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F2_RX063_ROT090_actual1117_XMF0_full401_original116_023_hard2GiB_render_1143"
)
XMF_HANDOFF = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F2_RX063_ROT090_actual1013_typed0_full401_original108_104_N3_XMF_fairCPU2_1117"
)
TYPED_HANDOFF = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F2_source140_twelve_actual812_native0_full401_typed157_actual974_decoder_Home4GiB_1013"
)
NATIVE_HANDOFF = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F2_actual804809_full401_native_correct_known_solver_literal_prelaunch_repair1_812"
)
F6_OWNER = PKG.parent / (
    "root_followup_140_f2_actual_native_typed157_home4gib_v1/owners/"
    "F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010-actual-native-typed157-owner.json"
)
PRIOR_REVIEW = RENDER_HANDOFF / "actual1117-full401-XMF-and-actual-typed-producer-typed-independent-review.json"

ALLOWED_METADATA = {".json", ".xml", ".xmf"}
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp", ".pvd", ".raw"}


def load(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metadata_ref(path: str | Path, role: str, expected: str | None = None) -> dict:
    p = Path(path)
    assert p.is_file(), p
    assert p.suffix.lower() in ALLOWED_METADATA, p
    assert not any(str(p).lower().endswith(s) for s in FORBIDDEN), p
    got = digest(p)
    if expected is not None:
        assert got == expected, (p, got, expected)
    return {"path": str(p), "sha256": got, "bytes": p.stat().st_size, "kind": "metadata", "role": role}


def png_ref(path: Path, producer: dict, role: str, **extra) -> dict:
    assert path.is_file(), path
    assert path.suffix.lower() == ".png", path
    got = digest(path)
    assert got == producer["sha256"], (path, got, producer["sha256"])
    assert path.stat().st_size == producer["bytes"], (path, path.stat().st_size, producer["bytes"])
    out = {"path": str(path), "sha256": got, "bytes": path.stat().st_size, "kind": "visualization", "role": role, "viewed": True}
    out.update(extra)
    return out


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n")


def main() -> None:
    qi = load(QI)
    qev = qi["actual_completed_metadata_evidence"]
    report = load(RENDER_DIR / "paraview-full-animation-report.json")
    publish = load(RENDER_DIR / "render-publish-receipt.json")
    render_receipt = load(RENDER_ATTEMPT / "execution-receipt.json")
    manifest = load(XMF_ATTEMPT / "xdmf/manifest.json")

    assert QI.is_file() and digest(QI) == QI_SHA
    assert qi["case_id"] == CASE and qi["physical_case_id"] == PHYS
    assert qi["frames"] == 401 and qi["particles"] == 418104
    assert qi["actual_initial_type_counts"] == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114, "total": 418104}
    assert qi["actual_terminal_type_counts"] == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21099, "total": 418089}
    assert qi["actual_time_window_s"] == [0.0, 4.000030243152287]
    assert qi["native_canonical_condition_sha256"] == CANON
    assert qi["typed_XMF_actual_legacy_producer_condition_sha256"] == LEGACY
    assert qi["actual_native_XMF_plan_field_namespaces"] == {
        "native": {
            "source_plan_condition_sha256": {"present": False, "value": None},
            "source_plan_physical_condition_sha256": {"present": True, "value": CANON},
        },
        "XMF": {
            "source_plan_condition_sha256": {"present": False, "value": None},
            "source_plan_physical_condition_sha256": {"present": False, "value": None},
        },
    }
    assert qi["lifecycle_omissions"]["final_missing_particles"] == 15
    assert qi["lifecycle_omissions"]["max_missing_per_frame"] == 15
    assert qi["lifecycle_omissions"]["first_missing_frame"] == 158
    assert qi["lifecycle_omissions"]["cumulative_particle_frame_omissions"] == 2278
    assert qi["lifecycle_omissions"]["missing_location_state_cause_unknown"] is True
    assert qi["genuine_initial_QA_receipt_completed0_and_report_pass"] is True
    assert qi["root_QI_is_independent_proof_not_runner_receipt"] is True
    assert qi["case_credit"] == 0 and qi["q_n_granted"] is False and qi["q_e_granted"] is False
    assert qi["scientific_payload_IO"] is False

    assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report["frames"] == report["source_frames"] == 401
    assert report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True and report["nonfinite_active_states"] == 0
    assert publish["status"] == "published_after_atomic_rename"
    assert render_receipt["status"] == "completed" and render_receipt["returncode"] == 0
    assert manifest["case_id"] == CASE and manifest["physical_case_id"] == PHYS
    assert manifest["frames"] == manifest["expected_frames"] == 401
    assert manifest["particles"] == 418104
    assert manifest["actual_converter_legacy_scope_sha256"] == LEGACY
    assert manifest["canonical_source_physical_condition_sha256"] == CANON
    assert manifest["physical_condition_sha256"] == LEGACY
    assert manifest["scope_equality_not_claimed"] is True

    refs: dict[str, dict] = {}
    refs["main_qi_proof"] = metadata_ref(QI, "Root1366 independent full401 metadata QI proof", QI_SHA)
    refs["prior_scientific_integrity_review"] = metadata_ref(PRIOR_REVIEW, "prior native/typed/XMF metadata review; not personal visual evidence")
    refs["gencase_receipt"] = metadata_ref(GEN_ATTEMPT / "execution-receipt.json", "actual genuine GenCase completed/0 receipt", qev["typed_source_gencase_receipt"]["sha256"])
    refs["prepared_input_report"] = metadata_ref(GEN_ATTEMPT / "prepared/prepared-input-report.json", "actual prepared-input metadata report")
    refs["generated_xml"] = metadata_ref(GEN_ATTEMPT / f"prepared/{CASE}.xml", "actual generated GenCase XML", qev["typed_source_generated_xml"]["sha256"])
    refs["initial_qa_receipt"] = metadata_ref(QA_ATTEMPT / "execution-receipt.json", "actual initial QA completed/0 receipt", qev["initial_qa_receipt"]["sha256"])
    refs["initial_qa_report"] = metadata_ref(QA_ATTEMPT / "actual-initial-qa.json", "actual initial QA report", qev["initial_qa_report"]["sha256"])
    refs["native_request"] = metadata_ref(NATIVE_HANDOFF / f"requests/{CASE}-native-request.json", "actual full401 native request")
    refs["native_receipt"] = metadata_ref(NATIVE_ATTEMPT / "execution-receipt.json", "actual full401 native completed/0 receipt", qev["native_receipt"]["sha256"])
    refs["typed_request"] = metadata_ref(TYPED_HANDOFF / f"requests/{CASE}-enabled-typed-request.json", "actual typed request")
    refs["typed_report"] = metadata_ref(TYPED_ATTEMPT / "conversion-report.json", "actual typed producer conversion report; legacy scope", qev["typed_report"]["sha256"])
    refs["typed_receipt"] = metadata_ref(TYPED_ATTEMPT / "execution-receipt.json", "actual typed completed/0 receipt", qev["typed_receipt"]["sha256"])
    refs["source_owner"] = metadata_ref(F6_OWNER, "F6 source owner metadata; physical producer remains F2")
    refs["xmf_request"] = metadata_ref(XMF_HANDOFF / f"requests/{CASE}-enabled-full401-xmf-request.json", "actual N3 XMF request")
    refs["xmf_binding"] = metadata_ref(XMF_HANDOFF / f"bindings/{CASE}-actual{{producer}}-full401-xmf-binding.json", "actual XMF binding metadata")
    refs["xmf_registration"] = metadata_ref(XMF_HANDOFF / "actual1013-full401-independent-XMF-registration.json", "actual XMF registration metadata")
    refs["xmf_manifest"] = metadata_ref(XMF_ATTEMPT / "xdmf/manifest.json", "actual N3 XMF manifest", qev["XMF_manifest"]["sha256"])
    refs["xmf_xml"] = metadata_ref(XMF_ATTEMPT / "xdmf/case.xmf", "actual N3 XMF XML", qev["XMF_XML"]["sha256"])
    refs["xmf_receipt"] = metadata_ref(XMF_ATTEMPT / "execution-receipt.json", "actual N3 XMF completed/0 receipt", qev["XMF_receipt"]["sha256"])
    refs["render_request"] = metadata_ref(RENDER_HANDOFF / "enabled-full401-render-request.json", "actual completed full401 render request")
    refs["render_wrapper"] = metadata_ref(RENDER_HANDOFF / "enabled-render-wrapper.json", "actual render wrapper")
    refs["render_controller_result"] = metadata_ref(RENDER_HANDOFF / "controller-result.json", "actual render controller completed/0")
    refs["render_controller_config"] = metadata_ref(RENDER_HANDOFF / "controller-config.json", "actual render controller config")
    refs["render_independent_review"] = metadata_ref(PRIOR_REVIEW, "same immutable native/typed/XMF review used by render input closure")
    refs["render_receipt"] = metadata_ref(RENDER_ATTEMPT / "execution-receipt.json", "actual render completed/0 receipt", qev["render_receipt"]["sha256"])
    refs["render_report"] = metadata_ref(RENDER_DIR / "paraview-full-animation-report.json", "actual full401 ParaView report", qev["render_report"]["sha256"])
    refs["publish_receipt"] = metadata_ref(RENDER_DIR / "render-publish-receipt.json", "actual atomic PNG publication receipt", qev["render_publish_receipt"]["sha256"])

    published = {item["relative_path"]: item for item in publish["files_excluding_receipt"]}
    contacts = []
    for i in range(17):
        rel = f"all_frames_{i:03d}.png"
        contacts.append(png_ref(RENDER_DIR / rel, published[rel], "chronological contact sheet", sheet_index=i, frame_start=i * 24, frame_end=min(i * 24 + 23, 400)))
    keys = []
    for frame in [0, 50, 100, 150, 200, 250, 300, 350, 400]:
        rel = f"frames/frame_{frame:04d}.png"
        keys.append(png_ref(RENDER_DIR / rel, published[rel], "chronological key frame", frame=frame))

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    decision = {
        "schema": "ds02.f6.fresh193.f2-personal-visual-review.v1",
        "fresh_id": "fresh193",
        "family_id": "F6",
        "assigned_family": "F6",
        "actual_family": "F2",
        "created_at_utc": now,
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "recursive_delegation": False,
        "reviewer": "/root/f6_endpoint_initial_qa",
        "scope": "F6 handoff only; delegated personal visual evidence for one already-produced F2 render",
        "case": {
            "case_id": CASE,
            "physical_case_id": PHYS,
            "identity_role": "F2 physical producer case assigned to F6 only for delegated review; case_id and physical_case_id remain separate",
            "canonical_native_physical_condition_sha256": CANON,
            "actual_converter_legacy_scope_sha256": LEGACY,
            "producer_scope_schema": "legacy-owner-scope.v0",
            "declared_counts": {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114, "total": 418104},
            "terminal_counts": {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21099, "total": 418089},
            "dimension": 3,
            "expected_frames": 401,
            "nominal_save_interval_s": 0.01,
            "actual_time_s": [0.0, 4.000030243152287],
            "scope_roles": {
                "native_canonical_physical": CANON,
                "typed_actual_converter_legacy": LEGACY,
                "xmf_manifest_physical_condition_legacy": LEGACY,
                "xmf_manifest_canonical_source_physical_condition": CANON,
                "native_source_plan_condition_sha256": None,
                "native_source_plan_physical_condition_sha256": CANON,
                "xmf_source_plan_condition_sha256": None,
                "xmf_source_plan_physical_condition_sha256": None,
                "native_plan_equals_xmf_plan": False,
                "equality_claimed": False,
                "roles_remain_distinct": True,
                "absence_rule": "Native condition-plan is absent and native physical-plan is canonical; XMF condition-plan and physical-plan fields are absent/null in Root1366's field-presence evidence. The XMF manifest's derived physical_condition is legacy and its canonical_source_physical_condition is a separate canonical-source field; no value is filled across namespaces.",
            },
            "source_plan_field_presence": {
                "native": {"source_plan_condition_sha256": {"present": False, "value": None}, "source_plan_physical_condition_sha256": {"present": True, "value": CANON}},
                "XMF": {"source_plan_condition_sha256": {"present": False, "value": None}, "source_plan_physical_condition_sha256": {"present": False, "value": None}},
                "xmf_manifest_derived_fields": {"physical_condition_sha256": {"present": True, "value": LEGACY, "role": "actual converter legacy scope"}, "canonical_source_physical_condition_sha256": {"present": True, "value": CANON, "role": "canonical source physical scope"}},
                "typed_legacy": {"physical_scope_sha256": LEGACY, "schema": "legacy-owner-scope.v0", "status": "legacy scope; no equality claim"},
            },
            "lifecycle_omissions": qi["lifecycle_omissions"],
            "type_semantics": {
                "fixed": "gray fixed tank/tray boundary points; type 0",
                "moving": "orange prescribed moving/open-rim boundary points; type 1",
                "floating": "zero producer floating points; type 2 population is zero",
                "fluid": "blue fluid/free-surface points; type 3",
            },
            "mechanism_parameters": "F2 offset/open-rim RX063 ROT090 spatial-reference case: a moving orange boundary/container orientation drives the blue free-surface response over the full 4 s window; this is a visual mechanism description, not a numerical or containment claim.",
            "mass_semantics": "Producer/native and any converter physical roles remain as reported; this package applies no mass rescaling or normalization.",
        },
        "decision": {
            "status": "visual-approved-by-delegated-agent",
            "review_basis": "After Root1143 completed/0 and atomic publication, I personally viewed all 17 published chronological contact sheets and all 9 published key-frame PNGs with view_image.",
            "case_credit": 0,
            "global_acceptance": False,
            "main_process_qi": "evidence.main_qi_proof (Root1366 independent metadata QI; not claimed as this personal visual review)",
            "precision_status": "not accepted",
            "q_n_granted": False,
            "q_e_granted": False,
            "production_approval": False,
            "visual_scope": "delegated visual screening only; no numerical claim",
            "observations": {
                "initial_state": "Frame 0 shows the gray fixed tray/tank geometry, the orange moving/open-rim body, and the blue initial fluid region. The spatial-reference body and fluid are visible without an obvious initial blank or camera crop; no type-2 floating population is claimed because the producer count is floating=0.",
                "mechanism": "Across the contact sheets and keys, the orange body rotates/tilts while the blue free surface rises, spills from the local open-rim region, and spreads along the fixed tray. This is the visible moving-boundary/free-surface mechanism; the images do not identify the cause of any missing UID.",
                "mid_event": "Around the middle of the run the blue fluid forms a broad stream and splash over the tray floor, with detached blue points above the main surface. The gray fixed geometry and orange body remain identifiable. I saw no obvious catastrophic point-cloud explosion or unambiguous severe rigid-wall penetration in the rendered views.",
                "late_event": "The late contacts and frame 400 remain populated with a thin, laterally spread blue layer and localized ripples/splash remnants while the orange body remains visible. I saw no abrupt blank interval, early visual termination, or camera clipping; the fluid spread is visibly broad and should not be translated into a strict containment claim.",
                "failure_screen": "Visual screening found no obvious gross render failure, catastrophic scatter, or premature termination. Sparse detached points and the broad late fluid spread are recorded as visible features only. Producer metadata independently reports 15 terminal fluid omissions, first frame 158, 2278 cumulative particle-frame omissions, and unknown location/state/cause; those facts remain unresolved by the images.",
                "limits": "This review does not certify all UID activity, strict containment, wall clearance, sub-DP behavior, numerical precision, Q-N, Q-E, or production approval. Native canonical, typed legacy, XMF derived legacy/canonical-source, and absent source-plan fields remain separate exactly as in Root1366. No fluid-loss trajectory or escaping mechanism is inferred from pixels.",
            },
        },
        "producer_chain": {
            "gencase": {"receipt": "evidence.gencase_receipt", "generated_xml": "evidence.generated_xml", "prepared_report": "evidence.prepared_input_report", "terminal": "completed/0", "science_payload_read_or_hashed_by_agent": False},
            "initial_native_qa": {"receipt": "evidence.initial_qa_receipt", "report": "evidence.initial_qa_report", "terminal": "completed/0; producer placement QA", "science_payload_read_or_hashed_by_agent": False},
            "native": {"request": "evidence.native_request", "receipt": "evidence.native_receipt", "terminal": "completed/0", "frames": 401, "dimension": 3, "counts": "declared/terminal counts above"},
            "typed": {"request": "evidence.typed_request", "report": "evidence.typed_report", "receipt": "evidence.typed_receipt", "terminal": "completed/0", "scope_role": f"{LEGACY} legacy-owner-scope.v0; separate from native {CANON}"},
            "xmf": {"request": "evidence.xmf_request", "binding": "evidence.xmf_binding", "manifest": "evidence.xmf_manifest", "xml": "evidence.xmf_xml", "receipt": "evidence.xmf_receipt", "terminal": "completed/0", "scope_role": f"manifest physical_condition={LEGACY}; canonical_source_physical_condition={CANON}; source-plan physical field absent/null per Root1366"},
            "render": {"request": "evidence.render_request", "wrapper": "evidence.render_wrapper", "controller_result": "evidence.render_controller_result", "receipt": "evidence.render_receipt", "report": "evidence.render_report", "publish_receipt": "evidence.publish_receipt", "terminal": "completed/0 and atomically published", "renderer_sha256": "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"},
        },
        "evidence": refs,
        "visual_review": {
            "personally_viewed_with": "view_image",
            "reviewed_at_utc": now,
            "contact_sheet_count": 17,
            "contact_sheets": contacts,
            "key_frame_count": 9,
            "key_frames": keys,
            "key_frame_indices": [0, 50, 100, 150, 200, 250, 300, 350, 400],
            "published_product_root": str(RENDER_DIR),
            "report_frames": report["frames"],
            "report_source_frames": report["source_frames"],
            "actual_times_preserved_exactly": report["actual_times_preserved_exactly"],
            "nonfinite_active_states": report["nonfinite_active_states"],
            "visual_status": "delegated personal visual screen complete; awaiting Root global decision",
        },
        "source_boundaries": {
            "science_payload_read": False,
            "science_payload_hashed": False,
            "science_jobs_started": False,
            "shared_registry_or_ledger_written": False,
            "historical_source_changed": False,
            "model_substitution": False,
            "notes": "Only JSON/XML/XMF metadata and the already-published PNG visualization products were read. H5/BI4/CSV/DAT/VTK payloads were not opened, copied, or hashed; no solver, conversion, render, or QI job was started.",
        },
        "future_work": {"no_new_render_or_solver_request": True, "root_must_decide_global_credit": True, "main_qi_is_separate": True},
    }

    decision_path = PKG / "metadata/personal-visual-decision.json"
    write_json(decision_path, decision)
    (PKG / "README.md").write_text(f"""# F6 fresh193 — assigned-F6 personal visual review of F2 RX063/ROT090 Root1143

This source-only package records the delegated F6 personal visual review of the already-produced F2 case `{CASE}` / physical case `{PHYS}`. F2 is the physical producer; F6 is the assigned handoff/reviewer family.

After Root1143 completed with return code 0 and atomically published the full 401-frame product, I personally viewed all 17 published chronological contact sheets (`all_frames_000.png` through `all_frames_016.png`) and all 9 published key frames (`0, 50, 100, 150, 200, 250, 300, 350, 400`) with `view_image`. The visible sequence starts with the gray tray/tank, orange moving/open-rim body, and blue fluid, then shows rotation/tilting, free-surface rise and splash, and broad late spreading along the fixed tray. I saw no obvious gross point-cloud explosion, abrupt blank interval, premature visual termination, or camera clipping. The late broad spread and detached points are visual observations only; they do not prove or disprove containment or explain missing UIDs.

Root1366 independently reports 401 states, N=418104, N3, actual time window 0.0 to 4.000030243152287 s, and initial counts fixed=372840, moving=24150, floating=0, fluid=21114. The producer terminal metadata reports fluid=21099, 15 final/max missing fluid particles, first missing frame 158, and 2278 cumulative particle-frame omissions; missing location/state/cause is unknown and the 8-ID sample is partial. Native canonical `{CANON}`, typed converter legacy `{LEGACY}`, XMF manifest physical converter scope `{LEGACY}`, XMF canonical-source scope `{CANON}`, and Root1366's absent source-plan physical field are separate roles. No scope value is filled across namespaces.

This visual screen grants no numerical precision, strict containment, sub-DP conclusion, Q-N/Q-E, production approval, or global case credit. No H5/BI4/CSV/DAT/VTK payload was opened or hashed and no job, shared registry, ledger, or source was changed.

Validate from this F6 worktree:

```sh
python3 scripts/validate_fresh193.py
```
""")

    manifest_out = {
        "schema": "ds02.f6.fresh193.package-manifest.v1",
        "fresh_id": "fresh193",
        "package_root": str(PKG),
        "source_only": True,
        "scientific_payloads_excluded": ["H5", "BI4", "CSV", "DAT", "VTK"],
        "visual_products_viewed": {"contact_sheets": 17, "key_frames": 9, "view_tool": "view_image"},
        "files": [],
    }
    for rel in ["README.md", "metadata/personal-visual-decision.json", "scripts/build_fresh193.py", "scripts/validate_fresh193.py"]:
        p = PKG / rel
        manifest_out["files"].append({"path": rel, "sha256": digest(p), "bytes": p.stat().st_size})
    write_json(PKG / "metadata/package-manifest.json", manifest_out)
    print(f"built {decision_path}")


if __name__ == "__main__":
    main()
