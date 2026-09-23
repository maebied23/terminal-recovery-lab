import tempfile,unittest
from pathlib import Path
from terminal.domain import initial_state,transition,blockers,recommendations
from terminal.store import Store

class DomainTests(unittest.TestCase):
    def test_blocked_cargo_and_release(self):
        s=initial_state()
        with self.assertRaises(ValueError):transition(s,{'action':'dispatch','job':'J2'})
        with self.assertRaises(ValueError):transition(s,{'action':'dispatch','job':'J3'})
        self.assertEqual(s,initial_state())
    def test_failure_pauses_without_teleporting(self):
        s,_=transition(initial_state(),{'action':'dispatch','job':'J1'})
        s,_=transition(s,{'action':'fail','equipment':'YC1'})
        s,_=transition(s,{'action':'advance'})
        self.assertEqual(s['jobs'][0]['remaining'],4)
        self.assertEqual(s['positions']['in_transit'],['C2'])
        with self.assertRaises(ValueError):transition(s,{'action':'reassign','job':'J1','equipment':'YC2'})
    def test_recovery_and_completion(self):
        s,_=transition(initial_state(),{'action':'fail','equipment':'YC1'})
        rec=recommendations(s)[0];self.assertEqual(rec['action'],'reassign')
        s,_=transition(s,rec)
        s,_=transition(s,{'action':'dispatch','job':'J1'})
        for _ in range(4):s,_=transition(s,{'action':'advance'})
        s,_=transition(s,{'action':'reassign','job':'J2','equipment':'YC2'})
        self.assertEqual(blockers(s,s['jobs'][1]),[])
        s,_=transition(s,{'action':'dispatch','job':'J2'})
        for _ in range(6):s,_=transition(s,{'action':'advance'})
        self.assertEqual(s['positions']['rail'],['C1'])
        self.assertEqual(s['jobs'][1]['completed_at'],10)
        self.assertEqual(initial_state()['positions']['A1'],['C1','C2'])

class PersistenceTests(unittest.TestCase):
    def test_atomic_rejection_idempotency_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.db';store=Store(path)
            cmd={'action':'fail','equipment':'YC1','command_id':'x','expected_revision':0}
            first=store.apply(cmd);self.assertEqual(store.apply(cmd),first)
            self.assertEqual(len(store.events()),1)
            with self.assertRaises(ValueError):store.apply(dict(cmd,action='repair'))
            with self.assertRaises(ValueError):store.apply(dict(cmd,command_id='y'))
            self.assertEqual(Store(path).read(),first)
            self.assertEqual(len(store.events()),1)

if __name__=='__main__':unittest.main()
