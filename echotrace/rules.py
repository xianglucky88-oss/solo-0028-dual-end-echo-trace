from .pairing import closure_candidates, match_pairs
from .propagation import time_at


def _sample_support(trace, limit, time):
    if any(r['time'] == time for r in trace):
        return True
    return any(a['time'] <= time <= b['time'] and b['time'] - a['time'] <= limit
               for a, b in zip(trace, trace[1:]))


def _revise_revisit(model, rows):
    limit = model['sample_gap_limit']
    result = []
    for row in rows:
        side = row['side']
        time = time_at(model, side, row['distance'])
        supported = _sample_support(model['sides'][side]['trace'], limit, time)
        state = 'blind' if row['state'] == 'unconfirmed' and not supported else row['state']
        result.append(dict(row, state=state,
                           evidence=dict(peaks=row['evidence'], time=time, support=supported)))
    return result


def decide(model,facts):
    valid=[r for r in facts['location'] if r['state']=='candidate']
    candidates = closure_candidates(valid, model['tolerance'])
    windows={r['id']:r for r in facts['window']}
    matched, unresolved = match_pairs(valid, candidates)
    pending, revisit = [], []
    for r in unresolved:
        peers = candidates[r['id']]
        other_side='right' if r['side']=='left' else 'left'
        expected=model['length']-r['distance']
        window=windows[other_side]
        covered=window['start'] is not None and window['start']<=expected<window['end']
        state='ambiguous' if peers else 'unconfirmed' if covered else 'blind'
        pending.append(dict(id=r['id'],position=r['position'],state=state,side=r['side'],evidence=[p['id'] for p in peers]))
        revisit.append(dict(id=r['id'],state=state,side=other_side,distance=expected,evidence=[r['id']]))
    revisit.extend(dict(id=r['id'],state='masked',side=r['side'],distance=r['distance'],evidence=r['evidence'])
                   for r in facts['location'] if r['state']=='masked')
    revisit=sorted(revisit,key=lambda r:(r['side'],r['distance'],r['id']))
    if model.get('segments') is not None:
        revisit=_revise_revisit(model,revisit)
    return dict(facts,pair=matched,pending=pending,revisit=revisit)
