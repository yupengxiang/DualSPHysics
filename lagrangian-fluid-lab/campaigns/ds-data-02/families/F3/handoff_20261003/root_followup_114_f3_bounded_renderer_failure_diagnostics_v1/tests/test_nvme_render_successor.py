#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nvme_render_successor", HERE / "workers/nvme_render_successor.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def base_request(tmp: Path) -> dict:
    manifest = tmp / "case-manifest.json"
    renderer = tmp / "renderer.py"
    pvpython = tmp / "pvpython"
    manifest.write_text(json.dumps({
        "schema": "ds02.stage1.paraview-temporal-product.v1",
        "frames": 3,
        "particles": 11,
        "xdmf": str(tmp / "case.xmf"),
    }))
    (tmp / "case.xmf").write_text("toy xmf metadata")
    renderer.write_text("# future renderer")
    pvpython.write_text("# future pvpython")
    return {
        "schema": MODULE.SCHEMA,
        "family_id": "F6",
        "case_id": "F6_TOY",
        "attempt_id": "toy-attempt",
        "manifest": str(manifest),
        "renderer": str(renderer),
        "pvpython": str(pvpython),
        "home_root": str(tmp),
        "home_output": str(tmp / "Projects/DualSPHysics-data/ds-data-02/families/F6/F6_TOY/toy-attempt/render"),
        "nvme_root": str(tmp / "nvme"),
        "worktree_root": str(tmp),
        "cwd": str(tmp),
        "resource_ledger_lock": str(tmp / "resource-ledger.lock"),
        "reservation_id": None,
        "current_attempt_id": None,
        "launch_owner": "root",
        "cpu_threads": 24,
        "declared_cpu_cores": 24,
        "environment_threads": 2,
        "max_wall_seconds": 14400,
        "global_renderer_cap": 2,
        "home_free_floor_bytes": 500 * MODULE.GI,
        "home_reserved_bytes": 12 * MODULE.GI,
        "nvme_free_floor_bytes": 100 * MODULE.GI,
        "nvme_stage_cap_bytes": 24 * MODULE.GI,
        "home_publish_cap_bytes": 3 * MODULE.GI,
        "expected_frames": 3,
        "expected_particles": 11,
        "expected_contact_sheets": 1,
        "keyframe_indices": [0, 2],
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "future_input_hashes_null": True,
        "output_child": "render",
        "render_environment": {
            "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
            "NUMEXPR_NUM_THREADS": "2", "LP_NUM_THREADS": "2", "VTK_SMP_MAX_THREADS": "2",
            "LIBGL_ALWAYS_SOFTWARE": "1", "MESA_GLTHREAD": "false", "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
            "QT_QPA_PLATFORM": "offscreen", "VTK_DEFAULT_OPENGL_WINDOW": "vtkEGLRenderWindow",
            "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        },
        "renderer_argv_template": [str(pvpython), "--force-offscreen-rendering", str(renderer), "--manifest", "{manifest}", "--output-dir", "{stage_render}"],
    }


def write_ledger(root: Path, request: dict, *, other: bool = False) -> None:
    rows = [{"id": "toy-reservation", "kind": "cpu", "cpu_task_kind": "preview", "cpu_threads": 24, "cpu_core_seconds": 345600, "new_storage_bytes": 12 * MODULE.GI}]
    if other:
        rows.append({"id": "other-reservation", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "cpu_core_seconds": 100, "new_storage_bytes": 1024})
    request["reservation_id"] = "toy-reservation"
    request["current_attempt_id"] = "toy-reservation"
    (root / "resource-ledger.json").write_text(json.dumps({
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"storage_policy": "home_free_floor", "home_path": str(root), "home_min_free_bytes": 500 * MODULE.GI},
        "reservations": rows,
    }))
    (root / "resource-ledger.lock").touch()


def write_report(stage: Path) -> dict:
    report = {
        "schema": MODULE.REPORT_SCHEMA,
        "frames": 3,
        "source_frames": 3,
        "all_frames_rendered": True,
        "actual_times_preserved_exactly": True,
        "trajectory_h5": "/home/registered/F6_TOY/trajectory.h5",
        "outputs": {
            "frames_dir": str(stage / "frames"),
            "contact_sheets": [str(stage / "all_frames_000.png")],
            "gif": str(stage / "full_saved_animation.gif"),
            "pvsm": str(stage / "case.pvsm"),
        },
    }
    (stage / "paraview-full-animation-report.json").write_text(json.dumps(report))
    return report


