"""Exercise failure accounting and idempotency without the production ledger."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from external_storage_v1 import reconcile


class ExternalStorageTests(unittest.TestCase):
    def fixture(self, root, data, status='completed', reserved=1024):
        (root / 'tiny.h5').write_bytes(b'tiny-fixture')
        q = {'family_id':'F2','case_id':'CASE','attempt_id':'ATTEMPT',
             'estimated_storage_bytes':reserved + 1024,
             'storage_scope':{'external_filesystem':str(root)},
             'root_external_storage_accounting':{'same_parent_atomic_reservation_bytes':reserved + 1024,
                 'external_reserved_bytes':reserved,'home_reserved_bytes':1024}}
        qp = data / 'request.json'; qp.write_text(json.dumps(q))
        parent = 'F2/CASE/ATTEMPT'; base = data / 'families' / parent; base.mkdir(parents=True)
        r = {'request':q,'request_sha256':hashlib.sha256(qp.read_bytes()).hexdigest(),'status':status,'bytes':50}
        (base / 'execution-receipt.json').write_text(json.dumps(r))
        ledger = {'charges':[{'id':parent,'status':status,'new_storage_bytes':50}], 'reservations':[]}
        @contextmanager
        def lock(_):
            yield ledger
        return qp, lock, ledger

    def test_repeat_does_not_double_charge(self):
        with tempfile.TemporaryDirectory(prefix='STAGE2_F2_ROOT242_TEST_',dir='/var/tmp') as p, tempfile.TemporaryDirectory() as d:
            root, data = Path(p), Path(d); qp, lock, ledger = self.fixture(root,data)
            out = data / 'fee.json'
            self.assertEqual(reconcile(qp,data,lock,out)['status'],'APPENDED_SAME_PARENT_EXTERNAL_STORAGE')
            self.assertEqual(reconcile(qp,data,lock,out)['status'],'ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE')
            self.assertEqual(len(ledger['charges']),2)

    def test_failed_overflow_still_charged(self):
        with tempfile.TemporaryDirectory(prefix='STAGE2_F2_ROOT242_TEST_',dir='/var/tmp') as p, tempfile.TemporaryDirectory() as d:
            root, data = Path(p), Path(d); qp, lock, ledger = self.fixture(root,data,'failed',1)
            result = reconcile(qp,data,lock,data/'fee.json')
            self.assertFalse(result['evidence']['external_storage_within_reservation'])
            self.assertEqual(ledger['charges'][-1]['status'],'failed')
            self.assertEqual(ledger['charges'][-1]['new_storage_bytes'],len(b'tiny-fixture'))

    def test_mutation_rejected_after_fee(self):
        with tempfile.TemporaryDirectory(prefix='STAGE2_F2_ROOT242_TEST_',dir='/var/tmp') as p, tempfile.TemporaryDirectory() as d:
            root, data = Path(p), Path(d); qp, lock, ledger = self.fixture(root,data)
            out = data/'fee.json'; reconcile(qp,data,lock,out)
            (root/'tiny.h5').write_bytes(b'changed-fixture')
            with self.assertRaises(AssertionError):
                reconcile(qp,data,lock,out)
            self.assertEqual(len(ledger['charges']),2)


if __name__ == '__main__':
    unittest.main()
