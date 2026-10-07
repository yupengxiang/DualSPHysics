#!/usr/bin/env python3
"""Build the fresh183 F2 RX049/ROT075 personal visual-review handoff.

The source agent reads only JSON/XML/XMF/Python/Markdown metadata and stats
the already published PNGs.  PNG digests are copied from the immutable render
publish receipt; this builder never opens or hashes PNG/H5/BI4/CSV/DAT/VTK
payloads.  The visual statements in the decision record reflect the 17
contact sheets and nine key frames personally opened with ``view_image``.
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
    "root_stage1_F2_RX049ROT075_actual1009_full401_UID_N3_times_"
    "nativecanonical_typedlegacy_thirtyfive_fluid_omissions_actual_plan_"
    "namespaces_previsual_QI_1392/"
    "actual1009-full401-own-QI-UID-N3-native-typed-role-thirtyfive-"
    "fluid-omissions-previsual-proof.json"
)
CASE = "F2_STAGE1_FIRST48_EXPANSION_RX049_RY014_FILL080_ROT075_DP010_SPATIAL_REFERENCE_SAVE010"
PHYSICAL = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075"
CANONICAL = "27f952a271ff237e6fe2d09e21047786476f1ce9ad5157c94847097187026fa6"
LEGACY = "208d547c388db7caed982f1d088baf6fb942b46e48e4f8552a0e0cfe21cf1f9b"
FRAMES = 401
PARTICLES = 418104
INITIAL_COUNTS = {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114, "total": 418104}
TERMINAL_COUNTS = {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21079, "total": 418069}
TIME_WINDOW = [0.0, 4.00006189848381]
KEY_FRAMES = (0, 50, 100, 150, 200, 250, 300, 350, 400)
CONTACT_COUNT = 17
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EVIDENCE_KEYS = (
    "native_receipt", "initial_qa_receipt", "initial_qa_report",
    "typed_receipt", "typed_report", "XMF_receipt", "XMF_manifest",
    "XMF_XML", "render_receipt", "render_report", "render_publish_receipt",
    "typed_source_gencase_receipt", "typed_source_generated_xml",
    "typed_source_owner_metadata", "prior_full401_scientific_integrity_review",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"JSON read attempted for non-JSON {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {label}: {path}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"}:
        fail(f"unsupported metadata hash for {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        read_json(path, role)
    elif path.suffix.lower() not in {".xml", ".xmf"}:
        fail(f"metadata reference is not JSON/XML: {role}: {path}")
    return {"path": str(path), "sha256": metadata_sha(path, role), "role": role}


def evidence_ref(qi: dict[str, Any], key: str, role: str, *, receipt: bool = False) -> dict[str, Any]:
    item = qi.get("actual_completed_metadata_evidence", {}).get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"missing QI evidence {key}")
    path = Path(item["path"])
    actual = metadata_sha(path, role)
    if actual != item.get("sha256"):
        fail(f"QI SHA mismatch for {role}: {path}")
    result = metadata_ref(path, role)
    result["qi_declared_sha256"] = item["sha256"]
    if receipt:
        value = read_json(path, role)
        if value.get("status") != "completed" or value.get("returncode") != 0:
            fail(f"{role} is not completed/0")
        req = value.get("request")
        if isinstance(req, dict):
            if req.get("case_id") not in (None, CASE):
                fail(f"{role} case mismatch")
            if req.get("physical_case_id") not in (None, PHYSICAL):
                fail(f"{role} physical case mismatch")
        result.update({
            "status": value.get("status"),
            "returncode": value.get("returncode"),
            "attempt_id": req.get("attempt_id") if isinstance(req, dict) else None,
            "receipt_scope": req.get("physical_condition_sha256") if isinstance(req, dict) else None,
        })
    return result


def png_index(publish: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt has no files_excluding_receipt")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str):
            fail("malformed producer PNG entry")
        result[entry["relative_path"]] = entry
    return result


def published_png_ref(publish: dict[str, Any], index: dict[str, dict[str, Any]], relative: str, role: str) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    entry = index.get(relative)
    if entry is None:
        fail(f"{role} absent from producer receipt: {relative}")
    path = root / relative
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    # stat only: the declared digest belongs to the renderer receipt.
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
        "content_read_or_hashed_by_reviewer": False,
        "role": role,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build() -> Path:
    qi = read_json(QI, "Root1392 own QI")
    if qi.get("case_id") != CASE or qi.get("physical_case_id") != PHYSICAL:
        fail("QI identity mismatch")
    if qi.get("frames") != FRAMES or qi.get("particles") != PARTICLES:
        fail("QI dimensions mismatch")
    if qi.get("actual_time_window_s") != TIME_WINDOW:
        fail("QI time window mismatch")
    if qi.get("native_canonical_condition_sha256") != CANONICAL or qi.get("typed_XMF_actual_legacy_producer_condition_sha256") != LEGACY:
        fail("QI scope mismatch")
    if qi.get("all401_UID_axis_identity_N3_finite_active_states_native_actual_times_verified") is not True:
        fail("QI does not attest actual N3/time/finite identity")
    if qi.get("native_scientific_payloads_not_read_or_hashed_by_main") is not True:
        fail("QI scientific access boundary missing")

    refs = {}
    receipt_keys = {"native_receipt", "initial_qa_receipt", "typed_receipt", "XMF_receipt", "render_receipt", "render_publish_receipt", "typed_source_gencase_receipt"}
    for key in EVIDENCE_KEYS:
        if key == "prior_full401_scientific_integrity_review":
            prior = qi.get(key)
            if not isinstance(prior, dict) or not isinstance(prior.get("path"), str):
                fail("missing prior full401 review reference")
            prior_path = Path(prior["path"])
            if metadata_sha(prior_path, "prior full401 review") != prior.get("sha256"):
                fail("prior full401 review SHA mismatch")
            refs[key] = metadata_ref(prior_path, "prior full401 review")
            refs[key]["qi_declared_sha256"] = prior["sha256"]
        else:
            refs[key] = evidence_ref(qi, key, f"QI evidence {key}", receipt=key in receipt_keys and key != "render_publish_receipt")
    # render_publish_receipt is a publish record, not a runner receipt.
    publish_path = Path(refs["render_publish_receipt"]["path"])
    publish = read_json(publish_path, "render publish receipt")
    if publish.get("status") != "published_after_atomic_rename":
        fail("render is not atomically published")
    report = read_json(Path(refs["render_report"]["path"]), "render report")
    manifest = read_json(Path(refs["XMF_manifest"]["path"]), "XMF manifest")
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES or report.get("all_frames_rendered") is not True:
        fail("render report is not full 401")
    if report.get("actual_times_preserved_exactly") is not True:
        fail("render report does not preserve actual times")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostics are not 401 rows")
    times = []
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i:
            fail("render frame index is not contiguous")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail("render finite/identity evidence missing")
        finite = row.get("finite_fields")
        if not isinstance(finite, dict) or any(finite.get(n, {}).get("finite_active") is not True for n in ("density", "mass", "pressure", "velocity")):
            fail("render finite field evidence missing")
        if not isinstance(row.get("missing"), int) or row["missing"] < 0:
            fail("render missing count malformed")
        times.append(row.get("actual_time_s"))
    if times[0] != TIME_WINDOW[0] or times[-1] != TIME_WINDOW[1]:
        fail("render time endpoints differ from QI")
    if report.get("manifest_sha256") != refs["XMF_manifest"]["sha256"]:
        fail("render report manifest binding differs")
    if manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF dimensions mismatch")
    if manifest.get("physical_condition_sha256") != LEGACY or manifest.get("canonical_source_physical_condition_sha256") != CANONICAL:
        fail("XMF canonical/legacy role mismatch")
    if manifest.get("actual_converter_legacy_scope_sha256") != LEGACY:
        fail("XMF legacy scope mismatch")
    if publish.get("report_sha256_after_rebind") != refs["render_report"]["sha256"]:
        fail("publish report binding differs")
    if publish.get("case_id") != CASE or publish.get("attempt_id") != refs["render_receipt"].get("attempt_id"):
        fail("publish identity mismatch")

    index = png_index(publish)
    outputs = report.get("outputs", {})
    contact_paths = outputs.get("contact_sheets")
    if not isinstance(contact_paths, list) or len(contact_paths) != CONTACT_COUNT:
        fail("render report contact count mismatch")
    root = Path(str(publish["published_output_root"]))
    contacts = []
    for i, absolute in enumerate(contact_paths):
        path = Path(absolute)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            fail("contact path is outside published root")
        contacts.append(published_png_ref(publish, index, relative, f"contact_{i:02d}"))
    keys = [published_png_ref(publish, index, f"frames/frame_{frame:04d}.png", f"key_{frame:04d}") for frame in KEY_FRAMES]

    now = datetime.now(timezone.utc).isoformat()
    omission = qi["lifecycle_omissions"]
    decision = {
        "schema": "ds02.f3.fresh183.personal-visual-review.v1",
        "fresh_id": "fresh183",
        "review_completed_at_utc": now,
        "configured_model": "gpt-5.6-luna/max",
        "model_substitution": False,
        "recursive_delegation": False,
        "assigned_worktree_family": "F3",
        "actual_case_family": "F2",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "physical_condition_roles": {
            "native_canonical_condition_sha256": CANONICAL,
            "typed_legacy_converter_scope_sha256": LEGACY,
            "xmf_physical_condition_sha256": manifest.get("physical_condition_sha256"),
            "xmf_canonical_source_physical_condition_sha256": manifest.get("canonical_source_physical_condition_sha256"),
            "xmf_actual_converter_legacy_scope_sha256": manifest.get("actual_converter_legacy_scope_sha256"),
            "native_and_xmf_plan_fields": qi.get("actual_native_XMF_plan_field_namespaces"),
            "interpretation": "Native canonical, typed/XMF legacy, and source-plan namespaces remain separate; absent fields are not backfilled.",
        },
        "actual_dimensions": {
            "frames": FRAMES,
            "particles": PARTICLES,
            "initial_type_counts": INITIAL_COUNTS,
            "terminal_type_counts": TERMINAL_COUNTS,
            "vector_shape": "N x 3",
            "time_window_s": TIME_WINDOW,
            "actual_uid_axis": "Producer QI verifies N3/finite identity; terminal lifecycle omissions remain explicit.",
        },
        "lifecycle_omissions": omission,
        "actual_chain": refs,
        "producer_attestation": {
            "source_h5_sha256": report.get("source_h5_sha256"),
            "source_h5_opened_or_hashed_by_reviewer": False,
            "native_input_launch_after_digest_equality": True,
            "genuine_initial_qa_receipt_completed0": qi.get("genuine_initial_QA_receipt_completed0_and_report_pass"),
            "root_qi_is_independent_proof_not_runner_receipt": qi.get("root_QI_is_independent_proof_not_runner_receipt"),
        },
        "historical_outer_envelope": {
            "outer_request_expected_frames": qi.get("original_outer_expected_fields_preserved_not_authority", {}).get("expected_frames"),
            "outer_request_expected_particles": qi.get("original_outer_expected_fields_preserved_not_authority", {}).get("expected_particles"),
            "actual_loaded_wrapper_expected_frames": qi.get("actual_loaded_wrapper_expected_fields", {}).get("expected_frames"),
            "actual_loaded_wrapper_expected_particles": qi.get("actual_loaded_wrapper_expected_fields", {}).get("expected_particles"),
            "authority": "The completed 401-frame loaded wrapper and published reports are authoritative; the old 801/194427 envelope remains historical metadata.",
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "Personally viewed all published contact sheets and selected key frames with view_image after completed/0 and atomic publish.",
            "contact_sheets_viewed": CONTACT_COUNT,
            "key_frames_viewed": list(KEY_FRAMES),
            "observations": [
                "All 17 contact sheets and nine key frames rendered correctly and were visually inspectable.",
                "The sequence shows a coherent initial state, onset of motion around the open rim, downstream spreading, and a continuous late-time flow without abrupt truncation.",
                "Small detached or sprayed blue points are visible in later phases and are retained as an observation; they are consistent with the producer-reported lifecycle omissions but are not reclassified here.",
                "No obvious blank/corrupt frame, whole-domain explosion, unexplained abrupt stop, or gross display-level breakup was observed.",
            ],
            "physical_screen_limits": [
                "This is a first-stage visual screen only; it does not establish numerical precision, strict containment, sub-DP behavior, run-up magnitude, Q-N, Q-E, or production acceptance.",
                "The 35 terminal fluid omissions, first missing frame, cumulative omission count, partial sample, and unknown cause/location remain unchanged.",
                "Visual inspection does not infer missing-particle identities, conservation, or numerical truth.",
            ],
            "scientific_payload_opened_or_hashed_by_reviewer": False,
            "scientific_jobs_started_or_restarted": False,
            "shared_state_modified": False,
            "case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
            "precision_status": "not_accepted",
        },
        "visual_evidence": {"contacts": contacts, "keys": keys},
        "provenance": {
            "qi_proof": {"path": str(QI), "sha256": metadata_sha(QI, "Root1392 QI"), "role": "independent completed/0 QI"},
            "qi_at_utc": qi.get("at_utc"),
            "publisher_png_sha_source": "immutable render-publish-receipt.json; declared SHA copied, PNG content not hashed by reviewer",
            "review_timestamp_source": "recorded after the completed personal view_image session",
        },
    }
    decision_path = HERE / "metadata/actual1009-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual1009.json"
    write_json(decision_path, decision)
    write_json(png_path, {
        "schema": "ds02.f3.fresh183.png-evidence.v1",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "contacts": contacts,
        "keys": keys,
        "all_paths_stat_checked": True,
        "personally_viewed_after_atomic_publish": True,
        "content_read_or_hashed_by_reviewer": False,
        "declared_sha_source": "render-publish-receipt.json",
    })
    files = [HERE / "README.md", HERE / "build_fresh183.py", HERE / "validate_fresh183.py", decision_path, png_path]
    write_json(HERE / "package-manifest.json", {
        "schema": "ds02.f3.fresh183.package-manifest.v1",
        "fresh_id": "fresh183",
        "package_manifest_excluded_from_own_hash": True,
        "files": [{"path": str(p.relative_to(HERE)), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
    })
    return decision_path


if __name__ == "__main__":
    print(build())
