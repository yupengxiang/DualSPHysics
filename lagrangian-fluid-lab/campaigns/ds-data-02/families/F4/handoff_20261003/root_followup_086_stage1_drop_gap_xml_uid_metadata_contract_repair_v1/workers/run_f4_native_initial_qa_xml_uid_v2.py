#!/usr/bin/env python3
"""Root212 metadata-contract repair for the F4 XML/UID native QA worker.

The consumed F4 audit reads ``metadata['physical_binding']['geometry']['tank']``
and related fields before its native decoder stage. Fresh085 omitted that
owner binding. This wrapper reuses the immutable fresh085 worker and patches
only the derived metadata adapter: it copies the exact canonical owner
``physical_binding``, validates the XML-derived counts, dp, source regions,
continuum masses, and small-source hashes, then delegates to the same pinned
official audit. It never opens or hashes BI4/H5/VTK/CSV data and never starts a
job by itself.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable


FRESH085_WORKER = Path(__file__).resolve().parents[1].parent / (
    "root_followup_085_stage1_drop_gap_xml_uid_native_qa_v1/workers/"
    "run_f4_native_initial_qa_xml_uid_v1.py"
)
SCHEMA = "ds02.f4.internal8.native-initial-qa-xml-uid-metadata-repair.v1"


def load_worker():
    spec = importlib.util.spec_from_file_location("f4_root212_fresh085_worker", FRESH085_WORKER)
    if spec is None or spec.loader is None:
        raise ImportError(FRESH085_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_worker()
_base_adapter: Callable[..., Any] = BASE.adapter_metadata
_base_root195_rows: Callable[..., Any] = BASE.root195_rows


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_metadata_contract(
    *,
    metadata: dict[str, Any],
    owner: dict[str, Any],
    endpoint: dict[str, Any],
    xml: dict[str, Any],
    source_definition: Path,
    receipt_path: Path,
    sha256: Callable[[Path], str],
) -> None:
    physical = owner["physical_binding"]
    required = {
        "case_id",
        "physical_case_id",
        "physical_condition_sha256",
        "physical_binding",
        "physical_binding_sha256",
        "dp_m",
        "source_regions",
        "expected_counts_by_source",
        "continuous_mass_by_source_kg",
        "definition_sha256",
        "original_definition",
        "original_source_sha256",
        "generated_xml_partition",
    }
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValueError(f"metadata contract missing fields: {missing}")
    if metadata["case_id"] != endpoint["endpoint_id"]:
        raise ValueError("metadata case_id drift")
    if metadata["physical_case_id"] != physical["physical_case_id"]:
        raise ValueError("metadata physical_case_id drift")
    if metadata["physical_condition_sha256"] != owner["physical_condition_sha256"]:
        raise ValueError("metadata physical condition drift")
    if metadata["physical_binding"] != physical:
        raise ValueError("metadata physical_binding is not an exact owner copy")
    if metadata["physical_binding_sha256"] != owner["physical_binding_sha256"]:
        raise ValueError("metadata physical_binding_sha256 drift")
    expected_dp = float(owner["source_recipe"]["dp_m"])
    if float(metadata["dp_m"]) != expected_dp:
        raise ValueError("metadata dp_m drift")
    source_regions = physical["initial_state"]["source_regions"]
    if metadata["source_regions"] != source_regions:
        raise ValueError("metadata source_regions drift")
    expected_counts = {str(row["source"]): int(row["uid_count"]) for row in xml["source_rows"]}
    if metadata["expected_counts_by_source"] != expected_counts:
        raise ValueError("metadata dynamic source counts drift")
    density = float(physical["density_kg_m3"])
    expected_mass = {
        name: float(region["size_m"][0] * region["size_m"][1] * region["size_m"][2] * density)
        for name, region in source_regions.items()
    }
    if metadata["continuous_mass_by_source_kg"] != expected_mass:
        raise ValueError("metadata continuum mass derivation drift")
    if metadata["definition_sha256"] != sha256(source_definition):
        raise ValueError("metadata definition hash drift")
    original_hashes = metadata["original_source_sha256"]
    for path in (source_definition, Path(xml["xml_path"]), receipt_path):
        if original_hashes.get(str(path)) != sha256(path):
            raise ValueError(f"metadata source hash drift: {path}")
    if metadata["generated_xml_partition"]["xml_sha256"] != xml["xml_sha256"]:
        raise ValueError("metadata generated XML partition hash drift")
    if metadata.get("arrays_read_by_source") is not False or metadata.get("source_only") is not True:
        raise ValueError("metadata source-read boundary drift")


def adapter_metadata_v2(
    *,
    endpoint: dict[str, Any],
    owner: dict[str, Any],
    source_definition: Path,
    receipt_path: Path,
    xml: dict[str, Any],
    output_metadata: Path,
) -> None:
    _base_adapter(
        endpoint=endpoint,
        owner=owner,
        source_definition=source_definition,
        receipt_path=receipt_path,
        xml=xml,
        output_metadata=output_metadata,
    )
    metadata = load_json(output_metadata)
    # Keep the exact owner object, including geometry.tank, rather than
    # reconstructing a reduced geometry approximation.
    metadata["physical_binding"] = copy.deepcopy(owner["physical_binding"])
    metadata["physical_binding_sha256"] = owner["physical_binding_sha256"]
    metadata["source_recipe"] = copy.deepcopy(owner["source_recipe"])
    metadata["metadata_contract"] = {
        "consumer": "ds_data02_f4_centered_reference_v1.audit",
        "physical_binding_source": "canonical owner exact copy",
        "raw_native_arrays_observed_by_source": [],
        "raw_native_arrays_observed_by_job": ["Posd", "Idp"],
        "raw_native_marker_arrays": {"Mk": "not observed", "Type": "not observed"},
        "derived_fields": [
            "expected_counts_by_source",
            "continuous_mass_by_source_kg",
            "generated_xml_partition",
        ],
    }
    assert_metadata_contract(
        metadata=metadata,
        owner=owner,
        endpoint=endpoint,
        xml=xml,
        source_definition=source_definition,
        receipt_path=receipt_path,
        sha256=BASE.sha256,
    )
    write_json(output_metadata, metadata)


def root195_rows_v2(binding: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten producer output refs for every consumer access in fresh085.

    The producer row is intentionally nested under ``row`` in the fresh085
    adapter's internal result. Its later report/receipt path used
    ``row['generated_bi4']`` at the flattened level, which caused Root212 to
    fail before arrays. Preserve the producer row as evidence and expose only
    immutable aliases for all four generated-output accesses.
    """

    rows = _base_root195_rows(binding)
    for endpoint_id, value in rows.items():
        producer_row = value["row"]
        for key in ("generated_xml", "generated_bi4", "gencase_receipt", "endpoint_id"):
            if key not in value:
                value[key] = producer_row[key]
        if value["endpoint_id"] != endpoint_id:
            raise ValueError(f"Root195 endpoint alias drift: {endpoint_id}")
    return rows


