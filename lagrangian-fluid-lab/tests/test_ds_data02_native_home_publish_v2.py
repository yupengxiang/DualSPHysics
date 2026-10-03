import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from ds_data02_native_home_publish_v2 import require_terminal


def actual(source):
    command=['official','case',str(source),'-tmax:1.6','-tout:0.001']
    return dict(status='completed',returncode=0,request_sha256='registered',request=dict(command=command),command=[command[0],'-gpu:0',*command[1:]],input_hashes_at_launch={'x':'a'},input_hashes_after_run={'x':'a'})


def test_runner_gpu_insertion_preserves_full_actual_native_command(tmp_path):
    require_terminal(actual(tmp_path),'registered',tmp_path)


@pytest.mark.parametrize('field,value',[('status','running'),('returncode',-15),('request_sha256','different'),('command',['official','-gpu:0','case','wrong']),('input_hashes_after_run',{'x':'b'})])
def test_rejects_unclosed_or_changed_actual_source(tmp_path,field,value):
    r=actual(tmp_path);r[field]=value
    with pytest.raises(ValueError):require_terminal(r,'registered',tmp_path)
