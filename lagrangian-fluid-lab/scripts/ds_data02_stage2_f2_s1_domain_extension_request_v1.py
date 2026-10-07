#!/usr/bin/env python3
"""Prepare a source-exact F2-S1 numerical-domain paired control.

The completed original dp=0.01 F2-S1 full-window run is immutable.  This
forward-only preparation reuses its exact initial BI4 and motion file through
read-only symlinks and writes a new XML whose sole semantic change is the
runtime simulation-domain x-low face (``-1.40`` to ``-1.60`` m).  It does not
move a wetted wall, alter particles, rescale mass, change CFL, or run GenCase
or DualSPHysics.  The generated solver request is launch-disabled and belongs
to the primary coordinator.

The sidecar also carries a calibrated-observer plan for a later native
PartVTKOut/RunPARTs audit.  It does not make a physical-spill or dynamical
claim from the paired design.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
SOLVER_DEFAULT = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DISPATCH_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SOURCE_CASE_ID = "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
X_LOW_EXTENSION_M = -1.60
X_LOW_EXTENSION_TEXT = "-1.60"


class PreparationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).resolve()
    if not value.is_file():
        raise PreparationError(f"{label} is missing: {value}")
    return value


def require_dir(path: str | Path, label: str) -> Path:
    value = Path(path).resolve()
    if not value.is_dir():
        raise PreparationError(f"{label} is missing: {value}")
    return value


def require_file_preserve_symlink(path: str | Path, label: str) -> Path:
    """Validate a file without collapsing its lexical symlink path.

    The candidate BI4 and motion inputs deliberately remain symlinks to the
    immutable source.  The guard must receive the candidate path as an input,
    while the digest still follows the link to the source bytes.
    """
    value = Path(os.path.abspath(os.fspath(path)))
    if not value.is_file():
        raise PreparationError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        data = json.loads(value.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PreparationError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(data, dict):
        raise PreparationError(f"{label} is not an object: {value}")
    return value, data


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _descendant(root: ET.Element, tag: str) -> ET.Element:
    for node in root.iter():
        if _tag(node) == tag:
            return node
    raise PreparationError(f"XML element {tag} is missing")


def _simulation_domain(root: ET.Element) -> tuple[ET.Element, dict[str, dict[str, str]]]:
    parameters = _descendant(root, "parameters")
    domain = next((node for node in parameters if _tag(node) == "simulationdomain"), None)
    if domain is None:
        raise PreparationError("XML simulationdomain is missing")
    values: dict[str, dict[str, str]] = {}
    for name in ("posmin", "posmax"):
        node = next((item for item in domain if _tag(item) == name), None)
        if node is None:
            raise PreparationError(f"XML simulationdomain/{name} is missing")
        values[name] = {axis: node.attrib[axis] for axis in "xyz"}
    return domain, values


def _semantic_xml(path: Path, *, restore_domain: dict[str, dict[str, str]] | None = None) -> bytes:
    root = ET.parse(path).getroot()
    if restore_domain is not None:
        domain, _ = _simulation_domain(root)
        for name in ("posmin", "posmax"):
            node = next(item for item in domain if _tag(item) == name)
            node.attrib.update(restore_domain[name])
    # XML comments include generation timestamps in some source trees.  The
    # ElementTree representation intentionally compares semantic elements and
    # attributes only, so those comments cannot hide a geometry mutation.
    return ET.tostring(root, encoding="utf-8")


def _source_paths(receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise PreparationError("unsupported original solver receipt schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PreparationError("original F2-S1 solver receipt is not completed")
    request = receipt.get("request", {})
    if request.get("family_id") != "F2" or request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise PreparationError("original solver receipt is not the exact CURRENT F2-S1 physical case")
    if request.get("case_id") != SOURCE_CASE_ID:
        raise PreparationError("original solver receipt case ID is not the registered dp=0.01 source")
    root = require_dir(receipt.get("output_root", ""), "original solver output root")
    if root != receipt_path.parent:
        raise PreparationError("original solver receipt output_root is inconsistent")
    command = request.get("command", [])
    if not isinstance(command, list) or len(command) < 3:
        raise PreparationError("original solver command is incomplete")
    if command[2:] != [
        "{attempt_root}/solver_output", "-tmax:4", "-tout:0.01"
    ]:
        raise PreparationError("original solver control flags are not the registered dp=0.01 source")
    prefix = require_file(str(command[1]) + ".xml", "original generated XML")
    bi4 = require_file(str(command[1]) + ".bi4", "original generated BI4")
    tree = ET.parse(prefix)
    domain, domain_values = _simulation_domain(tree.getroot())
    try:
        original_x_low = float(domain_values["posmin"]["x"])
        source_dp = float(_descendant(tree.getroot(), "definition").attrib["dp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreparationError("original XML domain or dp is invalid") from exc
    if abs(original_x_low + 1.40) > 1e-12 or abs(source_dp - 0.01) > 1e-12:
        raise PreparationError("original XML is not the registered x=-1.40, dp=0.01 source")
    motion_node = next((node for node in tree.getroot().iter() if _tag(node) == "file" and "name" in node.attrib), None)
    if motion_node is None:
        raise PreparationError("original XML motion file is missing")
    motion = require_file(prefix.parent / motion_node.attrib["name"], "original motion file")
    receipt_inputs = request.get("input_sha256", {})
    bi4_declared = receipt_inputs.get(str(bi4))
    motion_declared = receipt_inputs.get(str(motion))
    if not bi4_declared or not motion_declared:
        raise PreparationError("original solver receipt lacks generated BI4 or motion digest")
    if sha256(motion) != motion_declared:
        raise PreparationError("original motion file changed from completed solver receipt")
    if sha256(bi4) != bi4_declared:
        raise PreparationError("original generated BI4 changed from completed solver receipt")
    gencase_receipt = request.get("gencase_receipt")
    if not gencase_receipt:
        raise PreparationError("original solver receipt lacks candidate GenCase receipt")
    gencase_receipt_path = require_file(gencase_receipt, "original GenCase receipt")
    try:
        gencase_data = json.loads(gencase_receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError("original GenCase receipt is invalid JSON") from exc
    if gencase_data.get("status") != "completed" or gencase_data.get("returncode") != 0:
        raise PreparationError("original GenCase receipt is not completed")
    return {
        "receipt_path": receipt_path,
        "receipt": receipt,
        "root": root,
        "command": command,
        "prefix": prefix,
        "bi4": bi4,
        "motion": motion,
        "gencase_receipt": gencase_receipt_path,
        "domain_values": domain_values,
        "original_x_low": original_x_low,
        "source_dp": source_dp,
        "bi4_sha256": bi4_declared,
        "motion_sha256": motion_declared,
    }


def prepare_candidate(*, solver_receipt_path: Path, output_dir: Path) -> dict[str, Any]:
    solver_receipt_path, receipt = read_json(solver_receipt_path, "original solver receipt")
    source = _source_paths(solver_receipt_path, receipt)
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PreparationError(f"candidate output directory must be fresh: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_prefix = output_dir / "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V1"
    candidate_xml = candidate_prefix.with_suffix(".xml")
    tree = ET.parse(source["prefix"])
    root = tree.getroot()
    domain, original_values = _simulation_domain(root)
    posmin = next(node for node in domain if _tag(node) == "posmin")
    posmin.set("x", X_LOW_EXTENSION_TEXT)
    candidate_values = {name: dict(values) for name, values in original_values.items()}
    candidate_values["posmin"]["x"] = X_LOW_EXTENSION_TEXT
    ET.indent(tree, space="    ")
    tree.write(candidate_xml, encoding="utf-8", xml_declaration=True)
    # The initial particle population and motion are immutable inputs.  A
    # symlink avoids copying a 25 MB BI4 into the source repository while the
    # guarded solver still hashes the actual target at launch.
    candidate_bi4 = candidate_prefix.with_suffix(".bi4")
    candidate_bi4.symlink_to(source["bi4"])
    motion_name = source["motion"].name
    candidate_motion = output_dir / motion_name
    candidate_motion.symlink_to(source["motion"])
    if _semantic_xml(candidate_xml, restore_domain=candidate_values) == _semantic_xml(source["prefix"]):
        raise PreparationError("candidate XML did not retain the intended domain change")
    if _semantic_xml(candidate_xml, restore_domain=original_values) != _semantic_xml(source["prefix"]):
        raise PreparationError("candidate XML changed fields outside simulationdomain/posmin.x")
    manifest = {
        "schema": "ds02.stage2.f2-s1-domain-extension-preparation.v1",
        "status": "PREPARED_LAUNCH_DISABLED",
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_solver_receipt": {"path": str(solver_receipt_path), "sha256": sha256(solver_receipt_path)},
        "source_generated_xml": {"path": str(source["prefix"]), "sha256": sha256(source["prefix"])},
        "source_generated_bi4": {"path": str(source["bi4"]), "sha256": source["bi4_sha256"]},
        "source_motion": {"path": str(source["motion"]), "sha256": source["motion_sha256"]},
        "source_gencase_receipt": {
            "path": str(source["gencase_receipt"]),
            "sha256": sha256(source["gencase_receipt"]),
        },
        "candidate_generated_xml": {"path": str(candidate_xml), "sha256": sha256(candidate_xml)},
        "candidate_generated_bi4": {"path": str(candidate_bi4), "sha256": source["bi4_sha256"], "symlink_target": str(source["bi4"])},
        "candidate_motion": {"path": str(candidate_motion), "sha256": source["motion_sha256"], "symlink_target": str(source["motion"])},
        "domain_control": {
            "changed_path": "parameters/simulationdomain/posmin/@x",
            "source_bounds": source["domain_values"],
            "candidate_bounds": candidate_values,
            "source_x_low_m": source["original_x_low"],
            "candidate_x_low_m": X_LOW_EXTENSION_M,
            "margin_m": round(X_LOW_EXTENSION_M - source["original_x_low"], 12),
            "other_faces_unchanged": True,
        },
        "invariants": {
            "dp_m": source["source_dp"],
            "initial_bi4_reused_without_rescale": True,
            "motion_reused_without_change": True,
            "physical_geometry_or_wetted_wall_changed": False,
            "boundary_treatment_changed": False,
            "cfl_or_solver_parameter_changed": False,
            "gencase_rerun": False,
            "solver_started": False,
        },
        "interpretation": {
            "hypothesis": "the original x-low numerical domain could censor the three native position exclusions near x=-1.40 m",
            "paired_readout": "compare exact native Idp survival, first-gap times, RunPARTs motive totals, Run.out MapRealPos and calibrated observers",
            "physical_fate": "UNKNOWN until an executed paired result; extension sensitivity is numerical evidence only",
            "dynamical_impact": "UNKNOWN",
            "qualification": "none",
        },
    }
    manifest_path = output_dir / "prepared.json"
    atomic_json(manifest_path, manifest)
    return {"status": manifest["status"], "prepared": str(output_dir),
            "manifest": str(manifest_path), "candidate_xml_sha256": manifest["candidate_generated_xml"]["sha256"]}


def make_request(*, prepared_dir: Path, solver_receipt_path: Path, output: Path,
                 solver: Path = SOLVER_DEFAULT,
                 dispatch_v4: Path = DISPATCH_V4_DEFAULT,
                 strict_v4: Path = STRICT_V4_DEFAULT,
                 runtime_v4: Path = RUNTIME_V4_DEFAULT,
                 worktree_root: Path = PRIMARY_WORKTREE) -> dict[str, Any]:
    prepared_dir = require_dir(prepared_dir, "prepared domain-extension directory")
    manifest_path, manifest = read_json(prepared_dir / "prepared.json", "domain-extension preparation manifest")
    if manifest.get("status") != "PREPARED_LAUNCH_DISABLED":
        raise PreparationError("domain-extension preparation is not launch-disabled")
    solver_receipt_path, source_receipt = read_json(solver_receipt_path, "original solver receipt")
    source = _source_paths(solver_receipt_path, source_receipt)
    solver = require_file(solver, "official DualSPHysics solver")
    dispatch_v4 = require_file(dispatch_v4, "Stage2 v4 dispatch")
    strict_v4 = require_file(strict_v4, "Stage2 strict v4 dispatch")
    runtime_v4 = require_file(runtime_v4, "Stage2 v4 runtime")
    candidate_xml = require_file_preserve_symlink(
        prepared_dir / "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V1.xml", "candidate XML"
    )
    candidate_bi4 = require_file_preserve_symlink(
        prepared_dir / "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V1.bi4", "candidate BI4"
    )
    candidate_motion = require_file_preserve_symlink(
        prepared_dir / source["motion"].name, "candidate motion"
    )
    worktree_root = Path(worktree_root).resolve()
    inputs = [SCRIPT, dispatch_v4, strict_v4, runtime_v4, solver, manifest_path,
              candidate_xml, candidate_bi4, candidate_motion, solver_receipt_path,
              source["prefix"], source["bi4"], source["motion"], source["gencase_receipt"]]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        # Preserve candidate symlink paths in the request; regular source and
        # runtime inputs use canonical absolute paths for stable guard binding.
        if path in (candidate_bi4, candidate_motion):
            path = Path(os.path.abspath(os.fspath(path)))
        else:
            path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)

    known_digests = {
        str(candidate_bi4): source["bi4_sha256"],
        str(source["bi4"]): source["bi4_sha256"],
        str(candidate_motion): source["motion_sha256"],
        str(source["motion"]): source["motion_sha256"],
    }
    input_digests: dict[str, str] = {}
    for path in unique:
        key = str(path)
        input_digests[key] = known_digests[key] if key in known_digests else sha256(path)
    source_request = source_receipt.get("request", {})
    command = [str(solver.resolve()), str(candidate_xml.with_suffix("")),
               "{attempt_root}/solver_output", "-tmax:4", "-tout:0.01"]
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f2-s1-original-dp010-domain-xlow-extended-v1",
        "kind": "qualification",
        "cpu_task_kind": "solver",
        "cpu_threads": int(source_request.get("cpu_threads", 2)),
        "omp_threads": int(source_request.get("omp_threads", source_request.get("cpu_threads", 2))),
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": int(source_request.get("estimated_storage_bytes", 8 * 2**30)),
        "command": command,
        "cwd": str(worktree_root),
        "worktree_root": str(worktree_root),
        "input_files": [str(path) for path in unique],
        "input_sha256": input_digests,
        "source_solver_receipt": str(solver_receipt_path),
        "source_solver_receipt_sha256": sha256(solver_receipt_path),
        "source_original_generated_xml": str(source["prefix"]),
        "source_original_generated_xml_sha256": sha256(source["prefix"]),
        "source_original_generated_bi4": str(source["bi4"]),
        "source_original_generated_bi4_sha256": source["bi4_sha256"],
        "source_original_motion": str(source["motion"]),
        "source_original_motion_sha256": source["motion_sha256"],
        "source_gencase_receipt": str(source["gencase_receipt"]),
        "source_gencase_receipt_sha256": sha256(source["gencase_receipt"]),
        "domain_control": manifest["domain_control"],
        "control_closure": {
            "fixed_dp_m": 0.01,
            "fixed_cfl": 0.2,
            "fixed_initial_bi4": True,
            "particle_mass_rescale": False,
            "motion_file_sha256": source["motion_sha256"],
            "solver_flags_equal_source": ["-tmax:4", "-tout:0.01"],
            "only_changed_input": "simulationdomain posmin.x",
        },
        "observer_plan": {
            "status": "PROPOSAL_ONLY_AFTER_PRIMARY_SOLVER_RECEIPT",
            "calibrated_native": {
                "tool": "official PartVTKOut",
                "argv_template": [
                    "PartVTKOut_linux64", "-dirdata", "{attempt_root}/solver_output/data",
                    "-savecsv", "{observer_root}/PartOut.csv", "-saveresume", "{observer_root}/resume.csv",
                    "-createdirs:1", "-csvsep:1",
                ],
                "readouts": ["Idp", "PartOut/time from RunPARTs", "Motive", "position", "density", "Run.out MapRealPos"],
            },
            "physical_observers": ["fluid retained count/mass visibility", "first-gap time distribution", "same-source calibrated body/impact observers"],
            "h5_opened_by_preparation": False,
        },
        "input_policy": {
            "initial_bi4": "exact immutable source symlink; guard hashes target",
            "xml": "new candidate with one simulationdomain face changed",
            "no_gencase": True,
            "no_solver_launch_by_preparation": True,
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "primary_launch_owner": "root",
        "foreign_process_protection_required": True,
        "qualification_claim": "none; numerical-domain paired diagnostic proposal only",
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }
    output = Path(output).resolve()
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if old != request:
            raise PreparationError(f"refusing to overwrite existing request: {output}")
    else:
        atomic_json(output, request)
    return {"status": "prepared", "request": str(output), "request_sha256": sha256(output),
            "candidate_xml_sha256": manifest["candidate_generated_xml"]["sha256"],
            "domain_control": manifest["domain_control"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--solver-receipt", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    req = sub.add_parser("request")
    req.add_argument("--prepared-dir", type=Path, required=True)
    req.add_argument("--solver-receipt", type=Path, required=True)
    req.add_argument("--output", type=Path, required=True)
    for item in (prep, req):
        item.add_argument("--worktree-root", type=Path, default=PRIMARY_WORKTREE)
    req.add_argument("--solver", type=Path, default=SOLVER_DEFAULT)
    req.add_argument("--dispatch-v4", type=Path, default=DISPATCH_V4_DEFAULT)
    req.add_argument("--strict-v4", type=Path, default=STRICT_V4_DEFAULT)
    req.add_argument("--runtime-v4", type=Path, default=RUNTIME_V4_DEFAULT)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_candidate(solver_receipt_path=args.solver_receipt,
                                   output_dir=args.output_dir)
    else:
        result = make_request(prepared_dir=args.prepared_dir,
                              solver_receipt_path=args.solver_receipt,
                              output=args.output, solver=args.solver,
                              dispatch_v4=args.dispatch_v4, strict_v4=args.strict_v4,
                              runtime_v4=args.runtime_v4, worktree_root=args.worktree_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreparationError as exc:
        raise SystemExit(f"PreparationError: {exc}")
