"""Close ROOT274 oomd SIGKILL with actual CPU/stat charge, no forged receipt."""
from pathlib import Path
import argparse
import importlib.util

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
BASE = S / 'governance/root-owned-lifecycle-continuation-v1/reconcile_orphan301_v1.py'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['snapshot', 'reconcile'])
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('root274_frozen_orphan_reconciler', BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Reuse the already verified append-only reconciliation, retaining all
    # original limits, history, ledger lock and idempotence checks.
    module.UNIT = 'ds02-generic-native-extract-v1-f6-root-274'
    module.REQUEST = S / 'requests/generic-native-extract-v1-root-forward-274-003.json'
    module.EVIDENCE = S / 'accounting/ROOT274_ORPHAN_SYSTEMD_FAILURE_EVIDENCE_V1.json'
    module.PROOF = S / 'checkpoints/ROOT274_ORPHAN_FAILED_PARENT_RECONCILIATION_V1.json'
    module.snapshot() if args.action == 'snapshot' else module.reconcile()


if __name__ == '__main__':
    main()
