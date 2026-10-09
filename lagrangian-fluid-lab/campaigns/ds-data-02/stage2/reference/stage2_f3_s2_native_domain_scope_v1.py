#!/usr/bin/env python3
"""Record the domain scope exposed by F3 native headers and generated XML.

This is deliberately a metadata-only audit.  It reads the two compact summary
files and the small generated XML files, plus the small ROOT150 verification
proof.  It never opens a full native observer report, a BI4 frame, or H5.

The compact observer schema records Dp/H/MassBound/MassFluid/PeriMode, but does
not currently record saved-domain bounds.  The generated XMLs have an empty
``simulationdomain`` element whose documented default is the min/max of the
generated particles.  The report therefore records the absence of a native
domain-bound witness rather than inferring one from XML draw boxes or from the
fine-grid losses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import xml.etree.ElementTree as ET
from typing import Any


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def _xml_scope(path: pathlib.Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        definition = root.find(".//definition")
    if definition is None:
        raise ValueError(f"missing geometry definition: {path}")

    simulation_domain = root.find("./execution/simulationdomain")
    if simulation_domain is None:
        simulation_domain = root.find(".//simulationdomain")
    if simulation_domain is None:
        raise ValueError(f"missing simulationdomain: {path}")

    sizes = []
    for node in definition.findall(".//drawbox/size"):
        sizes.append({key: node.attrib[key] for key in ("x", "y", "z") if key in node.attrib})

    particles = root.find("./execution/particles")
    if particles is None:
        particles = root.find(".//particles")

    comment = simulation_domain.attrib.get("comment", "")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "definition_dp_m": definition.attrib.get("dp"),
        "drawbox_sizes_m": sizes,
        "particle_counts": dict(particles.attrib) if particles is not None else None,
        "simulationdomain_attributes": dict(simulation_domain.attrib),
        "simulationdomain_text": (simulation_domain.text or "").strip(),
        "simulationdomain_has_explicit_bounds": bool(simulation_domain.attrib)
        or bool((simulation_domain.text or "").strip()),
        "simulationdomain_comment": comment,
        "simulationdomain_default_semantics": (
            "min/max generated-particle positions"
            if "minimum and maximum position of the generated particles" in comment
            else "UNSPECIFIED"
        ),
    }


def _header_scope(summary: dict[str, Any]) -> dict[str, Any]:
    # Keep this intentionally narrow.  Keys such as ``boundary`` in lifecycle
    # records are not native-header domain bounds.
    header_summary = summary.get("native_header_summary")
    first_header = None
    selected = summary.get("selected_observations")
    if isinstance(selected, list) and selected and isinstance(selected[0], dict):
        candidate = selected[0].get("native_header")
        if isinstance(candidate, dict):
            first_header = candidate
    consistency = summary.get("native_header_consistency")
    header_keys = set()
    for candidate in (header_summary, first_header, consistency):
        if isinstance(candidate, dict):
            header_keys.update(candidate.keys())
    # ``MassBound`` is a per-particle mass and must not be confused with a
    # saved-domain bound.  Only domain/bounds-named fields count here.
    bound_keys = sorted(
        key
        for key in header_keys
        if "domain" in key.lower() or "bounds" in key.lower()
    )
    return {
        "compact_summary_schema": summary.get("schema"),
        "compact_summary_sha256": None,
        "compact_summary_bytes": None,
        "header_fields_exposed": sorted(header_keys),
        "native_header_domain_bound_fields": bound_keys,
        "native_saved_domain_bounds_exposed": bool(bound_keys),
        "native_header_summary": header_summary,
        "first_native_header": first_header,
        "initial_counts": summary.get("initial_counts"),
        "final_counts": summary.get("final_counts"),
        "lifecycle_counts": summary.get("lifecycle_counts"),
    }


def _summary_scope(path: pathlib.Path) -> dict[str, Any]:
    summary = _read_json(path)
    result = _header_scope(summary)
    result["compact_summary_sha256"] = _sha256(path)
    result["compact_summary_bytes"] = path.stat().st_size
    result["summary_path"] = str(path)
    return result


def _proof_case_id(proof: dict[str, Any]) -> Any:
    request = proof.get("request")
    if isinstance(request, dict):
        return request.get("case_id")
    return proof.get("case_id")


def build_report(
    *,
    coarse_proof: pathlib.Path,
    coarse_xml: pathlib.Path,
    middle_summary: pathlib.Path,
    middle_xml: pathlib.Path,
    middle_proof: pathlib.Path,
    fine_summary: pathlib.Path,
    fine_xml: pathlib.Path,
    fine_proof: pathlib.Path,
) -> dict[str, Any]:
    coarse = _read_json(coarse_proof)
    middle = _read_json(middle_proof)
    fine = _read_json(fine_proof)
    middle_scope = _summary_scope(middle_summary)
    fine_scope = _summary_scope(fine_summary)

    return {
        "schema": "ds02.stage2.f3-native-domain-scope.v1",
        "status": "COMPLETED_METADATA_SCOPE_NO_DOMAIN_BOUND_WITNESS",
        "read_policy": {
            "full_reports_read": False,
            "native_bi4_frames_read": False,
            "h5_read": False,
            "allowed_inputs": "ROOT150 small proof, ROOT177/178 compact summaries, generated XML",
        },
        "cases": {
            "coarse150": {
                "case_id": _proof_case_id(coarse)
                or "F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150",
                "proof_path": str(coarse_proof),
                "proof_sha256": _sha256(coarse_proof),
                "frame_count": coarse.get("frame_count"),
                "native_massfluid_kg": coarse.get("native_massfluid_kg"),
                "xml_classification": coarse.get("fluid4320_and_fixed19944_XML_classification"),
                "native_header_domain_bounds_exposed": False,
                "domain_bound_scope_note": (
                    "ROOT150 verification proof exposes native header mass/finite/identity "
                    "scope but no saved-domain-bound field; the 14.8 MB full report was not read."
                ),
                "xml": _xml_scope(coarse_xml),
            },
            "middle177": {
                "case_id": _proof_case_id(middle)
                or "F3_S2_MIDDLE_FULL_NATIVE_STREAM_V6_ROOT_177",
                "proof_path": str(middle_proof),
                "proof_sha256": _sha256(middle_proof),
                "frame_count": middle.get("frame_count"),
                "native_header_domain_bounds_exposed": middle_scope[
                    "native_saved_domain_bounds_exposed"
                ],
                "compact_scope": middle_scope,
                "xml": _xml_scope(middle_xml),
            },
            "fine178": {
                "case_id": _proof_case_id(fine)
                or "F3_S2_FULL_NATIVE_STREAM_ROOT178_V6",
                "proof_path": str(fine_proof),
                "proof_sha256": _sha256(fine_proof),
                "frame_count": fine.get("frame_count"),
                "native_header_domain_bounds_exposed": fine_scope[
                    "native_saved_domain_bounds_exposed"
                ],
                "compact_scope": fine_scope,
                "xml": _xml_scope(fine_xml),
            },
        },
        "fine_loss_observation": {
            "initial_particle_count": fine.get("initial_counts", {}).get("total_particle_count"),
            "final_particle_count": fine.get("final_counts", {}).get("total_particle_count"),
            "lost_idp_count": fine.get("lifecycle_counts", {}).get("lost_idp_count"),
            "fate_or_flux": "UNKNOWN",
        },
        "interpretation": {
            "native_saved_domain_comparison": "UNAVAILABLE_FROM_EXPOSED_HEADER_SUMMARIES",
            "xml_execution_domain": (
                "All three generated XMLs have an empty simulationdomain element; their "
                "comment documents the default min/max generated-particle positions."
            ),
            "dp_dependence": (
                "The XML definitions and particle counts change with dp and drawbox sizes; "
                "this is source/execution metadata, not a measured native saved-domain bound."
            ),
            "fine_512_exclusions": (
                "The compact summary records 512 missing IDs at the fine terminal window, "
                "but no domain-bound witness is present, so this audit cannot attribute them "
                "to auto-domain extents or to legal outflow/numerical error."
            ),
            "scientific_qualification": "UNKNOWN",
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse-proof", type=pathlib.Path, required=True)
    parser.add_argument("--coarse-xml", type=pathlib.Path, required=True)
    parser.add_argument("--middle-summary", type=pathlib.Path, required=True)
    parser.add_argument("--middle-xml", type=pathlib.Path, required=True)
    parser.add_argument("--middle-proof", type=pathlib.Path, required=True)
    parser.add_argument("--fine-summary", type=pathlib.Path, required=True)
    parser.add_argument("--fine-xml", type=pathlib.Path, required=True)
    parser.add_argument("--fine-proof", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_report(
        coarse_proof=args.coarse_proof,
        coarse_xml=args.coarse_xml,
        middle_summary=args.middle_summary,
        middle_xml=args.middle_xml,
        middle_proof=args.middle_proof,
        fine_summary=args.fine_summary,
        fine_xml=args.fine_xml,
        fine_proof=args.fine_proof,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
