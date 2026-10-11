from pathlib import Path

import numpy as np
import pytest
import h5py

from scripts import ds_data02_direct_convert_v2 as adapter
from test_ds_data02_direct_convert import _write_fake_decoder, _write_provenance


def test_multiple_decodes_keep_arrays_and_remove_previous_scratch(tmp_path):
    decoder = tmp_path / "decoder"
    _write_fake_decoder(decoder)
    scratch = tmp_path / "scratch"
    retained = []
    for index in range(5):
        source = tmp_path / f"Part_{index:04d}.bi4"
        source.write_bytes(b"fixture")
        retained.append(adapter.decode_frame(source, decoder, scratch, index))
        assert list(scratch.iterdir()) == []
    for index, frame in enumerate(retained):
        np.testing.assert_array_equal(frame.ids, np.arange(4, dtype=np.uint32))
        np.testing.assert_array_equal(frame.position, np.arange(12, dtype=np.float32).reshape(4, 3) + index)
        np.testing.assert_array_equal(frame.velocity, np.full((4, 3), index + 1, dtype=np.float32))
        assert frame.time == index * .1


def test_failed_decode_removes_only_its_private_scratch(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    evidence = scratch / "previous-failed-evidence.bin"
    evidence.write_bytes(b"preserve")

    def fail(source, decoder, private, index):
        (private / "decoded.bin").write_bytes(b"partial")
        raise adapter.base.DirectConversionError("decoder failed")

    monkeypatch.setattr(adapter, "ORIGINAL_DECODE", fail)
    with pytest.raises(adapter.base.DirectConversionError, match="decoder failed"):
        adapter.decode_frame(Path("source"), Path("decoder"), scratch, 3)
    assert list(scratch.iterdir()) == [evidence]
    assert evidence.read_bytes() == b"preserve"


def test_complete_conversion_matches_preserved_converter_with_exclusions(tmp_path):
    source = _write_provenance(tmp_path)
    (source["data"] / "drop_frame_zero").write_text("initial exclusion\n")
    shared = dict(data_root=source["data"], generated_xml=source["xml"], decoder=source["decoder"],
                  solver_log=source["solver_log"], solver_receipt=source["solver_receipt"],
                  gencase_receipt=source["gencase_receipt"], owner_metadata=source["owner"], run_partvtk=False)
    original = tmp_path / "original.h5"
    bounded = tmp_path / "bounded.h5"
    adapter.ORIGINAL_CONVERT(**shared, output=original, report_path=tmp_path / "original.json")
    report = adapter.convert_direct(**shared, output=bounded, report_path=tmp_path / "bounded.json")
    with h5py.File(original, "r") as left, h5py.File(bounded, "r") as right:
        names = []
        left.visititems(lambda name, item: names.append(name) if isinstance(item, h5py.Dataset) else None)
        for name in names:
            np.testing.assert_array_equal(left[name][...], right[name][...], err_msg=name)
    assert report["decoder_scratch"]["decoded_frames"] == 2
    assert report["decoder_scratch"]["max_decoded_frame_bytes"] > 0
    assert report["source_provenance"]["raw_tree"]["unchanged"] is True
