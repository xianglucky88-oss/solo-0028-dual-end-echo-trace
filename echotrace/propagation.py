def _table(model, side):
    segments = model.get('segments')
    if segments is None:
        return None
    ordered = segments if side == 'left' else list(reversed(segments))
    table = [(0.0, 0.0)]
    for segment in ordered:
        far, oneway = table[-1]
        table.append((far + segment['length'], oneway + segment['length'] / segment['speed']))
    return table


def _end_speeds(model, side):
    segments = model.get('segments')
    if side == 'left':
        return segments[0]['speed'], segments[-1]['speed']
    return segments[-1]['speed'], segments[0]['speed']


def distance(model, side, time):
    table = _table(model, side)
    if table is None:
        return (time - model['sides'][side]['zero']) * model['speed'] / 2
    oneway = (time - model['sides'][side]['zero']) / 2
    near, far = _end_speeds(model, side)
    if oneway <= 0:
        return oneway * near
    for (d0, u0), (d1, u1) in zip(table, table[1:]):
        if u0 <= oneway <= u1:
            if oneway == u0:
                return d0
            if oneway == u1:
                return d1
            return d0 + (oneway - u0) * (d1 - d0) / (u1 - u0)
    end_d, end_u = table[-1]
    return end_d + (oneway - end_u) * far


def time_at(model, side, dist):
    table = _table(model, side)
    if table is None:
        oneway = dist / model['speed']
    else:
        near, far = _end_speeds(model, side)
        if dist <= 0:
            oneway = dist / near
        else:
            oneway = None
            for (d0, u0), (d1, u1) in zip(table, table[1:]):
                if d0 <= dist <= d1:
                    if dist == d0:
                        oneway = u0
                    elif dist == d1:
                        oneway = u1
                    else:
                        oneway = u0 + (dist - d0) * (u1 - u0) / (d1 - d0)
                    break
            if oneway is None:
                end_d, end_u = table[-1]
                oneway = end_u + (dist - end_d) / far
    return model['sides'][side]['zero'] + 2 * oneway


def locate(model, peak):
    side = peak['side']
    data = model['sides'][side]
    dist=distance(model,side,peak['time'])
    state='outside' if not 0<=dist<=model['length'] else 'masked' if dist<data['dead'] else 'candidate'
    return dict(id=peak['id'],side=side,distance=dist,position=dist if side=='left' else model['length']-dist,
                          state=state,polarity=peak['state'],evidence=peak['evidence'])


def capture_window(model, side):
    data = model['sides'][side]
    trace = data['trace']
    a=max(data['dead'],0,distance(model,side,trace[0]['time']))
    b=min(model['length'],distance(model,side,trace[-1]['time']))
    return dict(id=side,start=a if a<b else None,end=b if a<b else None,state='covered' if a<b else 'blind')
