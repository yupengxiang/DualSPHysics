#!/usr/bin/env python3
"""Build the immutable fresh191 F6 handoff from F5 M100/T080 metadata.

This builder reads JSON/XML/XMF metadata and published PNG products only.  It
does not open, copy, or hash H5/BI4/CSV/DAT/VTK scientific payloads.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F5_WT = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")

CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M100_T080_NEXT34"
PHYS = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M100_T080"
CANON = "984f9d8cbf42e1845e1f86d86faf2a9a2d7bcf9cf9f7e6c0556c41b58edd6b68"
LEGACY = "385f4332b4fdbe7127caac5f2a891a3cbd554b57c2695eb2cb158902a456e332"
SOURCEDEF = "cb23c5396ffc7d9eb5a48f119e65915b22bd158eb1af2367a1645bca46f0a25c"

QI = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F5_M100T080_actual1157_full801_complete_UID_N3_bed_actual_native_XMF_"
    "SourceDef_namespace_previsual_QI_1350/actual1157-full801-independent-QI-UID-N3-"
    "bed-scope-previsual-proof.json"
)
MANIFEST = DATA / (
    "families/F5/" + CASE + "/"
    "root-stage1-f5-m100_t080-actual1028-full801-N3-xmf129-root1059/xmf/manifest.json"
)
RENDER_ROOT = DATA / (
    "families/F5/" + CASE + "/"
    "root-stage1-f5-m100_t080-actual1115-bed0-full801-original116023-frozen-progress-root1157"
)
RENDER_DIR = RENDER_ROOT / "render"
RENDER_RECEIPT = RENDER_ROOT / "execution-receipt.json"
REPORT = RENDER_DIR / "paraview-full-animation-report.json"
PUBLISH = RENDER_DIR / "render-publish-receipt.json"
PREDECESSOR = PKG.parent / "root_followup_190_f6_final48_complete_particle_rigid_primary_delivery_v1/metadata/final48-delivery.json"

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
    return {
        "path": str(p),
        "sha256": got,
        "bytes": p.stat().st_size,
        "kind": "metadata",
        "role": role,
    }


def png_ref(path: Path, producer: dict, role: str, **extra) -> dict:
    assert path.is_file(), path
    # PNGs are published visualization products.  Their producer digest is
    # copied and independently checked here; no scientific payload is opened.
    got = digest(path)
    assert got == producer["sha256"], (path, got, producer["sha256"])
    assert path.stat().st_size == producer["bytes"], (path, path.stat().st_size, producer["bytes"])
    out = {
        "path": str(path),
        "sha256": got,
        "bytes": path.stat().st_size,
        "kind": "visualization",
        "role": role,
        "viewed": True,
    }
    out.update(extra)
    return out


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n")


def main() -> None:
    qi = load(QI)
    manifest = load(MANIFEST)
    report = load(REPORT)
    publish = load(PUBLISH)
    render_receipt = load(RENDER_RECEIPT)
    qev = qi["actual_completed_metadata_evidence"]

    assert qi["case_id"] == CASE and qi["physical_case_id"] == PHYS
    assert qi["canonical_actual_native_request_condition_sha256"] == CANON
    assert qi["actual_converter_legacy_scope_sha256"] == LEGACY
    assert qi["actual_native_XMF_plan_field_namespaces"]["native"] == {
        "source_plan_condition_sha256": {"present": False, "value": None},
        "source_plan_physical_condition_sha256": {"present": True, "value": CANON},
    }
    assert qi["actual_native_XMF_plan_field_namespaces"]["XMF"] == {
        "source_plan_condition_sha256": {"present": False, "value": None},
        "source_plan_physical_condition_sha256": {"present": True, "value": CANON},
    }
    assert qi["bed_declared_source_plan_field_sha256"] == SOURCEDEF
    assert manifest["case_id"] == CASE and manifest["physical_case_id"] == PHYS
    assert manifest["physical_condition_sha256"] == CANON
    assert manifest["source_plan_physical_condition_sha256"] == CANON
    assert manifest["frames"] == 801 and manifest["particles"] == 194427
    assert report["frames"] == report["source_frames"] == 801
    assert report["all_frames_rendered"] is True
    assert publish["status"] == "published_after_atomic_rename"
    assert render_receipt["status"] == "completed" and render_receipt["returncode"] == 0

    # These are all metadata references.  Scientific payloads (H5/BI4/CSV/
    # DAT/VTK) are deliberately absent from this package.
    refs: dict[str, dict] = {}
    refs["main_qi_proof"] = metadata_ref(QI, "Root1350 independent full801 metadata QI proof")
    refs["gencase_receipt"] = metadata_ref(qev["gencase_receipt"]["path"], "actual genuine GenCase completed/0 receipt", qev["gencase_receipt"]["sha256"])
    refs["generated_xml"] = metadata_ref(qev["generated_xml"]["path"], "actual generated GenCase XML", qev["generated_xml"]["sha256"])
    refs["prepared_input_report"] = metadata_ref(manifest["prepared_input_report"], "actual prepared-input metadata report", manifest["prepared_input_report_sha256"])
    refs["initial_qa_receipt"] = metadata_ref(qev["initial_qa_receipt"]["path"], "actual initial placement QA completed/0 receipt", qev["initial_qa_receipt"]["sha256"])
    refs["initial_qa_report"] = metadata_ref(qev["initial_qa_report"]["path"], "actual initial placement QA diagnostic report", qev["initial_qa_report"]["sha256"])
    refs["native_request"] = metadata_ref(manifest["actual_native_request"], "actual full801 native request", manifest["actual_native_request_sha256"])
    refs["native_receipt"] = metadata_ref(qev["native_receipt"]["path"], "actual full801 native completed/0 receipt", qev["native_receipt"]["sha256"])
    refs["typed_request"] = metadata_ref(manifest["typed_request"], "actual typed request", manifest["typed_request_sha256"])
    refs["typed_report"] = metadata_ref(qev["typed_report"]["path"], "actual typed producer conversion report; legacy scope", qev["typed_report"]["sha256"])
    refs["typed_receipt"] = metadata_ref(qev["typed_receipt"]["path"], "actual typed completed/0 receipt", qev["typed_receipt"]["sha256"])
    refs["xmf_manifest"] = metadata_ref(qev["xmf_manifest"]["path"], "actual full801 N3 XMF manifest", qev["xmf_manifest"]["sha256"])
    refs["xmf_xml"] = metadata_ref(qev["xmf_xml"]["path"], "actual N3 XMF XML", qev["xmf_xml"]["sha256"])
    refs["xmf_receipt"] = metadata_ref(qev["xmf_receipt"]["path"], "actual N3 XMF completed/0 receipt", qev["xmf_receipt"]["sha256"])
    refs["source_definition"] = metadata_ref(qi["actual_SourceDef"]["path"], "registered bed SourceDef XML", SOURCEDEF)
    refs["bed_receipt"] = metadata_ref(qev["bed_receipt"]["path"], "actual bed diagnostic completed/0 receipt", qev["bed_receipt"]["sha256"])
    refs["bed_report"] = metadata_ref(qev["bed_report"]["path"], "actual bed diagnostic report", qev["bed_report"]["sha256"])
    refs["source_owner"] = metadata_ref(manifest["source_owner"], "source owner metadata", manifest["owner_metadata_sha256"])
    refs["source_plan"] = metadata_ref(manifest["source_plan"], "source plan metadata; not a native physical hash")
    refs["physical_binding"] = metadata_ref(manifest["binding"], "actual native/typed physical binding metadata", manifest["physical_binding_sha256"])

    # Render-side request and lineage paths are taken from the immutable render
    # receipt's input list, never guessed from a directory scan.
    render_inputs = render_receipt["request"]["input_files"]
    expected_inputs = render_receipt.get("input_hashes_at_launch", {})
    def input_by_suffix(suffix: str) -> str:
        matches = [p for p in render_inputs if p.endswith(suffix)]
        assert len(matches) == 1, (suffix, matches)
        return matches[0]
    bed_request = input_by_suffix("M100_T080-enabled-bed-request.json")
    refs["bed_request"] = metadata_ref(bed_request, "actual bed diagnostic request", expected_inputs.get(bed_request))
    for key, suffix, role in [
        ("render_wrapper", "enabled-render-wrapper.json", "actual enabled render wrapper"),
        ("render_binding", "registered-render-binding.json", "actual registered render binding"),
        ("render_lineage", "actual-bed0-to-render-input-lineage.json", "actual bed-to-render lineage"),
        ("render_frozen_progress", "completed-bed-progress-frozen.json", "frozen render progress metadata"),
        ("render_independent_review", "actual-full801-bed-UID-footprint-times-and-scope-independent-review.json", "actual independent render metadata review"),
    ]:
        p = input_by_suffix(suffix)
        refs[key] = metadata_ref(p, role, expected_inputs.get(p))
    command = render_receipt["request"]["command"]
    assert "--request" in command
    render_request_path = Path(command[command.index("--request") + 1])
    refs["render_request"] = metadata_ref(render_request_path, "actual full801 render request", expected_inputs.get(str(render_request_path)))
    refs["render_receipt"] = metadata_ref(RENDER_RECEIPT, "actual render completed/0 receipt", qev["render_receipt"]["sha256"])
    refs["render_report"] = metadata_ref(REPORT, "actual full801 ParaView report", qev["render_report"]["sha256"])
    refs["publish_receipt"] = metadata_ref(PUBLISH, "actual atomic PNG publication receipt", qev["render_publish_receipt"]["sha256"])

    # Historical binding is metadata only; preserve it without interpreting it
    # as the current native physical scope.
    hist_binding = qi["historical_negative_flags"]["original_binding"]
    refs["historical_original_binding"] = metadata_ref(hist_binding["path"], "historical original binding; provenance only", hist_binding["sha256"])

    files = {x["relative_path"]: x for x in publish["files_excluding_receipt"]}
    contacts = []
    for i in range(34):
        rel = f"all_frames_{i:03d}.png"
        contacts.append(png_ref(RENDER_DIR / rel, files[rel], "chronological contact sheet", sheet_index=i, frame_start=i * 24, frame_end=min(i * 24 + 23, 800)))
    keys = []
    for frame in [0, 100, 200, 300, 400, 500, 600, 700, 800]:
        rel = f"frames/frame_{frame:04d}.png"
        keys.append(png_ref(RENDER_DIR / rel, files[rel], "chronological key frame", frame=frame))

    predecessor = metadata_ref(PREDECESSOR, "immutable fresh190 final48 predecessor")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    decision = {
        "schema": "ds02.f6.fresh191.f5-personal-visual-review.v1",
        "fresh_id": "fresh191",
        "family_id": "F6",
        "assigned_family": "F6",
        "actual_family": "F5",
        "created_at_utc": now,
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "recursive_delegation": False,
        "reviewer": "/root/f6_endpoint_initial_qa",
        "scope": "F6 handoff only; delegated personal visual evidence for one already-produced F5 render",
        "predecessor": predecessor,
        "case": {
            "case_id": CASE,
            "physical_case_id": PHYS,
            "identity_role": "F5 physical producer case assigned to F6 only for delegated review; mother case_id and physical_case_id remain separate",
            "canonical_native_physical_condition_sha256": CANON,
            "actual_converter_legacy_scope_sha256": LEGACY,
            "bed_xmf_source_definition_scope_sha256": SOURCEDEF,
            "producer_scope_schema": "legacy-owner-scope.v0",
            "scope_roles": {
                "native_canonical_physical": CANON,
                "typed_actual_converter_legacy": LEGACY,
                "xmf_source_plan_physical_native_canonical": CANON,
                "bed_source_definition": SOURCEDEF,
                "native_source_plan_condition_sha256": None,
                "xmf_source_plan_condition_sha256": None,
                "native_source_plan_physical_condition_present": True,
                "xmf_source_plan_physical_condition_present": True,
                "native_source_plan_physical_condition_sha256": CANON,
                "xmf_source_plan_physical_condition_sha256": CANON,
                "bed_source_plan_physical_condition_sha256": SOURCEDEF,
                "native_plan_equals_xmf_plan": True,
                "native_or_xmf_plan_equals_SourceDef": False,
                "equality_claimed": False,
                "roles_remain_distinct": True,
                "absence_rule": "Condition-plan fields are absent/null in native and XMF; physical-plan fields are present with native canonical 984f...; the bed SourceDef cb23... and typed legacy 385f... remain separate roles.",
            },
            "source_plan_field_presence": {
                "native": {
                    "source_plan_condition_sha256": {"present": False, "value": None},
                    "source_plan_physical_condition_sha256": {"present": True, "value": CANON},
                },
                "xmf": {
                    "source_plan_condition_sha256": {"present": False, "value": None},
                    "source_plan_physical_condition_sha256": {"present": True, "value": CANON, "role": "native canonical physical namespace"},
                },
                "bed_source_definition": {
                    "source_plan_condition_sha256": {"present": False, "value": None},
                    "source_plan_physical_condition_sha256": {"present": True, "value": SOURCEDEF, "role": "registered bed/SourceDef namespace"},
                },
                "typed_legacy": {
                    "physical_scope_sha256": LEGACY,
                    "schema": "legacy-owner-scope.v0",
                    "status": "legacy_incomplete; no cross-resolution physical claim",
                },
            },
            "declared_counts": {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "total": 194427},
            "terminal_counts": {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "total": 194427},
            "dimension": 3,
            "expected_frames": 801,
            "nominal_save_interval_s": 0.02,
            "actual_time_s": [0.0, 16.00016351906116],
            "type_semantics": {
                "fixed": "gray fixed tank/bed boundary points; type 0",
                "moving": "orange prescribed driven boundary points; type 1; no floating body",
                "floating": "zero producer points; no floating-body mechanism is claimed; type 2",
                "fluid": "blue fluid/free-surface/runup points; type 3",
            },
            "mechanism_parameters": "F5 compact runup recovery: an orange driven boundary feeds/maintains blue fluid motion along the fixed bed/tank over the full 16 s window; the viewed response is weak/low-amplitude.",
            "mass_semantics": "Native/producer and continuum mass roles remain separate; this package applies no rescaling or normalization.",
            "historical_negative_flags": [
                "weak response retained",
                "historical A/B and sub-DP diagnostics retained",
                "exact-DP/precision negative retained",
                "bed 1DP/2DP bins are diagnostic only, not numerical acceptance thresholds",
            ],
        },
        "decision": {
            "status": "visual-approved-by-delegated-agent",
            "review_basis": "After Root1157 completed/0 and atomic publication, I personally viewed all 34 published chronological contact sheets and all 9 published key-frame PNGs with view_image.",
            "case_credit": 0,
            "global_acceptance": False,
            "main_process_qi": "evidence.main_qi_proof (Root1350 independent metadata QI; not claimed as this personal visual review)",
            "precision_status": "not accepted",
            "q_n_granted": False,
            "q_e_granted": False,
            "production_approval": False,
            "visual_scope": "delegated visual screening only; no numerical claim",
            "observations": {
                "initial_state": "Frame 0 shows the complete gray fixed tank/bed, a continuous blue fluid region, and the orange type-1 driven boundary. No red type-2 floating body is present, consistent with floating=0.",
                "mechanism": "Across the contacts and keys, the blue fluid/free surface evolves along the fixed bed while the orange driven boundary remains identifiable. The visible process is boundary-driven fluid/runup evolution, not a floating-body response.",
                "mid_event": "Mid-window views show continuous blue free-surface/runup changes with the gray fixed geometry coherent and visible. I saw no obvious gross point-cloud explosion or severe rigid-wall penetration.",
                "late_event": "Late contacts through frame 800 remain populated and geometrically consistent. I saw no abrupt visual termination, blank interval, or camera clipping; the response remains visually weak/low-amplitude.",
                "failure_screen": "No obvious severe visual failure was observed in the published 801-frame product: no gross clipping, catastrophic scatter, or early termination. This is a visual screen only.",
                "limits": "Floating-body behavior is not assessed because the producer has zero floating points. Visual inspection does not certify containment, sub-DP behavior, precision, Q-N, Q-E, or bed diagnostic thresholds. All native/XMF/typed/SourceDef scope distinctions and absent condition-plan fields remain as reported.",
            },
        },
        "producer_chain": {
            "gencase": {"receipt": "evidence.gencase_receipt", "generated_xml": "evidence.generated_xml", "prepared_report": "evidence.prepared_input_report", "terminal": "completed/0", "science_payload_read_or_hashed_by_agent": False},
            "initial_native_qa": {"receipt": "evidence.initial_qa_receipt", "report": "evidence.initial_qa_report", "terminal": "completed/0; placement diagnostic", "science_payload_read_or_hashed_by_agent": False},
            "native": {"request": "evidence.native_request", "receipt": "evidence.native_receipt", "terminal": "completed/0", "frames": 801, "dimension": 3, "counts": "declared and terminal counts above"},
            "typed": {"request": "evidence.typed_request", "report": "evidence.typed_report", "receipt": "evidence.typed_receipt", "terminal": "completed/0", "scope_role": f"{LEGACY} legacy-owner-scope.v0; separate from native {CANON}"},
            "xmf": {"manifest": "evidence.xmf_manifest", "xml": "evidence.xmf_xml", "receipt": "evidence.xmf_receipt", "terminal": "completed/0", "scope_role": f"{CANON} native canonical physical-plan namespace; SourceDef remains {SOURCEDEF}"},
            "bed": {"request": "evidence.bed_request", "report": "evidence.bed_report", "receipt": "evidence.bed_receipt", "terminal": "completed/0; diagnostic only"},
            "render": {"request": "evidence.render_request", "wrapper": "evidence.render_wrapper", "receipt": "evidence.render_receipt", "report": "evidence.render_report", "publish_receipt": "evidence.publish_receipt", "terminal": "completed/0 and atomically published", "renderer_sha256": "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"},
        },
        "evidence": refs,
        "visual_review": {
            "personally_viewed_with": "view_image",
            "reviewed_at_utc": now,
            "contact_sheet_count": 34,
            "contact_sheets": contacts,
            "key_frame_count": 9,
            "key_frames": keys,
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
            "notes": "Only JSON/XML/XMF metadata and published PNG visualization products were read. H5/BI4/CSV/DAT/VTK payloads were not opened, copied, or hashed; no render/solver/QI job was started.",
        },
        "future_work": {
            "no_new_render_or_solver_request": True,
            "root_must_decide_global_credit": True,
            "main_qi_is_separate": True,
        },
    }

    decision_path = PKG / "metadata/personal-visual-decision.json"
    write_json(decision_path, decision)
    readme = f"""# F6 fresh191 — assigned-F6 personal visual review of F5 M100/T080 Root1157

