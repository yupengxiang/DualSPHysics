#!/usr/bin/env python3
"""Root-run CPU preparation entrypoint for 24 F3 first48 pitch/AY variants.

The reviewed preparation/transformer source is invoked once. The existing
transformer uses ``amplitude_x`` for the longitudinal pitch multiplier and
``amplitude_y`` for transverse linear acceleration; this entrypoint binds
those controls explicitly and never infers CSV column meaning. It never
invokes GenCase, DualSPHysics, a converter, ParaView, a GPU job, or an array
reader. Future forcing and condition hashes are bound only from actual
prepared-input reports emitted by the frozen preparation script.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPECTED_PITCHES = (0.8, 1.2)
EXPECTED_AYS = (0.25, 0.29, 0.32, 0.36, 0.39, 0.43, 0.46, 0.50, 0.54, 0.57, 0.64, 0.75)
EXPECTED_PAIRS = tuple((pitch, ay) for pitch in EXPECTED_PITCHES for ay in EXPECTED_AYS)
HEX = set("0123456789abcdef")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value.lower()) - HEX:
        raise RuntimeError(f"{label} is not an actual SHA-256")
    return value


def validate_binding(binding: dict[str, Any]) -> list[dict[str, Any]]:
    required = (
        "baseline_prefix", "baseline_native_receipt", "baseline_typed_receipt",
        "baseline_gencase_receipt", "baseline_xml_sha256", "baseline_bi4_sha256",
        "baseline_initial_reference", "baseline_physical_binding", "forcing_transformer",
        "nominal_source_forcing", "nominal_source_forcing_sha256", "preparation_script",
        "candidates",
    )
    missing = [key for key in required if key not in binding]
    if missing:
        raise RuntimeError(f"binding missing keys: {missing}")
    candidates = list(binding["candidates"])
    pairs = tuple(
        (float(row["nominal_pitch_multiplier"]), float(row["transverse_amplitude_m_s2"]))
        for row in candidates
    )
    if pairs != EXPECTED_PAIRS:
        raise RuntimeError(f"pitch/AY set changed: {pairs}")
    if len({row["case_id"] for row in candidates}) != len(candidates):
        raise RuntimeError("new case IDs are not unique")
    if len({row["physical_case_id"] for row in candidates}) != len(candidates):
        raise RuntimeError("new physical IDs are not unique")
    for key in ("baseline_native_receipt", "baseline_typed_receipt", "baseline_gencase_receipt"):
        receipt = load(Path(binding[key]))
        if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
            raise RuntimeError(f"{key} is not completed/0")
    for key in ("baseline_xml_sha256", "baseline_bi4_sha256", "nominal_source_forcing_sha256"):
        require_hash(binding[key], key)
    # ``baseline_prefix`` is the common stem for the XML/BI4 pair, not a
    # filesystem entry in the GenCase output directory.  Check the concrete
    # files so the source-only request is executable when Root runs it.
    baseline_prefix = Path(binding["baseline_prefix"])
    for suffix in (".xml", ".bi4"):
        concrete = baseline_prefix.with_suffix(suffix)
        if not concrete.is_file():
            raise RuntimeError(f"missing baseline preparation input: {concrete}")
    for key in ("forcing_transformer", "preparation_script"):
        if not Path(binding[key]).is_file():
            raise RuntimeError(f"missing preparation input: {binding[key]}")
    # Only bounded initial-QA metadata is inspected here; no binary/array body.
    qa_path = Path(binding["baseline_initial_reference"].get("initial_typed_qa", ""))
    if qa_path.is_file() and load(qa_path).get("passed") is False:
        raise RuntimeError("baseline initial QA is not passed")
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    binding_path = args.binding.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"refusing to reuse output directory: {output_dir}")
    binding = load(binding_path)
    candidates = validate_binding(binding)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(Path(binding["preparation_script"]).resolve()),
        "--binding", str(binding_path), "--output-dir", str(output_dir),
    ]
    # This is the sole child process and is the already-reviewed source-prep code.
    subprocess.run(command, check=True)
    prepared_index = output_dir / "prepared-cases.json"
    if not prepared_index.is_file():
        raise RuntimeError("frozen preparation did not emit prepared-cases.json")
    cases = list(load(prepared_index).get("cases", []))
    if len(cases) != len(candidates):
        raise RuntimeError(f"prepared case count {len(cases)} != {len(candidates)}")
    expected = {row["case_id"]: row for row in candidates}
    entries = []
    for case in cases:
        case_id = case.get("case_id")
        if case_id not in expected:
            raise RuntimeError(f"unexpected prepared case: {case_id}")
        candidate = expected.pop(case_id)
        if float(case["nominal_pitch_multiplier"]) != float(candidate["nominal_pitch_multiplier"]):
            raise RuntimeError(f"pitch multiplier mismatch for {case_id}")
        if float(case["transverse_amplitude_m_s2"]) != float(candidate["transverse_amplitude_m_s2"]):
            raise RuntimeError(f"transverse amplitude mismatch for {case_id}")
        require_hash(case.get("physical_condition_sha256"), f"{case_id}.physical_condition_sha256")
        require_hash(case.get("forcing_sha256"), f"{case_id}.forcing_sha256")
        if case.get("xml_sha256") != binding["baseline_xml_sha256"] or case.get("bi4_sha256") != binding["baseline_bi4_sha256"]:
            raise RuntimeError(f"initial XML/BI4 clone hash changed for {case_id}")
        report = Path(case["prepared_prefix"]).parent / "prepared-input-report.json"
        entries.append({
            "case_id": case_id,
            "role": candidate["role"],
            "nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"],
            "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"],
            "prepared_input_report": {"path": str(report), "sha256": sha256(report)},
            "forcing": {"path": case["forcing_path"], "sha256": case["forcing_sha256"]},
            "prepared_prefix": case["prepared_prefix"],
            "generated_xml": {"path": case["prepared_prefix"] + ".xml", "sha256": case["xml_sha256"]},
            "initial_bi4": {"path": case["prepared_prefix"] + ".bi4", "sha256": case["bi4_sha256"]},
            "physical_condition_sha256": case["physical_condition_sha256"],
            "status": "prepared_actual_hashes_pending_root_visual_authorizer",
            "launch_allowed": False,
        })
    if expected:
        raise RuntimeError(f"missing prepared cases: {sorted(expected)}")
    write_json(output_dir / "fresh065-prepared-index.json", {
        "schema": "ds02.stage1.f3.fresh065-prepared-index.v1",
        "status": "actual_cpu_preparation_completed_source_only",
        "source_binding": {"path": str(binding_path), "sha256": sha256(binding_path)},
        "prepared_cases": sorted(entries, key=lambda row: row["case_id"]),
        "production_approval": "none",
        "launch_allowed": False,
        "q_n": "not_granted",
        "numerical_precision_status": "not_accepted",
        "next_gate": "Root must bind this index into the 24 disabled visual-authorizer requests; the four .8/.1.2 x AY=.25/.75 corners require complete qualification before any pitch-domain registration.",
    })
    print(json.dumps({"prepared_new_cases": len(entries), "launch_allowed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
