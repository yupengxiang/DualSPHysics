#!/usr/bin/env python3
"""Measure one controller CLI; detached worker and guardian have other owners."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess

ROOT=Path('/data/nas/jade/Simulation/DualSPHysics/lfd-01')
P=ROOT/'worktree/lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--grant',type=Path,required=True)
    parser.add_argument('--job-id',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    for path in (args.runtime,args.request,args.grant,args.receipt):
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(P):
            raise ValueError('controller invocation paths must remain canonical inside LFD-01')
    if args.receipt.exists():raise ValueError('immutable controller invocation receipt exists')
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    # The controller wrapper's soft cap must not become an inherited hard
    # 60-second ceiling on a later scientific worker. The admitted child is
    # separately limited to the request's finite CPU reservation ceiling.
    adoption=json.loads((P/'control/ADOPTION.json').read_text())
    request=json.loads(args.request.read_text())
    campaign_cpu_hard=int(adoption['effective_caps']['cpu_core_seconds'])
    inherited_hard=resource.getrlimit(resource.RLIMIT_CPU)[1]
    if inherited_hard != resource.RLIM_INFINITY and inherited_hard < campaign_cpu_hard:
        raise ValueError('caller inherited CPU hard limit cannot support the campaign child scope')
    resource.setrlimit(resource.RLIMIT_CPU,(60,campaign_cpu_hard))
    child_cpu=int(math.ceil(float(request['max_wall_seconds'])*int(request['cpu_threads'])))
    if not 1 <= child_cpu <= campaign_cpu_hard:
        raise ValueError('child CPU ceiling differs from the adopted resource scope')
    # Fixed trusted tool bindings are declarations. Root skips all filesystem
    # inspection of these native leaves; admitted shared runtime owns validation.
    limiter=Path('/usr/bin/prlimit')
    expected_tools={
        '/usr/bin/prlimit':(27536,'740e7bb73625b7aa99821cd6641015dfd0430de801a86881837a2cb688182d94'),
        '/usr/bin/python3.10':(5941864,'a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae')}
    for tool,(size,digest) in expected_tools.items():
        rows=[row for row in request['source_bindings'] if row.get('path')==tool]
        if len(rows)!=1 or rows[0].get('bytes')!=size or rows[0].get('sha256')!=digest or rows[0].get('deferred') is not False:
            raise ValueError('trusted tool declared binding changed')
    required=request.get('required_dispatch_environment',{})
    if type(required) is not dict or not all(type(k) is str and type(v) is str and k in {'PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','PYTHONOPTIMIZE','TMPDIR'} and len(v)<=4096 for k,v in required.items()):
        raise ValueError('closed software dispatch environment')
    if set(required)!={'PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','PYTHONOPTIMIZE','TMPDIR'} or required!={'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHONOPTIMIZE':'0','TMPDIR':request['tmpdir']}:
        raise ValueError('complete exact software dispatch environment')
    environment=os.environ.copy()
    environment.update(required)
    command=[str(limiter),f'--cpu={child_cpu}:{child_cpu}','--','/usr/bin/python3.10',str(args.runtime),'controller','--request',str(args.request),
             '--grant',str(args.grant),'--job-id',args.job_id]
    started=datetime.now(timezone.utc).isoformat()
    result=subprocess.run(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,text=True,timeout=90,check=False,env=environment)
    own=resource.getrusage(resource.RUSAGE_SELF);child=resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt=dict(schema='lfd01.controller-invocation-cost.v1',campaign_id='LFD-01',job_id=args.job_id,
        command=command,returncode=result.returncode,started_at_utc=started,
        dispatch_environment_projection={k:environment[k] for k in required},
        cached_native_tools_root_filesystem_access=False,
        finished_at_utc=datetime.now(timezone.utc).isoformat(),
        cpu_core_seconds=own.ru_utime+own.ru_stime+child.ru_utime+child.ru_stime,
        cpu_owner='This wrapper SELF and reaped controller CLI tree only; detached un-waited guardian and its worker excluded.',
        guardian_controller_self_snapshot_must_not_be_charged_again=True,
        accounting='pending root unique infrastructure settlement',response=result.stdout[:32768])
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    with args.receipt.open('x') as handle:json.dump(receipt,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps(dict(returncode=result.returncode,cpu_core_seconds=receipt['cpu_core_seconds'],
                         receipt=str(args.receipt),response=result.stdout[:8192]),ensure_ascii=False))
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
