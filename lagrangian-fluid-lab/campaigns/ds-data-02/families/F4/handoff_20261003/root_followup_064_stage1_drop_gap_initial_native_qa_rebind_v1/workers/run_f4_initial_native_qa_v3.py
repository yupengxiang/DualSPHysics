#!/usr/bin/env python3
"""Bind the 063 per-endpoint GenCase outputs to a fresh initial-native QA run.

The 063 strict attempt produced two successful individual GenCase commands and
the all-numeric XML/BI4 files, but its shared runner receipt is failed because
the wrapper captured stdout and therefore did not register the actual particle
count.  This worker preserves that failure and derives the counts from each
actual generated XML.  It copies the exact XML and BI4 bytes into the fresh QA
attempt, writes a per-endpoint derived-evidence receipt beside the staged
prefix, and then invokes the consumed F4 native audit script against that
prefix.

The worker never runs GenCase, decodes BI4, reads H5/particle arrays, converts,
solves, or renders.  Root may launch it only through the disabled strict QA
request after reviewing the source bindings.  In particular, it never writes
inside the completed 063 GenCase attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.f4.drop-gap-initial-native-audit-index.v3"
DERIVED_RECEIPT_SCHEMA = "ds02.f4.drop-gap-derived-gencase-evidence-receipt.v1"
FAILURE_BINDING_SCHEMA = "ds02.f4.drop-gap-original-063-failure-binding.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_exact(source: Path, destination: Path) -> None:
    """Copy an immutable source artifact without ever replacing an output."""

    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    source_hash = sha256(source)
    if sha256(destination) != source_hash:
        raise RuntimeError(f"staged artifact hash mismatch: {source} -> {destination}")


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def generated_particle_counts(xml_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Read actual particle counts from the generated all-numeric XML.

    This is intentionally XML-only.  It does not infer counts from the shared
    runner receipt or from captured stdout, and it does not open the BI4.
    """

    root = ET.parse(xml_path).getroot()
    particles = root.find("execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks execution/particles: {xml_path}")
    fixed = particles.find("fixed")
    fluids = particles.findall("fluid")
    if fixed is None or not fluids:
        raise ValueError(f"generated XML lacks fixed/fluid partition: {xml_path}")
    total = int(particles.attrib["np"])
    fixed_count = int(fixed.attrib["count"])
    fluid_blocks = [
        {
            "mkfluid": int(node.attrib["mkfluid"]),
            "mk": int(node.attrib["mk"]),
            "begin": int(node.attrib["begin"]),
            "count": int(node.attrib["count"]),
        }
        for node in fluids
    ]
    fluid_count = sum(row["count"] for row in fluid_blocks)
    if total != fixed_count + fluid_count:
        raise ValueError(
            f"generated XML particle partition does not close: total={total}, "
            f"fixed={fixed_count}, fluid={fluid_count}"
        )
    if int(particles.attrib.get("nb", fixed_count)) != fixed_count:
        raise ValueError(f"generated XML fixed count disagrees with nb: {xml_path}")

    source_regions = metadata.get("source_regions")
    expected_sources = metadata.get("expected_counts_by_source")
    if not isinstance(source_regions, dict) or not isinstance(expected_sources, dict):
        raise ValueError(f"metadata lacks source count bindings: {xml_path}")
    by_mkfluid = {row["mkfluid"]: row["count"] for row in fluid_blocks}
    source_counts: dict[str, int] = {}
    for source, region in source_regions.items():
        if not isinstance(region, dict) or "mkfluid" not in region:
            raise ValueError(f"metadata source lacks mkfluid: {source}")
        mkfluid = int(region["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"generated XML lacks mkfluid={mkfluid} for source={source}")
        source_counts[str(source)] = int(by_mkfluid[mkfluid])
        expected = int(expected_sources[source])
        if source_counts[str(source)] != expected:
            raise ValueError(
                f"generated XML source count differs from completed metadata for {source}: "
                f"observed={source_counts[str(source)]}, expected={expected}"
            )
    return {
        "source": "generated_xml_execution_particles",
        "xml_sha256": sha256(xml_path),
        "total_particles": total,
        "fixed_particles": fixed_count,
        "fluid_particles": fluid_count,
        "fluid_blocks": fluid_blocks,
        "counts_by_source": source_counts,
        "expected_counts_by_source": {str(k): int(v) for k, v in expected_sources.items()},
    }


def positive_source_separation(result: dict[str, Any]) -> dict[str, bool]:
    rows = result.get("source_rows")
    by_source = (
        {
            str(row.get("source")): row
            for row in rows
            if isinstance(row, dict) and row.get("source") is not None
        }
        if isinstance(rows, list)
        else {}
    )
    drop = by_source.get("drop", {})
    pool = by_source.get("pool", {})
    positive = (
        set(by_source) == {"drop", "pool"}
        and int(drop.get("fluid_count", 0)) > 0
        and int(pool.get("fluid_count", 0)) > 0
        and float(drop.get("native_mass_kg", 0.0)) > 0.0
        and float(pool.get("native_mass_kg", 0.0)) > 0.0
    )
    drop_bounds = drop.get("bounds_m")
    pool_bounds = pool.get("bounds_m")
    finite = (
        isinstance(drop_bounds, list)
        and len(drop_bounds) == 2
        and isinstance(pool_bounds, list)
        and len(pool_bounds) == 2
        and all(
            isinstance(point, list)
            and len(point) == 3
            and all(finite_float(component) is not None for component in point)
            for bounds in (drop_bounds, pool_bounds)
            for point in bounds
        )
    )
    separated = False
    if finite:
        drop_low, drop_high = drop_bounds
        pool_low, pool_high = pool_bounds
        separated = bool(drop_low[2] > pool_high[2] or pool_low[2] > drop_high[2])
    return {
        "positive_drop_and_pool_source_rows": positive,
        "finite_drop_and_pool_bounds": finite,
        "drop_and_pool_bounds_are_separated": separated,
        "native_uid_type_mass_and_full3d_checks_present": all(
            bool(result.get("checks", {}).get(name))
            for name in (
                "finite_unique_complete_ids",
                "complete_type_partition",
                "all_source_population_checks",
                "true_3d",
            )
        ),
    }


def validate_original_failure(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    gencase_result_path: Path,
    gencase_result: dict[str, Any],
    original_receipt_path: Path,
    original_receipt: dict[str, Any],
    generated_root: Path,
) -> None:
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("endpoint plan must keep launch_allowed=false")
    if gencase_result.get("status") != "completed":
        raise RuntimeError("063 individual GenCase result is not completed")
    if gencase_result.get("scope_id") != plan.get("scope_id"):
        raise RuntimeError("063 individual GenCase result scope differs from the source plan")
    if Path(str(gencase_result.get("source_plan", ""))).resolve() != plan_path.resolve():
        raise RuntimeError("063 individual GenCase result is not bound to the source plan")
    result_plan_hash = gencase_result.get("source_plan_sha256")
    if result_plan_hash and result_plan_hash != sha256(plan_path):
        raise RuntimeError("063 individual GenCase result source-plan hash differs")
    if int(gencase_result.get("gencase_returncode_failures", -1)) != 0:
        raise RuntimeError("063 individual GenCase result reports a nonzero endpoint")
    if int(gencase_result.get("endpoint_count", -1)) != len(plan.get("endpoints", [])):
        raise RuntimeError("063 individual GenCase result endpoint count differs from source plan")
    if original_receipt.get("status") != "failed":
        raise RuntimeError("the bound 063 shared execution receipt must remain failed")
    if original_receipt.get("returncode") != 0:
        raise RuntimeError("the bound 063 shared receipt does not describe successful individual commands")
    if original_receipt.get("error") != "GenCase actual particle count missing":
        raise RuntimeError("the bound 063 receipt is not the captured-stdout actual-count failure")
    expected_root = generated_root.resolve().parent
    if Path(str(original_receipt.get("output_root", ""))).resolve() != expected_root:
        raise RuntimeError("063 shared receipt output_root differs from the bound generated root")
    if not gencase_result_path.is_file() or not original_receipt_path.is_file():
        raise FileNotFoundError("063 GenCase evidence binding is missing")


def endpoint_command_map(gencase_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = gencase_result.get("commands")
    if not isinstance(rows, list):
        raise ValueError("GenCase result lacks commands list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("endpoint_id"):
            raise ValueError("GenCase result contains malformed endpoint command")
        endpoint_id = str(row["endpoint_id"])
        if endpoint_id in result:
            raise ValueError(f"duplicate GenCase endpoint command: {endpoint_id}")
        result[endpoint_id] = row
    return result


def derived_receipt(
    *,
    endpoint_id: str,
    endpoint: dict[str, Any],
    command: dict[str, Any],
    gencase_result_path: Path,
    original_receipt_path: Path,
    staged_xml: Path,
    staged_bi4: Path,
    actual_counts: dict[str, Any],
) -> dict[str, Any]:
    if command.get("executed") is not True or command.get("returncode") != 0:
        raise RuntimeError(f"individual GenCase command did not complete: {endpoint_id}")
    argv = command.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) for value in argv):
        raise RuntimeError(f"individual GenCase command is not a genuine argv list: {endpoint_id}")
    if Path(argv[0]).name != "GenCase_linux64":
        raise RuntimeError(f"unexpected GenCase executable for {endpoint_id}: {argv[0]}")
    return {
        "schema": DERIVED_RECEIPT_SCHEMA,
        # The consumed audit requires this exact value.  The role and the
        # original receipt fields below make clear that it is a derived
        # per-endpoint evidence receipt, not a rewrite of the shared failure.
        "status": "completed",
        "evidence_role": "derived_per_endpoint_gencase_evidence",
        "endpoint_id": endpoint_id,
        "physical_condition_sha256": endpoint["physical_condition_sha256"],
        "individual_gencase_command": argv,
        "individual_gencase_command_sha256": hashlib.sha256(
            json.dumps(argv, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "individual_gencase_executed": True,
        "individual_gencase_returncode": 0,
        "generated_xml": str(staged_xml),
        "generated_xml_sha256": sha256(staged_xml),
        "generated_bi4": str(staged_bi4),
        "generated_bi4_sha256": sha256(staged_bi4),
        "actual_particle_counts": actual_counts,
        "actual_count_source": "generated XML execution/particles; not stdout or shared receipt",
        "source_gencase_result": str(gencase_result_path),
        "source_gencase_result_sha256": sha256(gencase_result_path),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": "failed",
        "original_shared_execution_receipt_error": "GenCase actual particle count missing",
        "claim_boundary": (
            "Per-endpoint GenCase command and exact generated XML/BI4 are bound "
            "for read-only initial QA. The original 063 shared execution receipt "
            "remains failed and is not promoted to completed."
        ),
        "read_policy": {
            "generated_xml": True,
            "native_bi4": "consumed initial QA only",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        },
        "launch_allowed": False,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
    }


def run(
    plan_path: Path,
    gencase_result_path: Path,
    original_receipt_path: Path,
    generated_root: Path,
    metadata_root: Path,
    audit_script: Path,
    output_root: Path,
    python_binary: Path,
) -> int:
    plan = load_json(plan_path)
    gencase_result = load_json(gencase_result_path)
    original_receipt = load_json(original_receipt_path)
    validate_original_failure(
        plan=plan,
        plan_path=plan_path,
        gencase_result_path=gencase_result_path,
        gencase_result=gencase_result,
        original_receipt_path=original_receipt_path,
        original_receipt=original_receipt,
        generated_root=generated_root,
    )
    commands = endpoint_command_map(gencase_result)
    expected_ids = [str(endpoint["endpoint_id"]) for endpoint in plan["endpoints"]]
    if set(commands) != set(expected_ids):
        raise RuntimeError("063 command endpoint IDs do not exactly preserve the physical source endpoints")
    output_root.mkdir(parents=True, exist_ok=False)
    failure_binding = {
        "schema": FAILURE_BINDING_SCHEMA,
        "scope_id": plan["scope_id"],
        "family_id": plan["family_id"],
        "original_attempt_id": "root-stage1-f4-gap0180-0260-genuine-gencase-063",
        "gencase_result": str(gencase_result_path),
        "gencase_result_sha256": sha256(gencase_result_path),
        "gencase_result_status": gencase_result.get("status"),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": original_receipt.get("status"),
        "original_shared_execution_receipt_returncode": original_receipt.get("returncode"),
        "original_shared_execution_receipt_error": original_receipt.get("error"),
        "failure_preservation": "The 063 shared receipt remains failed; no file in that attempt is modified.",
        "actual_count_policy": "derive per endpoint from the exact generated XML only",
        "launch_allowed": False,
    }
    write_json(output_root / "original-063-failure-binding.json", failure_binding)

    endpoint_results: list[dict[str, Any]] = []
    all_pass = True
    generated_root = generated_root.resolve()
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        if Path(endpoint_id).name != endpoint_id:
            raise ValueError(f"unsafe endpoint ID: {endpoint_id}")
        command = commands[endpoint_id]
        source_xml = Path(str(command.get("generated_xml", ""))).resolve()
        source_bi4 = Path(str(command.get("generated_bi4", ""))).resolve()
        expected_prefix = generated_root / endpoint_id / endpoint_id
        if source_xml != expected_prefix.with_suffix(".xml"):
            raise RuntimeError(f"063 XML path differs from the strict output contract: {endpoint_id}")
        if source_bi4 != expected_prefix.with_suffix(".bi4"):
            raise RuntimeError(f"063 BI4 path differs from the strict output contract: {endpoint_id}")
        if command.get("physical_condition_sha256") != endpoint["physical_condition_sha256"]:
            raise RuntimeError(f"physical condition digest drift: {endpoint_id}")
        if not source_xml.is_file() or not source_bi4.is_file():
            raise FileNotFoundError(f"063 generated endpoint outputs missing: {endpoint_id}")
        metadata_path = metadata_root / f"{endpoint_id}.metadata.json"
        if not metadata_path.is_file():
            raise FileNotFoundError(metadata_path)
        metadata = load_json(metadata_path)
        if metadata.get("case_id") != endpoint_id:
            raise RuntimeError(f"metadata case ID differs from physical endpoint: {endpoint_id}")
        if metadata.get("definition_sha256") != command.get("source_definition_sha256"):
            raise RuntimeError(f"metadata/individual command source hash differs: {endpoint_id}")
        actual_counts = generated_particle_counts(source_xml, metadata)

        endpoint_output = output_root / endpoint_id
        staged_prefix = endpoint_output / "derived-gencase" / endpoint_id
        staged_xml = staged_prefix.with_suffix(".xml")
        staged_bi4 = staged_prefix.with_suffix(".bi4")
        copy_exact(source_xml, staged_xml)
        copy_exact(source_bi4, staged_bi4)
        receipt_path = staged_prefix.parent / "execution-receipt.json"
        receipt = derived_receipt(
            endpoint_id=endpoint_id,
            endpoint=endpoint,
            command=command,
            gencase_result_path=gencase_result_path,
            original_receipt_path=original_receipt_path,
            staged_xml=staged_xml,
            staged_bi4=staged_bi4,
            actual_counts=actual_counts,
        )
        write_json(receipt_path, receipt)

        raw_output = endpoint_output / "native-preflight-audit.raw.json"
        final_output = endpoint_output / "native-preflight-audit.json"
        audit_command = [
            str(python_binary),
            str(audit_script),
            "audit",
            "--metadata",
            str(metadata_path),
            "--prefix",
            str(staged_prefix),
            "--output",
            str(raw_output),
        ]
        completed = subprocess.run(
            audit_command,
            cwd=str(audit_script.parents[1]),
            check=False,
            capture_output=True,
            text=True,
        )
        if not raw_output.is_file():
            raise RuntimeError(
                f"native audit did not produce its expected report for {endpoint_id}; "
                f"returncode={completed.returncode}, stderr={completed.stderr[-2000:]}"
            )
        result = load_json(raw_output)
        extra_checks = positive_source_separation(result)
        checks = result.setdefault("checks", {})
        checks.update(extra_checks)
        result["pass"] = bool(result.get("pass")) and completed.returncode == 0 and all(extra_checks.values())
        result["schema"] = "ds02.f4.drop-gap-native-preflight-audit.v3"
        result["endpoint_id"] = endpoint_id
        result["physical_condition_sha256"] = endpoint["physical_condition_sha256"]
        result["generated_xml_contract"] = {
            "path": str(staged_xml),
            "sha256": sha256(staged_xml),
            "source_path": str(source_xml),
            "source_sha256": sha256(source_xml),
            "native_bi4_path": str(staged_bi4),
            "native_bi4_sha256": sha256(staged_bi4),
            "source_native_bi4_path": str(source_bi4),
            "source_native_bi4_sha256": sha256(source_bi4),
        }
        result["actual_particle_counts_from_xml"] = actual_counts
        result["derived_gencase_execution_receipt"] = str(receipt_path)
        result["derived_gencase_execution_receipt_sha256"] = sha256(receipt_path)
        result["original_shared_execution_receipt"] = str(original_receipt_path)
        result["original_shared_execution_receipt_sha256"] = sha256(original_receipt_path)
        result["individual_gencase_command"] = command["command"]
        result["native_audit_command"] = audit_command
        result["native_audit_returncode"] = int(completed.returncode)
        result["read_policy"] = {
            "native_bi4": "delegated to consumed F4 audit only from staged exact bytes",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        }
        result["q_n_status"] = "not_assessed"
        result["precision_status"] = "not_accepted"
        result["production_approval"] = "none"
        write_json(final_output, result)
        endpoint_results.append(
            {
                "endpoint_id": endpoint_id,
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "gap_m": endpoint["gap_m"],
                "source_generated_xml": str(source_xml),
                "source_generated_xml_sha256": sha256(source_xml),
                "source_generated_bi4": str(source_bi4),
                "source_generated_bi4_sha256": sha256(source_bi4),
                "derived_generated_xml": str(staged_xml),
                "derived_generated_xml_sha256": sha256(staged_xml),
                "derived_generated_bi4": str(staged_bi4),
                "derived_generated_bi4_sha256": sha256(staged_bi4),
                "derived_gencase_execution_receipt": str(receipt_path),
                "derived_gencase_execution_receipt_sha256": sha256(receipt_path),
                "actual_particle_counts_from_xml": actual_counts,
                "individual_gencase_command": command["command"],
                "initial_qa_json": str(final_output),
                "initial_qa_json_sha256": sha256(final_output),
                "native_audit_returncode": int(completed.returncode),
                "pass": bool(result["pass"]),
                "checks": checks,
            }
        )
        all_pass = all_pass and bool(result["pass"])

    index = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "qa_scope_id": "root_followup_064_stage1_drop_gap_initial_native_qa_rebind_v1",
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "gencase_preflight_result": str(gencase_result_path),
        "gencase_preflight_result_sha256": sha256(gencase_result_path),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": original_receipt.get("status"),
        "original_shared_execution_receipt_error": original_receipt.get("error"),
        "original_063_failure_binding": str(output_root / "original-063-failure-binding.json"),
        "endpoints": endpoint_results,
        "pass": all_pass,
        "status": "initial-native-input-integrity-pass" if all_pass else "initial-native-input-integrity-fail",
        "actual_count_policy": "generated XML execution/particles only; individual command binding retained",
        "physical_endpoint_ids_preserved": expected_ids,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
        "read_policy": {
            "generated_xml": True,
            "native_bi4": "consumed audit only",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        },
        "claim_boundary": (
            "Initial input-integrity QA only. A passing index does not promote the "
            "063 shared receipt, grant numerical precision, assess q_n, or grant "
            "solver/visual/production acceptance."
        ),
    }
    write_json(output_root / "initial-native-audit-index.json", index)
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--gencase-result", required=True, type=Path)
    parser.add_argument("--original-execution-receipt", required=True, type=Path)
    parser.add_argument("--generated-root", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    parser.add_argument("--audit-script", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    return run(
        args.plan,
        args.gencase_result,
        args.original_execution_receipt,
        args.generated_root,
        args.metadata_root,
        args.audit_script,
        args.output_root,
        args.python,
    )


if __name__ == "__main__":
    raise SystemExit(main())
