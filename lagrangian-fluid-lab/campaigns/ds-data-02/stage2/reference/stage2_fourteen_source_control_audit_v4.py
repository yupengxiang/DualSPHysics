#!/usr/bin/env python3
"""Extract exact motion/forcing/control dependencies for all 14 sources.

The previous preparation metadata could leave ``motion_and_auxiliary_source``
empty even when the source XML contains an ``mvrotfile/file`` reference.  This
forward audit reads the frozen quality manifest and the 14 small source XMLs;
it records control node values, exact file references, launch-time hash
candidates, and unresolved/ambiguous cases without globbing or touching BI4,
H5, or solver outputs.  It does not claim control equivalence across grids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.fourteen-source-control-audit.v4"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
CONTROL_TAGS = {
    "motion", "objreal", "begin", "mvrotfile", "mvhlin", "mvlin", "mvrun",
    "file", "axisp1", "axisp2", "acceleration", "gravity", "table", "forcing",
    "inout", "wave", "floating", "moving", "boundary", "kernel", "viscotreatment",
    "densitydt", "shifting", "rigidalgorithm", "parameters", "parameter",
}
MOTION_TAGS = {"motion", "objreal", "mvrotfile", "mvhlin", "mvlin", "mvrun"}
FILE_ATTRS = ("file", "name", "path", "table", "forcing")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def local_tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def node_path(root: ET.Element, target: ET.Element) -> str:
    path: list[str] = []
    found = False

    def visit(node: ET.Element, prefix: str) -> None:
        nonlocal found
        if found:
            return
        if node is target:
            path.append(prefix)
            found = True
            return
        children = list(node)
        for index, child in enumerate(children):
            visit(child, f"{prefix}/{local_tag(child)}[{index}]")

    visit(root, local_tag(root))
    return "/".join(path) if path else "UNKNOWN"


def ancestors(root: ET.Element, target: ET.Element) -> list[ET.Element]:
    result: list[ET.Element] = []

    def visit(node: ET.Element, stack: list[ET.Element]) -> bool:
        if node is target:
            result.extend(stack)
            return True
        return any(visit(child, stack + [node]) for child in node)

    visit(root, [])
    return result


def scalar(raw: str) -> Any:
    try:
        value = float(raw)
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    return raw


def canonical_controls(root: ET.Element) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    nodes: list[dict[str, Any]] = []
    motion_refs: list[str] = []
    auxiliary_refs: list[str] = []
    for node in root.iter():
        tag = local_tag(node)
        attrs = {key: scalar(value) for key, value in sorted(node.attrib.items())}
        parent_tags = {local_tag(item) for item in ancestors(root, node)}
        is_motion_context = bool(parent_tags & MOTION_TAGS) or tag in MOTION_TAGS
        refs = [str(node.attrib[key]) for key in FILE_ATTRS if key in node.attrib and node.attrib[key]]
        # The XML contains duplicated source/execution motion tables; retain
        # occurrences in the node list but deduplicate only the summary refs.
        if tag == "file" or is_motion_context and refs:
            for ref in refs:
                if ref not in motion_refs:
                    motion_refs.append(ref)
        elif refs:
            for ref in refs:
                if ref not in auxiliary_refs:
                    auxiliary_refs.append(ref)
        relevant = tag in CONTROL_TAGS or bool(refs) or any(
            key in node.attrib for key in ("mov", "start", "finish", "duration", "anglesunits", "x", "y", "z")
        )
        if relevant:
            nodes.append({
                "path": node_path(root, node),
                "tag": tag,
                "attributes": attrs,
                "text": (node.text or "").strip() or None,
                "motion_context": is_motion_context,
            })
    return nodes, sorted(set(motion_refs)), sorted(set(auxiliary_refs))


def resolve_refs(refs: list[str], xml_path: Path, launch_hashes: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for ref in refs:
        candidates: list[dict[str, Any]] = []
        local = (xml_path.parent / ref).resolve()
        if local.is_file() and not local.is_symlink():
            candidates.append({"path": str(local), "source": "xml_parent", **record(local)})
        for raw_path, declared_sha in launch_hashes.items():
            if Path(raw_path).name != Path(ref).name:
                continue
            item = {"path": str(Path(raw_path).resolve()), "source": "launch_input_hash", "declared_sha256": declared_sha}
            candidate_path = Path(raw_path)
            if candidate_path.is_file() and not candidate_path.is_symlink():
                item.update({"actual_sha256": sha256_file(candidate_path), "bytes": candidate_path.stat().st_size})
            candidates.append(item)
        unique: dict[str, dict[str, Any]] = {item["path"]: item for item in candidates}
        unique_sha = sorted({str(item.get("declared_sha256") or item.get("actual_sha256")) for item in unique.values()})
        status = "AVAILABLE" if unique else "UNKNOWN_NO_EXACT_PATH"
        if len(unique) > 1 and len(unique_sha) > 1:
            status = "UNKNOWN_MULTIPLE_EXACT_BASENAME_HASHES"
        results.append({"reference": ref, "status": status, "candidates": list(unique.values()), "unique_declared_or_actual_sha256": unique_sha})
        if status != "AVAILABLE":
            unresolved.append(ref)
    return {"references": results, "unresolved": unresolved}


def audit_source(row: dict[str, Any]) -> dict[str, Any]:
    xml_path = Path(row["source_xml"]["path"])
    root = ET.parse(xml_path).getroot()
    nodes, motion_refs, auxiliary_refs = canonical_controls(root)
    controls = row.get("source_solver_controls", {})
    launch_hashes = controls.get("input_hashes_at_launch", {})
    motion = resolve_refs(motion_refs, xml_path, launch_hashes)
    auxiliary = resolve_refs(auxiliary_refs, xml_path, launch_hashes)
    canonical_payload = json.dumps({"nodes": nodes, "motion_refs": motion_refs, "auxiliary_refs": auxiliary_refs}, sort_keys=True, separators=(",", ":"))
    return {
        "sentinel_id": row["sentinel_id"],
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "source_xml": record(xml_path),
        "source_solver_control": {
            "status": controls.get("status"),
            "returncode": controls.get("returncode"),
            "command": controls.get("command"),
            "tmax_s": controls.get("tmax_s"),
            "tout_s": controls.get("tout_s"),
            "receipt": record(Path(controls["receipt"]["path"])) if controls.get("receipt", {}).get("path") else "UNKNOWN",
        },
        "control_nodes": nodes,
        "control_node_count": len(nodes),
        "motion_file_refs": motion_refs,
        "motion_file_resolution": motion,
        "auxiliary_file_refs": auxiliary_refs,
        "auxiliary_file_resolution": auxiliary,
        "canonical_control_payload_sha256": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        "quality_manifest_motion_refs": row.get("source_xml", {}).get("motion_refs", "UNKNOWN"),
        "motion_metadata_status": "PASS_EXACT_XML_FILE_REFS_EXTRACTED" if motion_refs else "UNKNOWN_NO_MOTION_FILE_REFERENCE_IN_XML",
        "control_equivalence": "UNKNOWN; extracted source dependencies do not prove cross-grid equivalence",
    }


def run() -> dict[str, Any]:
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    rows = quality.get("sources")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("quality manifest must contain exactly 14 source rows")
    audits = [audit_source(row) for row in rows]
    return {
        "schema": SCHEMA,
        "status": "ACTUAL_14_SOURCE_CONTROL_DEPENDENCY_AUDIT",
        "preparation_source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "scope": {
            "source_manifest": record(QUALITY),
            "source_xml_count": len(audits),
            "native_or_h5_read_by_this_worker": False,
            "solver_started": False,
            "latest_glob_or_family_fallback": False,
            "control_equivalence_claim": "NONE",
        },
        "sources": audits,
        "summary": {
            "sources_with_motion_refs": sum(bool(item["motion_file_refs"]) for item in audits),
            "sources_with_unresolved_motion_refs": sum(bool(item["motion_file_resolution"]["unresolved"]) for item in audits),
            "sources_with_auxiliary_refs": sum(bool(item["auxiliary_file_refs"]) for item in audits),
            "f7_s2_expected_motion_ref": next(item for item in audits if item["sentinel_id"] == "F7-S2")["motion_file_refs"],
            "interpretation": "file references and control values are source-bound inputs; solver effective semantics and scientific qualification remain UNKNOWN",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = run()
    atomic_json(args.output.resolve(), value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve()), "sources": len(value["sources"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