def metadata_preflight(argv: list[str]) -> int | None:
    """Exercise all eight metadata adapters without opening scientific data."""

    if "--metadata-preflight" not in argv:
        return None
    import argparse

    parser = argparse.ArgumentParser(description="F4 metadata-only preflight")
    parser.add_argument("--metadata-preflight", action="store_true")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--root195-binding", required=True, type=Path)
    parser.add_argument("--owner-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args, _ = parser.parse_known_args(argv[1:])
    plan = BASE.load_json(BASE.require_file(args.plan))
    binding = BASE.load_json(BASE.require_file(args.root195_binding))
    rows = root195_rows_v2(binding)
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 8:
        raise ValueError("metadata preflight requires exactly eight endpoints")
    with tempfile.TemporaryDirectory(prefix="ds02-f4-root216-metadata-") as temporary:
        root = Path(temporary)
        reports = []
        for endpoint in endpoints:
            endpoint_id = str(endpoint["endpoint_id"])
            row = rows[endpoint_id]
            owner = BASE.load_json(BASE.require_file(args.owner_root / f"{endpoint_id}.owner.json"))
            xml = BASE.xml_partition(row["xml_path"], owner["physical_binding"]["initial_state"]["source_regions"])
            if xml["total_particles"] != row["receipt"]["total_particles"] or xml["fluid_particles"] != row["receipt"]["fluid_particles"]:
                raise ValueError(f"{endpoint_id}: XML/count mismatch")
            metadata_path = root / "metadata" / f"{endpoint_id}.metadata.json"
            adapter_metadata_v2(
                endpoint=endpoint,
                owner=owner,
                source_definition=Path(owner["source_definition"]["path"]),
                receipt_path=row["receipt_path"],
                xml=xml,
                output_metadata=metadata_path,
            )
            metadata = load_json(metadata_path)
            reports.append({
                "endpoint_id": endpoint_id,
                "metadata": str(metadata_path),
                "physical_binding_present": "physical_binding" in metadata,
                "geometry_tank_present": "tank" in metadata["physical_binding"]["geometry"],
                "dynamic_counts": metadata["expected_counts_by_source"],
                "dp_m": metadata["dp_m"],
                "source_hash_count": len(metadata["original_source_sha256"]),
                "arrays_read_by_source": metadata["arrays_read_by_source"],
            })
        output = args.output_root
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "metadata-preflight.json", {
            "schema": "ds02.f4.internal8.native-initial-qa-metadata-preflight.v1",
            "status": "completed",
            "case_count": len(reports),
            "cases": reports,
            "scientific_arrays_opened": False,
            "claim_boundary": "Metadata/XML/JSON contract only; no BI4, solver, visual, or production claim.",
        })
    return 0


def main() -> int:
    # Load fresh085's parser/run contract, replacing only its adapter callback.
    BASE.adapter_metadata = adapter_metadata_v2
    BASE.root195_rows = root195_rows_v2
    BASE.SCHEMA = SCHEMA
    return BASE.main()


if __name__ == "__main__":
    try:
        preflight_result = metadata_preflight(sys.argv)
        raise SystemExit(main() if preflight_result is None else preflight_result)
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "error_type": type(error).__name__, "error": str(error), "arrays_read_by_source": False}, sort_keys=True))
        raise SystemExit(1)
