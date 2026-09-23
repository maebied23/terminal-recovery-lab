"""Atomic state/event persistence and idempotent command handling."""
import json,sqlite3
from datetime import datetime,timezone
from .domain import initial_state,transition

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT UNIQUE NOT NULL, occurred_minute INTEGER NOT NULL, recorded_at TEXT NOT NULL, body TEXT NOT NULL, snapshot TEXT NOT NULL);')
            db.execute('INSERT OR IGNORE INTO state VALUES (1,?)',(json.dumps(initial_state()),))
    def connect(self): return sqlite3.connect(self.path,timeout=10)
    def read(self):
        with self.connect() as db: return json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
    def events(self):
        with self.connect() as db:
            return [dict(sequence=r[0],command_id=r[1],occurred_minute=r[2],recorded_at=r[3],event=json.loads(r[4])) for r in db.execute('SELECT sequence,command_id,occurred_minute,recorded_at,body FROM events ORDER BY sequence DESC LIMIT 100')]
    def apply(self,command):
        key=command.get('command_id')
        if not isinstance(key,str) or not key or len(key)>128: raise ValueError('command_id required (max 128 characters)')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT body,snapshot FROM events WHERE command_id=?',(key,)).fetchone()
            if prior:
                if json.loads(prior[0])['command']!=command: raise ValueError('Idempotency key reused for different command')
                return json.loads(prior[1])
            current=json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if command.get('expected_revision')!=current['revision']: raise ValueError('Stale state: refresh before applying')
            state,event=transition(current,command); event['command']=command
            encoded=json.dumps(state)
            db.execute('UPDATE state SET body=? WHERE id=1',(encoded,))
            db.execute('INSERT INTO events(command_id,occurred_minute,recorded_at,body,snapshot) VALUES (?,?,?,?,?)',(key,state['minute'],datetime.now(timezone.utc).isoformat(),json.dumps(event),encoded))
            return state
