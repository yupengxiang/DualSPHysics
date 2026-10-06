#!/usr/bin/env python3
"""Metadata/PNG-only validator for fresh178.

This validator reads JSON metadata and PNG evidence only. It never opens H5,
BI4, CSV, DAT, VTK, XDMF payload arrays, or starts a scientific task.
"""
from __future__ import annotations
import hashlib, json, pathlib, sys

PKG=pathlib.Path(__file__).resolve().parents[0].parent

def load(rel):
    return json.loads((PKG/rel).read_text())

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def check(cond,msg):
    if not cond: raise SystemExit('FAIL: '+msg)

actual=load('metadata/actual984-render-metadata.json')
closure=load('metadata/physical-stage-closure.json')
png=load('metadata/png-visual-evidence.json')
dec=load('metadata/visual-decision.json')
check(actual['status']['execution_receipt_status']=='completed','render receipt not completed')
check(actual['status']['execution_receipt_returncode']==0,'render receipt returncode')
check(actual['status']['controller_status']=='completed','controller not completed')
check(actual['status']['controller_returncode']==0,'controller returncode')
check(actual['frames']['actual']==801,'frame count')
check(actual['frames']['all_frames_rendered'] is True,'all frames flag')
check(actual['frames']['expected_particles']==194427,'particle axis')
check(actual['frames']['actual_contact_sheet_files']==34,'actual producer contact sheets')
check(actual['frames']['keyframe_indices']==[0,100,200,300,400,500,600,700,800],'keyframe list')
check(len(png['contact_sheets'])==34 and png['all_producer_contact_sheets_reviewed'] is True,'contact evidence')
for x in png['contact_sheets']+png['keyframes']:
    p=pathlib.Path(x['path']); check(p.is_file(),f'missing PNG {p}')
    check(sha(p)==x['sha256'],f'PNG hash {p}')
check(len(png['keyframes'])==9 and png['keyframe_files_reviewed']==9,'keyframe evidence')
summary=closure['dynamic_bed_summary']
check(summary['frames_scanned']==801,'bed frames')
check(summary['initial_fluid_uid_count']==31658,'bed UID denominator')
check(summary['one_dp_max_count']==0 and summary['two_dp_max_count']==0,'bed penetration counts')
check(summary['missing_initial_uid_max']==0 and summary['unexpected_uid_max']==0,'UID loss')
check(summary['nonfinite_position_max']==0 and summary['nonfinite_mass_max']==0,'nonfinite')
check(dec['actual_producer_evidence_reviewed']['all_actual_contact_sheets_reviewed'] is True,'review count')
check(dec['actual_producer_evidence_reviewed']['all_nine_keyframes_reviewed'] is True,'keyframe review')
check(dec['decision']['standalone_first_stage_visual_approved'] is True,'visual decision')
check(dec['decision']['strict_container_guarantee'] is False,'strict container overclaim')
check(dec['decision']['numerical_precision_accepted'] is False,'precision overclaim')
check(dec['decision']['independent_case_count_increment']==0,'case credit')
check(closure['source_agent_science_payload_io']['read'] is False,'source scientific read')
check(closure['source_agent_science_payload_io']['hash'] is False,'source scientific hash')
check(closure['source_agent_science_payload_io']['copy'] is False,'source scientific copy')
check(closure['source_agent_science_payload_io']['launch'] is False,'source scientific launch')
print('PASS fresh178 metadata+PNG review')
print('actual984 completed/0, 801 frames, 34 producer contact sheets, 9 keyframes')
print('visual approval is first-stage only; strict container and precision remain false')
