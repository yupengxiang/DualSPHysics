#!/usr/bin/env python3
"""Write one fresh F5 Definition and scaled piston motion file.

This is an input materialization step after the F5 root review.  It copies
only pinned official source assets, writes a new literal XML/motion identity,
and records hashes.  It intentionally has no GenCase, decoder, solver, GPU,
queue, ledger, registry, or qualification entrypoint.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OFFICIAL = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup"
PROPOSAL = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f5-wave-runup-root-review-v1.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1"
CONTRACT = OUTPUT / "fresh-definition-contract-v1.json"

Q = 0.5
SCALE = 0.8 + 0.4 * Q
DP = 0.0075
TMAX = 16.0
TOUT = 0.02
GAUGE_CADENCE = 0.02
MOTION_SOURCE = "Mov_piston.dat"
MOTION_OUTPUT = "Mov_piston_q0p50_scaled.dat"
DEFINITION_OUTPUT = "F5_wave_runup_q0p50_dp0p0075_Def.xml"
COPIED_PROVENANCE = (
    "Slope.stl",
    "Blocks_3D_scaled.stl",
    "wg1234.txt",
    "EXP_CaseWaveRunup_CIEMito.txt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _node(parent: ET.Element, old: str, new: str) -> ET.Element:
    node = parent.find(old)
    if node is None:
        node = parent.find(new)
    if node is None:
        node = ET.SubElement(parent, new)
    else:
        node.tag = new
    return node


def write_motion(source: Path, target: Path, scale: float) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    previous = None
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 2:
            raise ValueError(f"motion row {line_number} has fewer than two fields")
        time_s, displacement = float(fields[0]), float(fields[1])
        if previous is not None and time_s < previous:
            raise ValueError(f"motion time decreases at row {line_number}")
        previous = time_s
        rows.append((time_s, displacement * scale))
    if not rows or rows[0][0] != 0.0 or rows[-1][0] < 15.0:
        raise ValueError("official piston motion does not cover the registered source window")
    target.write_text("".join(f"{time_s:.10f} {displacement:.10f}\n" for time_s, displacement in rows), encoding="utf-8")
    return {
        "source": bind(source, "official piston source"),
        "output": bind(target, "fresh scaled piston motion"),
        "row_count": len(rows),
        "time_start_s": rows[0][0],
        "time_end_s": rows[-1][0],
        "scale": scale,
    }


def write_definition(source: Path, target: Path, motion_name: str) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("official definition lacks geometry/definition")
    definition.set("dp", f"{DP:.9g}")
    motion_file = root.find("./casedef/motion/objreal/mvpredef/file")
    if motion_file is None:
        raise ValueError("official definition lacks piston motion file")
    motion_file.set("name", motion_name)
    parameters = {node.get("key"): node for node in root.findall("./execution/parameters/parameter")}
    parameters["TimeMax"].set("value", f"{TMAX:.9g}")
    parameters["TimeOut"].set("value", f"{TOUT:.9g}")
    gauges = root.find("./execution/special/gauges")
    if gauges is None:
        raise ValueError("official definition lacks gauges")
    default = gauges.find("default")
    if default is None:
        raise ValueError("official definition lacks gauges/default")
    for old, new in (("_computedt", "computedt"), ("_computetime", "computetime"),
                     ("_outputdt", "outputdt"), ("_outputtime", "outputtime")):
        _node(default, old, new)
    default.find("computedt").set("value", f"{GAUGE_CADENCE:.9g}")
    default.find("computetime").set("start", "0")
    default.find("computetime").set("end", f"{TMAX:.9g}")
    default.find("outputdt").set("value", f"{TOUT:.9g}")
    default.find("outputtime").set("start", "0")
    default.find("outputtime").set("end", f"{TMAX:.9g}")
    existing = {node.get("name") for node in gauges.findall("swl")}
    for name, x in (("WG1", 3.10), ("WG2", 3.20), ("WG3", 3.34), ("WG4", 3.63)):
        if name in existing:
            raise ValueError(f"duplicate external gauge {name}")
        node = ET.SubElement(gauges, "swl", {"name": name})
        ET.SubElement(node, "masslimit", {"coef": "0.4"})
        ET.SubElement(node, "pointdp", {"coefdp": "0.5"})
        ET.SubElement(node, "point0", {"x": f"{x:.9g}", "y": "0.18", "z": "0"})
        ET.SubElement(node, "point2", {"x": f"{x:.9g}", "y": "0.18", "z": "0.6"})
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source": bind(source, "official WaveRunup Definition"),
        "output": bind(target, "fresh Core F5 Definition"),
        "dp_m": DP,
        "time_max_s": TMAX,
        "output_interval_s": TOUT,
        "gauge_interval_s": GAUGE_CADENCE,
        "external_gauges": ["WG1", "WG2", "WG3", "WG4"],
        "motion_file": motion_name,
    }


def build() -> dict[str, Any]:
    proposal = load(PROPOSAL)
    review = load(ROOT_REVIEW)
    assert proposal["schema"] == "core.f5.third_t1.proposal_audit.v1"
    assert proposal["status"] == "proposal_only_root_review_required"
    assert review["schema"] == "core.f5.third_t1.root_review_receipt.v1"
    assert review["review_decision"]["authorized_action"] == "write_one_fresh_definition_and_scaled_motion_file"
    assert review["review_decision"]["authorized_solver"] is False
    if OUTPUT.exists():
        raise FileExistsError(f"fresh F5 output already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    source_definition = OFFICIAL / "CaseWaveRunup_Def.xml"
    source_motion = OFFICIAL / MOTION_SOURCE
    motion = write_motion(source_motion, OUTPUT / MOTION_OUTPUT, SCALE)
    definition = write_definition(source_definition, OUTPUT / DEFINITION_OUTPUT, MOTION_OUTPUT)
    copied = []
    provenance = OUTPUT / "provenance"
    provenance.mkdir()
    for name in COPIED_PROVENANCE:
        target = provenance / name
        shutil.copy2(OFFICIAL / name, target)
        copied.append(bind(target, "copied official F5 provenance asset"))
    result = {
        "schema": "core.f5.third_t1.definition_materialization.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "definition_written_preflight_pending",
        "qualification_claim": "none",
        "candidate": {"family": "F5", "scope_id": "F5_prescribed_wave_runup_x_v1", "q": Q,
                      "piston_scale": SCALE, "dp_m": DP},
        "authorization": {
            "root_review": bind(ROOT_REVIEW, "F5 root review authorization"),
            "authorized_action": "write_one_fresh_definition_and_scaled_motion_file",
            "gencase_authorized": False,
            "native_decode_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "fresh_identity": {
            "definition": definition,
            "motion": motion,
            "copied_provenance": copied,
            "output_directory": rel(OUTPUT),
            "old_generated_reused": False,
            "old_trajectory_reused": False,
        },
        "fixed_contract": {
            "denominator_rows": 15,
            "time_max_s": TMAX,
            "output_interval_s": TOUT,
            "gauge_interval_s": GAUGE_CADENCE,
            "event_window_required": True,
            "zero_credit_until_cpu_native_and_solver_reviews": True,
        },
        "implementation": bind(Path(__file__), "F5 Definition writer"),
        "execution_controls": {
            "definition_written": True,
            "motion_written": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "matrix_materialized": False,
            "matrix_submitted": False,
            "qualification_credit": 0,
        },
    }
    CONTRACT.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        data = load(CONTRACT)
        print(json.dumps({"status": data["status"], "contract": rel(CONTRACT), "sha256": sha256(CONTRACT)}, indent=2))
        return 0
    result = build()
    print(json.dumps({"status": result["status"], "output": rel(OUTPUT), "contract_sha256": sha256(CONTRACT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
