from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from scripts import f2_static_full_cup_matrix_prepare as matrix


LAB = Path(__file__).resolve().parents[1]
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
REGISTRY = LAB / "campaigns/core-v1/registry.json"
ANCHOR_SCRIPTS = (
    LAB / "scripts/f2_resting_fill_side_wet_v3.py",
    LAB / "scripts/core_f2_resting_fill.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_backend(card: dict, fail_indices: set[int] | None = None):
    fail_indices = set(fail_indices or ())
    cells = {int(cell["index"]): cell for cell in card["qualification_design"]["cells"]}
    by_bi4: dict[Path, tuple[dict, dict]] = {}
    calls: list[tuple[str, int]] = []

    def fake_gencase(gencase, definition, prefix, log_path, cwd, lab):
        case_id = prefix.name
        cell = next(cell for cell in cells.values() if cell["case_id"] == case_id)
        index = int(cell["index"])
        calls.append(("gencase", index))
        if index in fail_indices:
            raise RuntimeError(f"synthetic GenCase failure for cell {index}")
        sampling = matrix._sampling_for_cell(cell, card)
        expected = int(sampling["particle_count"])
        root = ET.Element("case")
        execution = ET.SubElement(root, "execution")
        parameters = ET.SubElement(execution, "parameters")
        domain = ET.SubElement(parameters, "simulationdomain")
        ET.SubElement(domain, "posmin", {"x": "-0.7", "y": "-0.65", "z": "-0.4"})
        ET.SubElement(domain, "posmax", {"x": "2.2", "y": "0.8", "z": "1.8"})
        particles = ET.SubElement(root, "particles")
        ET.SubElement(particles, "moving", {"mkbound": "0", "begin": "0", "count": "2"})
        ET.SubElement(particles, "fluid", {"mkfluid": "0", "begin": "2", "count": str(expected)})
        prefix.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(prefix.with_suffix(".xml"), encoding="utf-8", xml_declaration=True)
        prefix.with_suffix(".bi4").write_bytes(b"synthetic-bi4")
        log_path.write_text("synthetic GenCase; solver and GPU were not called\n")
        by_bi4[prefix.with_suffix(".bi4").resolve()] = (cell, sampling)

    def fake_decode(bi4, decode_dir, decoder):
        bi4 = Path(bi4).resolve()
        cell, sampling = by_bi4[bi4]
        calls.append(("decode", int(cell["index"])))
        count = int(sampling["particle_count"])
        ids = np.arange(count + 2, dtype=np.uint32)
        boundary = np.asarray([[0.0, -0.15, 0.65], [0.425, -0.15, 0.65]], dtype=float)
        fluid = np.tile(np.asarray([[0.005, -0.145, 0.655]], dtype=float), (count, 1))
        positions = np.vstack((boundary, fluid))
        velocities = np.zeros_like(positions, dtype=np.float32)
        density = np.full(count + 2, 1000.0, dtype=np.float32)
        decode_dir.mkdir(parents=True, exist_ok=True)
        arrays = decode_dir / "synthetic-native"
        arrays.mkdir(parents=True, exist_ok=True)
        (arrays / "Idp.bin").write_bytes(b"synthetic")
        metadata = {
            "CaseNfluid": str(count),
            "Dp": str(float(cell["dp_m"])),
            "MassFluid": str(float(sampling["continuous_mass_kg"]) / count),
        }
        return ids, positions, velocities, density, metadata, {}, arrays

    return fake_gencase, fake_decode, calls


def test_selected_cells_keep_fixed_denominator_and_raw_failure(tmp_path: Path) -> None:
    card = json.loads(CANDIDATE.read_text())
    fake_gencase, fake_decode, calls = _fake_backend(card, {1})
    before_registry = _sha256(REGISTRY)
    before_anchor = {path: _sha256(path) for path in ANCHOR_SCRIPTS}

    report = matrix.prepare_matrix(
        LAB,
        CANDIDATE,
        tmp_path / "matrix",
        [0, 1],
        run_gencase_fn=fake_gencase,
        decode_fn=fake_decode,
    )

    assert report["status"] == "partial_with_failures"
    assert report["registered_cell_count"] == 15
    assert report["selected_indices"] == [0, 1]
    assert report["prepared_cell_count"] == 1
    assert report["failed_cell_count"] == 1
    assert report["unattempted_cell_count"] == 13
    rows = report["failure_denominator"]["rows"]
    assert len(rows) == 15
    assert rows[0]["status"] == "prepared"
    assert rows[1]["status"] == "failed"
    assert rows[1]["failure"]["type"] == "RuntimeError"
    assert all(row["status"] == "unattempted" for row in rows[2:])
    assert calls == [("gencase", 0), ("decode", 0), ("gencase", 1)]

    case0 = card["qualification_design"]["cells"][0]["case_id"]
    prepared = json.loads((tmp_path / "matrix" / "cells" / f"00-{case0}" / "prepared.json").read_text())
    assert prepared["preflight_pass"] is True
    assert prepared["solver_invoked"] is False
    assert prepared["gpu_invoked"] is False
    assert prepared["registry_mutated"] is False
    roles = {item["role"] for item in prepared["hash_closure"]}
    assert any("Definition" in role for role in roles)
    assert any("motion" in role for role in roles)
    assert any("generated" in role for role in roles)
    assert any("preflight" in role for role in roles)
    assert any("native decoder" in role for role in roles)

    assert _sha256(REGISTRY) == before_registry
    assert {path: _sha256(path) for path in ANCHOR_SCRIPTS} == before_anchor


def test_temporal_rows_are_independent_inputs(tmp_path: Path) -> None:
    card = json.loads(CANDIDATE.read_text())
    fake_gencase, fake_decode, _calls = _fake_backend(card)
    report = matrix.prepare_matrix(
        LAB,
        CANDIDATE,
        tmp_path / "temporal",
        [13, 14],
        run_gencase_fn=fake_gencase,
        decode_fn=fake_decode,
    )
    assert report["status"] == "partial_prepared"
    assert [row["status"] for row in report["failure_denominator"]["rows"]][13:] == ["prepared", "prepared"]
    rows = report["cells"]
    assert rows[0]["q"] == rows[1]["q"] == 0.5
    assert rows[0]["dp_m"] == rows[1]["dp_m"] == 0.0075
    assert rows[0]["preflight_pass"] is True and rows[1]["preflight_pass"] is True
    cell13 = Path(rows[0]["prepared"])
    cell14 = Path(rows[1]["prepared"])
    prep13 = json.loads(cell13.read_text())
    prep14 = json.loads(cell14.read_text())
    assert prep13["output_interval_s"] == 0.02
    assert prep14["output_interval_s"] == 0.01
    assert _sha256(cell13.parent / f"{prep13['case_id']}_Def.xml") != _sha256(cell14.parent / f"{prep14['case_id']}_Def.xml")
    assert _sha256(cell13.parent / (prep13["case_id"] + "_motion.dat")) != _sha256(cell14.parent / (prep14["case_id"] + "_motion.dat"))
    assert prep13["hash_closure_pass"] is True and prep14["hash_closure_pass"] is True


def test_prepare_requires_explicit_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit --cell-index"):
        matrix.prepare_matrix(LAB, CANDIDATE, tmp_path / "empty", [])
