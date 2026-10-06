#!/usr/bin/env python3
"""Re-run fresh153 metadata probe; scientific paths are stat-only."""
from pathlib import Path
import json
META=Path(__file__).resolve().parents[1]/"metadata/storage-bound-audit.json"
def main():
    d=json.loads(META.read_text())
    assert d["science_payload_policy"]=={"opened":False,"hashed":False,"copied":False,"science_paths_representation":"stat-only; producer JSON attestations are not recomputed"}
    print(json.dumps({"schema":d["schema"],"representatives":list(d["representatives"]),"no_science_payload_read":True},indent=2))
if __name__=="__main__": main()
