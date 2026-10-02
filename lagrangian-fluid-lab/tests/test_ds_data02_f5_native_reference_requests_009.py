from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_native_reference_requests_009.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f5_native_reference_requests_009", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_native_reference_is_macro_only_and_uses_full_window() -> None:
    assert MODULE.EVENT_WINDOW_S == 16.0
    assert MODULE.SAVE_INTERVAL_S == 0.02
    assert MODULE.EXPECTED_FRAMES == 801
    assert MODULE.MAX_WALL_SECONDS == 5400


def test_storage_estimate_is_based_on_actual_particle_count_and_margin() -> None:
    total_particles = 627286
    expected_base = total_particles * MODULE.EXPECTED_FRAMES * MODULE.BYTES_PER_PARTICLE_FRAME

    estimate = MODULE.estimate_storage_bytes(total_particles)

    assert estimate >= expected_base + MODULE.STORAGE_MARGIN_BYTES
    assert estimate % (1024**3) == 0


def test_no_solver_launch_is_encoded_by_request_producer() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "subprocess.run" in source  # only git commit provenance is queried
    assert "runner.request.v1" in source
    assert '"qualification_claim": "none"' in source
    assert '"production_claim": "none"' in source
    assert "family_owner_gpu_launch_forbidden" in source
