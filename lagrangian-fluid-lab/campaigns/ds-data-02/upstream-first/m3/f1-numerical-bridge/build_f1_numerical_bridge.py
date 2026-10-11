#!/usr/bin/env python3
"""Prepare the bounded F1 dp=.015 numerical bridge and depth candidates.

This builder only reads the official XML definition and writes small metadata
artifacts plus three definition copies.  It never invokes GenCase or a solver.
The generated semantic diff is deliberately strict: the bridge may change the
definition ``dp`` attribute only; each depth candidate may change the fluid
fillbox ``size@z`` attribute only relative to the bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SOURCE_DEFAULT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml"
)
GENCASE_DEFAULT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)

DP_MOTHER = "0.01"
DP_BRIDGE = "0.015"
Z_MOTHER = "0.55"
Z_H050 = "0.50"
Z_H060 = "0.60"

MOTHER_TOTAL = 1_015_809
MOTHER_FLUID = 652_212
MOTHER_FRAMES = 601
MOTHER_RAW_GIB = 18.19


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def discover_worktree() -> Path:
    """Find the repository that contains the active runner scripts."""
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py").is_file():
            return candidate
    raise RuntimeError("could not locate the active upstream-first worktree")


def _definition_dp_matches(text: str) -> list[str]:
    pattern = re.compile(r"<definition\b[^>]*\bdp=\"([^\"]+)\"")
    return pattern.findall(text)


def _replace_definition_dp(text: str, new_dp: str) -> str:
    pattern = re.compile(r"(<definition\b[^>]*\bdp=\")([^\"]+)(\")")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one geometry definition dp, found {len(matches)}")
    if matches[0].group(2) != DP_MOTHER:
        raise ValueError(f"source definition dp is {matches[0].group(2)!r}, expected {DP_MOTHER!r}")
    return pattern.sub(lambda match: match.group(1) + new_dp + match.group(3), text, count=1)


def _replace_fillbox_z(text: str, new_z: str) -> str:
    fillbox_pattern = re.compile(r"(<fillbox\b[^>]*>.*?</fillbox>)", re.DOTALL)
    fillboxes = list(fillbox_pattern.finditer(text))
    if len(fillboxes) != 1:
        raise ValueError(f"expected one mainlist fillbox, found {len(fillboxes)}")
    block = fillboxes[0].group(1)
    size_pattern = re.compile(r"(<size\b[^>]*\bz=\")([^\"]+)(\")")
    sizes = list(size_pattern.finditer(block))
    if len(sizes) != 1:
        raise ValueError(f"expected one fillbox size@z, found {len(sizes)}")
    if sizes[0].group(2) != Z_MOTHER:
        raise ValueError(f"source fillbox size@z is {sizes[0].group(2)!r}, expected {Z_MOTHER!r}")
    replaced = size_pattern.sub(lambda match: match.group(1) + new_z + match.group(3), block, count=1)
    return text[: fillboxes[0].start()] + replaced + text[fillboxes[0].end() :]


def make_copy(source: Path, destination: Path, *, dp: str | None = None, fillbox_z: str | None = None) -> None:
    text = source.read_text(encoding="utf-8")
    if dp is not None:
        text = _replace_definition_dp(text, dp)
    if fillbox_z is not None:
        text = _replace_fillbox_z(text, fillbox_z)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="")


def normalized_text(value: str | None) -> str:
    return " ".join((value or "").split())


def canonical(node: ET.Element) -> dict[str, Any]:
    """Return a comment-free semantic tree; formatting whitespace is ignored."""
    return {
        "tag": node.tag,
        "attrs": [[key, node.attrib[key]] for key in sorted(node.attrib)],
        "text": normalized_text(node.text),
        "children": [canonical(child) for child in list(node)],
    }


def child_path(parent: str, children: list[ET.Element], index: int) -> str:
    child = children[index]
    tag = child.tag
    same = [item.tag for item in children]
    count = same.count(tag)
    token = tag if count == 1 else f"{tag}[{same[: index + 1].count(tag)}]"
    return f"{parent}/{token}" if parent else token


def semantic_diff(left: ET.Element, right: ET.Element) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []

    def visit(a: ET.Element, b: ET.Element, path: str) -> None:
        if a.tag != b.tag:
            diffs.append({"path": path or "ROOT", "kind": "tag", "before": a.tag, "after": b.tag})
            return
        keys = sorted(set(a.attrib) | set(b.attrib))
        for key in keys:
            before = a.attrib.get(key)
            after = b.attrib.get(key)
            if before != after:
                diffs.append({"path": f"{path}/@{key}", "kind": "attribute", "before": before, "after": after})
        before_text = normalized_text(a.text)
        after_text = normalized_text(b.text)
        if before_text != after_text:
            diffs.append({"path": f"{path}/#text", "kind": "text", "before": before_text, "after": after_text})
        left_children = list(a)
        right_children = list(b)
        if len(left_children) != len(right_children):
            diffs.append({
                "path": path or "ROOT",
                "kind": "child_count",
                "before": len(left_children),
                "after": len(right_children),
            })
        for index in range(min(len(left_children), len(right_children))):
            visit(left_children[index], right_children[index], child_path(path, left_children, index))
        for index in range(min(len(left_children), len(right_children)), len(left_children)):
            diffs.append({
                "path": child_path(path, left_children, index),
                "kind": "removed_element",
                "before": canonical(left_children[index]),
                "after": None,
            })
        for index in range(min(len(left_children), len(right_children)), len(right_children)):
            diffs.append({
                "path": child_path(path, right_children, index),
                "kind": "added_element",
                "before": None,
                "after": canonical(right_children[index]),
            })

    visit(left, right, "")
    return diffs


def parse(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def find_one(root: ET.Element, xpath: str) -> ET.Element:
    matches = root.findall(xpath)
    if len(matches) != 1:
        raise ValueError(f"expected one {xpath}, found {len(matches)}")
    return matches[0]


def physics_control_snapshot(root: ET.Element) -> dict[str, Any]:
    constants = find_one(root, "./casedef/constantsdef")
    execution = find_one(root, "./execution")
    parameters = find_one(root, "./execution/parameters")
    values = {
        parameter.attrib["key"]: parameter.attrib.get("value")
        for parameter in parameters.findall("./parameter")
    }
    constants_values = {
        child.tag: {key: child.attrib[key] for key in sorted(child.attrib)}
        for child in constants
    }
    control_tree = {"constantsdef": canonical(constants), "execution": canonical(execution)}
    return {
        "constants_values": constants_values,
        "parameter_values": values,
        "control_sha256": json_digest(control_tree),
        "time_max_s": values.get("TimeMax"),
        "time_out_s": values.get("TimeOut"),
    }


def geometry_snapshot(root: ET.Element) -> dict[str, Any]:
    definition = find_one(root, "./casedef/geometry/definition")
    size = find_one(root, "./casedef/geometry/commands/mainlist/fillbox/size")
    return {
        "definition_dp_m": definition.attrib.get("dp"),
        "fillbox_size_x_m": size.attrib.get("x"),
        "fillbox_size_y_m": size.attrib.get("y"),
        "fillbox_size_z_m": size.attrib.get("z"),
    }


def comparison_record(name: str, left_path: Path, right_path: Path, allowed: list[dict[str, str]]) -> dict[str, Any]:
    left = parse(left_path)
    right = parse(right_path)
    diffs = semantic_diff(left, right)
    expected = [(item["path"], item["before"], item["after"]) for item in allowed]
    actual = [(item["path"], item.get("before"), item.get("after")) for item in diffs]
    unexpected = [item for item in diffs if (item["path"], item.get("before"), item.get("after")) not in expected]
    missing = [item for item in allowed if (item["path"], item["before"], item["after"]) not in actual]
    if unexpected or missing or len(actual) != len(expected):
        raise AssertionError(
            f"{name} semantic diff is outside its one-axis contract: "
            f"unexpected={unexpected!r}, missing={missing!r}, actual={actual!r}"
        )
    return {
        "name": name,
        "left": str(left_path),
        "right": str(right_path),
        "allowed_changes": allowed,
        "changed_paths": diffs,
        "unexpected_changes": unexpected,
        "all_non_allowed_semantics_equal": not unexpected and not missing,
        "left_canonical_sha256": json_digest(canonical(left)),
        "right_canonical_sha256": json_digest(canonical(right)),
    }


def estimate_record() -> dict[str, Any]:
    dp_ratio = float(DP_MOTHER) / float(DP_BRIDGE)
    volume_ratio = dp_ratio**3
    surface_ratio = dp_ratio**2
    base_volume = 1.4 * 1.0 * float(Z_MOTHER)
    depth_ratios = {"H050": float(Z_H050) / float(Z_MOTHER), "H060": float(Z_H060) / float(Z_MOTHER)}
    cases: dict[str, dict[str, Any]] = {}
    for name, depth_ratio in [("BASE", 1.0), ("H050", depth_ratios["H050"]), ("H060", depth_ratios["H060"])]:
        scale = volume_ratio * depth_ratio
        cases[name] = {
            "volume_ratio_to_official_mother": scale,
            "nominal_fill_volume_m3": base_volume * depth_ratio,
            "rough_total_particles": round(MOTHER_TOTAL * scale),
            "rough_fluid_particles": round(MOTHER_FLUID * scale),
            "rough_601_frame_native_gib": round(MOTHER_RAW_GIB * scale, 3),
            "basis": "volume and particle-count scaling only; actual GenCase and solver receipts are authoritative",
        }
    return {
        "status": "rough_planning_only",
        "official_mother": {
            "dp_m": float(DP_MOTHER),
            "total_particles": MOTHER_TOTAL,
            "fluid_particles": MOTHER_FLUID,
            "raw_frames": MOTHER_FRAMES,
            "raw_native_storage_gib": MOTHER_RAW_GIB,
            "source": "parent-provided completed official F1 GenCase/601-frame planning facts",
        },
        "bridge": {
            "dp_ratio_mother_to_bridge": dp_ratio,
            "nominal_volume_ratio_mother_to_bridge": volume_ratio,
            "nominal_surface_area_ratio_mother_to_bridge": surface_ratio,
            "surface_note": "Boundary/surface storage follows dp^-2 only as a dimensional planning scale; geometry and compression can change the actual result.",
        },
        "depth_candidates": {
            "H050_volume_ratio_to_bridge": depth_ratios["H050"],
            "H060_volume_ratio_to_bridge": depth_ratios["H060"],
            "note": "Only fill volume is scaled for the depth candidates; no exact boundary-area estimate is asserted.",
        },
        "cases": cases,
        "not_a_reservation": True,
        "not_acceptance_evidence": True,
    }


def request_record(
    *,
    worktree: Path,
    gencase: Path,
    source: Path,
    definition: Path,
    case_id: str,
    role: str,
    order: int,
    gate: str,
    axis: str,
    axis_value: str | None,
    control_sha256: str,
    semantic_diff_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    runtime_v2 = worktree / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
    runtime_v6 = worktree / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
    builder = Path(__file__).resolve()
    command_prefix = definition.with_suffix("")
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": "gencase-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [str(gencase), str(command_prefix), "{attempt_root}/" + case_id, "-save:all"],
        "cwd": str(definition.parent),
        "worktree_root": str(worktree),
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 536_870_912,
        "estimated_peak_storage_bytes": 536_870_912,
        "output_storage": "upstream_nas",
        "requires_parent_nas_preflight": True,
        "reference_role": role,
        "upstream_case_id": "CaseDamBreak3D",
        "source_mother": "UF_F1_MDBC_DAMBREAK3D",
        "source_definition": str(source),
        "definition_copy": str(definition),
        "definition_copy_sha256": sha256(definition),
        "numerical_recipe": "dp=0.015m F1 official mDBC DamBreak3D geometry",
        "physical_axis": axis,
        "physical_axis_value_m": float(axis_value) if axis_value is not None else None,
        "numerical_bridge": True,
        "same_physical_mother": True,
        "root_submission_order": order,
        "root_may_submit_initially": order == 1,
        "launch_authorization": "root-controlled; this artifact is prepared metadata only",
        "launch_gate": gate,
        "solver_launch_forbidden": True,
        "fixed_physics_control_sha256": control_sha256,
        "semantic_diff": str(semantic_diff_path),
        "input_manifest": str(manifest_path),
        "request_note": (
            "GenCase receives the extensionless definition prefix because it appends .xml. "
            "This request prepares metadata only; no solver or derivative launch is authorized by the artifact."
        ),
        "input_files": [
            str(gencase),
            str(definition),
            str(source),
            str(builder),
            str(runtime_v2),
            str(runtime_v6),
            str(semantic_diff_path),
            str(manifest_path),
        ],
    }


def build(output_root: Path, source: Path, gencase: Path, worktree: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if not gencase.is_file():
        raise FileNotFoundError(gencase)
    runtime_v2 = worktree / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
    runtime_v6 = worktree / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
    if not runtime_v2.is_file() or not runtime_v6.is_file():
        raise FileNotFoundError("active runtime scripts are required as request provenance")

    input_dir = output_root / "input"
    request_dir = output_root / "requests"
    base = input_dir / "UF_F1_MDBC_DP015_BASE_Def.xml"
    h050 = input_dir / "UF_F1_MDBC_DP015_H050_Def.xml"
    h060 = input_dir / "UF_F1_MDBC_DP015_H060_Def.xml"
    make_copy(source, base, dp=DP_BRIDGE)
    make_copy(base, h050, fillbox_z=Z_H050)
    make_copy(base, h060, fillbox_z=Z_H060)

    source_root = parse(source)
    base_root = parse(base)
    h050_root = parse(h050)
    h060_root = parse(h060)
    source_controls = physics_control_snapshot(source_root)
    control_snapshots = {
        "official_mother": source_controls,
        "bridge_base": physics_control_snapshot(base_root),
        "H050": physics_control_snapshot(h050_root),
        "H060": physics_control_snapshot(h060_root),
    }
    control_hashes = {key: value["control_sha256"] for key, value in control_snapshots.items()}
    if len(set(control_hashes.values())) != 1:
        raise AssertionError(f"physics controls changed unexpectedly: {control_hashes}")
    if source_controls["time_max_s"] != "6" or source_controls["time_out_s"] != "0.01":
        raise AssertionError("official timing controls are not the requested TimeMax=6/TimeOut=.01")

    comparisons = [
        comparison_record(
            "official_mother_to_dp015_bridge",
            source,
            base,
            [{"path": "casedef/geometry/definition/@dp", "before": DP_MOTHER, "after": DP_BRIDGE}],
        ),
        comparison_record(
            "dp015_bridge_to_H050",
            base,
            h050,
            [{"path": "casedef/geometry/commands/mainlist/fillbox/size/@z", "before": Z_MOTHER, "after": Z_H050}],
        ),
        comparison_record(
            "dp015_bridge_to_H060",
            base,
            h060,
            [{"path": "casedef/geometry/commands/mainlist/fillbox/size/@z", "before": Z_MOTHER, "after": Z_H060}],
        ),
    ]

    manifest_path = output_root / "input-manifest.json"
    manifest = {
        "schema": "ds-data-02.upstream-first.m3.f1-numerical-bridge.input-manifest.v1",
        "status": "prepared_not_submitted",
        "source_mother": {
            "case_id": "UF_F1_MDBC_DAMBREAK3D",
            "official_definition": str(source),
            "official_definition_sha256": sha256(source),
            "role": "reference_only; immutable source; no derivative acceptance credit",
        },
        "recipes": {
            "bridge_base": {
                "case_id": "UF_F1_MDBC_DP015_BASE",
                "definition": str(base),
                "sha256": sha256(base),
                "geometry": geometry_snapshot(base_root),
                "edit_contract": "only casedef/geometry/definition@dp changes from official mother 0.01 to 0.015",
                "physical_condition": "same official F1 mother; numerical resolution recipe only",
            },
            "H050": {
                "case_id": "UF_F1_MDBC_DP015_H050",
                "definition": str(h050),
                "sha256": sha256(h050),
                "geometry": geometry_snapshot(h050_root),
                "edit_contract": "only casedef/geometry/commands/mainlist/fillbox/size@z changes from bridge 0.55 to 0.50",
                "physical_condition": "candidate initial fill-height derivative; no equivalence/acceptance claim",
            },
            "H060": {
                "case_id": "UF_F1_MDBC_DP015_H060",
                "definition": str(h060),
                "sha256": sha256(h060),
                "geometry": geometry_snapshot(h060_root),
                "edit_contract": "only casedef/geometry/commands/mainlist/fillbox/size@z changes from bridge 0.55 to 0.60",
                "physical_condition": "candidate initial fill-height derivative; no equivalence/acceptance claim",
            },
        },
        "physics_controls": {
            "shared_control_sha256": next(iter(control_hashes.values())),
            "snapshots": control_snapshots,
            "required_timing": {"TimeMax": "6", "TimeOut": "0.01"},
            "proof": "All non-allowed XML semantic paths are equal in each machine diff; constants and execution control digests match.",
        },
        "semantic_diff_file": str(output_root / "semantic-diff.json"),
        "semantic_diff_sha256_after_write": None,
        "rough_estimates": estimate_record(),
        "scope_policy": {
            "numerical_bridge_is_not_a_new_physical_condition": True,
            "children_wait_for_bridge_comparison_and_acceptance": True,
            "root_launch_order": ["UF_F1_MDBC_DP015_BASE", "UF_F1_MDBC_DP015_H050", "UF_F1_MDBC_DP015_H060"],
            "root_initial_submission": "BASE GenCase only; no solver launch implied",
            "acceptance_claim": "none",
        },
    }
    write_json(manifest_path, manifest)

    diff_path = output_root / "semantic-diff.json"
    diff_doc = {
        "schema": "ds-data-02.upstream-first.m3.f1-numerical-bridge.semantic-diff.v1",
        "status": "verified_prepared_definitions",
        "source_mother": str(source),
        "source_mother_sha256": sha256(source),
        "comparisons": comparisons,
        "all_comparisons_pass": all(item["all_non_allowed_semantics_equal"] for item in comparisons),
        "physics_control_sha256": control_hashes,
        "timing": {"TimeMax": source_controls["time_max_s"], "TimeOut": source_controls["time_out_s"]},
        "physical_axis": {
            "name": "initial_fill_height_m",
            "mother_reference_value_m": float(Z_MOTHER),
            "candidate_values_m": [float(Z_H050), float(Z_H060)],
            "path": "casedef/geometry/commands/mainlist/fillbox/size/@z",
        },
        "numerical_bridge": {
            "path": "casedef/geometry/definition/@dp",
            "mother_dp_m": float(DP_MOTHER),
            "bridge_dp_m": float(DP_BRIDGE),
            "same_physical_mother": True,
            "new_physical_condition": False,
        },
        "acceptance": {
            "status": "not_assessed",
            "claim": "No M1 mother acceptance, bridge equivalence, or derivative acceptance is claimed by this metadata package.",
        },
    }
    write_json(diff_path, diff_doc)
    manifest["semantic_diff_sha256_after_write"] = sha256(diff_path)
    write_json(manifest_path, manifest)

    request_specs = [
        ("BASE", base, "numerical_bridge_3d", 1, "Root may submit BASE GenCase after resource preflight and M1 mother review; no solver launch is implied.", "same physical mother; dp-only numerical recipe", None),
        ("H050", h050, "physical_derivative_candidate_3d", 2, "Do not submit before BASE GenCase receipt and an explicit bridge comparison/acceptance decision.", "initial_fill_height_m", Z_H050),
        ("H060", h060, "physical_derivative_candidate_3d", 2, "Do not submit before BASE GenCase receipt and an explicit bridge comparison/acceptance decision.", "initial_fill_height_m", Z_H060),
    ]
    for suffix, definition, role, order, gate, axis, axis_value in request_specs:
        case_id = f"UF_F1_MDBC_DP015_{suffix}"
        request = request_record(
            worktree=worktree,
            gencase=gencase,
            source=source,
            definition=definition,
            case_id=case_id,
            role=role,
            order=order,
            gate=gate,
            axis=axis,
            axis_value=axis_value,
            control_sha256=next(iter(control_hashes.values())),
            semantic_diff_path=diff_path,
            manifest_path=manifest_path,
        )
        request_path = request_dir / f"{case_id}-gencase.json"
        write_json(request_path, request)

    write_readme(output_root, source, base, h050, h060, diff_path, manifest_path)


def write_readme(output_root: Path, source: Path, base: Path, h050: Path, h060: Path, diff_path: Path, manifest_path: Path) -> None:
    readme = f"""# F1 dp=.015 numerical bridge preparation

