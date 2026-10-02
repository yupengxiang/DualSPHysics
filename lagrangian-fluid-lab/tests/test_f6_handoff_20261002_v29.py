from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v29.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v29_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v29_has_two_root_only_requests_from_passing_preflight():
    manifest = json.loads((MODULE.REQUEST_ROOT / "request_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "root_dispatch_pending"
    assert manifest["gpu_launch"] is False
    assert len(manifest["requests"]) == 2
    for record in manifest["requests"]:
        request = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
        assert request["kind"] == "qualification"
        assert request["root_review_required"] is True
        assert request["gpu_launch"] == "root_only"
        assert request["window_s"] == [0.0, 12.0]
        assert request["output_interval_s"] == 0.05
        assert request["command"][0].endswith("DualSPHysics5.4_linux64")
        assert request["command"][1] == request["actual_gencase_prefix"]
        assert request["cwd"] == str(Path(request["actual_gencase_prefix"]).parent.resolve())
        assert request["command"][2] == "{attempt_root}/solver_output"
        assert request["gencase_actual_particles"]["fluid"] == 327680
        assert request["gencase_actual_particles"]["total"] > request["gencase_actual_particles"]["fluid"]
        receipt = Path(request["gencase_receipt"])
        assert _sha256(receipt) == request["gencase_receipt_sha256"]
        assert request["estimated_storage_bytes"] == 10 * 1024**3
        assert request["estimated_peak_gpu_mib"] == 8192


def test_v29_binds_control_native_normal_and_generated_bytes():
    manifest = json.loads((MODULE.REQUEST_ROOT / "request_manifest.json").read_text(encoding="utf-8"))
    mother = json.loads((MODULE.FAMILY_ROOT / "manifest.json").read_text(encoding="utf-8"))
    cases = {row["case_id"]: row for row in mother["cases"]}
    for record in manifest["requests"]:
        request = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
        contract = request["source_contract"]
        case = cases[request["case_id"]]
        source_paths = {
            "definition_sha256": Path(case["definition"]["path"]),
            "control_sha256": Path(case["control"]["path"]),
            "native_sha256": Path(case["native"]["path"]),
            "normal_sha256": Path(case["normal"]["path"]),
        }
        for key, path in source_paths.items():
            assert path.is_file()
            assert str(path.resolve()) in request["input_files"]
            assert contract[key] == _sha256(path)
        prefix = Path(request["actual_gencase_prefix"])
        generated_paths = {
            "generated_xml_sha256": prefix.with_suffix(".xml"),
            "generated_bi4_sha256": prefix.with_suffix(".bi4"),
            "generated_all_vtk_sha256": prefix.with_name(prefix.name + "_All.vtk"),
            "generated_fluid_vtk_sha256": prefix.with_name(prefix.name + "_Fluid.vtk"),
            "generated_bound_vtk_sha256": prefix.with_name(prefix.name + "_Bound.vtk"),
        }
        for key, path in generated_paths.items():
            assert path.is_file()
            assert contract[key] == _sha256(path)
            assert str(path.resolve()) in request["input_files"]
        for path_string, digest in contract["source_input_hashes"].items():
            path = Path(path_string)
            assert path.is_file()
            assert _sha256(path) == digest
        assert request["postprocessing_plan"]["native_torque_semantics"].startswith("FloatingInfo")
