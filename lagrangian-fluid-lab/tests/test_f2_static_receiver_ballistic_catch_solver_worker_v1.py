from __future__ import annotations

from pathlib import Path

from scripts import f2_static_receiver_ballistic_catch_solver_worker_v1 as worker


def test_worker_inventory_is_content_addressed(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/Part_0000.bi4").write_bytes(b"frame")
    result = worker._inventory(tmp_path)
    assert result["frame_count"] == 1
    assert result["frame_names"] == ["Part_0000.bi4"]
    assert result["total_bytes"] == 5


def test_worker_uses_official_solver_library_environment():
    source = Path(worker.__file__).read_text()
    assert "environment(LAB_ROOT)" in source
    assert 'env["CUDA_VISIBLE_DEVICES"] = visible' in source
