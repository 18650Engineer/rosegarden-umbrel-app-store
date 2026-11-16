import base64
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rose_app_rest',ROOT/'server.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class BridgeRESTTests(unittest.TestCase):
    def test_camelcase_response_and_hash(self):
        expected=bytes(range(32))
        result=app.normalized({'result':{'holdInvoice':'lnbc'+'a'*100,
                 'hash':base64.b64encode(expected).decode(),
                 'incomingMsat':'1280000','outgoingMsat':'300000000',
                 'expiresAt':'1794781665','direction':'toBLAKE2b'}})
        self.assertEqual(result['hold_invoice'],'lnbc'+'a'*100)
        self.assertEqual(result['hash'],expected.hex())
        self.assertEqual(result['incoming_msat'],'1280000')
    def test_participant_info_direction_objects(self):
        response = {
            'directions': [
                {'name':'toSHA256','open':False,'refusal_code':'no_liquidity',
                 'refusal':'not enough liquidity to pay this now'},
                {'name':'toBLAKE2b','open':True,'rate':236.8},
            ]
        }
        summary = app.summarize_bridge_info(response)
        self.assertEqual(summary['directions'], ['toBLAKE2b'])
        self.assertEqual(summary['unavailable_directions'][0]['name'], 'toSHA256')
        self.assertEqual(summary['unavailable_directions'][0]['refusal_code'], 'no_liquidity')
        self.assertIsNone(summary['sha256_ready'])
        self.assertIsNone(summary['swaps_in_flight'])
        self.assertIsNone(summary['enabled'])

    def test_operator_status_string_directions(self):
        summary = app.summarize_bridge_info({
            'enabled': True,
            'directions': ['toSHA256','toBLAKE2b'],
            'sha256_node': {'state':'ready'},
            'swaps_in_flight':0,
        })
        self.assertEqual(summary['directions'], ['toSHA256','toBLAKE2b'])
        self.assertFalse(summary['unavailable_directions'])
        self.assertEqual(summary['sha256_ready'], 'ready')
        self.assertEqual(summary['swaps_in_flight'], 0)

    def test_bridge_rest_requires_credentials(self):
        with patch.object(app,'REST_URL',''), patch.object(app,'REST_CERT',''), patch.object(app,'REST_MACAROON',''):
            with self.assertRaisesRegex(app.AppError,'not configured'):
                app.bridge_rest(['quote','lnbc'+'a'*120])

if __name__=='__main__': unittest.main()
