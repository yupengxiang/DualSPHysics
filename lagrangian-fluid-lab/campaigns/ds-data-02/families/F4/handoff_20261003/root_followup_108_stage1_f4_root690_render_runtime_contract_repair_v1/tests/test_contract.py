#!/usr/bin/env python3
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve(); WORK=HERE.parents[1]/"workers/repair_disabled_root690_request.py"
spec=importlib.util.spec_from_file_location("repair",WORK); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
SRC=Path('/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_107_stage1_f4_root669_xmf_to_root023_adapter_v1')
q=json.loads(next((SRC/'requests').glob('*.request.json')).read_text())
r=mod.derive_disabled(q); mod.validate_runtime_fields(r,disabled=True)
checks=[]
for field in ('worktree_root','estimated_storage_bytes'):
    bad=copy.deepcopy(r); bad.pop(field)
    try: mod.validate_runtime_fields(bad,disabled=True)
    except ValueError: checks.append('missing '+field+' rejected')
    else: raise AssertionError(field)
bad=copy.deepcopy(r); bad['launch_owner']='worker'
try: mod.validate_runtime_fields(bad,disabled=True)
except ValueError: checks.append('foreign launch_owner rejected')
else: raise AssertionError('launch_owner')
bad=copy.deepcopy(r); bad['future_hashes']['manifest_sha256']='a'*64
try: mod.validate_runtime_fields(bad,disabled=True)
except ValueError: checks.append('future hash rejected')
else: raise AssertionError('future hash')
bad=copy.deepcopy(r); bad['command']=list(r['command']); bad['command'].remove('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py')
try: mod.validate_runtime_fields(bad,disabled=True)
except ValueError: checks.append('missing Root023 renderer rejected')
else: raise AssertionError('renderer')
print('fresh108 synthetic contract: PASS ('+'; '.join(checks)+')')
