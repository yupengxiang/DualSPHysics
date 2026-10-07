#!/usr/bin/env python3
"""Read-only validator for fresh191 terminal metadata preflight.

Only JSON/XML/XMF/Python/Markdown metadata may be opened or hashed. PNGs are
stat'ed and their producer-declared hashes are checked for shape only. H5,
BI4, IBI4, CSV, DAT and VTK references remain producer attestations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
METADATA = PACKAGE / "metadata" / "m110-t100-original1189-preflight.json"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
HASHABLE = {".json", ".xml", ".xmf", ".py", ".md"}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload read attempted: {p}")
    if p.suffix.lower() != ".json":
        fail(f"expected JSON metadata: {p}")
    value = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"metadata root is not an object: {p}")
    return value


def sha256(path: Path) -> str:
    if path.suffix.lower() not in HASHABLE:
        fail(f"non-metadata hash attempted: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def terminal(ref: dict[str, Any], label: str) -> dict[str, Any]:
    assert ref["status"] == "completed", f"{label} not completed"
    assert ref["returncode"] == 0, f"{label} returncode is not zero"
    data = load_json(ref["path"])
    assert data.get("status") == "completed", f"{label} source status is not completed"
    assert data.get("returncode") == 0, f"{label} source returncode is not zero"
    return data


def validate_png(entry: dict[str, Any], role: str) -> None:
    path = Path(entry["path"])
    assert path.suffix.lower() == ".png", f"{role} is not PNG"
    assert path.exists(), f"{role} missing: {path}"
    assert path.stat().st_size == entry["bytes_stat"], f"{role} stat changed: {path}"
    declared = entry.get("producer_declared_sha256")
    assert isinstance(declared, str) and len(declared) == 64 and all(c in "0123456789abcdef" for c in declared), f"{role} producer SHA malformed"
    assert entry["content_read_or_hashed"] is False, f"{role} was read/hashed by source package"


def main() -> int:
    doc = load_json(METADATA)
    package = doc["package"]
    identity = doc["case_identity"]
    runtime = doc["runtime_contract"]
    scope = doc["actual_scope"]
    upstream = doc["upstream_evidence"]

    assert doc["schema"] == "ds02.f3.assigned-f5.metadata-preflight.v2"
    assert package == {
        "name": "fresh191",
        "family_written": "F3",
        "actual_case_family": "F5",
        "assigned_family": "F3",
        "status": "metadata_preflight_terminal_render_complete",
        "case_credit": 0,
        "q_n": 0,
        "q_e": 0,
        "configured_model": "gpt-5.6-luna/max",
        "personal_visual_review": "deferred_to_fresh192",
        "personally_viewed_pngs": False,
    }
    assert identity["case_id"] == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T100_NEXT34"
    assert identity["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100"
    assert identity["expected_dimension"] == 3
    assert runtime["counts"] == {"frames": 801, "particles": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0}
    assert runtime["nominal_time_window_s"] == [0.0, 16.0]
    assert runtime["actual_time_window_s"] == [0.0, 16.00008511666941]
    assert runtime["expected_contact_sheets"] == 34
    assert runtime["keyframe_indices"] == [0, 100, 200, 300, 400, 500, 600, 700, 800]
    assert runtime["n3"] is True

    for name in ("gencase", "initial_qa", "native", "typed", "xmf", "bed", "render"):
        assert upstream[name]["status"] == "completed"
        assert upstream[name]["returncode"] == 0
    terminal(upstream["gencase"]["receipt"], "gencase")
    terminal(upstream["initial_qa"]["receipt"], "initial QA")
    terminal(upstream["native"]["primary_receipt"], "native")
    terminal(upstream["typed"]["receipt"], "typed")
    terminal(upstream["xmf"]["receipt"], "XMF")
    terminal(upstream["bed"]["receipt"], "bed")
    terminal(upstream["render"]["receipt"], "render")

    report = load_json(upstream["render"]["report"]["path"])
    publish = load_json(upstream["render"]["publish_receipt"]["path"])
    assert report["frames"] == 801 and report["source_frames"] == 801
    assert report["all_frames_rendered"] is True
    assert report["actual_times_preserved_exactly"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["manifest_sha256"] == "da60c416f57dc3e12ccc32cf9763ff7b1e5b1fa4b7980e84f577729a13946e51"
    assert publish["status"] == "published_after_atomic_rename"
    assert publish["published_bytes_excluding_receipt"] == 79057966
    assert publish["published_bytes_total"] == 79198659
    assert len(publish["files_excluding_receipt"]) == 838
    assert publish["pvsm_private_stage_paths_rebound"] is True
    assert publish["report_output_paths_rewritten_to_final_home"] is True
    assert upstream["render"]["published_files_excluding_receipt"] == 838
    assert upstream["render"]["atomic_publish_status"] == "published_after_atomic_rename"
    assert upstream["render"]["visual_review"] == "deferred_to_fresh192"
    assert upstream["render"]["personally_viewed_pngs"] is False
    assert len(upstream["render"]["contact_sheets"]) == 34
    assert len(upstream["render"]["key_frames"]) == 9
    for item in upstream["render"]["contact_sheets"]:
        validate_png(item, "contact sheet")
    for item in upstream["render"]["key_frames"]:
        validate_png(item, "key frame")

    assert scope["native_canonical"]["physical_condition_sha256"] == "83d6ff1798c49ce500aaf07d2319fac66f48d496d73fa1c044582fd9ec2b9024"
    assert scope["native_canonical"]["source_plan_condition_presence"] is False
    assert scope["native_canonical"]["source_plan_physical_condition_presence"] is True
    assert scope["xmf"]["physical_condition_sha256"] == "83d6ff1798c49ce500aaf07d2319fac66f48d496d73fa1c044582fd9ec2b9024"
    assert scope["xmf"]["source_plan_physical_condition_sha256"] == "da761772174d2a4ba20736647649b2e1117e48c55924426a3e24194057d366a7"
    assert scope["xmf"]["source_plan_condition_presence"] is False
    assert scope["typed_converter_legacy"]["physical_condition_sha256"] == "7b383a4e371948c22f8702cd9704844d1b16d8835fa12f203b688892fbc9f2a2"
    assert scope["prospective_canonical_preserved_separately"] == "9b51cce0a2f5940a8e6fdf2d284e407dd57f918fad42172eccfd498cbac1eaee"
    assert doc["qi_evidence"]["sha256"] == "1842851ab604f787bfba37e8b55e68463a8e1a81d94779c05412f0da1cca2652"
    assert doc["qi_evidence"]["role"].startswith("independent parent")
    assert doc["preflight_assertions"]["numerical_precision_not_accepted"] is True

    for entry in doc["metadata_input_closure"]:
        path = Path(entry["path"])
        suffix = path.suffix.lower()
        if entry.get("read_policy") == "producer_attestation_only_no_local_io":
            assert entry.get("sha256") is None, f"payload SHA present: {path}"
            assert entry.get("producer_attested_sha256"), f"producer attestation missing: {path}"
            assert suffix in FORBIDDEN or suffix == "", f"unexpected producer-only suffix: {path}"
            continue
        assert suffix in HASHABLE, f"unclassified closure suffix: {path}"
        assert path.exists(), f"closure path missing: {path}"
        assert entry.get("read_policy") != "producer_attestation_only_no_local_io"
        assert sha256(path) == entry["sha256"], f"closure SHA mismatch: {path}"

    for path in PACKAGE.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in FORBIDDEN, f"payload file in package: {path}"

    print("fresh191 metadata preflight PASS")
    print("terminal_chain=gencase,initial_qa,native,typed,xmf,bed,render")
    print("status=completed/0; atomic_publish=published_after_atomic_rename")
    print("PNG policy=stat + producer-declared SHA only; personal_review=deferred_to_fresh192")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
