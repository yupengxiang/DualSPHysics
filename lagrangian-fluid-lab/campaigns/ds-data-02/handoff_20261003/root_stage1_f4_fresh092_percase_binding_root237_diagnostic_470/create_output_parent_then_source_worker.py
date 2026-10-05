from pathlib import Path
import sys,subprocess
a=sys.argv[2:];cid=a[a.index('--case-id')+1];root=Path(a[a.index('--output-root')+1]);(root/'native-audit/cases'/cid).mkdir(parents=True,exist_ok=True)
raise SystemExit(subprocess.call([sys.executable,sys.argv[1],*a]))
