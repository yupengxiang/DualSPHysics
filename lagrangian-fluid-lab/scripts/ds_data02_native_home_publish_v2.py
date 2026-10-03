"""Publish verified native bytes using the actual runner-injected GPU command.

Consumed native staging v1 is immutable. This independently versioned CPU
publication validates the embedded request plus the actual normalized argv.
"""
import argparse
import json
from pathlib import Path
import ds_data02_native_nvme_stage_v1 as original


def require_terminal(receipt, request_sha, source):
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('Actual successful terminal native receipt required')
    if receipt.get('request_sha256') != request_sha:
        raise ValueError('Native request digest differs')
    request_command = receipt['request']['command']
    actual_command = receipt['command'][:]
    if len(actual_command)>1 and actual_command[1].startswith('-gpu:'):
        actual_command.pop(1)
    if actual_command != request_command:
        raise ValueError('Actual native command differs from immutable request')
    if Path(request_command[2]).resolve() != source.resolve():
        raise ValueError('Registered native staging source differs')
    if receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
        raise ValueError('Native inputs changed')


def publish(request, receipt, report):
    original.require_terminal = require_terminal
    return original.publish(request, receipt, report)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    result=publish(a.request,a.receipt,a.report)
    print(json.dumps(dict(status=result['status'],published_files=len(result['files']),publication=str(a.report))),flush=True)
