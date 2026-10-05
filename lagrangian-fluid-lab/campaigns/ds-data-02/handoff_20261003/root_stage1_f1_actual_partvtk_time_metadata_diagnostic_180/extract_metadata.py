from pathlib import Path
import argparse,csv,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
result={'diagnostic_only':True,'no_visual_count_increment':True,'sources':[]}
for name in b['csv_sources']:
 path=Path(name);before=sha(path);prefix=[]
 with path.open(newline='',encoding='utf-8') as f:
  for row in csv.reader(f):
   prefix.append(row)
   if 'Pos.x [m]' in row or len(prefix)>=16:break
 after=sha(path);assert before==after
 result['sources'].append({'path':name,'sha256':before,'csv_prefix_through_header_only':prefix,'input_unchanged':True})
(out/'actual-csv-time-metadata.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
