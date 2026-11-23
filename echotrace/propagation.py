def distance(model, side, time):
    return (time-model['sides'][side]['zero'])*model['speed']/2


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
