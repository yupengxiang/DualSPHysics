#!/usr/bin/env python3
"""Official BI4 decoder adapter for GenCase-produced initial files.

The regular saved-frame observer intentionally rejects ``PeriMode=96`` because
that value means ``PERI_Unknown`` in the official source.  GenCase's standalone
``generated.bi4`` uses that source-defined default when no periodic condition
is present in the generated XML.  This adapter permits exactly that
source-grounded case (96, or explicit no-periodic 0), while still rejecting
all other values.  It reuses the official observer's XML/range/field helpers
but keeps this GenCase exception in a new, separately hashed module.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np


BASE_PATH = Path(__file__).with_name("stage2_native_physical_observer_v2.py")
MODULE_NAME = "ds02_stage2_native_physical_observer_v2_for_generated_initial"
spec = importlib.util.spec_from_file_location(MODULE_NAME, BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base native observer: {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = base
spec.loader.exec_module(base)

UnsupportedSemantics = base.UnsupportedSemantics
sha256_file = base.sha256_file
file_record = base.file_record
parse_source_xml = base.parse_source_xml
assign_particle_ranges = base.assign_particle_ranges
frame_observables = base.frame_observables
decoder_source_contract = base.decoder_source_contract
manufactured_semantic_selftests = base.manufactured_semantic_selftests
_decoder_particle_paths = base._decoder_particle_paths

SCHEMA = "ds02.stage2.f1-s1.generated-initial-observer.v1"
PERIODIC_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPeriodicDef.h")
PERIODIC_BI4_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
PERIODIC_BI4_SOURCE = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")
# Official JSph execution keys that request periodic boundaries.  A generated
# XML without these keys still needs the source-bound BI4-default explanation;
# the absence of a bespoke <periodic> node alone is insufficient.
PERIODIC_EXECUTION_KEYS = (
    "XPeriodicIncY", "XPeriodicIncZ", "YPeriodicIncX", "YPeriodicIncZ",
    "ZPeriodicIncX", "ZPeriodicIncY", "XYPeriodic", "XZPeriodic", "YZPeriodic",
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def gencase_periodic_contract(source_xml: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Prove the narrow GenCase source-default case for ``PERI_Unknown``.

    ``96`` is an *unknown* metadata value, not a measured proof of active
    non-periodicity.  This contract only permits it for a completed GenCase
    output whose generated XML has neither periodic elements nor the official
    JSph periodic execution keys, while the v5.4 source default path is bound.
    """

    root = ET.parse(source_xml).getroot()
    request = receipt.get("request", {})
    if request.get("cpu_task_kind") != "gencase":
        raise UnsupportedSemantics("initial BI4 is not bound to a completed GenCase request")
    command = request.get("command", [])
    command_text = " ".join(str(value) for value in command)
    if "GenCase" not in command_text and "gencase" not in command_text.lower():
        raise UnsupportedSemantics("receipt command is not an official GenCase command")
    explicit_nodes = [node for node in root.iter() if local_name(node.tag) in {"periodic", "periodiccondition", "periodicconditions"}]
    explicit_text = [ET.tostring(node, encoding="unicode") for node in explicit_nodes]
    parameter_keys = [
        str(node.get("key")) for node in root.iter()
        if local_name(node.tag) == "parameter" and node.get("key") is not None
    ]
    active_execution_keys = sorted(set(parameter_keys).intersection(PERIODIC_EXECUTION_KEYS))
    header = PERIODIC_HEADER.read_text(encoding="utf-8", errors="replace")
    bi4_header = PERIODIC_BI4_HEADER.read_text(encoding="utf-8", errors="replace")
    bi4_source = PERIODIC_BI4_SOURCE.read_text(encoding="utf-8", errors="replace")
    enum_checks = {
        "peri_none_zero": "PERI_None=0" in header,
        "peri_unknown_96": "PERI_Unknown=96" in header,
        "unknown_name": "PERI_Unknown" in header and "TpPeriName" in header,
        "unknown_resets_to_zero_active": "return(tperi==PERI_Unknown? 0" in header,
        "bi4_header_default_note": "Establece PERI_Unknown por defecto" in bi4_header,
        "bi4_configbasic_unknown": "ConfigSimPeri(PERI_Unknown" in bi4_source,
    }
    if not all(enum_checks.values()):
        raise UnsupportedSemantics("official periodic enum/source contract is incomplete")
    if explicit_nodes or active_execution_keys:
        raise UnsupportedSemantics(
            "generated XML has explicit periodic semantics; default-unknown contract is not applicable: "
            f"nodes={len(explicit_nodes)} execution_keys={active_execution_keys}"
        )
    return {
        "status": "PASS_GENCASE_DEFAULT_PERIODIC_SOURCE_CONTRACT",
        "source_xml_has_explicit_periodic": False,
        "execution_parameter_keys": parameter_keys,
        "active_periodic_execution_keys": active_execution_keys,
        "allowed_peri_mode_values": [0, 96],
        "default_unknown_value": 96,
        "default_unknown_name": "PERI_Unknown",
        "no_periodic_value": 0,
        "source_enum": {
            "path": str(PERIODIC_HEADER.resolve()),
            "sha256": sha256_file(PERIODIC_HEADER)[0],
            "checks": enum_checks,
        },
        "source_default_evidence": {
            "jpartdata_bi4_header": {
                "path": str(PERIODIC_BI4_HEADER.resolve()),
                "sha256": sha256_file(PERIODIC_BI4_HEADER)[0],
            },
            "jpartdata_bi4_source": {
                "path": str(PERIODIC_BI4_SOURCE.resolve()),
                "sha256": sha256_file(PERIODIC_BI4_SOURCE)[0],
            },
            "configbasic_line": "JPartDataBi4::ConfigBasic calls ConfigSimPeri(PERI_Unknown, zero increments)",
            "unknown_interpretation": "PERI_Unknown is retained as UNKNOWN metadata; this does not measure active nonperiodicity",
        },
        "explicit_nodes": explicit_text,
        "reason": "completed GenCase XML has no periodic element or official execution periodic key; standalone BI4 may retain source default PERI_Unknown=96",
    }


