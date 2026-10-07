#!/usr/bin/env python3
"""Read-only metadata validator for fresh188.

This validator never opens scientific payloads. It may hash JSON/XML/XMF and
the package's own Python/Markdown files, while H5/BI4/IBI4/CSV/DAT/VTK
references are checked only as producer attestations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
METADATA = PACKAGE / "metadata" / "m110-t080-original1159-preflight.json"
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
    with p.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
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


def receipt(path: str, label: str) -> dict[str, Any]:
    data = load_json(path)
    if data.get("status") != "completed":
        fail(f"{label} is not completed: {path}")
    if data.get("returncode") != 0:
        fail(f"{label} returncode is not zero: {path}")
    return data


def main() -> int:
    doc = load_json(METADATA)
    identity = doc["case_identity"]
    package = doc["package"]
    runtime = doc["runtime_contract"]
    upstream = doc["upstream_evidence"]

    assert package["name"] == "fresh188"
    assert package["family_written"] == "F3"
    assert package["actual_case_family"] == "F5"
    assert package["assigned_family"] == "F3"
    assert package["status"] == "metadata_preflight_complete"
    assert package["personally_viewed_pngs"] is False
    assert package["personal_visual_review"] == "deferred_to_fresh189"
    assert package["configured_model"] == "gpt-5.6-luna/max"

    assert identity["case_id"] == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T080_NEXT34"
    assert identity["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T080"
    assert identity["family_id"] == "F5"
    assert identity["expected_dimension"] == 3

    counts = runtime["counts"]
    assert counts == {
        "frames": 801,
        "particles": 194427,
        "fixed": 158559,
        "moving": 4210,
        "fluid": 31658,
        "floating": 0,
    }
    assert runtime["time_window_s"] == [0.0, 16.0]
    assert runtime["expected_contact_sheets"] == 34
    assert runtime["keyframe_indices"] == [0, 100, 200, 300, 400, 500, 600, 700, 800]
    assert runtime["n3"] is True

    expected_terminal = ("gencase", "initial_qa", "native", "typed", "xmf", "bed", "render")
    for name in expected_terminal:
        evidence = upstream[name]
        status = evidence.get("status")
        if name == "gencase":
            receipt(evidence["receipt"], name)
        elif name == "initial_qa":
            receipt(evidence["receipt"], name)
        elif name == "native":
            receipt(evidence["primary_receipt"], name)
        elif name == "typed":
            receipt(evidence["receipt"], name)
        elif name == "xmf":
            receipt(evidence["receipt"], name)
        elif name == "bed":
            receipt(evidence["receipt"], name)
        elif name == "render":
            receipt(evidence["receipt"], name)
        assert status == "completed", f"{name} evidence is not terminal"

    assert upstream["gencase"]["total_particles"] == counts["particles"]
    assert upstream["gencase"]["fluid_particles"] == counts["fluid"]
    assert upstream["gencase"]["solver_dimension_from_gencase"] == 3
    assert upstream["render"]["atomic_publish_status"] == "published_after_atomic_rename"
    assert upstream["render"]["all_frames_rendered"] is True
    assert upstream["render"]["actual_times_preserved_exactly"] is True
    assert upstream["render"]["published_files_excluding_receipt"] == 838
    assert upstream["render"]["home_publish_cap_bytes"] == 2147483648

    report = load_json(upstream["render"]["report"])
    assert report["frames"] == 801
    assert report["source_frames"] == 801
    assert report["all_frames_rendered"] is True
    assert report["actual_times_preserved_exactly"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["manifest_sha256"] == upstream["xmf"]["manifest_sha256"]
    assert len(report["outputs"]["contact_sheets"]) == 34
    assert package["personally_viewed_pngs"] is False

    publish = load_json(upstream["render"]["publish_receipt"])
    assert publish["status"] == "published_after_atomic_rename"
    assert publish["published_bytes_excluding_receipt"] == 79190210
    assert len(publish["files_excluding_receipt"]) == 838
    assert publish["pvsm_private_stage_paths_rebound"] is True
    assert publish["report_output_paths_rewritten_to_final_home"] is True

    xmf = load_json(upstream["xmf"]["manifest"])
    assert xmf["case_id"] == identity["case_id"]
    assert xmf["physical_case_id"] == identity["physical_case_id"]
    assert xmf["expected_frames"] == 801
    assert xmf["expected_particles"] == 194427
    assert xmf["actual_native_receipt_status"] == "completed"
    assert xmf["actual_native_receipt_returncode"] == 0
    assert xmf["physical_condition_sha256"] == "873b4e8ab9cc1fe351876d13063f1eb42fb722302f2f77b7684a6bd44ee1fbee"
    assert xmf["source_plan_physical_condition_sha256"] == "873b4e8ab9cc1fe351876d13063f1eb42fb722302f2f77b7684a6bd44ee1fbee"
    assert xmf.get("source_plan_condition_sha256") is None
    assert xmf["source_h5_physical_condition_sha256"] == "06e5dafcbb4dd8f471b6071dbff6a51e97111a2c13fe3108f5a5169ed5c8b034"
    assert xmf["source_h5_legacy_scope_sha256"] == "bce58b61516e24a72e1ba899561f4518f58e493e34b0c2e491428a5d8c6ee1d0"

    typed = load_json(upstream["typed"]["conversion_report"])
    assert typed["frames"] == 801
    assert typed["particles"] == 194427
    assert typed["hash_scopes"]["physical_condition_sha256"] == "06e5dafcbb4dd8f471b6071dbff6a51e97111a2c13fe3108f5a5169ed5c8b034"
    assert typed["hash_scopes"]["physical_condition"]["schema"] == "legacy-owner-scope.v0"

    bed = load_json(upstream["bed"]["report"])
    assert bed["status"] == "completed_worker_output_pending_root_review"
    assert bed["physical_condition_sha256"] == "873b4e8ab9cc1fe351876d13063f1eb42fb722302f2f77b7684a6bd44ee1fbee"
    assert bed["source_plan_physical_condition_sha256"] == "426b2eb0d07213735d4754efa99fb02c8a5d94a2bc66b4bfbb45767f1c933047"
    assert bed["source_h5_physical_condition_sha256"] == "06e5dafcbb4dd8f471b6071dbff6a51e97111a2c13fe3108f5a5169ed5c8b034"

    for entry in doc["metadata_input_closure"]:
        path = Path(entry["path"])
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN:
            assert entry.get("read_policy") == "producer_attestation_only_no_local_io"
            assert entry.get("sha256") is None
            continue
        assert suffix in HASHABLE, f"unclassified input suffix: {path}"
        assert entry.get("read_policy") != "producer_attestation_only_no_local_io"
        assert path.exists(), f"metadata input missing: {path}"
        expected = entry.get("sha256")
        if expected is not None:
            actual = sha256(path)
            assert actual == expected, f"metadata hash mismatch: {path}: {actual} != {expected}"

    own_files = [p for p in PACKAGE.rglob("*") if p.is_file()]
    for path in own_files:
        assert path.suffix.lower() not in FORBIDDEN, f"payload file in source package: {path}"

    print("fresh188 metadata preflight PASS")
    print(f"case={identity['physical_case_id']} frames=801 particles=194427")
    print("terminal_chain=gencase,initial_qa,native,typed,xmf,bed,render")
    print("visual_review=deferred_to_fresh189; payload_io=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
