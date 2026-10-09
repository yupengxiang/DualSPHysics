from __future__ import annotations

import csv
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
INTAKE = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f6_root245_native_cause_intake_v2.py"
EXTRACTOR = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f6_root259_native_extract_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location("stage2_intake_v2_test", INTAKE)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def _row(module) -> list[str]:
    values = {
        "Part": "0", "TimeStep [s]": "0.0", "Steps": "0", "DTsMin": "0",
        "PartRuntime [s]": "0.0", "NpSave": "1", "NpSim": "1", "NpNew": "0",
        "NpOut": "0", "NctSim": "0", "NpAlloc [X]": "1.000307", "NctAlloc [X]": "1.0",
        "SimRuntime [s]": "0.0", "NpbSim": "0", "NpfSim": "1", "NpNormal": "1",
        "NpOutPos": "0", "NpOutRho": "0", "NpOutMov": "0", "DtMin [s]": "0.001",
        "DtMax [s]": "0.002", "MemCPU [MiB]": "1", "MemGPU [MiB]": "1",
        "MemGPU_Cells [MiB]": "1", "NpAlloc": "1", "NctAlloc": "1",
    }
    return [values[name] for name in module.RUNPARTS_COLUMNS]


def test_v2_runparts_accepts_ratio_columns_and_legal_footer(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "RunPARTs.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(module.RUNPARTS_COLUMNS)
        writer.writerow(_row(module))
        writer.writerow([])
        stream.write("# official footer\n")
    stat = module._stat(path, "fixture")
    stat["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    times, evidence = module._runparts_times(path, stat)
    assert times == [0.0]
    assert evidence["rows"] == 1
    assert evidence["footer_comment_count"] == 1
    assert evidence["blank_row_count"] >= 1


@pytest.mark.parametrize(
    "column, value",
    [("NpAlloc [X]", "not-a-ratio"), ("NpOut", "1.000307")],
)
def test_v2_runparts_rejects_malformed_nonempty_data_rows(tmp_path: Path, column: str, value: str) -> None:
    module = _module()
    path = tmp_path / "RunPARTs.csv"
    values = _row(module)
    values[list(module.RUNPARTS_COLUMNS).index(column)] = value
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(module.RUNPARTS_COLUMNS)
        writer.writerow(values)
    stat = module._stat(path, "fixture")
    stat["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(module.IntakeError):
        module._runparts_times(path, stat)


def test_root259_extractor_is_new_namespace_and_uses_v2_intake() -> None:
    result = subprocess.run([sys.executable, str(EXTRACTOR), "self-test"], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "root259-native-extract.v3" in result.stdout
    source = EXTRACTOR.read_text(encoding="utf-8")
    assert "ds_data02_stage2_f6_root245_native_cause_intake_v2.py" in source
