"""Freeze the statically evidenced BI4/decode contract for F8 R008.

This audit reads pinned sources and already-existing artifacts only. It never
invokes ``bi4_dump``, GenCase, a solver, or any worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = (
    LAB
    / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "bi4-format-static-audit-v1/receipt.json"
)
SCHEMA = "core.cfd.f8.r008_bi4_format_static_audit.v1"

# Pins for inputs whose content defines this audit. The native decoder is an
# ignored, untracked executable; pinning it here identifies the inspected file,
# but does not claim that a prior receipt executed this exact binary.
PINNED_EVIDENCE: dict[str, tuple[str, str]] = {
    "decoder_binary": (
        "campaigns/l1-resume/artifacts/bi4_dump",
        "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e",
    ),
    "decoder_source": (
        "scripts/native/bi4_dump.cpp",
        "5d63457cf7427128aa564639cfb77af70edacb5237371113697c478067bb7fe6",
    ),
    "q1_jbinarydata_cpp": (
        "/home/jade/Projects/DualSPHysics/src/source/JBinaryData.cpp",
        "29b39fe132795fe941d83c7ade8a842d2b47da281a3dc7855003c2ddb2f899e1",
    ),
    "q1_jbinarydata_header": (
        "/home/jade/Projects/DualSPHysics/src/source/JBinaryData.h",
        "88198fd737c17c83cdfaa2cbb889e09e439f2bd9f9cf76d10e9d4d6e5a454e3e",
    ),
    "official_jbinarydata_cpp": (
        "vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.cpp",
        "a166250e1d339b45c549c25ed49e9533742bf52ce722102b96042f54c750566d",
    ),
    "official_jbinarydata_header": (
        "vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.h",
        "e63f60e6ae6d3ee8ed1f137ebca1bf45e6b783fb5a54c510fa80a3b09556af38",
    ),
    "official_partdata_writer": (
        "vendor/official/DualSPHysics_v5.4/src/source/JPartDataBi4.cpp",
        "e507d88c8fac9b990b74d8dce71edb3524f71f46a04b3bdc5d289bf0af4ecdfc",
    ),
    "official_partdata_header": (
        "vendor/official/DualSPHysics_v5.4/src/source/JPartDataBi4.h",
        "80130f90bbb9334315da90c66c63cf9df9723abc431e49cb219af1f038a32dec",
    ),
    "official_excluded_particle_writer": (
        "vendor/official/DualSPHysics_v5.4/src/source/JPartOutBi4Save.cpp",
        "1a5d746ae5a962bc10d752e0f96d8acaacb02c31ab3dc647f447f4b2a3b3e2d3",
    ),
    "official_solver_writer": (
        "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp",
        "8729eb29db778288b0495855a04fa0984000896546f484dcf96176ec48da5454",
    ),
    "official_native_types": (
        "vendor/official/DualSPHysics_v5.4/src/source/TypesDef.h",
        "f8b252fb7fbb178344e62263a277b174f900d413cababad453a5842ecbe151f2",
    ),
    "official_byteorder": (
        "vendor/official/DualSPHysics_v5.4/src/source/Functions.cpp",
        "b362c2ad604dd514494a52b0e6b5ee78b74378d08afa896076de7d4934adffc1",
    ),
    "q1_validation": (
        "campaigns/l1-resume/continuation/Q1-NATIVE-READER-VALIDATION.json",
        "25b20e0cb00362f5bf6298682f380001aa21f13eeb24357857586644e0a4414d",
    ),
    "r008_initial_xml": (
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "cpu-native-preflight-v3/native-initial.xml",
        "0c5201e6177346f618018a0b7cd918e83d9c883c466b3ccbaf698277afd20f9f",
    ),
    "r008_decoder_log": (
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "cpu-native-preflight-v3/native-decode.stdout.log",
        "c55686d67c63a2c2acb03821ad891b5dd31dc90136d29f6079a46859a0a29fbd",
    ),
    "r008_preflight_receipt": (
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "cpu-native-preflight-v3/receipt.json",
        "4db07cb997746352d13850103aba86f58bbd9af4d71e22bafdcde67919d38b13",
    ),
}

ANCHOR_FILES: dict[str, tuple[int, str]] = {
    "BoundNor.bin": (
        49152,
        "0f12a4377bef1e3589f3a653ffedd2483339bd4fadc4e90d068e87f92eda00fb",
    ),
    "Idp.bin": (
        43008,
        "ace966ef28bf7776f762d09dd9637027fd7ab25fe8b87b9965e610748b12bf81",
    ),
    "Posd.bin": (
        258048,
        "842d5d142d7c35069b091813266dbc016e1406b757356c3b0b34aa18722c3ef6",
    ),
    "Rhop.bin": (
        43008,
        "745b719cd4231e16a279010ef28df113cbc7228638d6ecab249283a9cfd4f5d5",
    ),
    "Vel.bin": (
        129024,
        "bab4e6a5d6ef38877caddf543e92dc396a7538722dab6f24cee596db2427110b",
    ),
}


def _path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else LAB / candidate


def _fingerprint(path: Path, role: str, expected_sha256: str | None = None) -> dict[str, Any]:
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"evidence is not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ValueError(f"evidence changed between lstat and open: {path}")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError(f"evidence changed while hashing: {path}")
    actual = digest.hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError(f"pinned evidence hash mismatch: {path}")
    try:
        shown_path = str(path.relative_to(LAB))
    except ValueError:
        shown_path = str(path)
    return {
        "path": shown_path,
        "role": role,
        "bytes": after.st_size,
        "sha256": actual,
        "regular_file": True,
        "symlink": False,
        "link_count": after.st_nlink,
    }


def _anchor_manifest() -> list[dict[str, Any]]:
    root = (
        LAB
        / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "cpu-native-preflight-v3/native-initial/PART_0000"
    )
    result = []
    for name, (expected_bytes, expected_sha256) in sorted(ANCHOR_FILES.items()):
        ref = _fingerprint(root / name, "already-existing decoded GenCase array", expected_sha256)
        if ref["bytes"] != expected_bytes:
            raise ValueError(f"pinned anchor byte count mismatch: {name}")
        ref["array_name"] = name.removesuffix(".bin")
        result.append(ref)
    actual_names = sorted(path.name for path in root.iterdir())
    if actual_names != sorted(ANCHOR_FILES):
        raise ValueError("R008 native-initial sample has an unexpected array namespace")
    return result


def build_receipt() -> dict[str, Any]:
    evidence = {
        name: _fingerprint(_path(path), name, sha256)
        for name, (path, sha256) in PINNED_EVIDENCE.items()
    }
    script_ref = _fingerprint(Path(__file__), "this static audit implementation")
    anchor_manifest = _anchor_manifest()
    return {
        "schema": SCHEMA,
        "status": "format_contract_bounded_historical_binary_build_linkage_unverified",
        "created_at_utc": "2026-09-24",
        "scope": {
            "campaign": "F8 R008",
            "evidence_case": "space-q0p5-dp0p0075",
            "evidence_role": "GenCase initial BI4 format anchor only; not a solver frame or qualification result",
            "supported_solver_source": "local official DualSPHysics v5.4 source snapshot, JSph::SavePartData path",
        },
        "audit_implementation": script_ref,
        "evidence": evidence,
        "observed_initial_decode": {
            "decoder_xml": evidence["r008_initial_xml"],
            "decoder_stdout": evidence["r008_decoder_log"],
            "preflight_receipt": evidence["r008_preflight_receipt"],
            "array_files": anchor_manifest,
            "array_shape_and_type": {
                "Idp": {"xml_type": "uint", "numpy_contract": "<u4", "shape": [10752]},
                "Posd": {"xml_type": "double3", "numpy_contract": "<f8", "shape": [10752, 3]},
                "Vel": {"xml_type": "float3", "numpy_contract": "<f4", "shape": [10752, 3]},
                "Rhop": {"xml_type": "float", "numpy_contract": "<f4", "shape": [10752]},
                "BoundNor": {"xml_type": "float3", "numpy_contract": "<f4", "shape": [4096, 3]},
            },
            "q1_independent_check": {
                "identity_exact": True,
                "position_max_abs_error_m": 4.768371586472142e-08,
                "velocity_max_abs_error": 0.0,
                "density_max_abs_error_kg_m3": 4.843750002692104e-05,
                "pressure_max_abs_error_pa": 0.00018074428498948691,
                "scope_limit": "one initial frame checked against PartVTK; does not establish R008 solver-frame output or historical decoder binary identity",
            },
        },
        "source_contract": {
            "bi4_header_byte_order": "JBinaryData records host byte order and rejects an input BI4 whose header byte order differs from the decoder host; raw arrays are exposed in native memory order.",
            "target_byte_order": "little-endian only for the pinned ELF x86-64 decoder; a future verifier must assert little-endian host and pin the actual executable hash for each decode stage.",
            "type_sizes_bytes": {
                "uint": 4,
                "ullong": 8,
                "float": 4,
                "double": 8,
                "float3": 12,
                "double3": 24,
            },
            "global_metadata": ["B", "Rhop0", "Gamma", "CaseNp", "CaseNfixed", "CaseNmoving", "CaseNfloat", "CaseNfluid"],
            "per_part_metadata": ["Cpart", "TimeStep", "Npok", "Nout", "Step", "RunTime", "DomainMin", "DomainMax"],
            "solver_writer_arrays": {
                "identity": "Idp:uint32; official JSph output path checks Idp as TypeUint",
                "position": "exactly one of Pos:float32[3] and Posd:float64[3]; effective output depends on SavePosDouble/extra-data path, so bind to exact solver command and XML array declaration rather than assuming a variant",
                "velocity": "Vel:float32[3]",
                "density": "Rhop:float32",
                "extensions": "JSph writes any additional JDataArrays as named BI4 arrays; preserve and hash all as opaque arrays unless a separately reviewed decoder contract consumes them",
            },
            "decoded_namespace": {
                "xml": "<decode-base>.xml; metadata-only array declarations are written because bi4_dump calls SaveFileXml(..., false)",
                "arrays": "one <item>/<array-name>.bin file per recursively declared array",
                "array_bytes": "count multiplied by JBinaryDataDef::SizeOfType(type); native bytes, no per-array header",
                "strictness": "Require a fresh absent decode namespace before launch. Afterward exact recursive XML-to-file closure, hashes, regular files, O_NOFOLLOW reads, st_nlink==1, exact byte sizes, and no extra/stale files; bi4_dump itself does not clean output or check stream write errors.",
            },
        },
        "future_per_case_acceptance_contract": {
            "one_raw_bi4_to_one_decoder_invocation_and_namespace": True,
            "required_arrays": ["Idp", "Vel", "Rhop", "exactly_one_of(Pos, Posd)"],
            "id_contract": "Idp is uint32 and its sorted unique set must exactly match the frozen generated cohort; reject Idpd for this R008 JSph path.",
            "position_contract": "XML type, file length, exact solver argv/effective SavePosDouble configuration, and declared shape must agree.",
            "frame_contract": "TimeStep comes from the selected PART item and must be finite, unique, monotonic, and tied one-to-one to the raw BI4 manifest; Npok/Nout and complete identity/integrity gates are checked per case.",
            "extension_contract": "Every XML-declared array, including opaque extras, is included in the exact manifest. Unknown or unsupported types fail closed; extras are never silently dropped.",
            "not_yet_evidenced": [
                "No F8 R008 solver output frame exists in this audit, so the solver's complete emitted-array set and real output cadence are not observed here.",
                "The old Q1 and R008 decode receipts record the executable path/command but not the decoder binary SHA-256 at invocation.",
                "No repository compile command or build record ties the ignored bi4_dump binary to the inspected .cpp/.h sources; current binary build provenance is unverified.",
            ],
        },
        "historical_build_linkage": {
            "binary_sha256": evidence["decoder_binary"]["sha256"],
            "elf_build_id_sha1": "849e881d39081e58f81acfef8faa3951612fe226",
            "binary_is_git_tracked": False,
            "recorded_compile_command_found": False,
            "binary_built_from_pinned_cpp_and_header_proven": False,
            "q1_receipt_pins_decoder_cpp_and_external_jbinarydata_cpp": True,
            "q1_receipt_pins_decoder_binary_or_jbinarydata_header": False,
            "r008_preflight_pins_decoder_binary_at_invocation": False,
            "future_policy": "Pin executable SHA-256, ELF/build identity, argv, host byte order, and pre/post file identity in every new decode receipt. Historical decoded artifacts remain format anchors only unless a separate receipt binds their exact decoder binary.",
        },
        "execution_controls_for_this_audit": {
            "bi4_dump_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "readiness_effect": {
            "per_case_provenance_verifier_implemented": False,
            "formal_15_case_t1_results_exist": False,
            "readiness_pass": False,
            "qualification_credit": 0,
            "solver_execution_authorized": False,
        },
    }


def verify_receipt(receipt: dict[str, Any]) -> bool:
    if receipt.get("schema") != SCHEMA:
        return False
    if receipt.get("status") != "format_contract_bounded_historical_binary_build_linkage_unverified":
        return False
    if receipt.get("historical_build_linkage", {}).get("binary_built_from_pinned_cpp_and_header_proven") is not False:
        return False
    if receipt.get("readiness_effect", {}).get("readiness_pass") is not False:
        return False
    if receipt.get("execution_controls_for_this_audit", {}).get("bi4_dump_invoked") is not False:
        return False
    try:
        rebuilt = build_receipt()
    except (OSError, ValueError):
        return False
    return (
        receipt.get("evidence") == rebuilt.get("evidence")
        and receipt.get("observed_initial_decode") == rebuilt.get("observed_initial_decode")
        and receipt.get("historical_build_linkage") == rebuilt.get("historical_build_linkage")
    )


def write_immutable_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_receipt()
    # Exclusive creation preserves prior evidence instead of replacing it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable static audit receipt")
    args = parser.parse_args(argv)
    if args.write:
        receipt = write_immutable_receipt()
        print(json.dumps({"status": receipt["status"], "output": str(OUTPUT)}))
    else:
        receipt = build_receipt()
        print(json.dumps({"status": receipt["status"], "evidence_count": len(receipt["evidence"])}))
    return 0 if verify_receipt(receipt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
