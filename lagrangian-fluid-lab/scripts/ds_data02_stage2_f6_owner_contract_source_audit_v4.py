#!/usr/bin/env python3
"""Audit the F6 source contract without opening generated particle payloads.

The F6 Def XMLs declare a fluid ``drawbox`` and a floating body.  This worker
checks those declarations against the official ``JCaseParts`` parser source.
It records which fields are actually authoritative in the source contract and
which proposed continuous-fluid-owner fields are absent.  It does not infer an
owner mass from particle counts, comments, or a generated drawbox volume, and
it never opens H5, BI4, OBI4, VTK, or solver output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f6.owner-contract-source-audit.v4"
MANIFEST_SCHEMA = "ds02.stage2.f6.owner-contract-source-audit.manifest.v4"
UNKNOWN_OWNER = "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT"
BODY_MASS_KG = 128.0
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".vtk", ".vtu"}
OWNER_TOKENS = {
    "owner",
    "ownercontract",
    "physicalowner",
    "fluidowner",
    "fluid_owner",
    "continuumowner",
    "continuum_owner",
    "regionowner",
    "region_owner",
}


class ContractError(ValueError):
    """Raised when the bounded source contract is not internally consistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ContractError(f"missing source file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object: {path}")
    return value


def expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ContractError(f"{label}: expected {expected!r}, got {actual!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ContractError(f"{label} is not finite")
    return result


def load_sources(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise ContractError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise ContractError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ContractError(f"forbidden payload source: {path}")
        actual = record(path)
        if ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(ref["sha256"]), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        records[key] = actual
    return paths, records


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_definition(path: Path, label: str) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ContractError(f"{label} XML parse failed: {path}") from exc
    if local_tag(root) != "case":
        raise ContractError(f"{label} root is not <case>")
    owner_hits: list[dict[str, Any]] = []
    for element in root.iter():
        tag = local_tag(element)
        normalized_tag = tag.lower().replace("-", "_")
        if normalized_tag in OWNER_TOKENS:
            owner_hits.append({"kind": "element", "tag": tag})
        for attr, value in element.attrib.items():
            normalized_attr = attr.lower().replace("-", "_")
            if normalized_attr in OWNER_TOKENS:
                owner_hits.append({"kind": "attribute", "element": tag, "attribute": attr, "value": value})

    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ContractError(f"{label} lacks geometry definition")
    dp = finite(definition.attrib.get("dp"), f"{label} dp")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ContractError(f"{label} lacks geometry mainlist")
    fluid_selector: dict[str, Any] | None = None
    body_selector: dict[str, Any] | None = None
    active_mkfluid: str | None = None
    active_mkbound: str | None = None
    for element in list(mainlist):
        tag = local_tag(element)
        if tag == "setmkfluid":
            active_mkfluid = element.attrib.get("mk")
        elif tag == "setmkbound":
            active_mkbound = element.attrib.get("mk")
        elif tag == "drawbox":
            point = element.find("point")
            size = element.find("size")
            if point is None or size is None:
                raise ContractError(f"{label} drawbox lacks point/size")
            geometry = {
                "mkfluid": active_mkfluid,
                "mkbound": active_mkbound,
                "comment": element.attrib.get("cmt"),
                "point": {axis: finite(point.attrib.get(axis), f"{label} point.{axis}") for axis in "xyz"},
                "size": {axis: finite(size.attrib.get(axis), f"{label} size.{axis}") for axis in "xyz"},
            }
            if active_mkfluid is not None and fluid_selector is None:
                fluid_selector = geometry
            if active_mkbound == "50" and body_selector is None:
                body_selector = geometry
    if fluid_selector is None:
        raise ContractError(f"{label} has no mkfluid drawbox")
    if body_selector is None:
        raise ContractError(f"{label} has no mkbound=50 drawbox")
    mkconfig = root.find("./casedef/mkconfig")
    constants = root.find("./casedef/constantsdef")
    floating = root.find("./casedef/floatings/floating[@mkbound='50']")
    if mkconfig is None or constants is None or floating is None:
        raise ContractError(f"{label} lacks mkconfig/constants/floating contract")
    massbody_element = floating.find("massbody")
    if massbody_element is None:
        raise ContractError(f"{label} floating body lacks massbody")
    massbody = finite(massbody_element.attrib.get("value"), f"{label} massbody")
    center_element = floating.find("center")
    inertia_element = floating.find("inertia")
    if center_element is None or inertia_element is None:
        raise ContractError(f"{label} floating body lacks center/inertia")
    center = [finite(center_element.attrib.get(axis), f"{label} center.{axis}") for axis in "xyz"]
    inertia = [finite(inertia_element.attrib.get(axis), f"{label} inertia.{axis}") for axis in "xyz"]
    angular = floating.find("angularvelini")
    angular_velocity = None if angular is None else [finite(angular.attrib.get(axis), f"{label} angularvelini.{axis}") for axis in "xyz"]
    rhop0 = constants.find("rhop0")
    gravity = constants.find("gravity")
    if rhop0 is None or gravity is None:
        raise ContractError(f"{label} lacks density/gravity constants")
    simulationdomain = root.find("./execution/parameters/simulationdomain")
    posmin = None if simulationdomain is None else simulationdomain.find("posmin")
    posmax = None if simulationdomain is None else simulationdomain.find("posmax")
    return {
        "label": label,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "dp_m": dp,
        "mkconfig": {"boundcount": int(mkconfig.attrib["boundcount"]), "fluidcount": int(mkconfig.attrib["fluidcount"])},
        "fluid_selector": fluid_selector,
        "body_selector": body_selector,
        "body_contract": {
            "mkbound": 50,
            "massbody_kg": massbody,
            "center_m": center,
            "inertia_kg_m2": inertia,
            "angular_velocity_rad_s": angular_velocity,
        },
        "rhop0_kg_m3": finite(rhop0.attrib.get("value"), f"{label} rhop0"),
        "gravity_m_s2": [finite(gravity.attrib.get(axis), f"{label} gravity.{axis}") for axis in "xyz"],
        "simulationdomain": {
            "posmin": None if posmin is None else dict(posmin.attrib),
            "posmax": None if posmax is None else dict(posmax.attrib),
        },
        "owner_contract_tokens_in_xml": owner_hits,
        "comment_only_owner_language": [
            item["comment"] for item in (fluid_selector, body_selector) if isinstance(item.get("comment"), str)
        ],
    }


def source_parser_evidence(paths: dict[str, Path], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cpp = paths["jcaseparts_cpp"].read_text(encoding="utf-8", errors="strict")
    header = paths["jcaseparts_h"].read_text(encoding="utf-8", errors="strict")
    # Keep these checks anchored to the official statements while tolerating
    # harmless casts/whitespace between the assignment and the call.  The
    # v5.4 source writes ``MkType=(word)sxml->...`` rather than the shorter
    # expression used by an earlier probe.
    base_patterns = (
        r"MkType\s*=.*GetAttributeUnsigned\(ele,\s*\(Bound\?\s*\"mkbound\"\s*:\s*\"mkfluid\"\)\)",
        r"Begin\s*=.*GetAttributeUlong\(ele,\s*\"begin\"\)",
        r"Count\s*=.*GetAttributeUlong\(ele,\s*\"count\"\)",
        r"Props\s*=.*GetAttributeStr\(ele,\s*\"property\",\s*true\)",
    )
    if any(re.search(pattern, cpp) is None for pattern in base_patterns):
        raise ContractError("official JCasePartBlock::ReadXml base fields changed or are missing")
    floating_patterns = (
        r"Massbody\s*=\s*sxml->ReadElementDouble\(ele,\s*\"massbody\",\s*\"value\"\)",
        r"Masspart\s*=\s*sxml->ReadElementDouble\(ele,\s*\"masspart\",\s*\"value\"\)",
        r"Center\s*=\s*sxml->ReadElementDouble3\(ele,\s*\"center\"\)",
        r"Inertia\s*=\s*(?:TMatrix3d|sxml->ReadElementMatrix3d)",
    )
    if any(re.search(pattern, cpp) is None for pattern in floating_patterns):
        raise ContractError("official floating parser mass/center/inertia fields changed or are missing")
    dispatch = 'cmd=="floating"' in cpp and 'cmd=="fluid"' in cpp
    if not dispatch:
        raise ContractError("official parser does not expose separate fluid/floating dispatch")
    fluid_class = re.search(r"class JCasePartBlock_Fluid.*?class JCaseParts", header, re.S)
    if fluid_class is None:
        raise ContractError("official JCasePartBlock_Fluid class is missing")
    fluid_block = fluid_class.group(0)
    unexpected_fluid_fields = [token for token in ("Massbody", "Masspart", "Center", "Inertia", "Owner", "Continuum") if token in fluid_block]
    if unexpected_fluid_fields:
        raise ContractError(f"fluid block unexpectedly contains owner/body fields: {unexpected_fluid_fields}")
    def line_for(pattern: str, text: str) -> int:
        match = re.search(pattern, text, re.M)
        if match is None:
            raise ContractError(f"source anchor missing: {pattern}")
        return text.count("\n", 0, match.start()) + 1
    return {
        "JCasePartBlock_ReadXml": {
            "source": records["jcaseparts_cpp"],
            "line": line_for(r"void JCasePartBlock::ReadXml", cpp),
            "recognized_fields": ["mkfluid_or_mkbound", "begin", "count", "property"],
        },
        "JCasePartBlock_Floating_ReadXml": {
            "source": records["jcaseparts_cpp"],
            "line": line_for(r"void JCasePartBlock_Floating::ReadXml", cpp),
            "recognized_fields": ["massbody", "masspart", "center", "inertia", "translationDOF_or_translation", "rotationDOF_or_rotation", "angularvelini_or_omegaini"],
        },
        "JCaseParts_dispatch": {
            "source": records["jcaseparts_cpp"],
            "line": line_for(r"void JCaseParts::ReadXml", cpp),
            "separate_fluid_and_floating_blocks": dispatch,
        },
        "JCasePartBlock_Fluid": {
            "source": records["jcaseparts_h"],
            "line": line_for(r"class JCasePartBlock_Fluid", header),
            "recognized_fields": ["base particle block fields only"],
            "body_or_owner_fields": [],
        },
        "interpretation": {
            "fluid_geometry_is_particle_selector": True,
            "floating_massbody_is_rigid_body_contract": True,
            "fluid_owner_contract_in_parser": False,
            "parser_owner_semantics": UNKNOWN_OWNER,
        },
    }


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve(), "F6 owner contract manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    paths, records = load_sources(manifest)
    definitions = []
    for key in sorted(key for key in paths if key.startswith("definition_")):
        definitions.append(parse_definition(paths[key], key))
    if len(definitions) != 6:
        raise ContractError(f"expected six F6 definitions, got {len(definitions)}")
    first = definitions[0]
    for row in definitions:
        expect(row["mkconfig"], first["mkconfig"], f"{row['label']} mkconfig")
        expect(row["fluid_selector"]["point"], first["fluid_selector"]["point"], f"{row['label']} fluid point")
        expect(row["fluid_selector"]["size"], first["fluid_selector"]["size"], f"{row['label']} fluid size")
        expect(row["body_selector"]["point"], first["body_selector"]["point"], f"{row['label']} body point")
        expect(row["body_selector"]["size"], first["body_selector"]["size"], f"{row['label']} body size")
        expect(row["body_contract"]["massbody_kg"], BODY_MASS_KG, f"{row['label']} body mass")
        if row["owner_contract_tokens_in_xml"]:
            raise ContractError(f"{row['label']} unexpectedly declares owner token: {row['owner_contract_tokens_in_xml']}")
    parser_evidence = source_parser_evidence(paths, records)
    fluid_size = first["fluid_selector"]["size"]
    selector_volume = fluid_size["x"] * fluid_size["y"] * fluid_size["z"]
    return {
        "schema": SCHEMA,
        "status": "F6_OWNER_CONTRACT_SOURCE_BOUND_BODY_EXPLICIT_FLUID_OWNER_UNLINKED",
        "source_inputs": records,
        "definition_rows": definitions,
        "parser_evidence": parser_evidence,
        "source_contract_findings": {
            "six_definitions_same_fluid_and_body_geometry": True,
            "dp_values_m": sorted({row["dp_m"] for row in definitions}),
            "angular_release_values_rad_s": [row["body_contract"]["angular_velocity_rad_s"] for row in definitions],
            "fluid_mk": 0,
            "fluid_selector_volume_m3": selector_volume,
            "fluid_selector_volume_is_not_owner_mass": True,
            "fluid_selector_comment_is_non_authoritative_annotation": True,
            "body_mkbound": 50,
            "body_mass_kg": BODY_MASS_KG,
            "body_center_m": first["body_contract"]["center_m"],
            "body_inertia_kg_m2": first["body_contract"]["inertia_kg_m2"],
            "continuous_fluid_owner_contract": UNKNOWN_OWNER,
            "owner_contract_tokens_in_six_definitions": [],
        },
        "owner_contract_gap": {
            "status": UNKNOWN_OWNER,
            "closed_by_this_audit": False,
            "specific_missing_links": [
                "A source-declared continuum owner shape or named material/region contract linked to mkfluid=0.",
                "An explicit clipping/transform/lattice-phase rule relating that owner to the drawbox selector.",
                "A source-authorized mapping from the generated fluid sample to a physical continuum mass/volume.",
            ],
            "evidence_boundary": "The parser source confirms particle block semantics and floating body fields; it does not establish continuum-owner equivalence.",
        },
        "qualification": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
        },
        "read_policy": {
            "xml_json_cpp_only": True,
            "h5_opened": False, "bi4_opened": False, "obi4_opened": False,
            "vtk_opened": False, "solver_started": False, "gencase_started": False,
            "particle_arrays_read": False, "old_products_modified": False,
        },
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise ContractError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest))
    except ContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
