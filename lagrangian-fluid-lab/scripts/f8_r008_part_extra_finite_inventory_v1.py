"""Diagnostic finite inventory for one synthetic/raw R008 PartExtra BI4.

This additive parser covers the bounded CPU ``JPartExtraBi4`` shape emitted by
``JDsExtraDataSave``. It uses the existing SAFE BI4 scanner's bounded item
parser and raw-I/O primitives, but independently validates the PartExtra file
code and root contract. It does not establish bundle membership/completeness,
source/runtime trust, or native-integrity qualification.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

import numpy as np

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_part_extra_finite_inventory.v1"
FILE_PREFIX = b"#FileJBD JPartExtraBi4"
FORMAT_VERSION = 211030
STREAM_CHUNK_ELEMENTS = 1 << 16


class PartExtraFiniteInventoryError(ValueError):
    """A bounded PartExtra input violates the reviewed R008 subset."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PartExtraFiniteInventoryError(message)


def _scan_part_extra_fd(
    raw_fd: int, expected_sha256: str,
) -> tuple[decoder.ItemRecord, int, str, tuple[int, int, int, int, int]]:
    _require(type(expected_sha256) is str and bool(decoder._SHA256.fullmatch(expected_sha256)),
             "an expected raw PartExtra SHA-256 is required")
    try:
        before = decoder._check_input_stat(raw_fd)
        before_identity = decoder._identity(before)
        header = decoder._pread_exact(raw_fd, decoder.HEADER_BYTES, 0, before.st_size)
        title = header[:60]
        _require(title[:len(FILE_PREFIX)] == FILE_PREFIX
                 and title[len(FILE_PREFIX):58] == b" " * (58 - len(FILE_PREFIX))
                 and title[58:] == b"\n\0",
                 "BI4 filecode is not one fixed JPartExtraBi4 header")
        _require(header[60] == 0 and header[61] == 0 and header[62:64] == b"\0\0",
                 "PartExtra BI4 must use the reviewed little-endian non-SI64 header")
        raw_hash = decoder._hash_fd(raw_fd, before.st_size)
        _require(raw_hash == expected_sha256,
                 "raw PartExtra hash does not match the held input binding")

        scanner = decoder._Scanner(raw_fd, before.st_size)
        root = scanner._item(1, ())
        _require(scanner.pos == before.st_size,
                 "PartExtra BI4 has trailing bytes or multiple top-level records")
        _require(root.name == "JPartExtraBi4" and not root.children,
                 "PartExtra BI4 must contain one flat JPartExtraBi4 root")

        after = decoder._check_input_stat(raw_fd)
        _require(decoder._same_stat(before, after)
                 and decoder._hash_fd(raw_fd, before.st_size) == raw_hash,
                 "held PartExtra identity or bytes changed during bounded scan")
        return root, before.st_size, raw_hash, before_identity
    except (OSError, decoder.Bi4FormatError, OverflowError) as error:
        if isinstance(error, PartExtraFiniteInventoryError):
            raise
        raise PartExtraFiniteInventoryError(
            "held raw input did not produce a stable bounded PartExtra BI4"
        ) from error


def _required_value(root: decoder.ItemRecord, name: str, type_code: int) -> Any:
    matched = [value for value in root.values if value.name == name]
    _require(len(matched) == 1 and matched[0].type_code == type_code,
             f"PartExtra metadata {name} is missing, duplicated, or mistyped")
    return matched[0].value


