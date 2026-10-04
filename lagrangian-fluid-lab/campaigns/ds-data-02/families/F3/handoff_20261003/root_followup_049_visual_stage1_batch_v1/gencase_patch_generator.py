#!/usr/bin/env python3
"""Exact Native GenCase & Input Preparation Generator Patch (Followup 049).

Campaign: DS-DATA-02
Family: F3 (Two-Axis Tank Sloshing)
Authority: Root Followup 049 under F3 isolated worktree ds-data-02-f6
Lineage: Derived from root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056 (Followup 056 / 040)
Status: SOURCE-ONLY, DISABLED UNTIL ROOT VISUAL REVIEW OF ANCHOR

Governance:
- launch_allowed: False across all emitted requests.
- No execution in this worker: Root strict dispatcher alone.
- Preserves known macro fails (spatial 5% budget KE/meanV/localV) and transport differences.
- Marks numerical precision strictly 'not accepted'.
- Supports 2D physical parameterization:
    * transverse_amplitude_m_s2 (Ay in [0.25, 0.75])
    * pitch_amplitude_ratio (A_pitch in [0.90, 1.10])
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

from twoaxis_pitch_forcing_transformer import (
    DEFAULT_OMEGA_Y,
    DEFAULT_PHASE_Y,
    DEFAULT_RAMP_DURATION,
    PINNED_NOMINAL_FORCING_SHA256,
    compute_sha256,
    transform_twoaxis_forcing_file,
)


def semantic_xml(node):
    """Normalize XML element for semantic structure comparison."""
    return (
        node.tag,
        sorted((k, v) for k, v in node.attrib.items() if not k.endswith("comment")),
        (node.text or "").strip(),
        [semantic_xml(child) for child in node],
    )


def generate_gencase_request(
    case_id: str,
    transverse_amplitude_m_s2: float,
    pitch_amplitude_ratio: float,
    binding_path: Path,
    output_dir: Path,
    worktree_root: Path,
    python_bin: Path,
) -> dict:
    """Generate unlaunchable runner request for GenCase input preparation."""
    attempt_id = f"root-cell3-dp006-twoaxis-ay{str(transverse_amplitude_m_s2).replace('.', 'p')}-p{str(pitch_amplitude_ratio).replace('.', 'p')}-gencase-049"

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 1,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 1073741824,
        "cwd": str(worktree_root / "lagrangian-fluid-lab"),
        "worktree_root": str(worktree_root),
        "command": [
            str(python_bin),
            str(worktree_root / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_049_visual_stage1_batch_v1/gencase_patch_generator.py"),
            "--binding",
            str(binding_path),
            "--output-dir",
            "{attempt_root}/prepared",
        ],
        "launch_allowed": False,
        "launch_owner": "root",
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_n": "not_granted",
        "visual_review_status": "disabled until Root visual review anchor",
        "numerical_precision_status": "not accepted",
        "historical_evidence": "Preserves known macro fails (spatial coarse-vs-fine 5% budget KE/meanV/localV) and transport differences",
        "claim": "Source-only prospective batch entry; no numerical precision claim",
    }
    return request


def prepare_case_inputs(
    binding_path: Path,
    output_dir: Path,
    dry_run: bool = True,
) -> dict:
    """Prepare definition XML and transformed forcing CSV from case binding.
    
    Guarded with dry_run mode to prevent unreviewed execution outside Root dispatcher.
    """
    binding = json.loads(binding_path.read_text())
    case_id = binding["case_id"]
    ay = float(binding["transverse_amplitude_m_s2"])
    a_pitch = float(binding["pitch_amplitude_ratio"])

    original_def = Path(binding["original_definition"])
    assert original_def.exists(), f"Original definition missing: {original_def}"
    def_tree = ET.parse(original_def).getroot()

    source_forcing = Path(binding["source_forcing"])
    assert source_forcing.exists(), f"Source forcing missing: {source_forcing}"
    assert compute_sha256(source_forcing) == binding["source_forcing_sha256"]

    if dry_run:
        # In source-only mode, validate specifications without invoking external binaries
        return {
            "status": "validated_source_only",
            "case_id": case_id,
            "transverse_amplitude_m_s2": ay,
            "pitch_amplitude_ratio": a_pitch,
            "omega_y": DEFAULT_OMEGA_Y,
            "original_definition_sha256": compute_sha256(original_def),
            "source_forcing_sha256": binding["source_forcing_sha256"],
            "launch_allowed": False,
            "visual_review": "disabled until Root visual review anchor",
            "numerical_precision_status": "not accepted",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    target_def = output_dir / f"{case_id}_Def.xml"
    if not target_def.exists():
        shutil.copyfile(original_def, target_def)

    target_forcing = output_dir / "CaseSloshingAccData.csv"
    report = transform_twoaxis_forcing_file(
        source_forcing,
        target_forcing,
        amplitude_x=a_pitch,
        amplitude_y=ay,
        omega_y=DEFAULT_OMEGA_Y,
        phase_y=DEFAULT_PHASE_Y,
        tau_ramp=DEFAULT_RAMP_DURATION,
        expected_source_hash=binding["source_forcing_sha256"],
        overwrite=False,
    )

    return {
        "status": "prepared",
        "case_id": case_id,
        "definition": str(target_def),
        "definition_sha256": compute_sha256(target_def),
        "forcing": str(target_forcing),
        "forcing_sha256": report["output_sha256"],
        "forcing_transform_report": report,
        "launch_allowed": False,
        "q_n": "not_granted",
        "production_approval": "none",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="Path to case binding JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="Target directory for prepared files")
    parser.add_argument("--execute", action="store_true", help="Execute preparation (Root dispatcher only)")
    args = parser.parse_args()

    res = prepare_case_inputs(
        binding_path=args.binding,
        output_dir=args.output_dir,
        dry_run=not args.execute,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
