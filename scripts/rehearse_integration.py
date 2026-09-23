"""Rehearse approved work interrupted by the separately authenticated sender.

Requires a fresh movement-shift run scoped by TERMINAL_FEED_RUN on the server.
Writes private restart evidence to .local/integration-rehearsal.json.
"""
import argparse,json,os,time,uuid
from pathlib import Path
from datetime import datetime,timedelta
import httpx

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--url',default='http://127.0.0.1:8790')
p.add_argument('--run',required=True)
p.add_argument('--admin-code-file',default='.local/admin-code')
a=p.parse_args()
c=httpx.Client(base_url=a.url,timeout=180)
r=c.post('/api/session',json={'code':Path(a.admin_code_file).read_text().strip()});r.raise_for_status()
headers={'X-CSRF-Token':r.json()['csrf']}
def get(path):
 r=c.get(path,params={'run':a.run});r.raise_for_status();return r.json()
def post(path,payload):
 r=c.post(path,params={'run':a.run},json=payload,headers=headers);r.raise_for_status();return r.json()
def command(action,**extra):
 state=get('/api/state');receipt=post('/api/commands',dict(action=action,command_id=str(uuid.uuid4()),expected_revision=state['revision'],**extra))
 for _ in range(200):
  new=get('/api/state')
  if new['revision']>state['revision']:return new
  time.sleep(.1)
 raise RuntimeError('Command did not acknowledge; inspect command ledger')
s=get('/api/state')
if s['minute']!=0 or s.get('schedule'):raise SystemExit('Use a fresh paused movement shift')
req=post('/api/schedules',dict(expected_revision=s['revision'],focus_commitment='NORTH-RAIL',horizon=80))
for _ in range(360):
 rows=get('/api/schedules');job=next(r for r in rows if r['id']==req['id'])
 if job['status']=='failed':raise RuntimeError(job['error'])
 if job['status']=='completed':break
 time.sleep(.5)
else:raise RuntimeError('Comparison timed out')
plan=next(p for p in job['result']['candidates'] if p['key']=='deadline' and p['validation']=='passed')
command('approve_schedule',plan_id=plan['plan_id'])
s=command('advance',minutes=8)
cargo=next(c for c in s['containers'] if c.get('custody',{}).get('id','').startswith('TT'))
job=next(j for j in s['jobs'] if j['id']==cargo['job_id'])
receiver=next(e for stage in job['movement_stages'] if stage['kind']=='setdown' for e in stage['resources'] if not e.startswith('TT'))
identity=next(m for m in s['source_identities'] if m['entity_id']==receiver and m['source']=='fleet')
observed=datetime.fromisoformat(s['dataset']['shift_start'].replace('Z','+00:00'))+timedelta(minutes=s['minute'])
event=dict(schema_version=1,source='fleet',event_id='rehearsal-'+str(uuid.uuid4()),external_id=identity['external_id'],kind='equipment.status',observed_at=observed.isoformat(),sequence=1,value='failed')
auth={'Authorization':'Bearer '+os.environ['TERMINAL_FEED_TOKEN']}
first=c.post('/api/integrations/equipment',params={'run':a.run},json=event,headers=auth);first.raise_for_status();assert first.json()['status']=='applied'
again=c.post('/api/integrations/equipment',params={'run':a.run},json=event,headers=auth);again.raise_for_status();assert again.json()['status']=='duplicate'
after=get('/api/state');holder=next(x for x in after['containers'] if x['id']==cargo['id'])['custody']
assert after['schedule']['status']=='interrupted' and after['minute']==8 and holder==cargo['custody']
out=Path('.local/integration-rehearsal.json');out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(dict(run=a.run,revision=after['revision'],minute=8,cargo=cargo['id'],custody=holder,receiver=receiver,schedule_status='interrupted',event=event,receipt=first.json()),indent=2))
print('External failure interrupted approved work; duplicate had no repeated equipment effect; custody retained.')
