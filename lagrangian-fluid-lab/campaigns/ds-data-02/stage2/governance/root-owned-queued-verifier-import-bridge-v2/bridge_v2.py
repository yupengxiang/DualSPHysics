"""Add-only verifier import bootstrap for frozen waiting continuations."""
from pathlib import Path
import hashlib
import importlib.util
import subprocess
import sys

SOURCES = {'continue_after_portable_v1.py': {'path': '/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/governance/root-owned-reference-admission-v1/continue_after_portable_v1.py', 'sha256': 'ca7ecabcaf0eb9aecb5c888065121806b99a29de094b4210702f8646c7e23085'}, 'continue_frame0_after_support_v1.py': {'path': '/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/governance/root-owned-reference-admission-v1/continue_frame0_after_support_v1.py', 'sha256': 'ecd46e07c22b23f9f092065d5da8fb055f22d5c41fab1f79d23455dfc1d6aa03'}, 'continue_mass30_after_frame0_v1.py': {'path': '/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/governance/root-owned-native-admission-v1/continue_mass30_after_frame0_v1.py', 'sha256': 'd14a371b536078908bdb14d0d1ecfb5dcf99922791a0f1082294671bc5657ece'}}
VERIFIERS = {'verify_support276_v1.py', 'verify_frame0314_v1.py', 'verify_actual_mass30_v1.py'}
BOOT = "import importlib.util,runpy,sys;from pathlib import Path;p=sys.argv[1];sys.argv=sys.argv[1:];sys.path.insert(0,str(Path(p).parent));runpy.run_path(p,run_name='__main__')"

def run_waiter(wrapper):
    wrapper=Path(wrapper).absolute()
    record=SOURCES[wrapper.name]; old=Path(record['path'])
    data=old.read_bytes(); assert hashlib.sha256(data).hexdigest()==record['sha256']
    original_run=subprocess.run
    def guarded_run(argv,*args,**kwargs):
        if isinstance(argv,(list,tuple)) and len(argv)>=3 and argv[1]=='-B' and Path(str(argv[2])).name in VERIFIERS:
            assert Path(str(argv[2])).is_relative_to(old.parent.parent)
            argv=[argv[0],'-B','-c',BOOT,*argv[2:]]
        return original_run(argv,*args,**kwargs)
    subprocess.run=guarded_run
    text=data.decode()
    marker="context['write'](q, source, name, extra=extra)" if wrapper.name!='continue_after_portable_v1.py' else "context['write'](q,source,name,extra=extra)"
    assert text.count(marker)==1
    text=text.replace(marker,"extra += [Path("+repr(str(wrapper))+"), Path("+repr(str(Path(__file__).absolute()))+")]; "+marker)
    exec(compile(text,str(old),'exec'),{'__file__':str(old),'__name__':'__main__'})
