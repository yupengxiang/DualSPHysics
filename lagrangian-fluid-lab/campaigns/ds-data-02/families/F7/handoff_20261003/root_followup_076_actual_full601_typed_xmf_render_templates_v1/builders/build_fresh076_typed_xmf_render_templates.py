#!/usr/bin/env python3
"""Provenance builder marker for fresh076.

The package was generated from the fresh074 owner registry and the successful
fresh073 metadata adapter. Runtime binding remains Root-owned; this file is a
source marker and never launches scientific workers.
"""
from pathlib import Path
PACKAGE = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    print(PACKAGE)