class SuccessorTests(unittest.TestCase):
    def test_disabled_request_preflight_does_not_execute(self):
        with tempfile.TemporaryDirectory() as raw:
            request = base_request(Path(raw))
            result = MODULE.preflight_request(request)
            self.assertTrue(result["valid"])
            with self.assertRaises(MODULE.ContractError):
                MODULE.execute_request(request, authorized=True)

    def test_publish_cap_rejects_before_home_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            stage = root / "stage-render"
            (stage / "frames").mkdir(parents=True)
            (stage / "frames/frame_0000.png").write_bytes(b"0123456789")
            (stage / "all_frames_000.png").write_bytes(b"contact")
            (stage / "case.pvsm").write_text("pvsm")
            (stage / "full_saved_animation.gif").write_bytes(b"gif")
            write_report(stage)
            write_ledger(root, request)
            request["home_publish_cap_bytes"] = 5
            with self.assertRaises(MODULE.ContractError):
                MODULE._publish_files(stage, Path(request["home_output"]), request, {})
            self.assertFalse(Path(request["home_output"]).exists())

    def test_publish_copies_derived_bytes_and_rewrites_report(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            stage = root / "stage-render"
            (stage / "frames").mkdir(parents=True)
            for frame in range(3):
                (stage / "frames" / f"frame_{frame:04d}.png").write_bytes(f"frame{frame}".encode())
            (stage / "all_frames_000.png").write_bytes(b"contact")
            (stage / "case.pvsm").write_text(f"private={stage}/frames")
            (stage / "full_saved_animation.gif").write_bytes(b"gif")
            report = write_report(stage)
            out = Path(request["home_output"])
            out.parent.mkdir(parents=True)
            Path(request["resource_ledger_lock"]).write_text("")
            write_ledger(root, request, other=True)
            MODULE._rewrite_report(stage, out)
            MODULE._rewrite_pvsm(stage, out)
            usage = shutil.disk_usage(root)
            fake_usage = shutil._ntuple_diskusage(usage.total, usage.used, 600 * MODULE.GI)
            with patch.object(MODULE.shutil, "disk_usage", return_value=fake_usage):
                result = MODULE._publish_files(stage, out, request, report)
            self.assertEqual(result["status"], "completed")
            published_report = json.loads((out / "paraview-full-animation-report.json").read_text())
            self.assertTrue(str(out) in published_report["outputs"]["gif"])
            self.assertEqual((out / "frames/frame_0000.png").read_bytes(), b"frame0")
            receipt = json.loads((out / "render-publish-receipt.json").read_text())
            self.assertEqual(receipt["report_sha256_after_rebind"], MODULE._sha256(out / "paraview-full-animation-report.json"))
            self.assertNotIn(str(stage), (out / "case.pvsm").read_text())
            published_report = json.loads((out / "paraview-full-animation-report.json").read_text())
            self.assertEqual(published_report["trajectory_h5"], "/home/registered/F6_TOY/trajectory.h5")
            self.assertTrue(result["post_publish_home_floor_rechecked"])
            self.assertGreaterEqual(result["publish_fixed_point_iterations"], 1)

    def test_owned_renderer_group_is_terminated(self):
        process = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
        MODULE._terminate_owned_process(process, timeout=2)
        self.assertIsNotNone(process.poll())

    def test_enabled_binding_reads_live_ledger_and_uses_root732_argv(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            request.update({
                "disabled": False,
                "launch": True,
                "launch_allowed": True,
                "execution_allowed": True,
                "source_only": False,
                "future_input_hashes_null": False,
                "input_files": [request["manifest"], request["renderer"]],
            })
            request["input_sha256"] = {path: MODULE._sha256(Path(path)) for path in request["input_files"]}
            write_ledger(root, request)
            out = Path(request["home_output"])
            out.parent.mkdir(parents=True)
            seen = {}

            class FakeProcess:
                pid = 99999999

                def __init__(self, argv, **kwargs):
                    seen["argv"] = argv
                    output = Path(argv[argv.index("--output-dir") + 1])
                    (output / "frames").mkdir(parents=True)
                    for frame in range(3):
                        (output / "frames" / f"frame_{frame:04d}.png").write_bytes(f"f{frame}".encode())
                    (output / "all_frames_000.png").write_bytes(b"contact")
                    (output / "full_saved_animation.gif").write_bytes(b"gif")
                    (output / "case.pvsm").write_text(f"stage={output}")
                    write_report(output)
                    self.polls = 0

                def poll(self):
                    self.polls += 1
                    return None if self.polls == 1 else 0

                def wait(self, timeout=None):
                    return 0

            usage = shutil.disk_usage(root)
            fake_usage = shutil._ntuple_diskusage(usage.total, usage.used, 600 * MODULE.GI)
            with patch.object(MODULE.shutil, "disk_usage", return_value=fake_usage):
                result = MODULE.execute_request(request, authorized=True, popen=FakeProcess)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(seen["argv"][1], "--force-offscreen-rendering")
            self.assertNotIn("--diagnostic-frames", seen["argv"])
            self.assertTrue((out / "render-publish-receipt.json").exists())
            self.assertFalse(list(Path(request["nvme_root"]).iterdir()))

    def test_failed_renderer_persists_bounded_diagnostics_after_stage_cleanup(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            request.update({
                "disabled": False,
                "launch": True,
                "launch_allowed": True,
                "execution_allowed": True,
                "source_only": False,
                "future_input_hashes_null": False,
                "input_files": [request["manifest"], request["renderer"]],
            })
            request["input_sha256"] = {path: MODULE._sha256(Path(path)) for path in request["input_files"]}
            write_ledger(root, request)

            class FailingProcess:
                pid = 991234
                returncode = 17

                def __init__(self, argv, **kwargs):
                    kwargs["stdout"].write(b"stdout-line\n" + b"o" * (MODULE.MAX_DIAGNOSTIC_TAIL_BYTES + 4096))
                    kwargs["stderr"].write(b"stderr-line\n" + b"e" * (MODULE.MAX_DIAGNOSTIC_TAIL_BYTES + 4096))
                    kwargs["stdout"].flush()
                    kwargs["stderr"].flush()

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    return self.returncode

            usage = shutil.disk_usage(root)
            fake_usage = shutil._ntuple_diskusage(usage.total, usage.used, 600 * MODULE.GI)
            with patch.object(MODULE.shutil, "disk_usage", return_value=fake_usage):
                result = MODULE.execute_request(request, authorized=True, popen=FailingProcess)

            self.assertEqual(result["status"], "renderer_failed")
            self.assertEqual(result["returncode"], 17)
            self.assertEqual(result["attempt_id"], "toy-attempt")
            self.assertEqual(result["reservation_id"], "toy-reservation")
            self.assertEqual(result["renderer_returncode"], 17)
            self.assertEqual(result["termination_reason"], "renderer exited with returncode 17")
            self.assertTrue(result["stage_removed_after_rejection"])
            diagnostics = result["renderer_diagnostics"]
            self.assertEqual(diagnostics["pid"], 991234)
            self.assertIsNone(diagnostics["pgid"])
            self.assertEqual(diagnostics["returncode"], 17)
            self.assertEqual(diagnostics["reason"], "renderer exited with returncode 17")
            self.assertEqual(diagnostics["actual_argv"][1], "--force-offscreen-rendering")
            self.assertLessEqual(diagnostics["stdout_tail_bytes"], MODULE.MAX_DIAGNOSTIC_TAIL_BYTES)
            self.assertLessEqual(diagnostics["stderr_tail_bytes"], MODULE.MAX_DIAGNOSTIC_TAIL_BYTES)
            self.assertTrue(diagnostics["stdout_tail"].endswith("o" * 100))
            self.assertTrue(diagnostics["stderr_tail"].endswith("e" * 100))
            rejection_files = list((root / "nvme").glob("*.rejection.json"))
            self.assertEqual(len(rejection_files), 1)
            persisted = json.loads(rejection_files[0].read_text())
            self.assertEqual(persisted["renderer_diagnostics"], diagnostics)
            self.assertTrue(persisted["stage_removed_after_rejection"])
            self.assertFalse(Path(result["stage_root"]).exists())

    def test_generic_family_preflight_is_supported(self):
        with tempfile.TemporaryDirectory() as raw:
            request = base_request(Path(raw))
            request["family_id"] = "F5"
            request["case_id"] = "F5_TOY"
            request["physical_case_id"] = "F5_TOY"
            result = MODULE.preflight_request(request)
            self.assertTrue(result["valid"])

    def test_recursive_private_path_rejection_preserves_external_h5_reference(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            stage = root / "nvme" / "attempt" / "render"
            (stage / "frames").mkdir(parents=True)
            for frame in range(3):
                (stage / "frames" / f"frame_{frame:04d}.png").write_bytes(b"f")
            (stage / "all_frames_000.png").write_bytes(b"contact")
            (stage / "full_saved_animation.gif").write_bytes(b"gif")
            (stage / "case.pvsm").write_text(f"trajectory=/home/registered/F6_TOY/trajectory.h5\nprivate={stage.parent}/hidden")
            report = write_report(stage)
            report["private_stage_reference"] = str(stage.parent / "hidden")
            MODULE._write_json(stage / "paraview-full-animation-report.json", report)
            out = root / "Projects/DualSPHysics-data/ds-data-02/families/F6/F6_TOY/toy-attempt/render"
            with self.assertRaises(MODULE.ContractError):
                MODULE._rewrite_report(stage, out, private_roots=(stage.parent, root / "nvme"))
            report.pop("private_stage_reference")
            MODULE._write_json(stage / "paraview-full-animation-report.json", report)
            MODULE._rewrite_report(stage, out, private_roots=(stage.parent, root / "nvme"))
            with self.assertRaises(MODULE.ContractError):
                MODULE._rewrite_pvsm(stage, out, private_roots=(stage.parent, root / "nvme"))

    def test_systemexit_during_atomic_copy_cleans_own_temp(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            stage = root / "stage-render"
            (stage / "frames").mkdir(parents=True)
            for frame in range(3):
                (stage / "frames" / f"frame_{frame:04d}.png").write_bytes(b"f")
            (stage / "all_frames_000.png").write_bytes(b"contact")
            (stage / "full_saved_animation.gif").write_bytes(b"gif")
            (stage / "case.pvsm").write_text("pvsm")
            write_report(stage)
            write_ledger(root, request)
            out = Path(request["home_output"])
            out.parent.mkdir(parents=True)
            MODULE._rewrite_report(stage, out)
            MODULE._rewrite_pvsm(stage, out)
            usage = shutil.disk_usage(root)
            fake_usage = shutil._ntuple_diskusage(usage.total, usage.used, 600 * MODULE.GI)
            with patch.object(MODULE.shutil, "disk_usage", return_value=fake_usage), patch.object(MODULE.os, "replace", side_effect=SystemExit("toy stop")):
                with self.assertRaises(SystemExit):
                    MODULE._publish_files(stage, out, request, {})
            self.assertFalse(out.exists())
            self.assertEqual(list(out.parent.glob(f".{out.name}.publish-*")), [])

    def test_systemexit_after_renderer_is_bounded_rejection(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = base_request(root)
            request.update({
                "disabled": False,
                "launch": True,
                "launch_allowed": True,
                "execution_allowed": True,
                "source_only": False,
                "future_input_hashes_null": False,
                "input_files": [request["manifest"], request["renderer"]],
            })
            request["input_sha256"] = {path: MODULE._sha256(Path(path)) for path in request["input_files"]}
            write_ledger(root, request)

            class FakeProcess:
                pid = 99999998

                def __init__(self, argv, **kwargs):
                    output = Path(argv[argv.index("--output-dir") + 1])
                    (output / "frames").mkdir(parents=True)
                    for frame in range(3):
                        (output / "frames" / f"frame_{frame:04d}.png").write_bytes(b"f")
                    (output / "all_frames_000.png").write_bytes(b"contact")
                    (output / "full_saved_animation.gif").write_bytes(b"gif")
                    (output / "case.pvsm").write_text(f"stage={output}")
                    write_report(output)
                    self.polls = 0

                def poll(self):
                    self.polls += 1
                    return None if self.polls == 1 else 0

                def wait(self, timeout=None):
                    return 0

            usage = shutil.disk_usage(root)
            fake_usage = shutil._ntuple_diskusage(usage.total, usage.used, 600 * MODULE.GI)
            with patch.object(MODULE.shutil, "disk_usage", return_value=fake_usage), patch.object(MODULE, "_publish_files", side_effect=SystemExit("toy stop")):
                result = MODULE.execute_request(request, authorized=True, popen=FakeProcess)
            self.assertEqual(result["status"], "wrapper_exception_before_publish")
            self.assertFalse(Path(request["home_output"]).exists())
            rejection_files = list(Path(request["nvme_root"]).glob("*.rejection.json"))
            self.assertEqual(len(rejection_files), 1)


if __name__ == "__main__":
    unittest.main()
