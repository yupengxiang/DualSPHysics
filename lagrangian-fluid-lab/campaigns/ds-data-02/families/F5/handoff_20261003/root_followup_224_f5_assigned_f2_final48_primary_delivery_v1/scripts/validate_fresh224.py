#!/usr/bin/env python3
"""Read-only validator for fresh224 metadata and package closure."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
PRODUCTS = PACKAGE / "metadata" / "f2-final48-products.json"
PENDING_VIEW = PACKAGE / "metadata" / "pending-rx053-rot090-package-view.json"
PROVENANCE = PACKAGE / "metadata" / "source-provenance.json"
MANIFEST = PACKAGE / "manifest.json"
PENDING_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090"
KEYFRAMES = [0, 50, 100, 150, 200, 250, 300, 350, 400]
PAYLOAD_SUFFIX = re.compile(r"\.(?:h5|bi4|ibi4|csv|dat|vtk)(?:[\"'/]|$)", re.I)


def load(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    raise AssertionError(message)


def ref_ok(value, label: str, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"{label}: reference missing path")
    sha = value.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        fail(f"{label}: invalid SHA metadata")


def validate_manifest() -> None:
    manifest = load(MANIFEST)
    if manifest.get("schema") != "ds02.f5.fresh224.manifest.v1":
        fail("manifest schema")
    if manifest.get("self_hash_excluded") is not True:
        fail("manifest self-hash policy")
    listed = {item["path"]: item for item in manifest.get("files", [])}
    expected = {
        "README.md",
        "metadata/f2-final48-products.json",
        "metadata/pending-rx053-rot090.json",
        "metadata/pending-rx053-rot090-package-view.json",
        "metadata/source-provenance.json",
        "scripts/build_fresh224.py",
        "scripts/validate_fresh224.py",
    }
    if set(listed) != expected:
        fail(f"manifest file set mismatch: {sorted(set(listed) ^ expected)}")
    actual = {
        p.relative_to(PACKAGE).as_posix()
        for p in PACKAGE.rglob("*")
        if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts
    }
    if actual != expected:
        fail(f"unexpected package files: {sorted(actual ^ expected)}")
    for rel, item in listed.items():
        path = PACKAGE / rel
        if item.get("bytes") != path.stat().st_size:
            fail(f"manifest byte count: {rel}")
        if item.get("sha256") != digest(path):
            fail(f"manifest SHA: {rel}")


def validate_provenance(doc: dict, products: dict) -> None:
    if doc.get("schema") != "ds02.f5.fresh224.source-provenance.v1":
        fail("provenance schema")
    if doc.get("source_only") is not True or doc.get("payload_boundary", {}).get("scientific_payload_IO") is not False:
        fail("provenance payload boundary")
    for name, item in doc.get("authoritative_sources", {}).items():
        ref_ok(item, f"authoritative source {name}")
        path = Path(item["path"])
        if path.suffix.lower() != ".json" or not path.is_file():
            fail(f"authoritative source is not an existing JSON metadata file: {path}")
        if digest(path) != item["sha256"]:
            fail(f"authoritative source SHA changed: {path}")
    m = doc["root1330_membership"]
    if m != products["membership"]:
        fail("membership copy differs between provenance and products")
    if doc["payload_boundary"].get("jobs_started") != 0:
        fail("fresh224 starts a job")


def validate_visual(row: dict, label: str) -> None:
    if row.get("inherited_from_root1330_primary_sidecar"):
        contacts = row.get("main_contact_refs", [])
        keys = row.get("main_published_navigation_keys", [])
        if len(contacts) != 17 or len(keys) != 9:
            fail(f"{label}: inherited contact/key cardinality")
        paths = [item.get("path") for item in contacts]
        key_paths = [item.get("path") for item in keys]
    else:
        visual = row.get("visual", {})
        personal = visual.get("personal_visual_role", {})
        navigation = visual.get("published_navigation_role", {})
        contacts = personal.get("contact_sheets", [])
        keys = personal.get("keyframes", [])
        if personal.get("contact_count") != 17 or personal.get("keyframe_count") != 9:
            fail(f"{label}: personal contact/key cardinality")
        if navigation.get("contact_count") != 17 or navigation.get("keyframe_count") != 9:
            fail(f"{label}: navigation contact/key cardinality")
        if navigation.get("unique_contact_paths") != 17 or navigation.get("unique_keyframe_paths") != 9:
            fail(f"{label}: navigation path uniqueness")
        if navigation.get("keyframe_indices") != KEYFRAMES:
            fail(f"{label}: keyframe indices")
        paths = [item.get("path", item.get("absolute_path")) for item in contacts]
        key_paths = [item.get("path", item.get("absolute_path")) for item in keys]
    if len(set(paths)) != 17 or len(set(key_paths)) != 9:
        fail(f"{label}: duplicate PNG metadata paths")
    for collection, name in ((contacts, "contact"), (keys, "keyframe")):
        for item in collection:
            if not isinstance(item, dict):
                fail(f"{label}: {name} metadata is not an object")
            if not isinstance(item.get("path", item.get("absolute_path")), str):
                fail(f"{label}: {name} path")
            if not isinstance(item.get("sha256", item.get("producer_sha256")), str):
                fail(f"{label}: {name} producer SHA")
            # Root1330's inherited navigation sidecar records producer SHA and
            # path for some references without copying a stat byte count.  A
            # byte count is checked when the producer actually supplied one;
            # it must not be invented for inherited metadata.
            if "bytes" in item or "observed_stat_bytes" in item:
                if not isinstance(item.get("bytes", item.get("observed_stat_bytes")), int):
                    fail(f"{label}: {name} producer/stat bytes")


def validate_products(products: dict, pending: dict) -> None:
    if products.get("schema") != "ds02.f2.final48.primary-delivery-products.v1":
        fail("products schema")
    if products.get("registered_final48_count") != 48 or products.get("accepted_actual_product_count") != 47:
        fail("final48 counts")
    if products.get("pending_primary_count") != 1 or products.get("pending_case_id") != PENDING_ID:
        fail("pending boundary")
    if products.get("case_credit") != 0 or products.get("Q_N") != 0 or products.get("Q_E") != 0:
        fail("package credit boundary")
    membership = products["membership"]
    frozen = membership["frozen_first8_physical_case_ids"]
    actual24 = membership["actual_first24_physical_case_ids"]
    final48 = membership["registered_final48_physical_case_ids"]
    if len(frozen) != 8 or len(actual24) != 24 or len(final48) != 48:
        fail("membership cardinality")
    if not set(frozen) <= set(actual24) <= set(final48):
        fail("frozen8/actual24/final48 subset relation")
    rows = products["products"]
    if len(rows) != 47 or len({row.get("physical_case_id") for row in rows}) != 47:
        fail("product row uniqueness/count")
    expected = [case for case in final48 if case != PENDING_ID]
    actual = [row.get("physical_case_id") for row in rows]
    if actual != expected:
        fail("product order does not follow final48 minus pending")
    for row in rows:
        label = row["physical_case_id"]
        if row.get("case_credit") not in (None, 0) or row.get("case_credit_delta") not in (None, 0):
            fail(f"{label}: nonzero case credit")
        if row.get("Q_N", 0) != 0 or row.get("Q_E", 0) != 0:
            fail(f"{label}: nonzero Q-N/Q-E")
        if row.get("main_scientific_payload_IO", row.get("scientific_payload_IO", False)) is not False:
            fail(f"{label}: scientific payload IO")
        if label in {"F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075",
                     "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
                     "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090",
                     "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT090",
                     "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105"}:
            validate_visual(row, label)
            proof = row.get("proofs", {})
            ref_ok(proof.get("accepted_visual_decision"), f"{label} decision")
            ref_ok(proof.get("own_full401_QI"), f"{label} QI")
            ref_ok(proof.get("source_validator"), f"{label} validator")
            if not proof.get("actual_initial_QA_explicit"):
                fail(f"{label}: initial QA was not explicitly proven")
            if not row.get("primary_product_metadata", {}).get("XMF_manifest"):
                fail(f"{label}: XMF manifest missing")
            if not row.get("primary_product_metadata", {}).get("render_publish_receipt"):
                fail(f"{label}: render publish receipt missing")
        else:
            validate_visual(row, label)
            if not row.get("actual_render_receipt") or not row.get("primary_XMF_manifest"):
                fail(f"{label}: inherited primary refs missing")

    # This is a metadata package: no generated JSON may smuggle payload paths.
    for path in PACKAGE.glob("metadata/*.json"):
        if PAYLOAD_SUFFIX.search(path.read_text(encoding="utf-8")):
            fail(f"payload path appears in metadata JSON: {path.name}")
    if pending.get("status") != "pending_running_not_completed":
        fail("pending package status")


def main() -> int:
    validate_manifest()
    products = load(PRODUCTS)
    pending = load(PENDING_VIEW)
    provenance = load(PROVENANCE)
    validate_products(products, pending)
    validate_provenance(provenance, products)
    # The final48 membership uses the physical-case identity.  The producer's
    # execution case_id additionally carries its expansion/solver suffix.
    if pending.get("physical_case_id") != PENDING_ID or pending.get("actual_product", {}).get("completed") is not False:
        fail("pending identity/completion")
    live = pending.get("live_observation", {})
    if live.get("actual_registered_worker_pid") != 772469 or live.get("actual_registered_worker_start_ticks") != "215275078":
        fail("pending actual worker identity")
    if live.get("running_is_not_completed0") is not True or live.get("same_handle_running") is not True:
        fail("pending must remain running/unknown")
    print("fresh224 validation PASS: 47 products, one running pending boundary, metadata-only")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"fresh224 validation FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
