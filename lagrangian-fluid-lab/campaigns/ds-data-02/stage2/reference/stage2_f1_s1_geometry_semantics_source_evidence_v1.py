#!/usr/bin/env python3
"""Record the official GenCase documentation boundary for F1-S1 semantics.

This forward sidecar consumes the immutable F1-S1 geometry audit and small
official documentation files only.  It does not reread XML/VTK, BI4, or H5.
The official v5.4 changelog says that ``pointref`` fits according to reference
position and Dp, while the XML template lists ``setshapemode`` tokens.  Neither
document specifies this case's boundary tie-breaking or cell crop rule, so
the actual generated `.01`/`.009` VTK observations remain the narrow evidence
for this source, and generic parser semantics stay UNKNOWN.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s1-geometry-semantics-source-evidence.v1"
REPO = Path(__file__).resolve().parents[5]
AUDIT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_audit_v2.json")
CHANGELOG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/CHANGES.txt")
TEMPLATE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml")
HELP = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/doc/help/GenCase_Help.out")
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_source_evidence_v1.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if not isinstance(audit, dict) or audit.get("schema") != "ds02.stage2.f1-s1-geometry-semantics-audit.v2":
        raise ValueError("geometry semantics input is not the immutable v2 audit")
    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    template_text = TEMPLATE.read_text(encoding="utf-8")
    help_text = HELP.read_text(encoding="utf-8")
    pointref_phrase = "New optional item <pointref> in <definition> to fit according to reference position and Dp value."
    shape_tokens = "<setshapemode>actual | dp | all</setshapemode>"
    bound_token = "<setshapemode>bound</setshapemode>"
    required = {
        "pointref_fit_changelog": pointref_phrase in changelog_text,
        "setshapemode_public_token_list": shape_tokens in template_text,
        "setshapemode_bound_token": bound_token in template_text,
        # The v5.4 help documents ``-save:<values>`` and lists ``vtkfluid``
        # as one of the values; it does not spell the combined form
        # ``-save:vtkfluid``.  Require the actual published tokens instead of
        # manufacturing a stronger CLI claim.
        "gencase_help_available": (
            "-dp:<float>" in help_text
            and "-save:<values>" in help_text
            and "+/-vtkfluid" in help_text
            and "-threads:<int>" in help_text
        ),
    }
    if not all(required.values()):
        raise ValueError(f"official documentation evidence is incomplete: {required}")
    # Keep the evidence bounded and reviewable.  The full documents are bound
    # by SHA; only the exact changelog sentence and token list are copied.
    report = {
        "schema": SCHEMA,
        "status": "PASS_OFFICIAL_INTERFACE_EVIDENCE_GENERIC_CROP_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_audit": binding(AUDIT),
        "official_sources": {
            "changelog": binding(CHANGELOG),
            "template": binding(TEMPLATE),
            "help": binding(HELP),
        },
        "exact_documented_evidence": {
            "pointref": {
                "source": "official CHANGES.txt line 263 (v5.4 package)",
                "text": pointref_phrase,
                "meaning": "reference-position/Dp fitting is documented; exact inclusion/crop boundaries are not specified",
            },
            "setshapemode": {
                "source": "official GenCase_CaseTemplate.xml",
                "token_examples": [shape_tokens, bound_token],
                "meaning": "public command tokens are documented; token combination and particle boundary ownership are not defined here",
            },
            "gencase_cli": {
                "source": "official GenCase_Help.out",
                "supported_controls_seen": ["-dp:<float>", "-save:<values> +/-vtkfluid", "-threads:<int>"],
                "meaning": "bounded VTK output can be requested; CLI help does not specify continuous volume semantics",
            },
        },
        "semantic_boundary": {
            "generic_setshapemode_parser": "UNKNOWN_NO_SOURCE_IMPLEMENTATION",
            "drawbox_endpoint_ownership": "UNKNOWN_FROM_PUBLIC_DOCS",
            "cell_centre_crop_rule": "UNKNOWN_GENERIC_BUT_OBSERVED_PER_RUN_IN_AUDIT_V2",
            "physical_continuum_authority": "CURRENT336 owner/physical-binding recorded in audit v2",
            "do_not_infer": [
                "Do not use XML drawbox primitive 36.036 kg as the sole continuous target when owner contract says 40.2 kg.",
                "Do not use a particle count or count*dp^3 as a continuous truth for a new grid without the same owner geometry contract.",
                "Do not claim generic boundary semantics from the `.01` observation alone.",
            ],
        },
        "audit_v2_observed_conclusions": {
            "dp0p010": "owner contract and observed half-cell envelope agree within float-output tolerance",
            "dp0p009": "sample mass is within 1 percent but observed envelope does not equal owner contract",
            "three_grid_qualification": "UNKNOWN until a third grid uses a validated owner-contract-compatible boundary rule",
        },
        "scope": {"bi4_read": False, "hdf5_read": False, "solver_launch": False, "gencase_launch": False},
    }
    atomic_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build(args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve()),
                      "bi4_read": False, "hdf5_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