Status: **prepared metadata only; no GenCase or solver has been launched here**.

The immutable official mother is `{source}` (`sha256={sha256(source)}`). It remains a
reference-only source. The three small XML copies are:

- `{base}` — `UF_F1_MDBC_DP015_BASE`, the same official dam-break condition with
  `casedef/geometry/definition@dp` changed from `0.01` m to `0.015` m. This is a
  numerical bridge, not a new physical condition.
- `{h050}` — `UF_F1_MDBC_DP015_H050`, copied from the bridge and changing only
  `casedef/geometry/commands/mainlist/fillbox/size@z` to `0.50` m.
- `{h060}` — `UF_F1_MDBC_DP015_H060`, copied from the bridge and changing only
  the same fillbox `size@z` to `0.60` m.

The machine proof is in `{diff_path}`. It compares the official mother to the
bridge, then the bridge to each child. Each comparison has exactly one allowed
attribute change and no other semantic XML change. The constants and execution
control digests match, including `TimeMax=6` and `TimeOut=0.01`; the full control
snapshots and source/copy hashes are in `{manifest_path}`.

## Bounded planning scales

The rough counts and raw-storage scales are planning values only. They use the
parent-provided official F1 facts (1,015,809 total particles, 652,212 fluid,
601 frames, about 18.19 GiB raw native output at `dp=.01`) and ideal volume
scaling `(0.01/0.015)^3 = 8/27`. The bridge therefore has a rough 0.2963 volume
scale and 0.4444 surface-area scale; actual GenCase counts, frame bytes,
compression, runtime, and terminal receipts remain authoritative. The `.50` and
`.60` candidates are then rough volume scales of `0.50/0.55` and `0.60/0.55`
relative to the bridge. No exact boundary-area estimate is asserted.

The three request files under `requests/` are GenCase-only, use the extensionless
definition prefix required by official GenCase, target `upstream_nas`, and require
the parent NAS preflight. `BASE` is the only first-order submission candidate.
`H050` and `H060` stay gated until BASE is compared and explicitly accepted as a
numerical bridge. No acceptance, equivalence, or production claim is made here.
"""
    (output_root / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--gencase", type=Path, default=GENCASE_DEFAULT)
    parser.add_argument("--worktree-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    worktree = (args.worktree_root or discover_worktree()).resolve()
    build(args.output_root.resolve(), args.source.resolve(), args.gencase.resolve(), worktree)
    print(f"prepared {args.output_root.resolve()}")


if __name__ == "__main__":
    main()
