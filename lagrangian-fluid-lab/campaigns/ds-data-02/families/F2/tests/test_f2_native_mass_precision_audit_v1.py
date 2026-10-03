from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
import pytest

F2_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
AUDIT_SCRIPT = F2_DIR / "f2_native_bi4_header_precision_audit_v1.py"
RUNTIME_SCRIPT = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"

HANDOFF_DIR = F2_DIR / "handoff_20261003" / "mass_precision_audit_v1"
SIDECAR_PATH = HANDOFF_DIR / "f2_native_mass_precision_provenance_sidecar_v1.json"
REPORT_MD_PATH = HANDOFF_DIR / "f2_native_mass_precision_provenance_report_v1.md"
CONFIG_PATH = HANDOFF_DIR / "configs" / "f2_native_bi4_header_precision_audit_config_v1.json"
REQUEST_PATH = HANDOFF_DIR / "requests" / "f2_native_bi4_header_precision_audit_request_v1.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit_mod = load_module(AUDIT_SCRIPT, "f2_native_bi4_header_precision_audit_v1")
runtime_mod = load_module(RUNTIME_SCRIPT, "ds_data02_runtime_v2")


def _pack_bi4_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _create_synthetic_bi4_header(
    output_path: Path,
    dp: float,
    mass_fluid: float,
    mass_bound: float,
    rhop0: float = 1000.0,
    gamma: float = 7.0,
    b: float = 840857.0,
    extra_constants: list[tuple[str, int, bytes]] | None = None,
) -> Path:
    """Create a minimal synthetic BI4 header containing only metadata constants."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        # Magic 64 bytes
        magic = audit_mod.HEADER_PREFIX + b"\x00" * (64 - len(audit_mod.HEADER_PREFIX))
        f.write(magic)

        # Build values block
        values_buf = bytearray()
        values_buf.extend(_pack_bi4_string(audit_mod.CODE_VALUES.decode("utf-8")))
        constants = [
            ("Dp", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(dp))),
            ("H", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(dp * 1.5))),
            ("B", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(b))),
            ("Rhop0", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(rhop0))),
            ("Gamma", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(gamma))),
            ("MassBound", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(mass_bound))),
            ("MassFluid", audit_mod.TYPE_DOUBLE, struct.pack("<d", float(mass_fluid))),
        ]
        if extra_constants:
            constants.extend(extra_constants)

        values_buf.extend(struct.pack("<I", len(constants)))
        for name, type_code, payload in constants:
            values_buf.extend(_pack_bi4_string(name))
            values_buf.extend(struct.pack("<i", type_code))
            values_buf.extend(payload)

        # Build item record
        item_buf = bytearray()
        item_buf.extend(_pack_bi4_string(audit_mod.CODE_ITEM.decode("utf-8")))
        item_buf.extend(_pack_bi4_string("PART_DATA"))
        item_buf.extend(struct.pack("<i", 0))  # item_hidden
        item_buf.extend(struct.pack("<i", 0))  # hide_values
        item_buf.extend(_pack_bi4_string("%.7E"))  # fmt_float
        item_buf.extend(_pack_bi4_string("%.15E"))  # fmt_double
        item_buf.extend(struct.pack("<I", 0))  # num_arrays
        item_buf.extend(struct.pack("<I", 0))  # num_items
        item_buf.extend(struct.pack("<I", len(values_buf)))  # values_bytes

        # Write item definition length
        f.write(struct.pack("<I", len(item_buf)))
        f.write(item_buf)
        f.write(values_buf)

    return output_path


def test_mass_precision_report_and_sidecar_exist():
    """Verify presence of report, sidecar, config, and request in handoff_20261003."""
    assert REPORT_MD_PATH.is_file(), f"Missing report: {REPORT_MD_PATH}"
    assert SIDECAR_PATH.is_file(), f"Missing sidecar: {SIDECAR_PATH}"
    assert CONFIG_PATH.is_file(), f"Missing config: {CONFIG_PATH}"
    assert REQUEST_PATH.is_file(), f"Missing request: {REQUEST_PATH}"


def test_mass_precision_sidecar_schema_and_policy():
    """Verify sidecar schema and strict scientific assertions."""
    with open(SIDECAR_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema"] == "ds-data-02.f2.mass-precision-provenance-sidecar.v1"
    assert data["family_id"] == "F2"

    # Check 10 pinned sources in inventory
    inv = data["source_inventory"]
    expected_sources = {
        "JPartDataBi4.h",
        "JPartDataBi4.cpp",
        "JBinaryData.h",
        "JBinaryData.cpp",
        "JSph.h",
        "JSph.cpp",
        "ds_data02_direct_convert.py",
        "f8_r008_safe_bi4_decoder_v1.py",
        "PartVTK_linux64",
        "bi4_dump",
    }
    assert set(inv.keys()) == expected_sources

    # Check actual BI4 audit targets in sidecar
    targets = data["actual_bi4_audit_targets"]
    assert len(targets) == 6
    assert "coarse_gencase_initial" in targets
    assert "coarse_solver_frame0" in targets
    assert "medium_gencase_initial" in targets
    assert "medium_solver_frame0" in targets
    assert "fine_gencase_initial" in targets
    assert "fine_solver_frame0" in targets

    # Check policy assertions
    policies = data["policy_and_scientific_assertions"]
    assert policies["bitwise_payload_invariance_is_not_physical_zero_defect"]["asserted"] is True
    assert policies["rescaling_and_normalization_forbidden"]["asserted"] is True
    assert policies["v6_labels_ledger_uses_xml_decimal_weights"]["asserted"] is True
    assert policies["native_weight_bitwise_label_mass_pass_claimable"]["claimable"] is False
    assert policies["solver_invalid_particles_classified_as_unknown_loss"]["asserted"] is True
    assert policies["timing_save_allowance_fails_preserved"]["status"] == "diagnostic_failure_preserved"
    assert policies["timing_save_allowance_fails_preserved"]["actual_simulation_save_interval_s"] > policies["timing_save_allowance_fails_preserved"]["frozen_contract_save_allowance_s"]


def test_ieee754_representation_math():
    """Verify exact float32 vs double representation discrepancies."""
    with open(SIDECAR_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    table = data["resolution_comparison_table"]

    # Coarse: dp=0.010, N=24576, m_xml=0.001
    c = table["coarse"]
    c_f32 = struct.unpack("<f", struct.pack("<f", 0.001))[0]
    assert math.isclose(c["native_float32_mass_per_particle_kg"], c_f32, rel_tol=1e-12)
    assert struct.pack("<f", c_f32).hex() == c["native_float32_hex"]
    assert math.isclose(c["xml_continuous_total_mass_kg"], 24.576, rel_tol=1e-12)

    # Medium: dp=0.008, N=48000, m_xml=0.000512
    m = table["medium"]
    m_f32 = struct.unpack("<f", struct.pack("<f", 0.000512))[0]
    assert math.isclose(m["native_float32_mass_per_particle_kg"], m_f32, rel_tol=1e-12)
    assert struct.pack("<f", m_f32).hex() == m["native_float32_hex"]

    # Fine: dp=0.005, N=196608, m_xml=0.000125
    fn = table["fine"]
    fn_f32 = struct.unpack("<f", struct.pack("<f", 0.000125))[0]
    assert math.isclose(fn["native_float32_mass_per_particle_kg"], fn_f32, rel_tol=1e-12)
    assert struct.pack("<f", fn_f32).hex() == fn["native_float32_hex"]


def test_synthetic_bi4_header_parsing_with_known_types(tmp_path: Path):
    """Test reading constants including known enum types (Char=1B, Short=2B, Int3=12B, Double3=24B)."""
    synthetic_bi4 = tmp_path / "synthetic_test.bi4"
    extras = [
        ("TestChar", 3, struct.pack("<b", 42)),             # 1 byte
        ("TestShort", 5, struct.pack("<h", 1234)),           # 2 bytes
        ("TestInt3", 20, struct.pack("<iii", 1, 2, 3)),      # 12 bytes
        ("TestFloat3", 22, struct.pack("<fff", 0.1, 0.2, 0.3)), # 12 bytes
        ("TestDouble3", 23, struct.pack("<ddd", 1.0, 2.0, 3.0)), # 24 bytes
    ]
    _create_synthetic_bi4_header(
        output_path=synthetic_bi4,
        dp=0.010,
        mass_fluid=0.001,
        mass_bound=0.001,
        extra_constants=extras,
    )

    parsed = parse_bi4_header_constants = audit_mod.parse_bi4_header_constants(synthetic_bi4)
    assert parsed["root_item_name"] == "PART_DATA"
    constants = parsed["constants"]
    assert "MassFluid" in constants
    assert constants["MassFluid"]["type_name"] == "DatDouble"
    assert math.isclose(constants["MassFluid"]["double_value"], 0.001, rel_tol=1e-12)
    assert constants["TestChar"]["int_value"] == 42
    assert constants["TestShort"]["int_value"] == 1234
    assert constants["TestInt3"]["int3_value"] == [1, 2, 3]


def test_synthetic_bi4_header_rejects_unknown_type(tmp_path: Path):
    """Test that encountering an unknown JBinaryData type immediately raises ValueError to prevent desync."""
    bad_bi4 = tmp_path / "bad_type.bi4"
    unknown_type_code = 99  # Undefined in JBinaryDataDef
    extras = [
        ("BadValue", unknown_type_code, b"\x00" * 4),
    ]
    _create_synthetic_bi4_header(
        output_path=bad_bi4,
        dp=0.010,
        mass_fluid=0.001,
        mass_bound=0.001,
        extra_constants=extras,
    )

    with pytest.raises(ValueError, match="Unknown JBinaryData type code 99"):
        audit_mod.parse_bi4_header_constants(bad_bi4)


def test_synthetic_bi4_header_precision_audit_run(tmp_path: Path):
    """Test full audit workflow using a synthetic config and fixtures in tmp_path."""
    mock_coarse_gencase = tmp_path / "mock_coarse_gencase.bi4"
    mock_coarse_solver = tmp_path / "mock_coarse_solver.bi4"
    _create_synthetic_bi4_header(mock_coarse_gencase, dp=0.010, mass_fluid=0.001, mass_bound=0.001)
    _create_synthetic_bi4_header(mock_coarse_solver, dp=0.010, mass_fluid=0.0010000000474974513, mass_bound=0.001)

    mock_config_path = tmp_path / "mock_audit_config.json"
    mock_config = {
        "schema": "ds-data-02.f2.bi4-header-precision-audit-config.v1",
        "targets": {
            "coarse_gencase_initial": {
                "target_id": "MOCK_COARSE_GENCASE",
                "target_role": "gencase_initial",
                "resolution": "COARSE",
                "dp_m": 0.010,
                "xml_decimal_mass_kg": 0.001,
                "bi4_path": str(mock_coarse_gencase),
            },
            "coarse_solver_frame0": {
                "target_id": "MOCK_COARSE_SOLVER",
                "target_role": "solver_frame0",
                "resolution": "COARSE",
                "dp_m": 0.010,
                "xml_decimal_mass_kg": 0.001,
                "bi4_path": str(mock_coarse_solver),
            },
        },
    }
    with open(mock_config_path, "w", encoding="utf-8") as f:
        json.dump(mock_config, f)

    output_dir = tmp_path / "audit_output"
    report = audit_mod.run_audit(mock_config_path, output_dir)

    assert report["schema"] == "ds-data-02.f2.bi4-header-precision-audit.v1"
    assert "coarse_gencase_initial" in report["results"]
    assert "coarse_solver_frame0" in report["results"]
    gc_res = report["results"]["coarse_gencase_initial"]
    sv_res = report["results"]["coarse_solver_frame0"]
    assert gc_res["target_role"] == "gencase_initial"
    assert sv_res["target_role"] == "solver_frame0"
    assert math.isclose(gc_res["header_mass_fluid_double"], 0.001, rel_tol=1e-12)

    report_file = output_dir / "f2_native_bi4_header_precision_audit_report.json"
    assert report_file.is_file()


def test_runner_request_validation():
    """Verify that the proposed runner request validates cleanly against ds_data02_runtime_v2."""
    with open(REQUEST_PATH, "r", encoding="utf-8") as f:
        req = json.load(f)

    # Must pass official shared strict runner request validation
    runtime_mod.validate_request(req)
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["cpu_task_kind"] == "audit"
    assert req["kind"] == "cpu"
    assert req["cpu_threads"] == 2
    assert req["max_wall_seconds"] <= 1800
    assert len(req["input_files"]) == len(req["input_sha256"])
