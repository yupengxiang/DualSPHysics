import argparse, hashlib, json, os, time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
base=Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first")
assert Path("/data/nas").is_mount()
assert base.stat().st_dev != Path("/home/jade").stat().st_dev
file=base/"scratch"/"nas-preflight-001.bin"
block=os.urandom(1024*1024);expected=hashlib.sha256();start=time.monotonic()
with file.open("xb") as f:
 for _ in range(32):f.write(block);expected.update(block)
 f.flush();os.fsync(f.fileno())
write_seconds=time.monotonic()-start;start=time.monotonic();actual=hashlib.sha256()
with file.open("rb") as f:
 while chunk:=f.read(1024*1024):actual.update(chunk)
read_seconds=time.monotonic()-start
assert actual.hexdigest()==expected.hexdigest()
stat=os.statvfs(base)
report={"status":"passed","bytes":32*1024**2,"write_seconds":write_seconds,"read_seconds":read_seconds,"write_mib_per_second":32/write_seconds,"read_mib_per_second":32/read_seconds,"read_may_be_cached":True,"sha256":actual.hexdigest(),"nas_available_bytes":stat.f_bavail*stat.f_frsize,"device":base.stat().st_dev,"scope":"small file I/O correctness; not sustained throughput guarantee"}
file.unlink()
(args.output/"nas-preflight.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report))
