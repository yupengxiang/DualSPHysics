#!/usr/bin/env python3
"""Bounded source-only owner-ladder audit for F2-S2, F3-S1 and F5-S1.

The worker reads source XML/Def, small receipts and motion/forcing files.
It never opens generated BI4/VTK/HDF5/Part payloads and never launches
GenCase or a solver.  A candidate request is only a future GenCase support
preflight; it is not a scientific qualification.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, sys
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-audit.v3"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v3"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
STATUS_SENTINELS = tuple(f"F{family}-S{slot}" for family in range(1, 8) for slot in (1, 2))
MAX_SMALL_BYTES = 16 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".h5", ".hdf5", ".part", ".hdf"}
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}
TOLERANCE_AUTHORITY: dict[str, Any] = {}

class AuditFailure(RuntimeError):
    pass

def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AuditFailure(f"{label} lacks a path")
    p = Path(value).expanduser().absolute()
    if p.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AuditFailure(f"{label} is a forbidden payload: {p}")
    return p

def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}

def _read(path: Path, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    path = _path(str(path), label)
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise AuditFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise AuditFailure(f"{label} changed during bounded read: {path}")
    rec = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
           "stat_before": before, "stat_after": after,
           "scope": "bounded_small_source_metadata"}
    if not parse_json:
        return raw, rec
    try:
        val = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not JSON: {exc}") from exc
    if not isinstance(val, dict):
        raise AuditFailure(f"{label} JSON must be an object")
    return val, rec

def _bound(binding: Any, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(binding, dict):
        raise AuditFailure(f"{label} binding is not an object")
    value, actual = _read(_path(binding.get("path"), label), label, parse_json=parse_json)
    if binding.get("sha256") is not None and actual["sha256"] != str(binding["sha256"]).lower():
        raise AuditFailure(f"{label} SHA differs from manifest binding")
    expected = binding.get("stat_after", binding.get("stat"))
    if isinstance(expected, dict):
        aliases = {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
                   "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
        for key, names in aliases.items():
            name = next((n for n in names if n in expected), None)
            if name is not None and int(expected[name]) != int(actual["stat_after"][key]):
                raise AuditFailure(f"{label} {key} differs from manifest binding")
    return value, actual

def _validate_v3_bindings(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate proof/tolerance/deferred records without opening deferred data."""
    proofs = manifest.get("proof_bindings")
    if not isinstance(proofs, list) or not proofs:
        raise AuditFailure("V3 manifest lacks exact 14-sentinel proof bindings")
    by_sid: dict[str, int] = {sid: 0 for sid in STATUS_SENTINELS}
    for item in proofs:
        if not isinstance(item, dict) or item.get("sentinel_id") not in by_sid:
            raise AuditFailure("V3 proof binding has an unknown sentinel")
        path = _path(item.get("path"), "V3 proof binding")
        raw, actual = _read(path, "V3 proof binding")
        if item.get("sha256") != actual["sha256"]:
            raise AuditFailure(f"V3 proof binding SHA changed: {path}")
        if item.get("bytes") is not None and int(item["bytes"]) != actual["stat_after"]["bytes"]:
            raise AuditFailure(f"V3 proof binding byte count changed: {path}")
        by_sid[item["sentinel_id"]] += 1
    if any(value == 0 for value in by_sid.values()):
        missing = [sid for sid, value in by_sid.items() if value == 0]
        raise AuditFailure(f"V3 proof bindings omit sentinel rows: {missing}")
    tolerance = manifest.get("tolerance_binding")
    if not isinstance(tolerance, dict) or tolerance.get("authority") != "fourteen-source-status-v3.frozen_gates":
        raise AuditFailure("V3 tolerance authority is not bound to the 14-row status card")
    source = tolerance.get("source")
    status_raw, status_rec = _bound(source, "V3 tolerance authority source", parse_json=True)
    if status_raw.get("schema") != "ds02.stage2.fourteen-source-status.v3":
        raise AuditFailure("V3 tolerance authority source schema mismatch")
    if tolerance.get("frozen_gates") != status_raw.get("frozen_gates"):
        raise AuditFailure("V3 tolerance values differ from the bound status card")
    return proofs, {"authority": tolerance["authority"], "source": status_rec,
                    "frozen_gates": status_raw.get("frozen_gates"),
                    "numeric_values_declared_in_source": False,
                    "numeric_tolerance_credit": "UNKNOWN_UNTIL_EXPLICIT_PREREGISTRATION"}

