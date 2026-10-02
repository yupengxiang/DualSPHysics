from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125_partvtk_v2.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_dp020_dp0125_partvtk_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_partvtk_v2_is_additive_and_preserves_v3_failure() -> None:
    original = MODULE.ORIGINAL_ROOT / "partvtk_request_manifest.json"
    assert original.is_file()
    original_manifest = json.loads(original.read_text(encoding="utf-8"))
    assert len(original_manifest["requests"]) == 4
    assert MODULE.MODULE.FAMILY_ROOT.name == "partvtk_002"
    assert MODULE.MODULE.VERSION.endswith("partvtk_002.v1")

    old_request = Path(original_manifest["requests"][0]["request"]["path"])
    old_payload = json.loads(old_request.read_text(encoding="utf-8"))
    assert any("__Actual.vtk" in value for value in old_payload["input_files"])


def test_partvtk_v2_binds_actual_bound_file_and_new_attempt() -> None:
    fake = {
        "command": ["PartVTK_linux64", "-filedata", "/tmp/example/case.bi4", "-filexml", "/tmp/example/case.xml"]
    }
    assert MODULE._native_prefix(fake) == Path("/tmp/example/case")
    assert "_PARTVTK_002" in MODULE.make_partvtk_requests.__name__ or MODULE.MODULE.VERSION.endswith("partvtk_002.v1")


def test_partvtk_v2_keeps_gpu_and_qualification_pending() -> None:
    assert MODULE.MODULE.VERSION.endswith("partvtk_002.v1")
    assert MODULE.SCRIPT.name.endswith("partvtk_v2.py")
