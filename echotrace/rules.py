from .pairing import closure_candidates, match_pairs


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
    return dict(facts,pair=matched,pending=pending,revisit=sorted(revisit,key=lambda r:(r['side'],r['distance'],r['id'])))