def _validate_deferred_sources(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest.get("deferred_input_records", [])
    if not isinstance(records, list):
        raise AuditFailure("V3 deferred input records are not a list")
    for item in records:
        if not isinstance(item, dict) or item.get("sentinel_id") not in TARGETS:
            raise AuditFailure("V3 deferred forcing record has invalid sentinel")
        path = _path(item.get("path"), "V3 deferred forcing")
        if item.get("read_by_builder") is not False or item.get("payload_read_by_builder") is not False:
            raise AuditFailure(f"V3 forcing was read during preparation: {path}")
        expected = item.get("stat_after", item.get("stat"))
        if not isinstance(expected, dict):
            raise AuditFailure(f"V3 deferred forcing lacks full stat: {path}")
        actual = _stat(path)
        for key, aliases in {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
                             "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
                             "ctime_ns": ("ctime_ns",)}.items():
            alias = next((name for name in aliases if name in expected), None)
            if alias is not None and int(expected[alias]) != actual[key]:
                raise AuditFailure(f"V3 deferred forcing {key} changed: {path}")
        declared = item.get("sha256")
        if declared not in (None, "PARENT_AFTER_RESERVATION_SHA_REQUIRED"):
            if not isinstance(declared, str) or len(declared) != 64:
                raise AuditFailure(f"V3 deferred forcing SHA marker is invalid: {path}")
    return records

def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()

def _num(value: Any, label: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditFailure(f"{label} is not numeric") from exc
    if not math.isfinite(x):
        raise AuditFailure(f"{label} is non-finite")
    return x

def _vector(node: ET.Element, label: str) -> list[float]:
    if not all(a in node.attrib for a in ("x", "y", "z")):
        raise AuditFailure(f"{label} lacks x/y/z")
    return [_num(node.attrib[a], f"{label}.{a}") for a in ("x", "y", "z")]

def _first(root: ET.Element, name: str, attribute: str = "value") -> str | None:
    for node in root.iter():
        if _tag(node) == name and attribute in node.attrib:
            return node.attrib[attribute]
    return None

def _parameters(root: ET.Element) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node in root.iter():
        if _tag(node) == "parameter" and "key" in node.attrib:
            out.setdefault(node.attrib["key"], []).append(node.attrib.get("value", ""))
    return out

def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in node if _tag(child) == name), None)

