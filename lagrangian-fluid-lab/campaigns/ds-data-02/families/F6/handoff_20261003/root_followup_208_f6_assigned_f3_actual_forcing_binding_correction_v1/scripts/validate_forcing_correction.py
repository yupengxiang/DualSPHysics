#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def fail(msg): raise SystemExit("FAIL: " + msg)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('audit',type=Path);a=ap.parse_args();d=json.loads(a.audit.read_text())
    if d.get('schema')!='ds02.f6.fresh208.f3.actual-forcing-correction.v1': fail('schema')
    if d.get('source_boundaries',{}).get('csv_read_or_hashed') is not False: fail('CSV boundary')
    if len(d.get('cases',[]))!=2: fail('case count')
    expected={'lower':.25,'upper':.75}
    for c in d['cases']:
        n=c['case_alias']; t=c['actual_forcing_tuple']; p=c['producer_report']; j=c['native_launch_after_join']; x=c['endpoint_xml']
        if c['status']!='PASS_ACTUAL_FORCING_ENDPOINT_DISTINCT_WITH_STALE_REQUEST_BINDING': fail(f'status {n}')
        if t['transverse_amplitude_m_s2']!=expected[n]: fail(f'actual amplitude {n}')
        if p['forcing_transform']['amplitude_y']!=expected[n]: fail(f'producer amplitude {n}')
        if j['status']!='completed' or j['returncode']!=0: fail(f'native terminal {n}')
        if not j['forcing_launch_after_equal'] or not j['forcing_launch_matches_producer_output']: fail(f'forcing launch/after pin {n}')
        if not j['endpoint_xml_launch_after_equal']: fail(f'XML launch/after {n}')
        if not x['resolved_acctimesfile_matches_producer_output']: fail(f'XML relative acctimesfile {n}')
        if c['actual_native_request_stale_binding']['physical_binding_transverse_amplitude_m_s2']!=.5: fail(f'stale request record {n}')
        if t['pitch_numeric'] is not None: fail(f'pitch inferred {n}')
    print(json.dumps({'schema':d['schema'],'status':'PASS','cases':2,'negative_contracts':['stale request is retained but cannot replace producer forcing','missing forcing launch/after pin fails','identifier P1000 cannot become numeric pitch','CSV payload is not read or hashed']},sort_keys=True))

if __name__=='__main__': main()
