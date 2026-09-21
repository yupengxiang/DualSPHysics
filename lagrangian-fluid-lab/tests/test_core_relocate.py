import json
import shutil
import pytest
from test_core_contract import tiny_manifest
from scripts.core_package import build_bundle, verify_bundle
from scripts.core_relocate import relocate


def test_relocation_reuses_only_hash_matching_local_data(tmp_path):
    source=tmp_path/'source';source.mkdir()
    manifest=source/'manifest.json';manifest.write_text(json.dumps(tiny_manifest(source)))
    original=tmp_path/'original';build_bundle(manifest,source,original)
    metadata=tmp_path/'metadata';shutil.copytree(original,metadata)
    (metadata/'data.h5').unlink()
    target=tmp_path/'relocated'
    result=relocate(metadata,source,target)
    assert result['passed'] and not result['model_prediction_reproduced']
    assert result['reused_hardlink_bytes']==(source/'data.h5').stat().st_size
    assert verify_bundle(target)['passed']
    with (source/'data.h5').open('ab') as f:f.write(b'corruption')
    with pytest.raises(ValueError,match='source hash mismatch'):
        relocate(metadata,source,tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()