def _geometry_records(root: ET.Element, *, fluid_only: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    role: str | None = None
    mk: str | None = None
    primitive = {"drawbox", "drawcylinder", "drawsphere", "drawextrude"}
    def child_terms(node: ET.Element) -> list[dict[str, Any]]:
        terms = []
        for child in node:
            attrs = dict(sorted(child.attrib.items()))
            terms.append({"kind": _tag(child), "attributes": attrs})
        return terms
    for node in root.iter():
        name = _tag(node)
        if name == "setmkfluid":
            role, mk = "fluid", node.attrib.get("mk")
        elif name == "setmkbound":
            role, mk = "bound", node.attrib.get("mk")
        elif name in {"clipplane", "clipreset", "resetdraw", "setdrawmode", "setshapemode"}:
            if not fluid_only or role == "fluid":
                out.append({"kind": name, "role": role, "mk": mk,
                            "attributes": dict(sorted(node.attrib.items())),
                            "children": child_terms(node)})
        elif name in primitive and (not fluid_only or role == "fluid"):
            item: dict[str, Any] = {"kind": name, "role": role, "mk": mk,
                                    "attributes": dict(sorted(node.attrib.items())),
                                    "children": child_terms(node)}
            point, size = _child(node, "point"), _child(node, "size")
            if point is not None and size is not None and all(a in point.attrib for a in ("x","y","z")) and all(a in size.attrib for a in ("x","y","z")):
                p, s = _vector(point, f"{name}.point"), _vector(size, f"{name}.size")
                item.update({"point_m": p, "size_m": s, "volume_m3": math.prod(s)})
            else:
                item["volume_m3"] = None
            out.append(item)
    return out

def _source_facts(raw: bytes, sentinel: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AuditFailure(f"{sentinel} XML malformed: {exc}") from exc
    dp = _num(_first(root, "definition", "dp"), f"{sentinel}.definition.dp")
    if dp <= 0:
        raise AuditFailure(f"{sentinel} dp must be positive")
    refs = [_vector(n, f"{sentinel}.pointref") for n in root.iter() if _tag(n) == "pointref" and all(a in n.attrib for a in ("x","y","z"))]
    density_values = [n.attrib.get("value") for n in root.iter() if _tag(n) == "rhop0" and "value" in n.attrib]
    density = _num(density_values[0], f"{sentinel}.rhop0") if density_values else None
    grav = [_vector(n, f"{sentinel}.gravity") for n in root.iter() if _tag(n) in {"gravity","globalgravity"} and all(a in n.attrib for a in ("x","y","z"))]
    fluid = _geometry_records(root, fluid_only=True)
    terms = _geometry_records(root)
    primitive_volume = sum(x["volume_m3"] for x in fluid if isinstance(x.get("volume_m3"), (float, int)))
    references = [{k:n.attrib[k] for k in ("file","name","path") if k in n.attrib}
                  for n in root.iter() if _tag(n) in {"file","geometryfile","vtkfile","motion","accinput","acctimesfile"}]
    clips = [x for x in fluid if x["kind"] in {"clipplane","clipreset","resetdraw"}]
    boxes = [x for x in fluid if x.get("point_m") and x.get("size_m")]
    diag_l = max((max(x["size_m"]) for x in boxes), default=1.0)
    return {"definition": {"dp_m": dp, "pointref_m": refs[0] if refs else None},
            "gravity_m_s2": grav, "parameters": _parameters(root),
            "fluid_geometry": fluid, "all_geometry_terms": terms,
            "fluid_primitive_volume_m3": primitive_volume, "density_kg_m3": density,
            "source_file_references": references,
            "clip_terms": clips, "diagnostic_L_m": diag_l,
            "source_semantics": {
                "has_clip_or_reset": bool(clips),
                "has_compound_geometry": any(x["kind"] in {"drawcylinder","drawsphere","drawextrude"} for x in fluid),
                "fluid_primitive_support_status": "EXPLICIT_PRIMITIVE_ONLY"}}

def _parse_xml(raw: bytes, label: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AuditFailure(f"{label} malformed: {exc}") from exc

def _tree_diffs(left: ET.Element, right: ET.Element, path: str = "") -> list[dict[str, Any]]:
    lp, rp = _tag(left), _tag(right)
    here = f"{path}/{lp}[0]"
    if lp != rp:
        return [{"path": here, "kind": "tag", "left": lp, "right": rp}]
    diffs: list[dict[str, Any]] = []
    for key in sorted(set(left.attrib) | set(right.attrib)):
        if left.attrib.get(key) != right.attrib.get(key):
            diffs.append({"path": here, "kind": "attribute", "attribute": key,
                          "left": left.attrib.get(key), "right": right.attrib.get(key)})
    if (left.text or "").strip() != (right.text or "").strip():
        diffs.append({"path": here, "kind": "text", "left": (left.text or "").strip(), "right": (right.text or "").strip()})
    if len(left) != len(right):
        diffs.append({"path": here, "kind": "child_count", "left": len(left), "right": len(right)})
    for index, (a, b) in enumerate(zip(left, right)):
        diffs.extend(_tree_diffs(a, b, f"{here[:-2]}[{index}]"))
    return diffs

def _candidate_diff(baseline: bytes, candidate: bytes, label: str) -> dict[str, Any]:
    diffs = _tree_diffs(_parse_xml(baseline, f"{label} baseline"), _parse_xml(candidate, label))
    allowed = [x for x in diffs if x.get("kind") == "attribute" and x.get("attribute") == "dp" and x.get("path","").endswith("/definition[0]")]
    unexpected = [x for x in diffs if x not in allowed]
    return {"all_differences": diffs, "allowed_definition_dp_differences": allowed,
            "unexpected_differences": unexpected,
            "status": "PASS_ONLY_DEFINITION_DP" if diffs and not unexpected else ("PASS_IDENTICAL_BASELINE" if not diffs else "FAIL_OTHER_SOURCE_EDIT")}

def _lattice_projection(facts: dict[str, Any], label: str) -> dict[str, Any]:
    """Compute arithmetic box-index brackets without calling GenCase.

    The endpoint convention and any clip/fill/overlap rule are intentionally
    left unresolved.  The result is a diagnostic precheck that tells the
    parent exactly which frame-zero counts and boundary tests are needed.
    """
    dp = facts["definition"]["dp_m"]
    origin = facts["definition"].get("pointref_m")
    boxes = [item for item in facts.get("fluid_geometry", []) if item.get("point_m") and item.get("size_m")]
    if origin is None:
        return {"status": "POINTREF_ORIGIN_UNKNOWN", "dp_m": dp, "boxes": [], "raw_count_bracket": UNKNOWN}
    records = []
    raw_counts = []
    for index, box in enumerate(boxes):
        axes = []
        for axis in range(3):
            low = box["point_m"][axis]
            high = low + box["size_m"][axis]
            start = origin[axis]
            qlow = (low - start) / dp
            qhigh = (high - start) / dp
            # Half-open and closed-high arithmetic hypotheses.  The epsilon
            # is only for decimal representation; no scientific tolerance is
            # applied and no count is treated as an observed GenCase result.
            eps = 1e-10
            lo = math.ceil(qlow - eps)
            hi_exclusive = math.ceil(qhigh - eps) - 1
            hi_inclusive = math.floor(qhigh + eps)
            n_exclusive = max(0, hi_exclusive - lo + 1)
            n_inclusive = max(0, hi_inclusive - lo + 1)
            axes.append({"low_m": low, "high_m": high, "origin_m": start,
                         "index_low": lo, "index_high_half_open": hi_exclusive,
                         "index_high_closed": hi_inclusive,
                         "count_half_open": n_exclusive, "count_closed_high": n_inclusive})
        exclusive = math.prod(axis["count_half_open"] for axis in axes)
        inclusive = math.prod(axis["count_closed_high"] for axis in axes)
        raw_counts.append({"box_index": index, "count_half_open": exclusive, "count_closed_high": inclusive})
        records.append({"box_index": index, "axes": axes})
    return {"status": "ARITHMETIC_BOX_INDEX_BRACKET_ONLY", "dp_m": dp,
            "origin_m": origin, "boxes": records, "raw_box_counts": raw_counts,
            "raw_count_bracket": {"lower": sum(x["count_half_open"] for x in raw_counts),
                                   "upper": sum(x["count_closed_high"] for x in raw_counts),
                                   "overlap_and_clip_unresolved": True}}

def _owner_region_predicate(sid: str, facts: dict[str, Any]) -> dict[str, Any]:
    terms = facts.get("fluid_geometry", [])
    boxes = [item for item in terms if item.get("kind") == "drawbox" and item.get("point_m") and item.get("size_m")]
    if sid in {"F2-S2", "F3-S1"}:
        return {"status": "SOURCE_AXIS_ALIGNED_UNION_PREDICATE",
                "expression": "OR over fluid drawboxes: low_x<=x<high_x AND low_y<=y<high_y AND low_z<=z<high_z",
                "boxes": [{"low_m": b["point_m"], "high_m": [b["point_m"][i]+b["size_m"][i] for i in range(3)]} for b in boxes],
                "endpoint_convention": "UNRESOLVED_UNTIL_GENERATED_SUPPORT_AUDIT",
                "overlap_status": UNKNOWN, "crop_status": UNKNOWN}
    clip = next((item for item in terms if item.get("kind") == "clipplane"), None)
    children = (clip or {}).get("children", [])
    point = next((x.get("attributes") for x in children if x.get("kind") == "point"), None)
    vector = next((x.get("attributes") for x in children if x.get("kind") == "vector"), None)
    return {"status": "SOURCE_PROFILE_AND_CLIP_PREDICATE_MATH_ONLY",
            "expression": "closed drawextrude profile intersect clip half-space; no particle crop assumed",
            "clip_point": point, "clip_normal": vector,
            "clip_half_space": "n dot x + d <= 0 with d=-n dot point; official implementation binding required",
            "profile_terms": [x for x in terms if x.get("kind") in {"drawextrude", "clipplane", "clipreset"}],
            "overlap_status": UNKNOWN, "crop_status": UNKNOWN,
            "continuous_owner_status": "UNKNOWN_UNTIL_CLIP_AND_FILL_SUPPORT_PROVED"}

def _status_index(status: dict[str, Any]) -> list[dict[str, Any]]:
    rows = status.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14:
        raise AuditFailure("status card must contain exactly 14 sentinels")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise AuditFailure("malformed status row")
        category = str((row.get("terminal_state") or {}).get("category", "UNKNOWN"))
        scopes = [str(e.get("claim_scope")) for e in row.get("evidence", []) if isinstance(e, dict) and e.get("claim_scope")]
        lower = " ".join([category, *scopes]).lower()
        def mark(dimension: str) -> str:
            # Use narrow phrases for a three-grid or one-variable study.  A
            # row saying "spatial" or "full window" alone is partial evidence,
            # not a completed three-grid error study.
            if dimension == "spatial":
                actual_words = ("cross-grid", "three-grid", "three grid")
                partial_words = ("grid", "spatial", "three-rung", "lattice")
            elif dimension == "time":
                actual_words = ("same-cfl", "half-cfl", "saved-time", "saved time", "integrat", "dt")
                partial_words = ("time", "frame", "window", "cfl")
            else:
                actual_words = ("output", "observer", "saved-time", "saved time", "frame")
                partial_words = ("output", "observer", "saved", "frame", "window")
            if "actual" in lower and any(w in lower for w in actual_words):
                return "ACTUAL_DIAGNOSTIC_EVIDENCE"
            if any(w in lower for w in partial_words):
                return "PARTIAL_ACTUAL_OR_SOURCE_PLAN"
            return "NOT_ESTABLISHED"
        terminal = row.get("terminal_state") or {}
        out.append({"sentinel_id": row["sentinel_id"], "family_id": row.get("family_id"),
                    "physical_case_id": row.get("physical_case_id"), "terminal_category": category,
                    "status": terminal.get("status"), "actual_evidence_scopes": scopes,
                    "spatial_three_grid_scope": mark("spatial"),
                    "time_step_scope": mark("time"),
                    "output_sampling_scope": mark("output"),
                    "next_guarded_task": row.get("next_guarded_task"),
                    "scientific_qualification": terminal.get("scientific_qualification", QUALIFICATION)})
    return out

def _owner_spec(sid: str, source: dict[str, Any]) -> dict[str, Any]:
    density = source.get("density_kg_m3")
    volume = source["fluid_primitive_volume_m3"]
    result = {"sentinel_id": sid, "status": "UNVERIFIED_SOURCE_CONTINUOUS_OWNER",
              "source_primitive_volume_m3": volume,
              "source_primitive_mass_kg": volume*density if density is not None else UNKNOWN,
              "source_region_definition": {
                  "fluid_primitives": source.get("fluid_geometry", []),
                  "clip_terms": source.get("clip_terms", []),
                  "gravity_m_s2": source.get("gravity_m_s2", []),
                  "pointref_m": source.get("definition", {}).get("pointref_m"),
                  "density_kg_m3": density,
                  "primitive_union_overlap": UNKNOWN,
                  "fill_crop_and_effective_support": UNKNOWN,
              },
              "source_region_predicate": _owner_region_predicate(sid, source),
              "source_lattice_projection": _lattice_projection(source, sid),
              "owner_mass_kg": UNKNOWN, "owner_region_support": UNKNOWN}
    if sid == "F2-S2":
        result.update({"status": "UNVERIFIED_SOURCE_PRIMITIVE_TARGET",
                       "reason": "18.876 kg is derived from this source's three fluid boxes only; no cross-sentinel owner import and no effective support proof."})
    elif sid == "F5-S1":
        result.update({"status": "CLIPPED_OR_COMPOUND_OWNER_REQUIRES_SUPPORT_AUDIT",
                       "reason": "clipplane/draw ordering is part of the source region; raw box volume cannot be called the continuous owner."})
    else:
        result["reason"] = "source box is explicit, but owner support/crop and authoritative continuous mass are unclosed."
    return result

def _request_case(sid: str, case: dict[str, Any], facts: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    tolerance_authority = TOLERANCE_AUTHORITY or {
        "authority": "UNBOUND_IN_UNIT_TEST",
        "frozen_gates": None,
        "numeric_values_declared_in_source": False,
        "numeric_tolerance_credit": "UNKNOWN",
    }
    return {"sentinel_id": sid, "family_id": case.get("family_id"), "physical_case_id": case.get("physical_case_id"),
            "grid_label": grid["label"], "candidate_dp_m": grid["dp_m"],
            "source_edit_contract": {"allowed": ["definition@dp"],
                "forbidden": ["drawbox","drawcylinder","drawextrude","clipplane","clipreset","pointref","size","motion","gravity","parameters"],
                "comparison_status": grid["comparison"]["status"]},
            "source_inputs": {"source_xml": case["source_xml"], "source_def": case["source_def"],
                              "motion_or_forcing": case.get("motion_or_forcing"), "candidate_def": grid["candidate_def"],
                              "owner_region_predicate": _owner_region_predicate(sid, facts)},
            "gencase_only": {"command_entry": "official GenCase_linux64 <case-stem> -threads:1",
                "stem_rule": "pass the stem without .xml; do not append an extra _Def",
                "execution": "PARENT_GUARDED_ONLY", "solver_launch": False},
            "deferred_generated_products": [
                {"role": role, "status": "PARENT_AFTER_RESERVATION_SHA_REQUIRED"}
                for role in ("generated_xml","generated_Fluid_vtk","generated_Bound_vtk","generated_bi4")],
            "initial_support_gate": {"required": [
                "generated XML role/count/mass metadata join",
                "Fluid/Bound finite coordinates and point-count/role join",
                "fluid-vs-bound overlap and owner-region membership",
                "native frame-0 Idp/type/role identity and finite fields when BI4 is available",
                "native MassFluid/MassBound when present; XML mass is separate"],
                "owner_mass_comparison": "DIAGNOSTIC_ONLY_UNTIL_OWNER_SPEC_CLOSED",
                "arithmetic_precheck": {
                    "status": "COMPARE_GUARDED_GENERATED_COUNTS_TO_SOURCE_LATTICE_BRACKET",
                    "candidate_raw_box_projection": grid.get("lattice_projection"),
                    "do_not_promote_to_observed_count": True,
                },
                "mass_rescale": False, "support_credit": "UNKNOWN_UNTIL_GUARDED_PRODUCT"},
            "pre_registered_observables": {"frame_zero": ["native time","native dp","native MassFluid/MassBound","role counts","finite Posd/Vel/Rhop","fluid weighted COM/velocity/KE"],
                "queries": [0.0,0.25,0.5,1.0], "alignment": "actual saved-time brackets only; no interpolation",
                "tolerance_authority": tolerance_authority,
                "position_tolerance_m": UNKNOWN,
                "velocity_relative_tolerance": UNKNOWN, "kinetic_energy_relative_tolerance": UNKNOWN,
                "mass_relative_tolerance": UNKNOWN, "time_output_budget_fraction": UNKNOWN,
                "event_time": UNKNOWN, "truth_source": UNKNOWN},
            "scientific_qualification": QUALIFICATION}

def _case_result(case: dict[str, Any]) -> dict[str, Any]:
    sid = case["sentinel_id"]
    source_raw, source_record = _bound(case["source_xml"], f"{sid} source XML")
    def_raw, def_record = _bound(case["source_def"], f"{sid} source Def")
    receipt, receipt_record = _bound(case.get("source_receipt"), f"{sid} source producer receipt", parse_json=True)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditFailure(f"{sid} source producer receipt is not completed with returncode 0")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict):
        raise AuditFailure(f"{sid} source producer receipt lacks request")
    if receipt_request.get("family_id") not in (None, case.get("family_id")):
        raise AuditFailure(f"{sid} source producer family identity mismatch")
    receipt_identity = {
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "case_id": receipt_request.get("case_id"),
        "attempt_id": receipt_request.get("attempt_id"),
        "physical_case_id": receipt_request.get("physical_case_id"),
        "request_sha256": receipt.get("request_sha256"),
        "output_root": receipt.get("output_root"),
    }
    source = _source_facts(source_raw, sid)
    source_def = _source_facts(def_raw, sid)
    if source["definition"]["dp_m"] != source_def["definition"]["dp_m"]:
        raise AuditFailure(f"{sid} generated XML and source Def dp disagree")
    baseline = next((g for g in case["grids"] if g.get("label") == "original"), None)
    if baseline is None:
        raise AuditFailure(f"{sid} lacks original candidate")
    baseline_raw, _ = _bound(baseline["candidate_def"], f"{sid} original candidate Def")
    source_alignment = _candidate_diff(def_raw, baseline_raw, f"{sid} source Def to original candidate")
    if source_alignment["unexpected_differences"]:
        raise AuditFailure(f"{sid} original candidate is not the actual source Def: unexpected semantic edits")
    grids, requests = [], []
    for g in case["grids"]:
        raw, rec = _bound(g["candidate_def"], f"{sid} {g['label']} candidate Def")
        facts = _source_facts(raw, f"{sid} {g['label']}")
        comparison = _candidate_diff(baseline_raw, raw, f"{sid} {g['label']}")
        item = {"label": g["label"], "dp_m": facts["definition"]["dp_m"],
                "candidate_def": rec, "comparison": comparison,
                "candidate_geometry_terms": facts["all_geometry_terms"],
                "candidate_controls": facts["parameters"], "motion_or_forcing": g.get("motion_or_forcing"),
                "lattice_projection": _lattice_projection(facts, f"{sid} {g['label']}"),
                "support_status": "UNKNOWN_UNTIL_PARENT_GUARDED_GENCASE"}
        grids.append(item)
        requests.append(_request_case(sid, case, source, item))
    return {"sentinel_id": sid, "family_id": case.get("family_id"), "physical_case_id": case.get("physical_case_id"),
            "source_bindings": {"source_xml": source_record, "source_def": def_record, "source_receipt": receipt_record},
            "producer_identity": receipt_identity,
            "source_control": {"gravity_m_s2": source["gravity_m_s2"], "definition_dp_m": source["definition"]["dp_m"],
                "pointref_m": source["definition"]["pointref_m"], "parameters": source["parameters"],
                "source_file_references": source["source_file_references"], "fluid_geometry": source["fluid_geometry"],
                "all_geometry_terms": source["all_geometry_terms"], "clip_terms": source["clip_terms"],
                "motion_or_forcing": case.get("motion_or_forcing"),
            "source_control_semantics": "SOURCE_PRIMITIVES_READ; ONLY_DEFINITION_DP_MAY_VARY",
            "source_def_to_original_candidate": source_alignment},
            "owner_spec": _owner_spec(sid, source), "grids": grids, "source_requests": requests,
            "missing_evidence": ["continuous-owner authority/source proof",
                "parent-generated Fluid/Bound support, overlap and owner-region containment",
                "effective/native fluid mass and MassFluid/MassBound fields",
                "world/event characteristic scale for event-time Q"],
            "scientific_qualification": QUALIFICATION}

def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    global TOLERANCE_AUTHORITY
    manifest, manifest_rec = _read(manifest_path, "owner-grid source manifest", parse_json=True)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_SOURCE_OWNER_GRID_AUDIT_V3":
        raise AuditFailure("manifest schema/status mismatch")
    if manifest.get("sentinel_ids") != list(TARGETS):
        raise AuditFailure("target sentinel list mismatch")
    inputs = manifest.get("source_inputs") or {}
    status, status_rec = _bound(inputs.get("status_report"), "14-sentinel status", parse_json=True)
    source_audit, source_audit_rec = _bound(inputs.get("source_control_audit"), "source/control audit", parse_json=True)
    geometry_bounds, geometry_bounds_rec = _bound(inputs.get("geometry_bounds"), "continuum geometry bounds", parse_json=True)
    if status.get("schema") != "ds02.stage2.fourteen-source-status.v3":
        raise AuditFailure("unexpected 14-sentinel status schema")
    if source_audit.get("schema") != "ds02.stage2.fourteen-source-control-audit.v5":
        raise AuditFailure("unexpected source/control audit schema")
    if geometry_bounds.get("schema") != "ds02.stage2.continuum-geometry-bounds.v1":
        raise AuditFailure("unexpected continuum geometry bounds schema")
    audit_rows = {row.get("sentinel_id"): row for row in source_audit.get("sources", []) if isinstance(row, dict)}
    bound_rows = {row.get("sentinel_id"): row for row in geometry_bounds.get("sources", []) if isinstance(row, dict)}
    cases = manifest.get("cases")
    if not isinstance(cases, list) or {x.get("sentinel_id") for x in cases} != set(TARGETS):
        raise AuditFailure("manifest cases do not cover targets")
    for case in cases:
        sid = case["sentinel_id"]
        audit_row, bound_row = audit_rows.get(sid), bound_rows.get(sid)
        if not isinstance(audit_row, dict) or not isinstance(bound_row, dict):
            raise AuditFailure(f"{sid} is missing from source/control or bounds audit")
        xml_ref = audit_row.get("source_xml")
        case_xml = case.get("source_xml")
        if not isinstance(xml_ref, dict) or not isinstance(case_xml, dict) or xml_ref.get("path") != case_xml.get("path") or xml_ref.get("sha256") != case_xml.get("sha256"):
            raise AuditFailure(f"{sid} source XML is not joined to the actual source audit")
        bound_xml = bound_row.get("source_xml")
        if not isinstance(bound_xml, dict) or bound_xml.get("path") != case_xml.get("path") or bound_xml.get("sha256") != case_xml.get("sha256"):
            raise AuditFailure(f"{sid} source XML is not joined to the geometry bounds audit")
        receipt_ref = ((audit_row.get("source_solver_control") or {}).get("receipt"))
        case_receipt = case.get("source_receipt")
        if not isinstance(receipt_ref, dict) or not isinstance(case_receipt, dict) or receipt_ref.get("path") != case_receipt.get("path") or receipt_ref.get("sha256") != case_receipt.get("sha256"):
            raise AuditFailure(f"{sid} receipt is not joined to the actual source audit")
    proof_bindings, tolerance = _validate_v3_bindings(manifest)
    deferred_sources = _validate_deferred_sources(manifest)
    TOLERANCE_AUTHORITY = tolerance
    results = [_case_result(x) for x in cases]
    result = {"schema": SCHEMA, "status": "COMPLETE_SOURCE_OWNER_GRID_AUDIT_V3_NO_SCIENTIFIC_Q",
              "manifest": manifest_rec, "source_status": status_rec,
              "source_control_audit": source_audit_rec, "geometry_bounds": geometry_bounds_rec,
              "proof_bindings": proof_bindings, "deferred_input_records": deferred_sources,
              "tolerance_binding": tolerance,
              "cases": results,
              "fourteen_scope_index": _status_index(status),
              "frozen_task_contract": {
                  "authority": tolerance["authority"],
                  "source_frozen_gates": tolerance["frozen_gates"],
                  "numeric_values_declared_in_source": False,
                  "spatial": "source diagnostic only; numeric position tolerance is not declared by this worker",
                  "velocity": "numeric tolerance unavailable until an explicit preregistration binds a nonzero scale",
                  "kinetic_energy": "numeric tolerance unavailable until an explicit preregistration binds a nonzero scale",
                  "mass": "continuous owner mass and numeric gate remain unresolved",
                  "time_and_output": "saved-time brackets remain un-interpolated; numeric budget authority is source-bound only",
                  "event_time": UNKNOWN},
              "read_scope": {"bounded_xml_json_csv_motion_only": True, "production_bi4_read": False,
                  "production_vtk_read": False, "hdf5_read": False, "solver_or_gencase_launch": False},
              "scientific_qualification": QUALIFICATION}
    output_path = output_path.expanduser().absolute()
    if output_path.exists() or output_path.is_symlink():
        raise AuditFailure(f"refusing to overwrite immutable output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    with temp.open("rb") as handle: os.fsync(handle.fileno())
    os.replace(temp, output_path)
    return result

def _fixture_manifest(tmp: Path) -> Path:
    source = b"""<case><casedef><constantsdef><gravity x='0' y='0' z='-9.81'/></constantsdef><geometry><definition dp='0.01'><pointref x='0.005' y='0.005' z='0.005'><commands><setmkfluid mk='0'/><drawbox><point x='0' y='0' z='0'/><size x='0.1' y='0.2' z='0.3'/></drawbox></commands></definition></geometry><execution><cflnumber value='0.2'/><parameter key='TimeMax' value='1'/><parameter key='TimeOut' value='0.1'/></execution></casedef></case>"""
    source = source.replace(b"<pointref x='0.005' y='0.005' z='0.005'>", b"<pointref x='0.005' y='0.005' z='0.005'/>")
    # The minimal fixture has separate commands under definition.
    source = source.replace(b"</pointref><commands>", b"<commands>")
    import tempfile
    receipt_raw = json.dumps({"status": "completed", "returncode": 0,
                              "request": {"case_id": "fixture", "attempt_id": "fixture-001"}}).encode()
    for name, raw in [("source.xml", source), ("source_Def.xml", source), ("original_Def.xml", source),
                      ("coarse_Def.xml", source.replace(b"dp='0.01'", b"dp='0.02'", 1))]:
        (tmp/name).write_bytes(raw)
    (tmp/"receipt.json").write_bytes(receipt_raw)
    rows = []
    for sid in ("F1-S1", "F1-S2", "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S1", "F4-S2", "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2"):
        rows.append({"sentinel_id": sid, "family_id": sid[:2], "physical_case_id": sid+"_case",
                     "evidence": [], "terminal_state": {"category": "SOURCE_PLAN"}, "next_guarded_task": {}})
    def rec(p: Path) -> dict[str, Any]:
        raw=p.read_bytes(); return {"path":str(p),"sha256":hashlib.sha256(raw).hexdigest(),"stat_after":_stat(p)}
    for row in rows:
        proof = tmp / (row["sentinel_id"].replace("-", "_") + "_proof.json")
        proof.write_text(json.dumps({"sentinel_id": row["sentinel_id"], "fixture": True}))
        proof_record = rec(proof)
        row["evidence"] = [{"kind": "proof_json", "name": proof.name,
                             "claim_scope": "fixture source proof",
                             "file": {"path": proof_record["path"], "sha256": proof_record["sha256"],
                                      "bytes": proof_record["stat_after"]["bytes"]}}]
    status = tmp/"status.json"
    status.write_text(json.dumps({"schema":"ds02.stage2.fourteen-source-status.v3",
                                  "frozen_gates": {"fixture": "diagnostic-only"}, "sentinels":rows}))
    audit_rows = []
    bound_rows = []
    for sid in TARGETS:
        audit_rows.append({"sentinel_id": sid, "source_xml": rec(tmp/"source.xml"),
                           "source_solver_control": {"receipt": rec(tmp/"receipt.json")}})
        bound_rows.append({"sentinel_id": sid, "source_xml": rec(tmp/"source.xml")})
    audit_path = tmp/"audit.json"
    audit_path.write_text(json.dumps({"schema": "ds02.stage2.fourteen-source-control-audit.v5", "sources": audit_rows}))
    bounds_path = tmp/"bounds.json"
    bounds_path.write_text(json.dumps({"schema": "ds02.stage2.continuum-geometry-bounds.v1", "sources": bound_rows}))
    def make_case(sid: str) -> dict[str, Any]:
        return {"sentinel_id":sid,"family_id":sid[:2],"physical_case_id":sid+"_case",
                "source_xml":rec(tmp/"source.xml"),"source_def":rec(tmp/"source_Def.xml"),
                "source_receipt":rec(tmp/"receipt.json"),
                "motion_or_forcing":None,
                "grids":[{"label":"original","candidate_def":rec(tmp/"original_Def.xml"),"motion_or_forcing":None},
                          {"label":"coarse","candidate_def":rec(tmp/"coarse_Def.xml"),"motion_or_forcing":None},
                          {"label":"fine","candidate_def":rec(tmp/"original_Def.xml"),"motion_or_forcing":None}]}
    m={"schema":MANIFEST_SCHEMA,"status":"PREPARED_SOURCE_OWNER_GRID_AUDIT_V3","sentinel_ids":list(TARGETS),
       "source_inputs":{"status_report":rec(status), "source_control_audit":rec(audit_path), "geometry_bounds":rec(bounds_path)},
       "proof_bindings": [{"sentinel_id": row["sentinel_id"], **row["evidence"][0]["file"]} for row in rows],
       "tolerance_binding": {"authority": "fourteen-source-status-v3.frozen_gates",
                             "source": rec(status), "frozen_gates": {"fixture": "diagnostic-only"},
                             "numeric_values_declared_in_source": False},
       "deferred_input_records": [],
       "cases":[make_case(s) for s in TARGETS],"static_sources":[]}
    out=tmp/"manifest.json"; out.write_text(json.dumps(m)); return out

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ds02-owner-grid-") as value:
        out=Path(value)/"report.json"
        result=run(_fixture_manifest(Path(value)), out)
        assert len(result["cases"]) == 3
        assert result["cases"][0]["grids"][1]["comparison"]["status"] == "PASS_ONLY_DEFINITION_DP"
        assert result["cases"][0]["owner_spec"]["owner_mass_kg"] == UNKNOWN
        assert len(result["fourteen_scope_index"]) == 14
    print("PASS_THREE_SENTINEL_OWNER_GRID_SOURCE_AUDIT_V3_SELFTEST")

def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path)
    args=parser.parse_args(argv)
    if args.self_test: self_test(); return 0
    if args.manifest is None or args.output is None: parser.error("--manifest and --output are required unless --self-test")
    try: result=run(args.manifest,args.output)
    except (AuditFailure,OSError,ValueError,ET.ParseError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_SOURCE_AUDIT: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status":result["status"],"output":str(Path(args.output).absolute()),"cases":len(result["cases"]),"scientific_credit":0},sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
