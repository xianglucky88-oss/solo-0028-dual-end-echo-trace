from collections import defaultdict


def closure_candidates(valid, tolerance):
    candidates=defaultdict(list)
    for a in (r for r in valid if r['side']=='left'):
        for b in (r for r in valid if r['side']=='right'):
            if a['polarity']==b['polarity'] and abs(a['position']-b['position'])<=tolerance:
                candidates[a['id']].append(b)
                candidates[b['id']].append(a)
    return candidates


def match_pairs(valid, candidates):
    matched, unresolved = [], []
    for r in valid:
        peers=candidates[r['id']]
        if len(peers)==1 and len(candidates[peers[0]['id']])==1:
            other=peers[0]
            if r['side']=='left':
                matched.append(dict(id=f"{r['id']}@{other['id']}",position=(r['position']+other['position'])/2,
                                    gap=abs(r['position']-other['position']),state='paired',polarity=r['polarity'],evidence=[r['id'],other['id']]))
            continue
        unresolved.append(r)
    return matched, unresolved
