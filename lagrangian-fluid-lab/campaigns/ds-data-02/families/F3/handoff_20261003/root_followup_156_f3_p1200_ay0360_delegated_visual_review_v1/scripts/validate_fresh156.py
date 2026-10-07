#!/usr/bin/env python3
"""Validate fresh156 metadata and PNG review evidence without scientific payload IO."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
CASE = "F3_STAGE1_DP006_P1200_AY0360"
PHYSICAL = "F3_TWOAXIS_P1200_AY0360_STAGE1_FIRST48_PITCH_VARIANT"
FORBIDDEN_PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}


def read_json(path: Path):
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message: str):
    raise AssertionError(message)


def assert_metadata_ref(ref, expected_kind=None):
    path = Path(ref["path"])
    if not path.exists():
        fail(f"missing metadata reference: {path}")
    if path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
        fail(f"payload reference in metadata evidence: {path}")
    if expected_kind is not None and ref.get("kind") != expected_kind:
        fail(f"unexpected metadata kind for {path}")
    if path.suffix.lower() == ".json" and sha256(path) != ref.get("sha256"):
        fail(f"metadata changed after capture: {path}")


def walk_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)
    elif isinstance(value, str):
        yield value


def main():
    chain = read_json(ROOT / "metadata/chain-audit" / f"{CASE}.json")
    png = read_json(ROOT / "metadata/png-hashes" / f"{CASE}.json")
    decision = read_json(ROOT / "metadata/visual-review" / f"{CASE}-delegated-visual-decision.json")
    provenance = read_json(ROOT / "metadata/source-review-provenance.json")

    if chain["case_id"] != CASE or chain["physical_case_id"] != PHYSICAL:
        fail("chain identity")
    if decision["status"] != "visual-approved-by-delegated-agent":
        fail("visual decision")
    if decision["review_limits"]["case_credit"] != 0 or decision["review_limits"]["independent_case_increment"] != 0:
        fail("credit boundary")
    if decision["review_limits"]["global_state_written"] or decision["review_limits"]["scientific_payload_opened_or_hashed_by_this_agent"]:
        fail("review boundary")
    if decision["review_limits"]["jobs_started"] or decision["review_limits"]["jobs_restarted"] or decision["review_limits"]["jobs_stopped"]:
        fail("job boundary")
    if decision["chain_requirements"]["actual_frames"] != 836 or decision["chain_requirements"]["actual_particles"] != 179208:
        fail("actual counts")
    if decision["contact_sheets_viewed"]["count"] != 35 or decision["keyframes_viewed"]["count"] != 9:
        fail("view counts")

    for stage in ("native", "typed", "xmf", "render"):
        if chain["stages"][stage]["status"] != "completed" or chain["stages"][stage]["returncode"] != 0:
            fail(f"stage not completed/0: {stage}")

    entries = png["entries"]
    contacts = [entry for entry in entries if entry["role"] == "contact_sheet"]
    keys = [entry for entry in entries if entry["role"] == "event_keyframe"]
    if len(contacts) != 35 or len(keys) != 9:
        fail("PNG evidence cardinality")
    if sorted(entry["contact_index"] for entry in contacts) != list(range(35)):
        fail("contact indices")
    if sorted(entry["frame_index"] for entry in keys) != [0, 104, 208, 312, 417, 521, 626, 730, 835]:
        fail("keyframe indices")
    for entry in entries:
        path = Path(entry["path"])
        if path.suffix.lower() != ".png" or not path.exists():
            fail(f"missing/non-PNG visual evidence: {path}")
        if not entry.get("viewed") or entry.get("view_method") != "view_image":
            fail(f"PNG not marked viewed with view_image: {path}")
        if sha256(path) != entry.get("sha256"):
            fail(f"PNG changed after capture: {path}")

    refs = chain["actual_paths"]
    for key in ("native_receipt", "typed_receipt", "typed_conversion_report", "xmf_receipt", "xmf_manifest", "render_receipt", "controller_result", "render_report", "publish_receipt", "root1248_previsual_qi_proof"):
        assert_metadata_ref(refs[key])
    for value in walk_strings(chain):
        if any(value.lower().endswith(suffix) for suffix in FORBIDDEN_PAYLOAD_SUFFIXES):
            fail(f"forbidden scientific payload path in chain: {value}")
    if refs["fresh155_path_correction"]["actual_controller_result_path"].endswith("/render/controller-result.json"):
        fail("stale render controller path")
    if refs["fresh155_path_correction"]["actual_xmf_manifest_path"].endswith("/render/manifest.json"):
        fail("stale render manifest path")

    if provenance["read_boundary"]["h5_opened_or_hashed"] or provenance["read_boundary"]["bi4_opened_or_hashed"]:
        fail("scientific payload boundary")
    if provenance["read_boundary"]["shared_index_or_ledger_modified"] or provenance["read_boundary"]["science_jobs_started_restarted_or_stopped"]:
        fail("shared/job boundary")

    integrity_path = ROOT / "metadata/package-integrity.json"
    integrity = read_json(integrity_path)
    listed = {item["path"]: item for item in integrity["files"]}
    actual = {
        str(path.relative_to(ROOT)): path
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != integrity_path.name
    }
    if set(listed) != set(actual):
        fail("package file set drift")
    for relative, item in listed.items():
        path = actual[relative]
        if item["bytes"] != path.stat().st_size or item["sha256"] != sha256(path):
            fail(f"package integrity mismatch: {relative}")
    print("fresh156 validation PASS: 35 contact sheets + 9 keyframes; Root1100 completed/0; PNG-only evidence; no scientific payload IO")


if __name__ == "__main__":
    main()
