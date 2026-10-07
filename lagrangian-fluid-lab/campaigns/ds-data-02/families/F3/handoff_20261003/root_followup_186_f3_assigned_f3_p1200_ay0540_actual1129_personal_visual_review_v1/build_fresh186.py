#!/usr/bin/env python3
"""Build the fresh186 F3 P1200/AY0540 personal visual-review handoff.

The builder consumes JSON/XML/XMF metadata and filesystem statistics for the
already completed and atomically published render.  It never opens or hashes
H5/BI4/CSV/DAT/VTK scientific payloads.  PNG SHA values are copied from the
immutable producer publish receipt; PNG bytes are only stat-checked here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F3_P1200AY0540_actual1129_full836_UID_N3_time_actual_native_both_plan_absent_XMF_"
    "condition_plan_present_previsual_QI_1411/"
    "actual1129-full836-completed-QI-UID-N3-native-scope-previsual-proof.json"
)
QI_SHA = "29ed8957714020185511e7cf202bd01f0fab2922b87e6a9fd4344d1bff5e3352"
CASE = "F3_STAGE1_DP006_P1200_AY0540"
PHYSICAL = "F3_TWOAXIS_P1200_AY0540_STAGE1_FIRST48_PITCH_VARIANT"
CANONICAL = "02c172c6742f50817771e41c6adef8703641b9179dc022859a1ed6a9b2a9b2f3"
FRAMES = 836
PARTICLES = 179208
TIME_WINDOW = [0.0, 8.350014835784549]
KEY_FRAMES = (0, 104, 208, 312, 417, 521, 626, 730, 835)
CONTACT_COUNT = 35
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json" or not path.is_file():
        fail(f"invalid JSON for {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON for {label}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"} or not path.is_file():
        fail(f"invalid metadata reference for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str, declared: str | None = None) -> dict[str, Any]:
    actual = metadata_sha(path, role)
    if declared is not None and actual != declared:
        fail(f"metadata SHA mismatch for {role}: {path}")
    if path.suffix.lower() == ".json":
        read_json(path, role)
    return {"path": str(path), "sha256": actual, "role": role}


def receipt_ref(item: dict[str, Any], role: str, *, exact_identity: bool = True) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"missing receipt reference: {role}")
    path = Path(item["path"])
    ref = metadata_ref(path, role, item.get("sha256"))
    obj = read_json(path, role)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{role} is not completed/0")
    req = obj.get("request")
    if exact_identity and isinstance(req, dict):
        if req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL):
            fail(f"{role} identity mismatch")
    ref.update({
        "status": obj.get("status"),
        "returncode": obj.get("returncode"),
        "finished_at_utc": obj.get("finished_at_utc"),
        "attempt_id": req.get("attempt_id") if isinstance(req, dict) else None,
    })
    return ref


def evidence_ref(qi: dict[str, Any], key: str, role: str, *, receipt: bool = False, exact_identity: bool = False) -> dict[str, Any]:
    item = qi.get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"missing QI reference {key}")
    path = Path(item["path"])
    ref = metadata_ref(path, role, item.get("sha256"))
    if receipt:
        obj = read_json(path, role)
        if obj.get("status") != "completed" or obj.get("returncode") != 0:
            fail(f"{role} is not completed/0")
        req = obj.get("request")
        if exact_identity and isinstance(req, dict) and (
            req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL)
        ):
            fail(f"{role} identity mismatch")
        ref.update({"status": obj.get("status"), "returncode": obj.get("returncode")})
    return ref


def png_index(publish: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt has no files_excluding_receipt")
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str):
            fail("malformed published-file entry")
        out[entry["relative_path"]] = entry
    return out


def published_png_ref(
    publish: dict[str, Any], index: dict[str, dict[str, Any]], relative: str, role: str
) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    entry = index.get(relative)
    if entry is None:
        fail(f"{role} absent from publish receipt: {relative}")
    path = root / relative
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    if path.stat().st_size != entry.get("bytes"):
        fail(f"{role} producer byte count changed: {path}")
    return {
        "path": str(path),
        "relative_path": relative,
        "bytes": entry.get("bytes"),
        "declared_sha256": entry.get("sha256"),
        "sha256_source": "render_publish_receipt",
        "stat_checked": True,
        "personally_viewed_with_view_image": True,
        "png_bytes_read_or_hashed_by_reviewer": False,
        "role": role,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build() -> Path:
    qi = read_json(QI, "Root1401 own QI")
    if metadata_sha(QI, "Root1401 own QI") != QI_SHA:
        fail("Root1401 QI SHA changed")
    if qi.get("case_id") != CASE or qi.get("physical_case_id") != PHYSICAL:
        fail("QI identity mismatch")
    if qi.get("native_request_condition_sha256") != CANONICAL or qi.get("actual_converter_condition_sha256") != CANONICAL:
        fail("QI canonical condition mismatch")
    if qi.get("actual_time_window_s") != TIME_WINDOW:
        fail("QI time window mismatch")
    if qi.get("all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified") is not True:
        fail("QI does not attest full836/N3/time sequence/native fields")
    if qi.get("all_native_UIds_active_each_frame") is not True:
        fail("QI does not attest UID lifecycle")
    if qi.get("new_case_credit") != 0 or qi.get("q_n_granted") is not False or qi.get("q_e_granted") is not False:
        fail("QI credit/qualification boundary changed")

    chain: dict[str, Any] = {}
    for name, item in qi.get("actual_completed_receipts", {}).items():
        chain[f"{name}_receipt"] = receipt_ref(item, f"actual {name} receipt", exact_identity=True)
    for name in ("typed_report", "XMF_manifest", "XMF_XML"):
        item = qi.get(name)
        if not isinstance(item, dict):
            fail(f"missing QI metadata reference {name}")
        chain[name] = metadata_ref(Path(item["path"]), f"QI {name}", item.get("sha256"))
    chain["render_report"] = evidence_ref(qi, "render_report", "actual render report")
    chain["publish"] = evidence_ref(qi, "publish", "actual atomic publish receipt")
    parent_refs = {
        "initial_parent_QA_report": "initial parent QA report",
        "initial_parent_QA_receipt": "initial parent QA receipt",
        "source_preparation_report": "actual source preparation report",
    }
    for key, role in parent_refs.items():
        chain[key] = evidence_ref(qi, key, role, receipt=key.endswith("receipt"), exact_identity=False)

    render_report = read_json(Path(chain["render_report"]["path"]), "render report")
    render_receipt = read_json(Path(chain["render_receipt"]["path"]), "render receipt")
    publish = read_json(Path(chain["publish"]["path"]), "render publish receipt")
    manifest = read_json(Path(chain["XMF_manifest"]["path"]), "XMF manifest")
    req = render_receipt.get("request", {})
    if publish.get("status") != "published_after_atomic_rename":
        fail("render is not atomically published")
    if publish.get("case_id") != CASE or publish.get("attempt_id") != req.get("attempt_id"):
        fail("publish identity mismatch")
    if render_report.get("frames") != FRAMES or render_report.get("source_frames") != FRAMES:
        fail("render frame count mismatch")
    if render_report.get("all_frames_rendered") is not True or render_report.get("actual_times_preserved_exactly") is not True:
        fail("render full-time metadata missing")
    if render_report.get("manifest_sha256") != chain["XMF_manifest"]["sha256"]:
        fail("render-to-XMF manifest SHA mismatch")
    diagnostics = render_report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostics are not 836 rows")
    times: list[float] = []
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i:
            fail(f"frame {i} identity missing")
        if row.get("active") != PARTICLES or row.get("missing") != 0:
            fail(f"frame {i} UID lifecycle differs")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail(f"frame {i} finite/N3 identity metadata missing")
        finite = row.get("finite_fields")
        if not isinstance(finite, dict) or any(
            not isinstance(finite.get(name), dict) or finite[name].get("finite_active") is not True
            for name in ("density", "mass", "pressure", "velocity")
        ):
            fail(f"frame {i} finite field metadata missing")
        t = row.get("actual_time_s")
        if not isinstance(t, (int, float)):
            fail(f"frame {i} actual time missing")
        times.append(float(t))
    if times[0] != TIME_WINDOW[0] or times[-1] != TIME_WINDOW[1] or any(b <= a for a, b in zip(times, times[1:])):
        fail("render time sequence differs from own QI")
    if manifest.get("case_id") != CASE or manifest.get("physical_case_id") != PHYSICAL:
        fail("XMF manifest identity mismatch")
    if manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF manifest dimensions mismatch")
    if manifest.get("physical_condition_sha256") != CANONICAL or manifest.get("actual_converter_scope_sha256") != CANONICAL:
        fail("XMF canonical scope mismatch")
    plan_masks = {
        name: {
            "present": name in manifest,
            "value": manifest.get(name),
        }
        for name in ("source_plan_condition_sha256", "source_plan_physical_condition_sha256")
    }
    expected_plan_masks = {
        "source_plan_condition_sha256": {
            "present": True,
            "value": "5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075",
        },
        "source_plan_physical_condition_sha256": {"present": False, "value": None},
    }
    if plan_masks != expected_plan_masks:
        fail("XMF source-plan namespace mask/value changed")
    if publish.get("report_sha256_after_rebind") != chain["render_report"]["sha256"]:
        fail("publish report binding mismatch")

    index = png_index(publish)
    outputs = render_report.get("outputs", {})
    contact_paths = outputs.get("contact_sheets")
    if not isinstance(contact_paths, list) or len(contact_paths) != CONTACT_COUNT:
        fail("render report contact count mismatch")
    root = Path(str(publish.get("published_output_root", "")))
    contacts: list[dict[str, Any]] = []
    for i, absolute in enumerate(contact_paths):
        path = Path(absolute)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            fail("contact path outside published root")
        contacts.append(published_png_ref(publish, index, relative, f"contact_{i:02d}"))
    keys = [published_png_ref(publish, index, f"frames/frame_{frame:04d}.png", f"key_{frame:04d}") for frame in KEY_FRAMES]

    plan_namespace = qi.get("actual_native_XMF_plan_field_namespaces")
    now = datetime.now(timezone.utc).isoformat()
    decision = {
        "schema": "ds02.f3.fresh186.personal-visual-review.v1",
        "fresh_id": "fresh186",
        "review_completed_at_utc": now,
        "configured_model": "gpt-5.6-luna/max",
        "model_substitution": False,
        "recursive_delegation": False,
        "assigned_worktree_family": "F3",
        "actual_case_family": "F3",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "physical_condition_roles": {
            "native_canonical_condition_sha256": CANONICAL,
            "typed_legacy_converter_scope_sha256": CANONICAL,
            "xmf_physical_condition_sha256": manifest.get("physical_condition_sha256"),
            "native_and_xmf_plan_field_namespaces": plan_namespace,
            "native_source_plan_condition_field": {
                "present": qi.get("native_source_plan_condition_field_present"),
                "value": qi.get("native_source_plan_condition_field_value"),
            },
            "native_source_plan_physical_condition_field": {
                "present": qi.get("native_source_plan_physical_condition_field_present"),
                "value": qi.get("native_source_plan_physical_condition_field_value"),
            },
            "xmf_source_plan_condition_field": {
                "present": qi.get("XMF_source_plan_condition_field_present"),
                "value": qi.get("XMF_source_plan_condition_field_value"),
            },
            "xmf_source_plan_physical_condition_field": {
                "present": qi.get("XMF_source_plan_physical_condition_field_present"),
                "value": qi.get("XMF_source_plan_physical_condition_field_value"),
            },
            "manifest_observed_plan_field_masks": plan_masks,
            "source_definition_role": "not inferred from absent native/XMF plan fields",
            "interpretation": "Native, typed, and XMF carry the same canonical physical digest for this case but remain separate namespace roles; native source-plan fields are absent/null, while XMF exposes only the source-plan condition digest and leaves source-plan physical condition absent. No plan field is backfilled from the canonical digest.",
        },
        "actual_dimensions": {
            "frames": FRAMES,
            "particles": PARTICLES,
            "vector_shape": "N x 3",
            "time_window_s": TIME_WINDOW,
            "all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified": qi.get("all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"),
            "all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified": qi.get("all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"),
            "all_native_UIds_active_each_frame": qi.get("all_native_UIds_active_each_frame"),
            "render_type_counts_frame0": diagnostics[0].get("type_counts_active"),
            "render_type_counts_last_frame": diagnostics[-1].get("type_counts_active"),
            "old_outer_envelope": qi.get("original_outer_frame_envelope_preserved_actual_wrapper836_and35_contacts"),
        },
        "precision_and_limits": {
            "numerical_precision_status": "not accepted",
            "q_n_granted": False,
            "q_e_granted": False,
            "case_credit": 0,
            "limits": [
                "Visual first-stage screen only; no numerical precision, strict containment, sub-DP, or production claim.",
                "No particle conservation or missing-particle identity is inferred from images.",
                "The historical outer 801/194427 envelope is retained as metadata and is not used as the actual 836/179208 authority.",
            ],
        },
        "actual_chain": chain,
        "producer_attestation": {
            "render_report_source_h5_sha256": render_report.get("source_h5_sha256"),
            "source_h5_sha256_source": "producer render report",
            "source_h5_opened_or_hashed_by_reviewer": False,
            "root_qi_is_independent_proof_not_runner_receipt": True,
            "genuine_receipts_completed0": True,
            "atomic_publish_status": publish.get("status"),
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "Personally viewed all 35 published contact sheets and nine requested key frames with view_image after the completed/0 receipt, atomic publish, and own QI were available.",
            "contact_sheets_viewed": CONTACT_COUNT,
            "key_frames_viewed": list(KEY_FRAMES),
            "observations": [
                "The full sequence is visually continuous from the shallow initial layer through crest growth, downstream spreading, decay, and late-time reformation.",
                "The inspected views show a coherent blue particle layer and smooth large-scale evolution; no blank/corrupt frame, abrupt truncation, or whole-domain explosion was observed.",
                "Fine edge speckling in the point rendering is recorded only as a display observation and is not reclassified against the producer UID/lifecycle metadata.",
                "No obvious severe visible wall/tank breach was observed at the published view scale; this is not a strict containment or numerical claim.",
            ],
            "physical_screen_limits": [
                "This is a visual screen only and does not establish numerical precision, strict containment, sub-DP behavior, forcing fidelity, or production acceptance.",
                "Producer finite/UID/N3 and time evidence remain metadata evidence; the reviewer did not reopen or hash scientific payloads.",
            ],
            "precision_status": "not_accepted",
            "png_files_opened_with_view_image": True,
            "png_bytes_read_or_hashed_by_reviewer": False,
            "scientific_payload_opened_or_hashed_by_reviewer": False,
            "scientific_jobs_started_or_restarted": False,
            "shared_state_modified": False,
            "case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
        },
        "visual_evidence": {"contacts": contacts, "keys": keys},
        "provenance": {
            "qi_proof": {"path": str(QI), "sha256": QI_SHA, "role": "independent completed/0 own QI"},
            "qi_main_commit": "58d810e9a8cb98b759d5289f4feac80f69f56460",
            "publisher_png_sha_source": "immutable render-publish-receipt.json; declared SHA copied, PNG bytes not hashed by reviewer",
            "review_timestamp_source": "recorded after the completed personal view_image session",
        },
    }
    decision_path = HERE / "metadata/actual1129-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual1129.json"
    write_json(decision_path, decision)
    write_json(
        png_path,
        {
            "schema": "ds02.f3.fresh186.png-evidence.v1",
            "case_id": CASE,
            "physical_case_id": PHYSICAL,
            "contacts": contacts,
            "keys": keys,
            "all_paths_stat_checked": True,
            "personally_viewed_after_atomic_publish_and_own_qi": True,
            "png_bytes_read_or_hashed_by_reviewer": False,
            "declared_sha_source": "render-publish-receipt.json",
        },
    )
    files = [HERE / "README.md", HERE / "build_fresh186.py", HERE / "validate_fresh186.py", decision_path, png_path]
    write_json(
        HERE / "package-manifest.json",
        {
            "schema": "ds02.f3.fresh186.package-manifest.v1",
            "fresh_id": "fresh186",
            "package_manifest_excluded_from_own_hash": True,
            "files": [
                {"path": str(path.relative_to(HERE)), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in files
            ],
        },
    )
    return decision_path


if __name__ == "__main__":
    print(build())
