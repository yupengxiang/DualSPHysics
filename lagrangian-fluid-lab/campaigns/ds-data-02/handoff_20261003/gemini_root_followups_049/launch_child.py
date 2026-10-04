import pathlib,json,os,subprocess,sys,time,datetime
s=pathlib.Path(__file__).resolve().parent;role=sys.argv[1];j=json.loads((s/(role+'-delegation.json')).read_text());env=os.environ.copy();env['DBUS_SESSION_BUS_ADDRESS']=j['child_bus'];base=pathlib.Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime');log=base/('gemini-root-followup-049-'+role+'.log');launch=base/('gemini-root-followup-049-'+role+'.launch.json')
cmd=['agy','--dangerously-skip-permissions','--model',j['model'],'--print',(s/(role+'-task.txt')).read_text()]
with log.open('x') as f:
 p=subprocess.Popen(cmd,cwd=j['worktree'],env=env,stdout=f,stderr=subprocess.STDOUT);meta={'role':role,'round':'049','pid':p.pid,'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'conversation':None,'public_log':str(log)};launch.write_text(json.dumps(meta,indent=2)+'\n')
 while p.poll() is None:
  if meta['conversation'] is None:
   for fd in pathlib.Path('/proc/'+str(p.pid)+'/fd').glob('*'):
    try: target=os.readlink(fd)
    except OSError:continue
    if '/antigravity-cli/conversations/' in target and target.endswith('.db'):
     meta['conversation']=pathlib.Path(target).stem;meta['owned_open_db_observed_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();launch.write_text(json.dumps(meta,indent=2)+'\n');print('Owned new conversation',role,meta['conversation'],flush=True);break
  time.sleep(.5)
 meta['cli_exit']=p.returncode;meta['finished_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();launch.write_text(json.dumps(meta,indent=2)+'\n')
print(role,'AGY process exit',p.returncode,'public log',log,flush=True);sys.exit(p.returncode)
