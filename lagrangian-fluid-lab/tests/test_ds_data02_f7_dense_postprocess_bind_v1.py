import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ds_data02_f7_dense_postprocess_bind_v1 as binding

@pytest.mark.parametrize('failure', ['running', 'wrong_request', 'coarse_saved_timeline'])
def test_reject_unfinished_mismatched_or_nondense_conversion(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(binding, 'DATA', tmp_path / 'native')
    request={'family_id':'F7','cpu_task_kind':'conversion','case_id':'case','attempt_id':'actual',
        'input_sha256':{'native.xml':'a'*64}}
    rp=tmp_path/'request.json';rp.write_text(json.dumps(request))
    folder=binding.DATA/'case'/'actual';folder.mkdir(parents=True)
    receipt={'status':'completed','returncode':0,'request_sha256':binding.digest(rp),
        'input_hashes_at_launch':request['input_sha256']}
    report={'output_hdf5':str(folder/'trajectory.h5'),'frames':6001,'partvtk_validation':{'all_passed':True}}
    (folder/'trajectory.h5').write_bytes(b'fixture final bytes')
    if failure=='running':receipt['status']='running'
    if failure=='wrong_request':receipt['request_sha256']='0'*64
    if failure=='coarse_saved_timeline':report['frames']=601
    (folder/'execution-receipt.json').write_text(json.dumps(receipt))
    (folder/'conversion-report.json').write_text(json.dumps(report))
    destination=tmp_path/'not_registered'
    with pytest.raises(ValueError):binding.register(rp,destination,'reviewed')
    assert not destination.exists()
