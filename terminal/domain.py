"""Pure rules and transitions for the deliberately small synthetic yard."""
from copy import deepcopy


def initial_state():
    return dict(revision=0, minute=0, equipment={'YC1': 'available', 'YC2': 'available'},
        positions={'A1': ['C1', 'C2'], 'A2': [], 'B1': ['C3'], 'rail': []},
        jobs=[dict(id='J1', cargo='C2', source='A1', destination='A2', deadline=30, duration=4, equipment='YC1', depends=[], status='queued', kind='rehandle', released=True),
              dict(id='J2', cargo='C1', source='A1', destination='rail', deadline=12, duration=6, equipment='YC1', depends=['J1'], status='queued', kind='outbound', released=True),
              dict(id='J3', cargo='C3', source='B1', destination='rail', deadline=18, duration=5, equipment='YC2', depends=[], status='queued', kind='outbound', released=False)], active=None)


def blockers(state, job):
    reasons=[]
    if state['active']: reasons.append('Shared transfer lane is occupied')
    if state['equipment'].get(job['equipment']) != 'available': reasons.append('Assigned crane unavailable')
    done={j['id'] for j in state['jobs'] if j['status']=='completed'}
    if not set(job['depends']) <= done: reasons.append('Predecessor move incomplete')
    stack=state['positions'][job['source']]
    if not stack or stack[-1] != job['cargo']: reasons.append('Cargo is not at the top of its source stack')
    if job['destination'] != 'rail' and len(state['positions'][job['destination']]) >= 2: reasons.append('Destination stack full')
    if job['kind']=='outbound' and not job['released']: reasons.append('Outbound authorization missing')
    return reasons


def transition(original, command):
    state=deepcopy(original); action=command['action']; details={}
    job=next((j for j in state['jobs'] if j['id']==command.get('job')),None)
    if action in ('dispatch','reassign','authorize') and not job: raise ValueError('Unknown job')
    if action=='dispatch':
        if job['status']!='queued': raise ValueError('Job is not queued')
        reasons=blockers(state,job)
        if reasons: raise ValueError('; '.join(reasons))
        job['status']='running'; state['active']=job['id']; job['remaining']=job['duration']
        state['positions'][job['source']].pop(); state['positions']['in_transit']=[job['cargo']]
        details={'job':job['id'],'event':'MoveStarted'}
    elif action=='advance':
        state['minute']+=1
        if state['active']:
            moving=next(j for j in state['jobs'] if j['id']==state['active'])
            if state['equipment'][moving['equipment']]=='available': moving['remaining']-=1
            if moving['remaining']==0:
                state['positions'][moving['destination']].append(moving['cargo'])
                state['positions']['in_transit']=[]; moving['status']='completed'
                moving['completed_at']=state['minute']; state['active']=None
                details={'job':moving['id'],'event':'MoveCompleted'}
    elif action in ('fail','repair'):
        equipment=command.get('equipment')
        if equipment not in state['equipment']: raise ValueError('Unknown equipment')
        state['equipment'][equipment]='failed' if action=='fail' else 'available'
        details={'equipment':equipment}
    elif action=='reassign':
        equipment=command.get('equipment')
        if job['status']!='queued': raise ValueError('Only queued jobs may be reassigned')
        if state['equipment'].get(equipment)!='available': raise ValueError('Target crane unavailable')
        job['equipment']=equipment; details={'job':job['id'],'equipment':equipment}
    elif action=='authorize':
        job['released']=True; details={'job':job['id'],'source':'synthetic authority'}
    else: raise ValueError('Unknown action')
    state['revision']+=1
    cargo=[c for values in state['positions'].values() for c in values]
    if sorted(cargo)!=['C1','C2','C3']: raise AssertionError('Cargo conservation violated')
    return state,dict(type=details.pop('event',action), **details)


def recommendations(state):
    """Transparent eligible-deadline heuristic, not ML or an optimizer."""
    suggestions=[]
    for job in sorted(state['jobs'],key=lambda j:min([j['deadline']]+[x['deadline'] for x in state['jobs'] if j['id'] in x['depends']])):
        if job['status']!='queued': continue
        reasons=blockers(state,job)
        if not reasons:
            suggestions.append(dict(action='dispatch',job=job['id'],reason='Eligible move; order includes direct dependent deadlines'))
        elif state['equipment'][job['equipment']]=='failed':
            alternate=next((e for e,status in state['equipment'].items() if status=='available'),None)
            if alternate: suggestions.append(dict(action='reassign',job=job['id'],equipment=alternate,reason='Failed crane; alternate compatible under this fixture’s shared-work-area assumption'))
    return suggestions