def _field_digest(arrays: list[tuple[str, np.ndarray]]) -> str:
    digest = hashlib.sha256()
    for name, array in arrays:
        digest.update(name.encode("ascii"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(json.dumps(list(array.shape)).encode("ascii"))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def validate_peri_mode(raw_value: Any, periodic_contract: dict[str, Any]) -> dict[str, Any]:
    """Apply the source-bound PeriMode gate used by the real decoder path."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedSemantics(f"generated BI4 PeriMode is non-numeric: {raw_value!r}") from exc
    allowed = [int(item) for item in periodic_contract.get("allowed_peri_mode_values", [])]
    if value not in allowed:
        raise UnsupportedSemantics(f"generated BI4 PeriMode={value} is outside source-bound allowed values {allowed}")
    return {
        "value": value,
        "interpretation": "PERI_None_explicit" if value == 0 else "PERI_Unknown_source_default_not_proof_of_active_nonperiodicity",
        "contract_status": periodic_contract.get("status", "UNKNOWN_CONTRACT"),
    }


def decode_generated_frame(
    frame_path: Path,
    decoder: Path,
    scratch_root: Path,
    frame: int,
    periodic_contract: dict[str, Any],
) -> dict[str, Any]:
    """Decode one GenCase BI4 while applying the narrow periodic exception."""

    if not frame_path.is_file() or frame_path.is_symlink():
        raise ValueError(f"selected generated BI4 is not a regular file: {frame_path}")
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"generated-initial-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / "decoded"
        try:
            subprocess.run([str(decoder), str(frame_path), str(prefix)], check=True, capture_output=True, text=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or ""
            raise UnsupportedSemantics(f"official BI4 decoder failed for generated frame {frame}: {detail[-1000:]}") from exc
        decoder_xml, data_root = _decoder_particle_paths(prefix)
        metadata = {**decoder_xml["metadata"], **decoder_xml["info"]}
        expected_values = {"Npiece": 1, "Piece": 0, "NpDynamic": 0, "ReuseIds": 0}
        dynamic_semantics: dict[str, Any] = {}
        for key, expected in expected_values.items():
            value = metadata.get(key)
            dynamic_semantics[key] = value if value is not None else "UNKNOWN_NOT_EXPOSED_BY_DECODER"
            if value is None:
                continue
            try:
                if int(value) != expected:
                    raise UnsupportedSemantics(f"unsupported generated BI4 dynamic field {key}={value}")
            except (TypeError, ValueError) as exc:
                raise UnsupportedSemantics(f"non-numeric generated BI4 field {key}={value!r}") from exc
        peri_value = metadata.get("PeriMode")
        if peri_value is None:
            raise UnsupportedSemantics("generated BI4 has no PeriMode metadata")
        peri_semantics = validate_peri_mode(peri_value, periodic_contract)
        dynamic_semantics["PeriMode"] = peri_semantics["value"]
        dynamic_semantics["PeriMode_contract"] = peri_semantics["contract_status"]
        dynamic_semantics["PeriMode_interpretation"] = peri_semantics["interpretation"]

        paths = {
            "ids": data_root / "Idp.bin",
            "position_double": data_root / "Posd.bin",
            "position_float": data_root / "Pos.bin",
            "velocity": data_root / "Vel.bin",
            "density": data_root / "Rhop.bin",
        }
        if not paths["ids"].is_file() or not paths["velocity"].is_file() or not paths["density"].is_file():
            raise UnsupportedSemantics("generated BI4 decoder lacks Idp/Vel/Rhop")
        if paths["position_double"].is_file():
            position_path = paths["position_double"]
            position_dtype = np.dtype("<f8")
        elif paths["position_float"].is_file():
            position_path = paths["position_float"]
            position_dtype = np.dtype("<f4")
        else:
            raise UnsupportedSemantics("generated BI4 decoder lacks Posd/Pos")
        ids_unsorted = np.fromfile(paths["ids"], dtype=np.dtype("<u4"))
        if ids_unsorted.size == 0 or np.unique(ids_unsorted).size != ids_unsorted.size:
            raise UnsupportedSemantics("generated BI4 Idp is empty or duplicated")
        order = np.argsort(ids_unsorted, kind="mergesort")
        count = int(ids_unsorted.size)
        position = np.fromfile(position_path, dtype=position_dtype)
        velocity = np.fromfile(paths["velocity"], dtype=np.dtype("<f4"))
        density = np.fromfile(paths["density"], dtype=np.dtype("<f4"))
        try:
            position = position.reshape(count, 3)[order]
            velocity = velocity.reshape(count, 3)[order]
            density = density.reshape(count)[order]
        except ValueError as exc:
            raise UnsupportedSemantics("generated BI4 arrays do not match Idp count") from exc
        ids = ids_unsorted[order]
        if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
            raise UnsupportedSemantics("generated BI4 fields contain NaN/Inf")
        raw_time = decoder_xml["info"].get("TimeStep")
        try:
            frame_time = float(raw_time)
        except (TypeError, ValueError) as exc:
            raise UnsupportedSemantics("generated BI4 has no finite TimeStep") from exc
        if not math.isfinite(frame_time):
            raise UnsupportedSemantics("generated BI4 TimeStep is non-finite")
        part_sha256, part_bytes = sha256_file(frame_path)
        return {
            "frame": frame,
            "saved_file": {"path": str(frame_path.resolve()), "bytes": part_bytes, "sha256": part_sha256},
            "decoder_xml_sha256": sha256_file(decoder_xml["xml_path"])[0],
            "decoded_time_s": frame_time,
            "field_digest_sha256": _field_digest([("Idp", ids), ("Pos", position), ("Vel", velocity), ("Rhop", density)]),
            "ids": ids,
            "position": position,
            "velocity": velocity,
            "density": density,
            "metadata": decoder_xml["metadata"],
            "info": decoder_xml["info"],
            "dynamic_semantics": dynamic_semantics,
            "position_dtype": str(position_dtype),
        }


def manufactured_generated_semantic_selftests() -> dict[str, Any]:
    base_result = manufactured_semantic_selftests()
    cases: list[dict[str, Any]] = []
    no_periodic = {"status": "PASS_GENCASE_DEFAULT_PERIODIC_SOURCE_CONTRACT", "allowed_peri_mode_values": [0, 96]}
    accepted = validate_peri_mode(96, no_periodic)["interpretation"].startswith("PERI_Unknown")
    try:
        validate_peri_mode(95, no_periodic)
    except UnsupportedSemantics:
        rejected_wrong = True
    else:
        rejected_wrong = False
    explicit_reject = {"status": "FAIL_EXPLICIT_PERIODIC_NOT_DEFAULT"}
    with tempfile.TemporaryDirectory(prefix="ds02-generated-periodic-contract-") as temporary:
        plain = Path(temporary) / "plain.xml"
        plain.write_text("<case><parameters/></case>", encoding="utf-8")
        explicit = Path(temporary) / "explicit.xml"
        explicit.write_text('<case><parameters><parameter key="XYPeriodic" value="1"/></parameters></case>', encoding="utf-8")
        receipt = {"request": {"cpu_task_kind": "gencase", "command": ["GenCase_linux64"]}}
        plain_contract_ok = gencase_periodic_contract(plain, receipt)["active_periodic_execution_keys"] == []
        try:
            gencase_periodic_contract(explicit, receipt)
        except UnsupportedSemantics:
            explicit_parameter_rejected = True
        else:
            explicit_parameter_rejected = False
    cases.append({"name": "GenCase_default_unknown_96_is_source_bound", "status": "PASS" if accepted else "FAIL"})
    cases.append({"name": "arbitrary_95_is_rejected", "status": "PASS" if rejected_wrong else "FAIL"})
    cases.append({"name": "explicit_periodic_does_not_use_default_exception", "status": "PASS" if explicit_reject["status"].startswith("FAIL") and plain_contract_ok and explicit_parameter_rejected else "FAIL"})
    status = "PASS" if base_result.get("status") == "PASS" and all(item["status"] == "PASS" for item in cases) else "FAIL"
    return {"status": status, "base_observer": base_result, "generated_cases": cases, "scope": "manufactured metadata only; no BI4 read"}
