#!/usr/bin/env python3
"""Prepare source-bound SaveDt overlays for the original CFL pair.

This forward-only preparation covers F2-S1 plus the twelve sentinels that do
not yet have the separate F4-S1 SaveDt pair.  Each mode gets a new XML prefix
and an immutable hardlink to the exact CURRENT native BI4.  The same-CFL
overlay adds only the official ``execution.special.savedt`` node; the
half-CFL overlay adds that node and changes the two generated XML CFL values
to half their CURRENT value.  Existing XML, BI4, motion assets, receipts,
solver outputs, and prior request files are never modified.

No solver is launched and no H5/native frame payload is read.  The old solver
receipt and its RunPARTs/Run.out are read only as exact text control/window
evidence.  Their saved cadence and absence of SaveDt do not grant per-step dt
or scientific qualification to either new request.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.savedt-cfl-pair-requests.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
GRAPH_PATH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
AUDIT_PATH = REFERENCE / "stage2_savedt_instrumentation_audit_v1.json"
INPUT_ROOT = REFERENCE / "stage2_savedt_cfl_pair_inputs_v1"
REQUEST_ROOT = STAGE2 / "requests/stage2-savedt-cfl-pairs-v1"
REPORT_PATH = REFERENCE / "stage2_savedt_cfl_pair_binding_v1.json"
EXISTING_F4_REPORT = REFERENCE / "stage2_f4_dp0_savedt_pair_binding_v1.json"
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}
ALL_SENTINELS = [
    "F1-S1", "F1-S2", "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S1",
    "F4-S2", "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2",
]
# F4-S1 was delivered separately in stage2_f4_dp0_savedt_pair_requests_v1.py.
TARGET_SENTINELS = [sid for sid in ALL_SENTINELS if sid != "F4-S1"]
SAVEDT_FIELDS = ("start", "finish", "interval", "fullinfo", "alldt")
STORAGE_MARGIN_BYTES = 256 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_HASH_CACHE: dict[str, str] = {}


def file_record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    key = str(path)
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = sha256_file(path)
    stat = path.stat()
    return {"path": key, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": _HASH_CACHE[key]}


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(f"refuse to overwrite differing file: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")


def dp_token(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", "p")


def float_text(value: float) -> str:
    """Shortest round-trip spelling of the graph's exact float value."""
    return repr(float(value))