This source-only package records a delegated F6 personal visual review of the already-produced F5 case `{CASE}` / physical case `{PHYS}`. The physical producer is F5; the assignment and handoff are F6. Root1157 completed with return code 0 and atomically published the full 801-frame product.

I personally viewed all 34 published chronological contact sheets (`all_frames_000.png` through `all_frames_033.png`) and all 9 published key frames (`0, 100, 200, 300, 400, 500, 600, 700, 800`) with `view_image`. The sequence shows the gray fixed tank/bed, orange type-1 driven boundary, and blue fluid. The blue fluid remains in the channel and evolves gradually over the full 16 s window. I saw no obvious camera clipping, gross wall penetration, catastrophic point-cloud explosion, blank interval, or premature visual termination. Moving points are the driven boundary; floating is zero, so no floating-body response is inferred.

Producer counts are fixed=158559, moving=4210, floating=0, fluid=31658, total=194427, dimension=3, and 801 saved states. Root1350 is referenced as the separate full801 metadata QI. Scope roles are preserved exactly: native canonical `{CANON}`, typed converter legacy `{LEGACY}`, XMF/native physical-plan `{CANON}`, and bed SourceDef `{SOURCEDEF}`. Native and XMF condition-plan fields are absent/null; their physical-plan fields are present with the native canonical value. The bed SourceDef and typed legacy values are separate namespaces, and no mass rescaling or normalization is applied.

