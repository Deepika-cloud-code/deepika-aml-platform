import unittest
from aml.core import normalize_esplora, risk_score

class PipelineTest(unittest.TestCase):
    def test_normalizer(self):
        tx={'txid':'a'*64, 'vin':[{'prevout':{'scriptpubkey_address':'a'}}],
            'vout':[{'scriptpubkey_address':'b','value':100000000}],
            'fee':1000,'status':{'confirmed':False}}
        e=normalize_esplora(tx)
        self.assertEqual(e['event_id'],'bitcoin:'+'a'*64)
        self.assertEqual(e['output_btc'],1)
        self.assertEqual(e['fee_btc'],0.00001)
    def test_risk(self):
        score,severity,why=risk_score({'amount_btc':6,'amount_usd':200000,
             'input_count':1,'output_count':1,'is_synthetic':False})
        self.assertEqual((score,severity),(70,'High'))

if __name__=='__main__': unittest.main()
