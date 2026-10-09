from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v48 = _load("ds02_v48_test", SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v48.py")
v3 = _load("ds02_scratch_v3_test", SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v3.py")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "root"
    consumer = tmp_path / "consumer"
    root.mkdir()
    consumer.mkdir()
    metadata = root / "metadata.json"
    old_worker = root / "old-worker.py"
    metadata.write_text("metadata\n", encoding="utf-8")
    old_worker.write_text("print('old')\n", encoding="utf-8")
    wrapper = root / "scratch-wrapper.py"
    wrapper.write_text("print('wrapper')\n", encoding="utf-8")
    bundle = root / "bundle.json"
    bundle_value = {"schema": "bundle", "sha256": "PENDING"}
    bundle_value["sha256"] = v48._canonical_sha(bundle_value)
    _write_json(bundle, bundle_value)

    source_entries = []
    for role, path, relative in (
        ("v2_worker", old_worker, "sources/worker.py"),
        ("metadata", metadata, "sources/metadata.json"),
    ):
        stat = path.stat()
        source_entries.append({"role": role, "path": str(path), "sha256": _sha(path),
                               "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                               "target_relative_path": relative})
    stale_worker = consumer / "old-worker.py"
    stale_metadata = consumer / "metadata.json"
    entries = []
    for role, old, source, relative in (
        ("v2_worker", stale_worker, old_worker, "sources/worker.py"),
        ("metadata", stale_metadata, metadata, "sources/metadata.json"),
    ):
        stat = source.stat()
        entries.append({"role": role, "original_path": str(old),
                        "expected_sha256": _sha(source), "expected_bytes": stat.st_size,
                        "bundle_relative_path": relative, "source_mode_bits": stat.st_mode & 0o777,
                        "target_mode_bits": stat.st_mode & 0o777})
    overlay = {"schema": v48.OVERLAY_SCHEMA, "role": "DEVELOPMENT", "bundle": {
        "path": str(consumer / "bundle.json"), "sha256": _sha(bundle),
        "canonical_sha256": bundle_value["sha256"]}, "entries": entries,
        "original_path_fallback": "FORBIDDEN", "target_root": str(tmp_path / "old-target"),
        "target_paths_are_new": True, "content_hash_verified": False}
    overlay["sha256"] = v48._canonical_sha(overlay)
    old_overlay = tmp_path / "old-overlay.json"
    _write_json(old_overlay, overlay)

    request = {
        "schema": v48.V34_SCHEMA, "request_id": "old", "role": "DEVELOPMENT",
        "source_entries": source_entries,
        "v5_bundle": {"path": str(bundle), "sha256": _sha(bundle),
                      "canonical_sha256": bundle_value["sha256"]},
        "v5_overlay_template": {"path": str(old_overlay), "sha256": _sha(old_overlay),
                                "canonical_sha256": overlay["sha256"]},
        "fresh_roots": {"target_root": str(tmp_path / "old-target"),
                        "output_root": str(tmp_path / "old-output")},
        "execution": {"original_path_fallback": "FORBIDDEN"},
        "qualification": dict(v48.UNKNOWN),
    }
    request["sha256"] = v48._canonical_sha(request)
    request_path = tmp_path / "old-request.json"
    _write_json(request_path, request)
    return request_path, old_overlay, wrapper, root


def test_v48_maps_stale_paths_and_binds_wrapper(tmp_path: Path) -> None:
    request, overlay, wrapper, root = _fixture(tmp_path)
    output_request = tmp_path / "out" / "request.json"
    output_overlay = tmp_path / "out" / "overlay.json"
    value = v48.build_forward(
        v47_request=request, v47_overlay=overlay, scratch_worker=wrapper,
        output_request=output_request, output_overlay=output_overlay,
        target_root=tmp_path / "fresh-target", output_root=tmp_path / "fresh-output",
    )
    assert value["status"] == "READY_FOR_PARENT_V48_METADATA_GUARD"
    new_request = json.loads(output_request.read_text(encoding="utf-8"))
    new_overlay = json.loads(output_overlay.read_text(encoding="utf-8"))
    assert new_request["sha256"] == v48._canonical_sha(new_request)
    assert new_overlay["sha256"] == v48._canonical_sha(new_overlay)
    assert all(str(root) in str(x.get("original_path")) for x in new_overlay["entries"])
    assert next(x for x in new_request["source_entries"] if x["role"] == "v2_worker")["path"] == str(wrapper)
    assert next(x for x in new_overlay["entries"] if x["role"] == "v2_worker")["original_path"] == str(wrapper)
    assert new_request["execution"]["decoder_scratch"]["default_tmp_forbidden"] is True
    assert value["content_read"] is False


def test_v48_rejects_unmatched_declared_identity(tmp_path: Path) -> None:
    request, overlay, wrapper, _ = _fixture(tmp_path)
    bad = json.loads(overlay.read_text(encoding="utf-8"))
    bad["entries"][1]["expected_sha256"] = "0" * 64
    bad["sha256"] = v48._canonical_sha(bad)
    bad_overlay = tmp_path / "bad-overlay.json"
    _write_json(bad_overlay, bad)
    # The old request binding must match the supplied overlay bytes first.
    old = json.loads(request.read_text(encoding="utf-8"))
    old["v5_overlay_template"]["path"] = str(bad_overlay)
    old["v5_overlay_template"]["sha256"] = _sha(bad_overlay)
    old["v5_overlay_template"]["canonical_sha256"] = bad["sha256"]
    old["sha256"] = v48._canonical_sha(old)
    bad_request = tmp_path / "bad-request.json"
    _write_json(bad_request, old)
    with pytest.raises(v48.PortableV48Error, match="compatible source matches"):
        v48.build_forward(
            v47_request=bad_request, v47_overlay=bad_overlay, scratch_worker=wrapper,
            output_request=tmp_path / "bad-out" / "request.json",
            output_overlay=tmp_path / "bad-out" / "overlay.json",
            target_root=tmp_path / "bad-target", output_root=tmp_path / "bad-output",
        )


class _FakeConverter:
    def decode_frame(self, frame: Path, decoder: Path, scratch: Path, index: int) -> int:
        scratch = Path(scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "array.bin").write_bytes(str(index).encode())
        return index


class _FakeLoader:
    def __init__(self) -> None:
        self.converter = _FakeConverter()

    def _load_module(self, path: Path, name: str) -> _FakeConverter:
        return self.converter


def test_v3_scratch_is_per_frame_and_removed_on_success(tmp_path: Path) -> None:
    loader = _FakeLoader()
    state: dict[str, object] = {}
    root = tmp_path / "attempt-scratch"
    with v3.owned_tempdir(root):
        original = v3.install_decoder_scratch(loader, state)
        converter = loader._load_module(Path("unused"), "_ds02_bound_converter_v2")
        shared = Path(tempfile.mkdtemp(prefix="ds02-direct-bi4-"))
        for index in range(3):
            converter.decode_frame(Path("frame"), Path("decoder"), shared, index)
            assert not (shared / f"owned-frame-{index:04d}").exists()
        shutil.rmtree(shared)
        loader._load_module = original
    assert not root.exists()
    assert state["max_live_frame_directories"] == 1
    assert state["frames_cleaned"] == 3


def test_v3_scratch_is_removed_when_decoder_fails(tmp_path: Path) -> None:
    class Failing(_FakeConverter):
        def decode_frame(self, frame: Path, decoder: Path, scratch: Path, index: int) -> int:
            Path(scratch).mkdir(parents=True, exist_ok=True)
            raise RuntimeError("decoder failure")

    loader = _FakeLoader()
    loader.converter = Failing()
    state: dict[str, object] = {}
    root = tmp_path / "attempt-scratch-failure"
    with v3.owned_tempdir(root):
        original = v3.install_decoder_scratch(loader, state)
        converter = loader._load_module(Path("unused"), "_ds02_bound_converter_v2")
        shared = Path(tempfile.mkdtemp(prefix="ds02-direct-bi4-"))
        with pytest.raises(RuntimeError, match="decoder failure"):
            converter.decode_frame(Path("frame"), Path("decoder"), shared, 0)
        assert not (shared / "owned-frame-0000").exists()
        shutil.rmtree(shared)
        loader._load_module = original
    assert not root.exists()
    assert state["frames_cleaned"] == 1
