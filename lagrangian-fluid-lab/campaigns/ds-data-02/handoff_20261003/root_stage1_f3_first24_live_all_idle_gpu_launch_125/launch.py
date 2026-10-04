"""Explicit Root all-idle selector with original strict dispatcher and UUID leases."""
import argparse,json,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),'/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts','/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_followup_055_stage1_production_adapter_v2']
import ds_data02_runtime_v2 as runtime
import ds_data02_stage1_dispatch_v2 as adapter
import ds02_root_all_idle_gpu_selector_v1 as selector

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run'])
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args()
    request=json.loads(args.request.read_text())
    with selector.install(runtime,request):
        receipt=adapter.run_request(args.request)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return int(receipt.get('status')!='completed')

if __name__=='__main__':
    raise SystemExit(main())
