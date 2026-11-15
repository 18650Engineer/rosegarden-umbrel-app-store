import importlib.util
import pathlib
import time
import unittest
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rose_server', ROOT/'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
INVOICE = 'lnbc' + 'a'*110

class Tests(unittest.TestCase):
    def sample(self, direction='toBLAKE2b'):
        return dict(hold_invoice=INVOICE, hash='a'*64,
                    direction=direction, incoming_msat='1289634',
                    outgoing_msat='300000000', spread=0.01,
                    rate=230.0, expires_at=str(int(time.time())+60))

    def test_reject_invalid_invoice(self):
        for value in ('', 'hello', 'lnbcq'*5000, 'lnbc\n'+'a'*100):
            with self.assertRaises(app.AppError): app.validate_invoice(value)

    def test_quote(self):
        with patch.object(app,'get_bridge',return_value=self.sample()):
            result=app.prepare_quote(INVOICE,'toBLAKE2b')
        self.assertEqual(result['incoming_sats'],1289.634)
        self.assertEqual(result['outgoing_sats'],300000)
        self.assertEqual(result['direction'],'toBLAKE2b')
        self.assertEqual(result['payment_state'],'NOT_STARTED')

    def test_direction_mismatch(self):
        with patch.object(app,'get_bridge',return_value=self.sample()):
            with self.assertRaisesRegex(app.AppError,'other network'):
                app.prepare_quote(INVOICE,'toSHA256')

    def test_quote_cap(self):
        q=self.sample();q['incoming_msat']='100000000000'
        with patch.object(app,'get_bridge',return_value=q):
            with self.assertRaisesRegex(app.AppError,'safety limit'):
                app.prepare_quote(INVOICE,'toBLAKE2b')

    def test_quote_expired(self):
        q=self.sample();q['expires_at']=str(int(time.time())-1)
        with patch.object(app,'get_bridge',return_value=q):
            with self.assertRaisesRegex(app.AppError,'expired'):
                app.prepare_quote(INVOICE,'toBLAKE2b')

    def test_non_shell_command(self):
        with patch.object(app.subprocess,'run') as run:
            run.return_value.returncode=0
            run.return_value.stdout='{}'
            run.return_value.stderr=''
            app.get_bridge(['status'])
            self.assertEqual(run.call_args[0][0],app.CLI+['status'])
            self.assertNotIn('shell',run.call_args.kwargs)

if __name__=='__main__':unittest.main()

# Additional REST-mode tests can be executed independently via unittest discovery.