This delegated visual screen grants no numerical precision, strict containment, sub-DP conclusion, Q-N/Q-E, production approval, or global case credit. Historical weak-response/A-B/precision-negative evidence remains intact. No H5/BI4/CSV/DAT/VTK payload was opened or hashed and no job, shared registry, ledger, or source was changed.

Validate from this F6 worktree:

```sh
python3 scripts/validate_fresh191.py
```
"""
    (PKG / "README.md").write_text(readme)

    manifest_out = {
        "schema": "ds02.f6.fresh191.package-manifest.v1",
        "fresh_id": "fresh191",
        "package_root": str(PKG),
        "source_only": True,
        "scientific_payloads_excluded": ["H5", "BI4", "CSV", "DAT", "VTK"],
        "files": [],
    }
    # Manifest excludes itself to avoid a self-hash cycle.
    for p in sorted(PKG.rglob("*")):
        if not p.is_file() or p.name == "package-manifest.json":
            continue
        manifest_out["files"].append({
            "path": str(p.relative_to(PKG)),
            "sha256": digest(p),
            "bytes": p.stat().st_size,
        })
    write_json(PKG / "metadata/package-manifest.json", manifest_out)
    print(f"built {decision_path}")
    print(f"contacts={len(contacts)} keys={len(keys)} metadata_refs={len(refs)}")


if __name__ == "__main__":
    main()
