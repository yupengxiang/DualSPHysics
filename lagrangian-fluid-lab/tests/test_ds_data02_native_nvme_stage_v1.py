import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from ds_data02_native_nvme_stage_v1 import require_terminal, publish, digest


def receipt(source, **override):
    r = dict(status='completed', returncode=0, request_sha256='registered',
        command=['DualSPHysics', 'native', str(source)], input_hashes_at_launch={'x':'a'}, input_hashes_after_run={'x':'a'})
    r.update(override)
    return r


@pytest.mark.parametrize('change', [dict(status='running'), dict(returncode=-15), dict(request_sha256='other'), dict(input_hashes_after_run={'x':'b'})])
def test_rejects_unclosed_or_changed_native(tmp_path, change):
    with pytest.raises(ValueError):
        require_terminal(receipt(tmp_path, **change), 'registered', tmp_path)


def test_actual_publication_byte_verifies_and_preserves_source(tmp_path):
    source=tmp_path/'stage'; source.mkdir(); (source/'Part_0000.bi4').write_bytes(b'actual binary bytes')
    output=tmp_path/'attempt'; output.mkdir()
    req=tmp_path/'request.json'; req.write_text(json.dumps(dict(command=['DualSPHysics','native',str(source)],estimated_storage_bytes=1024)))
    r=receipt(source,request_sha256=digest(req),output_root=str(output))
    rp=tmp_path/'receipt.json'; rp.write_text(json.dumps(r)); report=output/'publication.json'
    result=publish(req,rp,report)
    copy=output/'solver_output/Part_0000.bi4'
    assert copy.read_bytes()==(source/'Part_0000.bi4').read_bytes()
    assert result['files'][0]['sha256']==digest(copy)
    assert result['q_n_status']=='not_granted'
    with pytest.raises(FileExistsError): publish(req,rp,report)


def test_rejects_source_symlink_before_copy(tmp_path):
    source=tmp_path/'stage'; source.mkdir(); (source/'file').symlink_to(tmp_path/'target')
    req=tmp_path/'request'; req.write_text(json.dumps(dict(command=['DualSPHysics','native',str(source)],estimated_storage_bytes=1024)))
    rp=tmp_path/'receipt'; rp.write_text(json.dumps(receipt(source,request_sha256=digest(req),output_root=str(tmp_path/'attempt'))))
    with pytest.raises(ValueError): publish(req,rp,tmp_path/'publication')
