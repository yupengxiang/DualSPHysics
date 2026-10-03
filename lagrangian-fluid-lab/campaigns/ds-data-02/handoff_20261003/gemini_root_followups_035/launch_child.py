import pathlib,json,os,subprocess,sys
s=pathlib.Path(__file__).resolve().parent;role=sys.argv[1];j=json.loads((s/(role+'-delegation.json')).read_text());env=os.environ.copy();env['DBUS_SESSION_BUS_ADDRESS']=j['child_bus'];log=pathlib.Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime')/('gemini-root-followup-035-'+role+'.log')
cmd=['agy','--dangerously-skip-permissions','--model',j['model'],'--print',(s/(role+'-task.txt')).read_text()]
with log.open('x') as f:p=subprocess.run(cmd,cwd=j['worktree'],env=env,stdout=f,stderr=subprocess.STDOUT)
print(role,'AGY process exit',p.returncode,'public log',log,flush=True);sys.exit(p.returncode)