def graph_row(graph: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    rows = [row for row in graph["sentinels"] if row.get("sentinel_id") == sentinel_id]
    if len(rows) != 1:
        raise ValueError(f"expected one graph row for {sentinel_id}: {len(rows)}")
    return rows[0]


def cost_row(graph: dict[str, Any], sentinel_id: str, mode: str) -> dict[str, Any]:
    rows = [
        row for row in graph["cost_rows"]
        if row.get("sentinel_id") == sentinel_id
        and row.get("grid") == "original"
        and row.get("cfl_mode") == mode
        and row.get("cadence_kind") == "dense"
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one original dense {mode} row for {sentinel_id}: {len(rows)}")
    return rows[0]


def source_cfl_values(text: str) -> list[str]:
    return re.findall(r"<cflnumber\b[^>]*?\bvalue=\"([^\"]+)\"", text)


def relative_input_names(xml_path: Path, root: ET.Element) -> list[str]:
    """Find input files whose relative path must survive moving the XML.

    Generated VTK/shape names are deliberately excluded.  In addition to
    normal ``<file name=...>`` motion entries, F3's acceleration configuration
    uses ``<acctimesfile value=...>`` and therefore needs explicit handling.
    """
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name or name in {"NONE", "none"} or "[CaseName]" in name:
            return
        if name not in seen:
            seen.add(name)
            names.append(name)

    for node in root.iter():
        if node.tag == "file":
            add(node.get("name"))
        if node.tag == "acctimesfile":
            add(node.get("value"))
    return names


def link_input(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"overlay dependency missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != sha256_file(source):
            raise FileExistsError(f"existing overlay dependency differs: {destination}")
    else:
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    src_stat = source.stat()
    dst_stat = destination.stat()
    return {
        "source": file_record(source),
        "destination": file_record(destination),
        "materialization": (
            "hardlink_same_inode" if src_stat.st_dev == dst_stat.st_dev and src_stat.st_ino == dst_stat.st_ino
            else "byte_identical_copy"
        ),
    }


def savedt_fragment(interval: str, indent: str) -> str:
    child = indent + "    "
    return (
        f'{child}<savedt active="true">\n'
        f'{child}    <start value="0" comment="per-step dt starts at initial time" />\n'
        f'{child}    <finish value="0" comment="official v5.4 zero means no finish limit" />\n'
        f'{child}    <interval value="{interval}" comment="explicit positive interval" />\n'
        f'{child}    <fullinfo value="0" comment="compact statistics" />\n'
        f'{child}    <alldt value="1" comment="all final-step dt rows" />\n'
        f'{child}</savedt>\n'
    )


def add_savedt_text(source_text: str, interval: str) -> str:
    if re.search(r"<savedt\b", source_text):
        raise ValueError("CURRENT XML unexpectedly already contains savedt")
    exec_match = re.search(r"<execution(?:\s[^>]*)?>", source_text)
    if exec_match is None:
        raise ValueError("CURRENT XML lacks execution node")
    exec_end = source_text.find("</execution>", exec_match.end())
    if exec_end < 0:
        raise ValueError("CURRENT XML lacks execution close")
    special_match = re.search(r"<special(?:\s[^>]*)?>", source_text[exec_match.end():exec_end])
    if special_match is not None:
        special_start = exec_match.end() + special_match.start()
        special_close = source_text.find("</special>", special_start, exec_end)
        if special_close < 0:
            raise ValueError("special node lacks close")
        line_start = source_text.rfind("\n", 0, special_close) + 1
        indent = source_text[line_start:special_close]
        return source_text[:line_start] + savedt_fragment(interval, indent) + source_text[line_start:]
    line_start = source_text.rfind("\n", 0, exec_end) + 1
    indent = source_text[line_start:exec_end]
    special = (
        f"{indent}<special>\n"
        f"{savedt_fragment(interval, indent)}"
        f"{indent}</special>\n"
    )
    return source_text[:line_start] + special + source_text[line_start:]


def half_cfl_text(source_text: str, source_values: list[str]) -> tuple[str, list[dict[str, str]]]:
    parsed = [float(value) for value in source_values]
    if len(parsed) != 2 or abs(parsed[0] - parsed[1]) > 1e-12:
        raise ValueError(f"CURRENT CFL entries disagree: {source_values}")
    half = format(parsed[0] / 2.0, ".17g")
    pattern = re.compile(r'(<cflnumber\b[^>]*?\bvalue=")([^"]+)(")')
    changes: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        changes.append({"old": match.group(2), "new": half})
        return match.group(1) + half + match.group(3)

    result, count = pattern.subn(replace, source_text)
    if count != 2 or len(changes) != 2:
        raise ValueError(f"expected exactly two CFL replacements, got {count}")
    return result, changes


def parsed_without_savedt(text: str, *, restore_cfl: list[str] | None = None) -> bytes:
    root = ET.fromstring(text)
    execution = root.find("execution")
    if execution is None:
        raise ValueError("parsed XML lacks execution")
    special = execution.find("special")
    if special is not None:
        for node in list(special):
            if node.tag == "savedt":
                special.remove(node)
        if len(special) == 0 and not (special.text or "").strip():
            execution.remove(special)
    if restore_cfl is not None:
        nodes = root.findall(".//cflnumber")
        if len(nodes) != len(restore_cfl):
            raise ValueError("CFL count changed while proving overlay")
        for node, value in zip(nodes, restore_cfl):
            node.set("value", value)
    # Inserting a child necessarily changes indentation whitespace tails of
    # neighboring elements.  Remove whitespace-only text/tails before the
    # semantic comparison so the proof covers element/attribute meaning while
    # the separate text-edit list records the actual insertion/replacements.
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(root, encoding="utf-8")


def overlay_xml(source_xml: Path, mode: str, cadence: float, directory: Path) -> tuple[Path, Path, dict[str, Any], list[dict[str, Any]]]:
    source_text = source_xml.read_text(encoding="utf-8")
    source_values = source_cfl_values(source_text)
    if len(source_values) != 2:
        raise ValueError(f"expected two source CFL values: {source_xml}: {source_values}")
    source_root = ET.fromstring(source_text)
    interval = float_text(cadence)
    changes: list[dict[str, str]] = []
    transformed = source_text
    if mode == "half_cfl":
        transformed, changes = half_cfl_text(transformed, source_values)
    elif mode != "same_cfl":
        raise ValueError(mode)
    transformed = add_savedt_text(transformed, interval)
    overlay_root = ET.fromstring(transformed)
    savedt_nodes = overlay_root.findall("execution/special/savedt")
    if len(savedt_nodes) != 1:
        raise ValueError(f"expected one savedt node for {source_xml}: {len(savedt_nodes)}")
    savedt = savedt_nodes[0]
    savedt_values = {node.tag: node.get("value") for node in savedt}
    expected = {"start": "0", "finish": "0", "interval": interval, "fullinfo": "0", "alldt": "1"}
    if savedt.get("active") != "true" or savedt_values != expected:
        raise ValueError(f"unexpected SaveDt values: {savedt_values}")
    source_canonical = parsed_without_savedt(source_text)
    if mode == "same_cfl":
        restored_canonical = parsed_without_savedt(transformed)
    else:
        restored_canonical = parsed_without_savedt(transformed, restore_cfl=source_values)
    if source_canonical != restored_canonical:
        raise ValueError(f"non-CFL/non-SaveDt XML semantics changed for {source_xml}")
    overlay = directory / f"{safe_token(source_xml.stem)}_{mode}_savedt.xml"
    atomic_bytes(overlay, transformed.encode("utf-8"))
    bi4 = directory / overlay.with_suffix(".bi4").name
    link_info = link_input(source_xml.with_suffix(".bi4"), bi4)
    dependency_records: list[dict[str, Any]] = []
    for name in relative_input_names(source_xml, source_root):
        source_dep = (source_xml.parent / name).resolve()
        destination = (directory / name).resolve()
        try:
            destination.relative_to(directory.resolve())
        except ValueError as exc:
            raise ValueError(f"dependency escapes overlay directory: {name}") from exc
        dependency_records.append(link_input(source_dep, destination))
    proof = {
        "mode": mode,
        "source_cfl_values": source_values,
        "overlay_cfl_values": source_cfl_values(transformed),
        "cfl_replacements": changes,
        "parsed_non_savedt_tree_equivalent": True,
        "savedt_values": savedt_values,
        "source_xml_comments_and_bytes_preserved_outside_declared_edits": True,
        "declared_text_edits": ["savedt_node_insertion"] + (["two_cfl_value_replacements"] if changes else []),
    }
    manifest = {
        "schema": "ds02.stage2.savedt-cfl-overlay.v1",
        "mode": mode,
        "source_xml": file_record(source_xml),
        "source_bi4": file_record(source_xml.with_suffix(".bi4")),
        "overlay_xml": file_record(overlay),
        "overlay_bi4": link_info,
        "motion_or_auxiliary_dependencies": dependency_records,
        "xml_diff_proof": proof,
        "solver_started": False,
        "hdf5_read": False,
    }
    manifest_path = directory / "overlay-manifest.json"
    atomic_json(manifest_path, manifest)
    return overlay, bi4, proof, dependency_records


def source_run_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    output_root = receipt.get("output_root")
    if not output_root:
        return {"status": "UNKNOWN", "reason": "source receipt lacks output_root"}
    root = Path(output_root) / "solver_output"
    runparts = root / "RunPARTs.csv"
    runout = root / "Run.out"
    summary: dict[str, Any] = {
        "runparts": file_record(runparts) if runparts.is_file() else "UNKNOWN",
        "runout": file_record(runout) if runout.is_file() else "UNKNOWN",
        "numeric_rows": "UNKNOWN",
        "first_part": "UNKNOWN",
        "last_part": "UNKNOWN",
        "first_time_s": "UNKNOWN",
        "last_time_s": "UNKNOWN",
        "sum_saved_window_steps": "UNKNOWN",
        "dtallinfo_present": False,
    }
    if not runparts.is_file():
        return summary
    rows: list[list[str]] = []
    for line in runparts.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and line[0].isdigit():
            rows.append(line.split(";"))
    if rows:
        summary.update({
            "numeric_rows": len(rows),
            "first_part": int(rows[0][0]),
            "last_part": int(rows[-1][0]),
            "first_time_s": float(rows[0][1]),
            "last_time_s": float(rows[-1][1]),
            "sum_saved_window_steps": sum(int(row[2]) for row in rows),
        })
    summary["dtallinfo_present"] = (root / "DtAllInfo.csv").is_file()
    return summary


def source_command(receipt: dict[str, Any]) -> dict[str, Any]:
    command = receipt.get("command")
    if not isinstance(command, list) or len(command) < 3:
        raise ValueError("source solver receipt command is missing")
    tmax = next((float(item.split(":", 1)[1]) for item in command if str(item).startswith("-tmax:")), None)
    tout = next((float(item.split(":", 1)[1]) for item in command if str(item).startswith("-tout:")), None)
    source_prefix_index = next((i for i, item in enumerate(command) if str(item).endswith(".xml") or Path(str(item) + ".xml").is_file()), None)
    # Official receipts use [solver, flags..., input-prefix, output-root, ...].
    # Preserve all flags other than GPU selection and path/time/output values.
    flags: list[str] = []
    for item in command[1:]:
        item = str(item)
        if item.startswith("-gpu:") or item.startswith("-tmax:") or item.startswith("-tout:"):
            continue
        if source_prefix_index is not None and item == str(command[source_prefix_index]):
            continue
        if source_prefix_index is not None and item == str(command[source_prefix_index + 1]):
            continue
        # Defensive path test for receipts whose input prefix is not a local
        # XML sibling at parse time.
        if item.startswith("/") and (Path(item).is_dir() or Path(item + ".xml").is_file()):
            continue
        flags.append(item)
    return {
        "command": command,
        "source_tmax_s": tmax,
        "source_tout_s": tout,
        "preserved_non_gpu_flags": flags,
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "gpu_seconds": receipt.get("gpu_seconds"),
        "bytes": receipt.get("bytes"),
        "output_root": receipt.get("output_root"),
    }


def rounded_storage(raw_reserved: int) -> int:
    return int(raw_reserved) + STORAGE_MARGIN_BYTES


def planned_frames(end_s: float, cadence: float) -> int:
    return max(1, math.ceil(end_s / cadence - 1e-12) + 1)


def proxy_wall_seconds(source: dict[str, Any], mode: str) -> tuple[int, float]:
    gpu_seconds = float(source.get("gpu_seconds") or source.get("elapsed_seconds") or 0.0)
    # Dense output and SaveDt add I/O; half CFL is a distinct numerical recipe.
    factor = 3.0 if mode == "same_cfl" else 4.0
    proxy = gpu_seconds * factor
    return int(min(7200, max(900, math.ceil(proxy * 4.0)))), proxy


def request_inputs(row: dict[str, Any], overlay: Path, overlay_bi4: Path,
                   manifest: Path, dependency_records: list[dict[str, Any]]) -> list[Path]:
    source_xml = Path(row["source_xml"]["path"]).resolve()
    source_bi4 = source_xml.with_suffix(".bi4")
    gencase_receipt = Path(row["current_binding"]["gencase_receipt"]["path"]).resolve()
    solver_receipt = Path(row["source_solver_controls"]["receipt_runtime"]["path"]).resolve()
    source_output = json.loads(solver_receipt.read_text(encoding="utf-8")).get("output_root")
    paths = [DISPATCH, STRICT, RUNTIME, RUNTIME_V2, SOLVER, Path(__file__), GRAPH_PATH,
             AUDIT_PATH, source_xml, source_bi4, gencase_receipt, solver_receipt,
             overlay, overlay_bi4, manifest]
    if source_output:
        for name in ("RunPARTs.csv", "Run.out"):
            candidate = Path(source_output) / "solver_output" / name
            if candidate.is_file():
                paths.append(candidate)
    paths.extend(Path(item["destination"]["path"]) for item in dependency_records)
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def build_pair(row: dict[str, Any], graph: dict[str, Any], mode: str, commit: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = row["sentinel_id"]
    source_xml = Path(row["source_xml"]["path"]).resolve()
    source_bi4 = source_xml.with_suffix(".bi4")
    gencase_receipt_path = Path(row["current_binding"]["gencase_receipt"]["path"]).resolve()
    solver_receipt_path = Path(row["source_solver_controls"]["receipt_runtime"]["path"]).resolve()
    gencase = load_json(gencase_receipt_path)
    receipt = load_json(solver_receipt_path)
    if gencase.get("status") != "completed" or gencase.get("returncode") != 0:
        raise ValueError(f"CURRENT GenCase receipt is not successful: {sid}")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"CURRENT solver receipt is not successful: {sid}")
    source_text = source_xml.read_text(encoding="utf-8")
    source_values = source_cfl_values(source_text)
    if len(source_values) != 2:
        raise ValueError(f"expected two source CFL values: {sid}")
    source_cfl = float(source_values[0])
    if abs(source_cfl - float(source_values[1])) > 1e-12:
        raise ValueError(f"source CFL entries disagree: {sid}: {source_values}")
    end_s = float(row["effective_time_window_s"][1])
    cadence = float(row["dense_output_cadence_s"])
    source_control = source_command(receipt)
    old_window = source_run_summary(receipt)
    mode_dir = INPUT_ROOT / safe_token(sid) / mode
    overlay, overlay_bi4, proof, dependencies = overlay_xml(source_xml, mode, cadence, mode_dir)
    manifest_path = mode_dir / "overlay-manifest.json"
    cost = cost_row(graph, sid, mode)
    request_path = REQUEST_ROOT / f"{safe_token(sid).lower()}_original_savedt_{mode}.json"
    case_id = f"{safe_token(sid)}_ORIGINAL_DP{dp_token(float(row['source_dp_m']))}_SAVEDT_{mode.upper()}_DENSE"
    attempt_id = f"{safe_token(sid).lower()}-original-savedt-{mode}-dense-root-001"
    input_paths = request_inputs(row, overlay, overlay_bi4, manifest_path, dependencies)
    input_files = [str(path) for path in input_paths]
    input_hashes = {str(path): sha256_file(path) for path in input_paths}
    source_prefix = source_control["command"]
    # Preserve source runtime flags such as -mdbc_noslip and -ompthreads, but
    # leave GPU selection to the parent UUID/lease guard.
    flags = source_control["preserved_non_gpu_flags"]
    prefix = overlay.with_suffix("")
    max_wall, proxy_gpu = proxy_wall_seconds(source_control, mode)
    requested_tmax = float_text(end_s)
    requested_tout = float_text(cadence)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "family_id": row["family_id"],
        "case_id": case_id,
        "physical_case_id": row["physical_case_id"],
        "attempt_id": attempt_id,
        "kind": "qualification",
        "qualification_stage": "stage2_original_savedt_cfl_pair_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": max_wall,
        "estimated_storage_bytes": rounded_storage(int(cost["raw_native_reserved_bytes"])),
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(overlay.parent),
        "command": [str(SOLVER), *flags, str(prefix), "{attempt_root}/solver_output",
                     f"-tmax:{requested_tmax}", f"-tout:{requested_tout}"],
        "gencase_receipt": str(gencase_receipt_path),
        "gencase_receipt_sha256": sha256_file(gencase_receipt_path),
        "expected_particles": int(row["source_particles"]),
        "expected_fluid_particles": int(row["source_fluid_particles"]),
        "expected_native_frames": planned_frames(end_s, cadence),
        "expected_dimension": 3,
        "physical_window_s": [0.0, end_s],
        "save_interval_s": cadence,
        "source_binding": {
            "schema": "ds02.stage2.savedt-cfl-pair-binding.v1",
            "sentinel_id": sid,
            "family_id": row["family_id"],
            "physical_case_id": row["physical_case_id"],
            "source": {
                "current_xml": file_record(source_xml),
                "current_bi4": file_record(source_bi4),
                "gencase_receipt": file_record(gencase_receipt_path),
                "solver_receipt": file_record(solver_receipt_path),
                "solver_control": source_control,
                "old_preflight_window": old_window,
                "graph_window_s": [0.0, end_s],
                "graph_dense_cadence_s": cadence,
            },
            "overlay": {
                "xml": file_record(overlay),
                "bi4": file_record(overlay_bi4),
                "manifest": file_record(manifest_path),
                "motion_or_auxiliary_dependencies": dependencies,
                "xml_diff_proof": proof,
            },
            "effective_conditions": {
                "source_cfl": source_cfl,
                "effective_cfl": source_cfl if mode == "same_cfl" else source_cfl / 2.0,
                "mode": mode,
                "original_dp_m": float(row["source_dp_m"]),
                "particle_state_and_mass": "exact CURRENT BI4; no rescaling",
                "continuous_geometry_motion_control": "CURRENT XML and referenced files unchanged outside SaveDt/CFL declaration",
                "preserved_non_gpu_cli_flags": flags,
            },
            "savedt_contract": {
                "active": True,
                "start_s": 0.0,
                "finish_s": 0.0,
                "finish_semantics": "official v5.4 Config maps finish<=0 to DBL_MAX",
                "interval_s": cadence,
                "fullinfo": 0,
                "alldt": 1,
                "DtAllInfo": "one row per final simulation step: Time [s];Dtf [s]",
                "RunPARTs_DTsMin": "count of minimum-dt updates, not seconds and not a full-step trace",
            },
            "window_policy": {
                "requested_tmax_text": requested_tmax,
                "old_preflight_is_not_new_dense_pair": True,
                "full_graph_window_retained": True,
                "no_short_window_credit": True,
            },
        },
        "output_plan": {
            "native_output": "retain every Part_*.bi4 over complete graph window",
            "planned_frames": planned_frames(end_s, cadence),
            "dt_files": {
                "DtAllInfo.csv": "exact per-final-step trace; row count and final time pending actual receipt",
                "DtInfo.csv": "official grouped summary at explicit positive interval",
            },
            "postrun_crosscheck": [
                "count DtAllInfo data rows",
                "compare last DtAllInfo Time [s] with RunPARTs final saved time and requested endpoint",
                "compare sum RunPARTs Steps with DtAllInfo rows under documented initialization/terminal convention",
                "join Run.out DtMin and aggregate DTs adjusted to DtMin",
            ],
            "clamp_semantics": "no per-row clamp flag; report aggregate Run.out count only",
            "field_observables": "UNKNOWN",
            "scientific_qualification": "UNKNOWN",
        },
        "cost": {
            "graph_row": cost,
            "raw_native_reserved_bytes": int(cost["raw_native_reserved_bytes"]),
            "request_storage_reservation_bytes": rounded_storage(int(cost["raw_native_reserved_bytes"])),
            "planned_frames": planned_frames(end_s, cadence),
            "source_scaled_gpu_seconds_proxy": proxy_gpu,
            "source_scaled_gpu_hours_proxy": proxy_gpu / 3600.0,
            "two_frame_ratio": cost.get("archive_ratio_measured_pair"),
            "two_frame_ratio_use": "diagnostic only; excluded from reservation and full-window claims",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "input_sha256": dict(input_hashes),
        "resource_guard": {
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "launch_commit": commit,
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_gpu": PROTECTED_GPU,
            "storage_policy": "raw full-window reservation plus 256MiB SaveDt/log margin; terminal v4 guard authoritative",
            "solver_started_by_preparation": False,
            "hdf5_read_by_preparation": False,
        },
        "scope": {
            "sentinel_id": sid,
            "physical_case_id": row["physical_case_id"],
            "grid": "CURRENT original dp0",
            "cfl_mode": mode,
            "same_geometry_and_particle_state": True,
            "full_time_window": True,
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": True,
        "do_not_execute_from_preparation_worktree": True,
    }
    report_row = {
        "sentinel_id": sid,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "mode": mode,
        "request_path": str(request_path.resolve()),
        "request": {"case_id": case_id, "attempt_id": attempt_id},
        "overlay_xml": file_record(overlay),
        "overlay_bi4": file_record(overlay_bi4),
        "overlay_manifest": file_record(manifest_path),
        "xml_diff_proof": proof,
        "old_preflight_window": old_window,
        "requested_window_s": [0.0, end_s],
        "requested_tout_s": cadence,
        "requested_tmax_text": requested_tmax,
        "planned_frames": planned_frames(end_s, cadence),
        "estimated_storage_bytes": rounded_storage(int(cost["raw_native_reserved_bytes"])),
        "launch_disabled": True,
        "solver_started": False,
        "hdf5_read": False,
    }
    return request, report_row


def prepare(graph: dict[str, Any]) -> dict[str, Any]:
    commit = git_head()
    requests: list[dict[str, Any]] = []
    output_paths: list[str] = []
    for sid in TARGET_SENTINELS:
        row = graph_row(graph, sid)
        for mode in ("same_cfl", "half_cfl"):
            request, report_row = build_pair(row, graph, mode, commit)
            path = REQUEST_ROOT / f"{safe_token(sid).lower()}_original_savedt_{mode}.json"
            atomic_json(path, request)
            report_row["request_file"] = file_record(path)
            report_row["input_hashes_count"] = len(request["input_hashes"])
            requests.append(report_row)
            output_paths.append(str(path.resolve()))
    existing_f4 = file_record(EXISTING_F4_REPORT) if EXISTING_F4_REPORT.is_file() else "UNKNOWN"
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED_26_SAVEDT_REQUESTS",
        "generated_at_commit": commit,
        "scope": {
            "target_sentinels": TARGET_SENTINELS,
            "target_count": len(TARGET_SENTINELS),
            "request_count": len(requests),
            "modes": ["same_cfl", "half_cfl"],
            "excluded_existing_pair": "F4-S1; delivered by stage2_f4_dp0_savedt_pair_requests_v1.py",
            "hdf5_read": False,
            "solver_started": False,
            "gpu_started": False,
        },
        "existing_f4_s1_pair_report": existing_f4,
        "official_savedt_audit": file_record(AUDIT_PATH),
        "source_policy": {
            "identity": "exact CURRENT graph row XML/BI4/GenCase receipt/completed solver receipt",
            "same_cfl": "new SaveDt XML overlay with CURRENT CFL values and original particle BI4",
            "half_cfl": "same overlay plus exactly two generated cflnumber value changes to half",
            "dependencies": "all relative motion/auxiliary input files materialized beside overlay; F3 acctimes CSV included",
            "old_preflight": "reported as source control/window evidence only; it does not grant SaveDt or dense-pair dt credit",
        },
        "cost_policy": {
            "native": "full graph window and every planned dense frame retained",
            "storage": "graph raw_native_reserved_bytes plus 256MiB SaveDt/log margin per request",
            "two_frame_ratio": "diagnostic only, never used as full-window upper bound",
            "actual_guard": "parent v4 UUID/lease/terminal storage guard remains authoritative",
        },
        "requests": requests,
        "unknowns": [
            "actual solver wall time and terminal bytes",
            "DtAllInfo row count/final time until a guarded run",
            "per-step clamp locations; Run.out provides aggregate only",
            "observer calibration and QI/QN/QE",
        ],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REPORT_PATH, report)
    return {"report": str(REPORT_PATH), "requests": output_paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("choose --prepare")
    result = prepare(load_json(GRAPH_PATH))
    print(json.dumps({"status": "PASS", "report": result["report"],
                      "request_count": len(result["requests"]),
                      "solver_started": False, "hdf5_read": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
