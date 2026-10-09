#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build source-bound ROOT173/ROOT174 one-variable solver requests (v6).

This is a forward builder for the consumed ROOT162 middle recipe.  It writes
new XML overlays from the small ROOT086 generated XML and emits the strict
``ds02.stage2.external-solver-request.v5`` request consumed by the existing
external-v5 materializer.  ROOT173 changes only the two actual CFL constants
from 0.05 to 0.025.  ROOT174 changes only the execution ``TimeOut`` from
0.01 s to 0.005 s.  The source XML, BI4 bytes, forcing table, geometry,
motion, owner recipe, and all other execution parameters remain bound to the
ROOT161/ROOT162 source.

The builder reads only small XML/JSON/code metadata.  It stats but does not
open or hash the BI4 or forcing payload; their SHA values are supplied by the
ROOT161 snapshot and ROOT086 receipt/control binding.  It never launches a
solver.  The parent guard owns reservation, fresh UUID selection, payload
pre/post hashing, launch, terminal accounting, and scientific qualification.
    """

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
LOCAL_REPO = Path(__file__).resolve().parents[5]
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

REFERENCE_DIR = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DELEGATE = REFERENCE_DIR / "stage2_f3_s2_middle_external_solver_v5_request_v1.py"
MATERIALIZER = REFERENCE_DIR / "stage2_f3_s2_external_solver_v5_materialize.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")

MIDDLE_ROOT = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001"
BASE_XML = MIDDLE_ROOT / "generated/F3_S2_P1200_AY0750_MATCHED.xml"
MIDDLE_BI4 = MIDDLE_ROOT / "generated/F3_S2_P1200_AY0750_MATCHED.bi4"
MIDDLE_FORCING = MIDDLE_ROOT / "generated/CaseSloshingAccData.csv"
MIDDLE_RECEIPT = MIDDLE_ROOT / "execution-receipt.json"
GENCASE_REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-source-clone-gencase-v1-root-forward-082-001/f3-s2-source-clone-gencase-v1-request.json"
SUPPORT_REPORT = DATA_ROOT / "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/f3-s2-root086-vtk-support-qa-v2.json"
SOURCE_XML = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
ROOT161_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_MIDDLE_BI4_SINGLE_STREAM_ACTUAL_SOURCE_SNAPSHOT_ROOT_VERIFICATION_161.json"
ROOT153_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_MIDDLE_STAGING_ACTUAL_METADATA_ROOT_VERIFICATION_153.json"
ROOT153_REPORT = DATA_ROOT / "families/F3/F3_S2_MATCHED_MIDDLE_CONTROL_COST_QA_V1_ROOT_153/f3-s2-matched-middle-control-cost-qa-v1-root-153-001-root-forward-030-001/report/f3_s2_matched_middle_control_cost_qa_v1.json"
ROOT162_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP006_MIDDLE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_162.json"
ROOT162_RECEIPT = DATA_ROOT / "families/F3/F3_S2_MATCHED_MIDDLE_SAME_CFL_ROOT_162/f3-s2-matched-middle-same-cfl-v5-root-162-001/execution-receipt.json"
SOURCE_CARD = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-external-v5-source-card-v1.json"
CALIBRATION_CONTRACT = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"

ROOT161_BI4_SHA = "3bd6d0a5e70dca477aad347b54057c2169de4fab8ca41cd5ac1af59e5142459a"
ROOT161_BI4_BYTES = 9_227_118
ROOT086_XML_SHA = "3ae2aae572b0fc8cb0687e0590b0fb1762af61212d037da603d4bc8326a8ae9d"
ROOT086_RECEIPT_SHA = "68ce1e593c568941af8ffadcf37949a1a53714f2e9b99f203b715ed47931e14f"
FORCING_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
ROOT153_PROOF_SHA = "e94f6f93f6864740a79328a2786d86cebbbbd2c69b730432bcea8a598e0fa574"
ROOT153_REPORT_SHA = "2569c320a72c43081fb95c6881e53106077395448c0793d1255e9e4e775eecca"
ROOT162_PROOF_SHA = "4a4cb60050b65256d60162118db25aeb8bf83e9ac8203235d29d01254f3114a1"
ROOT162_RECEIPT_SHA = "1ce719cc8e18df0039196f064a92566cf641486094a5f558e0579142db9364a0"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
TMAX_S = 8.350016881886734
BASE_CFL = 0.05
HALF_CFL = 0.025
BASE_TOUT_S = 0.01
HALF_TOUT_S = 0.005
COEF_DT_MIN = 0.005
ROOT162_EXTERNAL_BYTES = 6_627_692_045
ROOT162_PART_BYTES = 6_593_641_516
ROOT162_FRAMES = 836
SCHEMA = "ds02.stage2.f3-s2.middle-overlay-external-solver-request.v6"
STRICT_SCHEMA = "ds02.stage2.external-solver-request.v5"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _regular(path: Path, label: str) -> Path:
    path = _resolve(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_record(path: Path, label: str, expected_sha: str | None = None, *, max_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    path = _regular(path, label)
    stat = path.stat()
    if int(stat.st_size) > max_bytes:
        raise ValueError(f"{label} exceeds small metadata limit: {stat.st_size}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha or _sha256(path),
        "content_scope": "small_metadata_hashed_by_builder_and_parent",
        "content_read_by_builder": True,
    }


def _payload_record(path: Path, label: str, expected_sha: str, expected_bytes: int) -> dict[str, Any]:
    """Bind a dynamic payload by known SHA/stat without opening it."""

    path = _regular(path, label)
    stat = path.stat()
    if int(stat.st_size) != expected_bytes:
        raise ValueError(f"{label} bytes {stat.st_size} != frozen {expected_bytes}")
    if not HEX64.fullmatch(expected_sha):
        raise ValueError(f"{label} expected SHA is not lowercase SHA-256")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha,
        "content_read_by_builder": False,
        "sha256_authority": "ROOT161_snapshot_or_parent_after_reservation_pre_post_hash",
        "content_scope": "parent_after_reservation_pre_post_hash",
    }


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _resolve(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _semantic_tree(root: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}

    def walk(element: ET.Element, path: str) -> None:
        for key, value in sorted(element.attrib.items()):
            if path == "case" and key in {"date", "app"}:
                continue
            values[f"{path}/@{key}"] = value
        counts: dict[str, int] = {}
        for child in list(element):
            index = counts.get(child.tag, 0)
            counts[child.tag] = index + 1
            walk(child, f"{path}/{child.tag}[{index}]")

    walk(root, root.tag)
    return values


def _find_one(root: ET.Element, predicate, description: str) -> ET.Element:
    matches = [element for element in root.iter() if predicate(element)]
    if len(matches) != 1:
        raise ValueError(f"expected one {description}, found {len(matches)}")
    return matches[0]


def _element_path(root: ET.Element, target: ET.Element) -> str:
    """Return the same indexed semantic path used by ``_semantic_tree``."""

    result: list[str] | None = None

    def walk(element: ET.Element, path: str) -> None:
        nonlocal result
        if element is target:
            result = [path]
            return
        counts: dict[str, int] = {}
        for child in list(element):
            index = counts.get(child.tag, 0)
            counts[child.tag] = index + 1
            walk(child, f"{path}/{child.tag}[{index}]")
            if result is not None:
                return

    walk(root, root.tag)
    if result is None:
        raise ValueError("target XML node is not in the parsed tree")
    return result[0]


def _parameter_snapshot(root: ET.Element) -> dict[str, str]:
    params = [element for element in root.iter() if element.tag == "parameter" and "key" in element.attrib]
    return {str(element.attrib["key"]): str(element.attrib.get("value", "")) for element in params}


def _critical_snapshot(root: ET.Element, *, enforce_root086_values: bool = True) -> dict[str, str]:
    params = _parameter_snapshot(root)
    expected = {
        "CoefDtMin": "0.005",
        "DtMin": "0",
        "DtFixed": "0",
        "TimeMax": "8.35",
        "StepAlgorithm": "2",
        "DensityDT": "3",
        "Kernel": "2",
        "ViscoTreatment": "1",
        "RigidAlgorithm": "1",
        "TimeOut": "0.01",
    }
    if enforce_root086_values:
        for key, value in expected.items():
            if params.get(key) != value:
                raise ValueError(f"ROOT086 base parameter {key}={params.get(key)!r}, expected {value!r}")
    return {key: params[key] for key in sorted(params)}


def _overlay_nodes(root: ET.Element) -> tuple[ET.Element, ET.Element, ET.Element]:
    cfl_casedef = _find_one(root, lambda e: e.tag == "cflnumber" and any(parent.tag == "constantsdef" for parent in root.iter() if e in list(parent)), "casedef cflnumber")
    # ElementTree has no parent pointer; use explicit ancestry for the second
    # cfl node and keep the predicates structural rather than index-based.
    cfl_nodes = [e for e in root.iter() if e.tag == "cflnumber"]
    if len(cfl_nodes) != 2:
        raise ValueError(f"expected two cflnumber nodes, found {len(cfl_nodes)}")
    casedef = _find_one(root, lambda e: e.tag == "casedef", "casedef")
    execution = _find_one(root, lambda e: e.tag == "execution", "execution")
    casedef_nodes = [e for e in casedef.iter() if e.tag == "cflnumber"]
    execution_nodes = [e for e in execution.iter() if e.tag == "cflnumber"]
    if len(casedef_nodes) != 1 or len(execution_nodes) != 1:
        raise ValueError("ROOT086 must have one casedef and one execution cflnumber")
    timeout_nodes = [e for e in execution.iter() if e.tag == "parameter" and e.attrib.get("key") == "TimeOut"]
    if len(timeout_nodes) != 1:
        raise ValueError(f"expected one execution TimeOut parameter, found {len(timeout_nodes)}")
    return casedef_nodes[0], execution_nodes[0], timeout_nodes[0]


def _assert_base(root: ET.Element) -> dict[str, Any]:
    casedef, execution, timeout = _overlay_nodes(root)
    for element, label in ((casedef, "casedef cflnumber"), (execution, "execution cflnumber")):
        if abs(float(element.attrib.get("value", "nan")) - BASE_CFL) > 1e-12:
            raise ValueError(f"{label} is not ROOT086 CFL 0.05: {element.attrib.get('value')!r}")
    if abs(float(timeout.attrib.get("value", "nan")) - BASE_TOUT_S) > 1e-12:
        raise ValueError(f"ROOT086 TimeOut is not 0.01: {timeout.attrib.get('value')!r}")
    return {
        "casedef_cfl_path": _element_path(root, casedef),
        "execution_cfl_path": _element_path(root, execution),
        "timeout_path": _element_path(root, timeout),
        "execution_parameters": _critical_snapshot(root),
    }


def _replace_registered_bytes(
    data: bytes,
    pattern: bytes,
    expected_old: list[bytes],
    replacements: list[bytes],
) -> bytes:
    """Apply only the registered value spans to an immutable XML byte string."""

    matches = list(re.finditer(pattern, data))
    actual_old = [match.group(2) for match in matches]
    if actual_old != expected_old or len(matches) != len(replacements):
        raise ValueError(f"registered byte targets changed: {actual_old!r}")
    pieces: list[bytes] = []
    cursor = 0
    for match, replacement in zip(matches, replacements):
        pieces.extend((data[cursor:match.start(2)], replacement))
        cursor = match.end(2)
    pieces.append(data[cursor:])
    return b"".join(pieces)


def _audit_overlay(study: str, overlay_path: Path) -> dict[str, Any]:
    base_path = _regular(BASE_XML, "ROOT086 base generated XML")
    overlay_path = _regular(overlay_path, "new overlay XML")
    base_tree = ET.parse(base_path)
    overlay_tree = ET.parse(overlay_path)
    base_root = base_tree.getroot()
    overlay_root = overlay_tree.getroot()
    base_nodes = _assert_base(base_root)
    overlay_nodes = _overlay_nodes(overlay_root)
    base_values = _semantic_tree(base_root)
    overlay_values = _semantic_tree(overlay_root)
    if set(base_values) != set(overlay_values):
        raise ValueError("overlay changed XML semantic key set")
    changed = {key: {"base": base_values[key], "overlay": overlay_values[key]} for key in base_values if base_values[key] != overlay_values[key]}
    expected_paths = {base_nodes["casedef_cfl_path"], base_nodes["execution_cfl_path"]} if study == "half_cfl" else {base_nodes["timeout_path"]}
    # The generated XML serializer retains the semantic structure.  Resolve
    # the overlay paths independently so a serializer cannot hide a reordering.
    overlay_expected_paths = {_element_path(overlay_root, overlay_nodes[0]), _element_path(overlay_root, overlay_nodes[1])} if study == "half_cfl" else {_element_path(overlay_root, overlay_nodes[2])}
    if expected_paths != overlay_expected_paths:
        raise ValueError("overlay changed the registered target XML path")
    if set(changed) != {f"{path}/@value" for path in expected_paths}:
        raise ValueError(f"overlay changed fields outside one registered variable: {sorted(changed)}")
    if study == "half_cfl":
        for element in overlay_nodes[:2]:
            if abs(float(element.attrib.get("value", "nan")) - HALF_CFL) > 1e-12:
                raise ValueError("half-CFL overlay does not set both cflnumber values to 0.025")
        if abs(float(overlay_nodes[2].attrib.get("value", "nan")) - BASE_TOUT_S) > 1e-12:
            raise ValueError("half-CFL overlay changed TimeOut")
    elif study == "half_output":
        if abs(float(overlay_nodes[2].attrib.get("value", "nan")) - HALF_TOUT_S) > 1e-12:
            raise ValueError("half-output overlay does not set TimeOut to 0.005")
        for element in overlay_nodes[:2]:
            if abs(float(element.attrib.get("value", "nan")) - BASE_CFL) > 1e-12:
                raise ValueError("half-output overlay changed CFL")
    else:
        raise ValueError(f"unknown study {study}")
    overlay_params = _critical_snapshot(overlay_root, enforce_root086_values=False)
    base_params = base_nodes["execution_parameters"]
    # The registered TimeOut is the one allowed execution-parameter change
    # for ROOT174; all other parameters, including CoefDtMin, stay byte-
    # semantic equal to the ROOT086 recipe.
    for key, value in base_params.items():
        if key == "TimeOut" and study == "half_output":
            continue
        if overlay_params.get(key) != value:
            raise ValueError(f"overlay changed fixed execution parameter {key}")
    if overlay_params.get("CoefDtMin") != "0.005":
        raise ValueError("overlay changed CoefDtMin")
    base_bytes = base_path.read_bytes()
    overlay_bytes = overlay_path.read_bytes()
    # SequenceMatcher may split a short decimal replacement into adjacent
    # insert/delete/insert opcodes (for example ``.05`` -> ``.025``).  The
    # authoritative byte check is therefore the exact bytewise clone built
    # from the registered attribute spans below, rather than a heuristic diff
    # opcode shape.
    if study == "half_cfl":
        expected_bytes = _replace_registered_bytes(
            base_bytes,
            rb'(<cflnumber\b[^>]*\bvalue=")([^\"]*)(")',
            [b".05", b"0.05"],
            [b".025", b".025"],
        )
        byte_opcodes = [
            {"tag": "replace", "base": ".05", "overlay": ".025"},
            {"tag": "replace", "base": "0.05", "overlay": ".025"},
        ]
    else:
        expected_bytes = _replace_registered_bytes(
            base_bytes,
            rb'(<parameter\b[^>]*\bkey="TimeOut"[^>]*\bvalue=")(0\.01)(")',
            [b"0.01"],
            [b"0.005"],
        )
        byte_opcodes = [{"tag": "replace", "base": "0.01", "overlay": "0.005"}]
    if overlay_bytes != expected_bytes:
        actual_opcodes = [
            {"tag": tag, "base": base_bytes[a:b].decode("utf-8"), "overlay": overlay_bytes[c:d].decode("utf-8")}
            for tag, a, b, c, d in difflib.SequenceMatcher(None, base_bytes, overlay_bytes, autojunk=False).get_opcodes()
            if tag != "equal"
        ]
        raise ValueError(f"overlay is not an exact bytewise registered clone: {actual_opcodes}")
    return {
        "study": study,
        "base_xml_path": str(base_path),
        "base_xml_sha256": _sha256(base_path),
        "overlay_xml_path": str(overlay_path),
        "overlay_xml_sha256": _sha256(overlay_path),
        "changed": changed,
        "allowed_target_paths": sorted(expected_paths),
        "fixed_execution_parameters": overlay_params,
        "byte_clone_target_only": True,
        "byte_replacements": byte_opcodes,
    }


def write_overlay(study: str, output: Path) -> dict[str, Any]:
    base_path = _regular(BASE_XML, "ROOT086 base generated XML")
    base_bytes = base_path.read_bytes()
    root = ET.fromstring(base_bytes)
    casedef, execution, timeout = _overlay_nodes(root)
    _assert_base(root)
    # The semantic parse above locates the registered nodes.  The output is
    # then made from the original bytes so whitespace, comments, text nodes,
    # attribute order, and XML declaration remain unchanged.
    if study == "half_cfl":
        pattern = re.compile(rb'(<cflnumber\b[^>]*\bvalue=")([^"]*)(")')
        matches = list(pattern.finditer(base_bytes))
        if len(matches) != 2 or [match.group(2) for match in matches] != [b".05", b"0.05"]:
            raise ValueError("ROOT086 cflnumber byte targets do not match the frozen source")
        pieces: list[bytes] = []
        cursor = 0
        for match in matches:
            pieces.extend((base_bytes[cursor:match.start(2)], b".025"))
            cursor = match.end(2)
        pieces.append(base_bytes[cursor:])
        overlay_bytes = b"".join(pieces)
    elif study == "half_output":
        pattern = re.compile(rb'(<parameter\b[^>]*\bkey="TimeOut"[^>]*\bvalue=")0\.01(")')
        matches = list(pattern.finditer(base_bytes))
        if len(matches) != 1:
            raise ValueError("ROOT086 TimeOut byte target is not unique")
        match = matches[0]
        overlay_bytes = base_bytes[:match.start() + len(match.group(1))] + b"0.005" + base_bytes[match.end(0) - 1:]
    else:
        raise ValueError(f"unknown study {study}")
    output = _resolve(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite overlay: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(overlay_bytes)
    audit = _audit_overlay(study, output)
    audit["status"] = "PASS_NEW_OVERLAY_ONE_VARIABLE"
    return audit


def _load_module(path: Path, name: str):
    path = _regular(path, f"module {name}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _study(study: str) -> dict[str, Any]:
    if study == "half_cfl":
        return {
            "study_id": "ROOT173",
            "case_id": "F3_S2_MATCHED_MIDDLE_HALF_CFL_ROOT173",
            "attempt_id": "f3-s2-matched-middle-half-cfl-root-173-001",
            "cfl_mode": "half_cfl",
            "cflnumber": HALF_CFL,
            "tout_s": BASE_TOUT_S,
            "external_reserve_bytes": 16 * 1024**3,
            "variable_path": "execution/casedef constants cflnumber + casedef constantsdef cflnumber",
        }
    if study == "half_output":
        return {
            "study_id": "ROOT174",
            "case_id": "F3_S2_MATCHED_MIDDLE_HALF_OUTPUT_ROOT174",
            "attempt_id": "f3-s2-matched-middle-half-output-root-174-001",
            "cfl_mode": "same_cfl",
            "cflnumber": BASE_CFL,
            "tout_s": HALF_TOUT_S,
            "external_reserve_bytes": 24 * 1024**3,
            "variable_path": "execution/parameters/parameter[@key='TimeOut']",
        }
    raise ValueError(f"unknown study {study}")


def _replace_arg(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"materializer command has no {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"materializer command has no value after {flag}")
    command[index + 1] = value


def _add_record(request: dict[str, Any], record: dict[str, Any]) -> None:
    path = record["path"]
    files = list(request.get("input_files", []))
    if path not in files:
        files.append(path)
    request["input_files"] = sorted(set(files))
    hashes = dict(request.get("input_sha256", {}))
    hashes[path] = record["sha256"]
    request["input_sha256"] = hashes
    scopes = dict(request.get("input_content_scope", {}))
    scopes[path] = record.get("content_scope", "small_metadata_hashed_by_builder_and_parent")
    request["input_content_scope"] = scopes


def _build_via_delegate(study: str, overlay: Path, output: Path, launch_commit: str) -> dict[str, Any]:
    """Use the existing strict middle external-v5 builder, then specialize it."""

    delegate = _load_module(DELEGATE, "stage2_middle_external_v5_delegate_v2")
    overlay = _regular(overlay, "overlay XML")
    output = _resolve(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite request: {output}")
    item = _study(study)
    # The delegate's ROOT153/ROOT086 joins and strict v5 command construction
    # are retained.  It writes to a private temporary path so this forward
    # builder has one immutable final write below.
    temporary = output.with_name(f".{output.name}.{os.getpid()}.delegate.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary request already exists: {temporary}")
    args = argparse.Namespace(
        gencase_request=GENCASE_REQUEST,
        receipt=MIDDLE_RECEIPT,
        # The immutable delegate validates that producer XML and BI4 share the
        # ROOT086 generated directory.  Give it the actual base XML for that
        # join; the new overlay is substituted only in the emitted materializer
        # argv below, and is recorded as a separate input binding.
        generated_xml=BASE_XML,
        generated_bi4=MIDDLE_BI4,
        generated_bi4_sha256=ROOT161_BI4_SHA,
        source_xml=SOURCE_XML,
        source_control=MIDDLE_FORCING,
        forcing_sha256=FORCING_SHA,
        support_report=SUPPORT_REPORT,
        source_card=SOURCE_CARD,
        cost_basis_receipt=ROOT162_RECEIPT,
        launch_commit=launch_commit,
        case_id=item["case_id"],
        attempt_id=item["attempt_id"],
        external_filesystem="/var/tmp/ds02-stage2",
        external_reserve_bytes=item["external_reserve_bytes"],
        home_receipt_reserve_bytes=16 * 1024**2,
        max_wall_seconds=3600.0,
        output=temporary,
    )
    try:
        delegate.build_request(args)
        request = json.loads(temporary.read_text(encoding="utf-8"))
    finally:
        temporary.unlink(missing_ok=True)
    if request.get("schema") != STRICT_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("delegate did not produce strict external-v5 request")
    command = list(request.get("command", []))
    _replace_arg(command, "--generated-xml", str(overlay))
    _replace_arg(command, "--expected-generated-xml-sha", _sha256(overlay))
    _replace_arg(command, "--tout", repr(item["tout_s"]))
    request["command"] = command
    request["case_id"] = item["case_id"]
    request["attempt_id"] = item["attempt_id"]
    request["request_variant_schema"] = SCHEMA
    request["request_variant_status"] = "READY_FOR_PARENT_GUARD_ONE_VARIABLE_OVERLAY"
    request["study"] = {
        "study_id": item["study_id"],
        "variable": "CFLnumber" if study == "half_cfl" else "TimeOut",
        "base_value": BASE_CFL if study == "half_cfl" else BASE_TOUT_S,
        "overlay_value": HALF_CFL if study == "half_cfl" else HALF_TOUT_S,
        "only_semantic_change": True,
        "full_window_required": True,
        "solver_started": False,
    }
    overlay_audit = _audit_overlay(study, overlay)
    base_record = _small_record(BASE_XML, "ROOT086 immutable base generated XML", ROOT086_XML_SHA)
    overlay_record = _small_record(overlay, "new one-variable XML overlay", overlay_audit["overlay_xml_sha256"])
    snapshot_record = _small_record(ROOT161_PROOF, "ROOT161 BI4 snapshot proof")
    root162_proof_record = _small_record(ROOT162_PROOF, "ROOT162 same-CFL terminal proof", ROOT162_PROOF_SHA)
    root162_receipt_record = _small_record(ROOT162_RECEIPT, "ROOT162 same-CFL terminal receipt", ROOT162_RECEIPT_SHA)
    calibration_record = _small_record(CALIBRATION_CONTRACT, "frozen observer calibration contract")
    source_card_record = _small_record(SOURCE_CARD, "existing F3 middle source card")
    builder_record = _small_record(Path(__file__), "ROOT173/174 v6 builder")
    for record in (base_record, overlay_record, snapshot_record, root162_proof_record, root162_receipt_record, calibration_record, source_card_record, builder_record):
        _add_record(request, record)
    request.setdefault("deferred_input_files", [])
    for path in (str(_resolve(MIDDLE_BI4)), str(_resolve(MIDDLE_FORCING))):
        if path not in request["deferred_input_files"]:
            request["deferred_input_files"].append(path)
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    request["source_provenance"].update({
        "base_generated_xml": base_record,
        "overlay_generated_xml": overlay_record,
        "root161_snapshot_proof": snapshot_record,
        "root162_reference_proof": root162_proof_record,
        "root162_reference_receipt": root162_receipt_record,
        "source_card": source_card_record,
        "calibration_contract": calibration_record,
        "v6_builder": builder_record,
        "middle_bi4_sha256": ROOT161_BI4_SHA,
        "middle_bi4_bytes": ROOT161_BI4_BYTES,
        "forcing_sha256": FORCING_SHA,
        "forcing_sha_authority": "ROOT086_receipt_and_ROOT161/parent_snapshot",
        "owner_and_execution_parameters": "ROOT153/ROOT162 source card; all XML semantics fixed except registered overlay variable",
        "continuous_equivalence": "UNKNOWN",
        "mass_rescale": False,
    })
    request["source_binding"] = {
        "base_generated_xml_sha256": ROOT086_XML_SHA,
        "overlay_generated_xml_sha256": overlay_audit["overlay_xml_sha256"],
        "middle_bi4_sha256": ROOT161_BI4_SHA,
        "middle_bi4_bytes": ROOT161_BI4_BYTES,
        "forcing_sha256": FORCING_SHA,
        "physical_case_id": PHYSICAL_CASE_ID,
        "window_s": [0.0, TMAX_S],
        "cflnumber": item["cflnumber"],
        "tout_s": item["tout_s"],
        "coefdtmin": COEF_DT_MIN,
        "only_one_semantic_xml_change": True,
        "changed_semantic_paths": overlay_audit["allowed_target_paths"],
        "fixed_execution_parameters": overlay_audit["fixed_execution_parameters"],
        "source_control_and_motion_unchanged": True,
    }
    request["solver_plan"] = {
        "grid": "middle_dp0.006",
        "window_s": [0.0, TMAX_S],
        "cfl_mode": item["cfl_mode"],
        "cflnumber": item["cflnumber"],
        "tout_s": item["tout_s"],
        "time_output_study_variable": "CFL only" if study == "half_cfl" else "output cadence only",
        "actual_effective_dt_and_clamp": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS_RUNOUT_DTALLINFO_DTSMIN",
        "terminal_frames": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS",
        "root162_reference": {"external_product_bytes": ROOT162_EXTERNAL_BYTES, "part_bytes": ROOT162_PART_BYTES, "frames": ROOT162_FRAMES},
        "storage_reservation_is_conservative_proxy_not_guarantee": True,
    }
    request["storage_scope"] = dict(request.get("storage_scope", {}))
    reservation = dict(request["storage_scope"].get("reservation_basis", {}))
    reservation.update({
        "actual_cost_basis_receipt": str(_resolve(ROOT162_RECEIPT)),
        "actual_cost_basis_receipt_sha256": ROOT162_RECEIPT_SHA,
        "actual_cost_basis_terminal_external_product_bytes": ROOT162_EXTERNAL_BYTES,
        "actual_cost_basis_terminal_part_bytes": ROOT162_PART_BYTES,
        "actual_cost_basis_native_frames": ROOT162_FRAMES,
        "study_reservation_is_not_a_frame_or_wall_guarantee": True,
    })
    request["storage_scope"]["reservation_basis"] = reservation
    request["storage_scope"]["external_product_reserved_bytes"] = item["external_reserve_bytes"]
    request["storage_scope"]["home_receipt_reserved_bytes"] = 16 * 1024**2
    request["storage_scope"]["new_storage_bytes"] = item["external_reserve_bytes"] + 16 * 1024**2
    request["execution"] = dict(request.get("execution", {}))
    request["execution"].update({
        "source_overlay_generated_by_v6": True,
        "overlay_xml_semantic_audit": "PASS_ONE_VARIABLE",
        "native_bi4_payload_open": True,
        "native_raw_hdf5_open": False,
        "solver_launch": "PARENT_ONLY",
    })
    request["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request["physical_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "one-variable CFL/output control canary; no scientific credit before terminal dt/output/field checks"}
    request["solver_started"] = False
    request["cfd_invoked"] = False
    request["raw_opened"] = False
    request["hdf5_opened"] = False
    request["launch_allowed"] = True
    request["sha256"] = _canonical(request)
    _write_once(output, request)
    return {
        "status": "PASS_STRICT_EXTERNAL_V5_ONE_VARIABLE_REQUEST",
        "output": str(output),
        "request_sha256": request["sha256"],
        "study": study,
        "overlay_xml_sha256": overlay_audit["overlay_xml_sha256"],
        "generated_bi4_sha256": ROOT161_BI4_SHA,
        "forcing_sha256": FORCING_SHA,
        "solver_started": False,
        "payload_read_by_builder": False,
    }


def _fixture_test() -> dict[str, Any]:
    """Exercise path-discovery and negative one-variable audit on a small copy."""

    with tempfile.TemporaryDirectory(prefix="ds02-middle-overlay-v2-test-") as directory:
        root = Path(directory)
        original = root / "base.xml"
        overlay = root / "half-cfl.xml"
        negative = root / "negative.xml"
        original.write_bytes(_regular(BASE_XML, "ROOT086 base XML").read_bytes())
        # Audit helpers intentionally use the frozen ROOT086 path.  Generate
        # actual overlays through the public function in a temp tree only by
        # temporarily validating the resulting semantics against a parsed
        # copy below; no source payload is touched.
        parsed = ET.parse(original).getroot()
        casedef, execution, timeout = _overlay_nodes(parsed)
        casedef.attrib["value"] = ".025"
        execution.attrib["value"] = ".025"
        ET.indent(ET.ElementTree(parsed), space="  ")
        ET.ElementTree(parsed).write(overlay, encoding="utf-8", xml_declaration=True)
        # Negative control: a registered overlay with an unrelated TimeMax
        # change must be rejected by the same semantic diff rules.  Use a
        # direct comparison fixture because _audit_overlay is intentionally
        # bound to the immutable ROOT086 source path.
        bad = ET.parse(original).getroot()
        bad_timeout = _find_one(bad, lambda e: e.tag == "parameter" and e.attrib.get("key") == "TimeMax", "TimeMax")
        bad_timeout.attrib["value"] = "8.0"
        ET.indent(ET.ElementTree(bad), space="  ")
        ET.ElementTree(bad).write(negative, encoding="utf-8", xml_declaration=True)
        base_sem = _semantic_tree(ET.parse(original).getroot())
        overlay_sem = _semantic_tree(ET.parse(overlay).getroot())
        changed = {key for key in base_sem if base_sem[key] != overlay_sem[key]}
        casedef_o, execution_o, timeout_o = _overlay_nodes(ET.parse(overlay).getroot())
        assert len(changed) == 2
        assert abs(float(casedef_o.attrib["value"]) - HALF_CFL) < 1e-12
        assert abs(float(execution_o.attrib["value"]) - HALF_CFL) < 1e-12
        bad_sem = _semantic_tree(ET.parse(negative).getroot())
        bad_changed = {key for key in base_sem if base_sem[key] != bad_sem[key]}
        assert any(key.endswith("/@value") and "TimeMax" not in key for key in bad_changed)
        return {"status": "PASS", "actual_root086_xml_path_discovery": True, "half_cfl_changed_nodes": sorted(changed), "negative_unregistered_change_detected": True}


def self_test() -> dict[str, Any]:
    if str(VENV_PYTHON) != "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise AssertionError("literal venv path changed")
    if BASE_CFL != 0.05 or HALF_CFL != 0.025 or BASE_TOUT_S != 0.01 or HALF_TOUT_S != 0.005:
        raise AssertionError("one-variable study values changed")
    if not HEX64.fullmatch(ROOT161_BI4_SHA) or not HEX64.fullmatch(FORCING_SHA):
        raise AssertionError("frozen dynamic SHA malformed")
    fixture = _fixture_test()
    return {"status": "PASS", "schema": SCHEMA, "strict_solver_schema": STRICT_SCHEMA, "fixture": fixture, "payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-overlay", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--study", choices=("half_cfl", "half_output"))
    parser.add_argument("--overlay-xml", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        elif args.build_overlay:
            if args.study is None or args.output is None:
                parser.error("--build-overlay requires --study and --output")
            result = write_overlay(args.study, args.output)
        else:
            if args.study is None or args.overlay_xml is None or args.output is None or not args.launch_commit:
                parser.error("--build-request requires --study, --overlay-xml, --output and --launch-commit")
            result = _build_via_delegate(args.study, args.overlay_xml, args.output, args.launch_commit)
    except Exception as exc:
        print(json.dumps({"status": "FAILED_MIDDLE_OVERLAY_V2", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
