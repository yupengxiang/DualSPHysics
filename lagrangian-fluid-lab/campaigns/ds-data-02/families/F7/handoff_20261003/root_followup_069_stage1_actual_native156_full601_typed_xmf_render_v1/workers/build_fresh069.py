#!/usr/bin/env python3
"""Fresh069 package is built once by the source owner; this helper only locates immutable disabled requests."""
from pathlib import Path
import argparse
p=argparse.ArgumentParser(); p.add_argument('--package-root',type=Path,required=True); a=p.parse_args()
root=a.package_root
print('\n'.join(str(p) for p in sorted(root.glob('requests/*/*.json'))))