def summarize_part_extra_fd(
    raw_fd: int,
    expected_sha256: str,
    *,
    expected_part: int,
    expected_case_nbound: int,
    expected_case_nfloat: int,
) -> dict[str, Any]:
    """Inventory all floating values in one held, bounded PartExtra BI4.

    The expected part and case populations are caller claims. They are checked
    against the raw file but are not authenticated by this diagnostic API.
    """
    _require(type(expected_part) is int and 0 < expected_part <= 99_999,
             "expected PartExtra part number is outside the reviewed bound")
    _require(type(expected_case_nbound) is int
             and 0 < expected_case_nbound <= decoder.MAX_ARRAY_COUNT,
             "expected CaseNbound is outside the reviewed array bound")
    _require(type(expected_case_nfloat) is int
             and 0 <= expected_case_nfloat <= expected_case_nbound,
             "expected CaseNfloat is outside the boundary population")

    root, input_bytes, raw_hash, input_identity = _scan_part_extra_fd(raw_fd, expected_sha256)
    required_types = {
        "AppName": 1,
        "FormatVer": 8,
        "CaseNbound": 8,
        "CaseNfloat": 8,
        "Cpart": 7,
        "Step": 8,
        "TimeStep": 12,
        "UseNormalsFt": 2,
    }
    _require({value.name for value in root.values} == set(required_types),
             "PartExtra root metadata inventory has missing or unknown fields")
    values = {
        name: _required_value(root, name, type_code)
        for name, type_code in required_types.items()
    }
    _require(isinstance(values["AppName"], str) and bool(values["AppName"]),
             "PartExtra AppName must be nonempty text")
    _require(values["FormatVer"] == FORMAT_VERSION,
             "PartExtra FormatVer differs from the frozen CPU writer contract")
    _require(values["CaseNbound"] == expected_case_nbound
             and values["CaseNfloat"] == expected_case_nfloat,
             "PartExtra boundary populations differ from caller-supplied frozen claims")
    _require(values["Cpart"] == expected_part,
             "PartExtra Cpart differs from the expected part number")

    normals = [array for array in root.arrays if array.name == "Normals"]
    _require(len(root.arrays) == 1 and len(normals) == 1,
             "PartExtra must contain exactly one classified Normals array")
    normal_array = normals[0]
    expected_normals = (
        expected_case_nbound if values["UseNormalsFt"]
        else expected_case_nbound - expected_case_nfloat
    )
    _require(not (values["UseNormalsFt"] and expected_case_nfloat == 0),
             "PartExtra UseNormalsFt cannot be true when CaseNfloat is zero")
    _require(normal_array.type_code == 22 and normal_array.count == expected_normals
             and normal_array.byte_count == expected_normals * 3 * 4,
             "PartExtra Normals dtype or population differs from the CPU writer contract")

    digest = hashlib.sha256()
    normals_finite_count = normals_nonfinite_count = 0
    component_count = normal_array.count * 3
    try:
        for element_start in range(0, normal_array.count, STREAM_CHUNK_ELEMENTS):
            elements = min(STREAM_CHUNK_ELEMENTS, normal_array.count - element_start)
            byte_offset = normal_array.offset + element_start * 12
            byte_count = elements * 12
            block = decoder._pread_exact(raw_fd, byte_count, byte_offset, input_bytes)
            digest.update(block)
            finite = np.isfinite(np.frombuffer(block, dtype="<f4"))
            normals_finite_count += int(np.count_nonzero(finite))
            normals_nonfinite_count += int(finite.size - np.count_nonzero(finite))
        after_values = decoder._check_input_stat(raw_fd)
        _require(decoder._identity(after_values) == input_identity
                 and decoder._hash_fd(raw_fd, input_bytes) == raw_hash,
                 "held PartExtra identity or bytes changed during finite-value scan")
    except PartExtraFiniteInventoryError:
        raise
    except (OSError, decoder.Bi4FormatError, OverflowError) as error:
        raise PartExtraFiniteInventoryError(
            "I/O failure or source mutation during bounded PartExtra finite scan"
        ) from error

    timestep_finite = math.isfinite(float(values["TimeStep"]))
    finite_count = normals_finite_count + int(timestep_finite)
    nonfinite_count = normals_nonfinite_count + int(not timestep_finite)
    finite_values = finite_count + nonfinite_count
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_not_adjudicated",
        "source_part_extra_sha256": raw_hash,
        "source_part_extra_bytes": input_bytes,
        "part_claim": expected_part,
        "case_nbound_claim": expected_case_nbound,
        "case_nfloat_claim": expected_case_nfloat,
        "metadata": {
            "format_version": values["FormatVer"],
            "app_name": values["AppName"],
            "cpart": values["Cpart"],
            "step": values["Step"],
            "time_step_s": values["TimeStep"] if timestep_finite else None,
            "time_step_raw_bits_le_hex": np.asarray([values["TimeStep"]], dtype="<f8").tobytes().hex(),
            "time_step_finite": timestep_finite,
            "use_normals_ft": values["UseNormalsFt"],
            "source_part_extra_sha256": raw_hash,
        },
        "arrays": [{
            "name": "Normals",
            "type_code": normal_array.type_code,
            "dtype": "<f4",
            "shape": [normal_array.count, 3],
            "unit": "dimensionless",
            "semantic": "saved boundary-normal direction vectors",
            "population": "CaseNbound entries, or CaseNbound-CaseNfloat when floating normals are disabled",
            "source_part_extra_sha256": raw_hash,
            "raw_array_sha256": digest.hexdigest(),
            "finite_component_count": normals_finite_count,
            "nonfinite_component_count": normals_nonfinite_count,
            "all_components_finite": normals_nonfinite_count == 0,
        }],
        "floating_metadata": {
            "records": [{
                "item_path": [root.name],
                "metadata_name": "TimeStep",
                "type_code": 12,
                "dtype": "<f8",
                "component_count": 1,
                "unit": "s",
                "semantic": "simulation time represented by this saved PartExtra part",
                "population": "one root metadata scalar",
                "source_part_extra_sha256": raw_hash,
                "finite_count": int(timestep_finite),
                "nonfinite_count": int(not timestep_finite),
            }],
            "finite_count": int(timestep_finite),
            "nonfinite_count": int(not timestep_finite),
            "all_floating_metadata_finite": timestep_finite,
        },
        "floating_value_inventory": {
            "policy": "all float/double metadata and every scalar component of every classified PartExtra floating array",
            "finite_count": finite_count,
            "nonfinite_count": nonfinite_count,
            "all_floating_values_finite": nonfinite_count == 0 and finite_values == component_count + 1,
        },
        "bundle_membership_verified": False,
        "bundle_output_completeness_verified": False,
        "source_build_runtime_authenticated": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = ["PartExtraFiniteInventoryError", "SCHEMA", "summarize_part_extra_fd"]
