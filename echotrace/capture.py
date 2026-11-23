from .propagation import distance


def capture_regions(model, limit):
    result = []
    for side, data in model['sides'].items():
        for a, b in zip(data['trace'], data['trace'][1:]):
            if b['time']-a['time'] <= limit:
                continue
            local_start = max(data['dead'], distance(model, side, a['time']))
            local_end = min(model['length'], distance(model, side, b['time']))
            if local_start >= local_end:
                continue
            start, end = (local_start, local_end) if side == 'left' else (model['length']-local_end, model['length']-local_start)
            result.append(dict(id=f"{side}/{a['id']}@{b['id']}", side=side, start=start, end=end,
                               state='blind', evidence=[f"{side}/{r['id']}" for r in (a,b)]))
    return result


def supported_visibility(visibility, gaps, pairs):
    edges = sorted({r[k] for rows in (visibility, gaps) for r in rows for k in ('start', 'end')})
    result = []
    for i, (a,b) in enumerate(zip(edges, edges[1:]), 1):
        base = next(r for r in visibility if r['start'] <= a and b <= r['end'])
        holes = [r for r in gaps if r['start'] <= a and b <= r['end']]
        visible = [side for side in base['evidence']['ends'] if not any(r['side'] == side for r in holes)]
        result.append(dict(id=f'capture-{i}', start=a, end=b, state='dual' if len(visible) == 2 else visible[0] if visible else 'blind',
                           evidence={'location_only': base['id'], 'ends': visible, 'gaps': [r['id'] for r in holes],
                                     'closures': [r['id'] for r in pairs if a <= r['position'] < b]}))
    return result


def sample_support(model, outputs, limit):
    result = []
    times = {f"{side}/{r['id']}": r['time'] for side, data in model['sides'].items() for r in data['trace']}
    for row in outputs['peak']:
        side = row['side']
        a, m, b = (times[key] for key in row['evidence'])
        result.append(dict(id=row['id'], side=side, time=m, lo=m-a, hi=b-m,
                           state='sparse' if max(m-a,b-m) > limit else 'supported',
                           evidence=row['evidence']))
    return result
