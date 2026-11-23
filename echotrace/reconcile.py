def summarize(model, facts, outputs):
    length = model['length']
    windows = {}
    for row in facts['window']:
        a,b = row['start'],row['end']
        if a is not None:
            windows[row['id']] = (a,b) if row['id'] == 'left' else (length-b,length-a)
    boundaries = sorted({0,length} | {x for span in windows.values() for x in span})
    result = []
    for n,(a,b) in enumerate(zip(boundaries,boundaries[1:]), 1):
        visible = [side for side,(start,end) in windows.items() if start <= a and b <= end]
        state = 'dual' if len(visible)==2 else visible[0] if visible else 'blind'
        result.append(dict(id=f'view-{n}', start=a, end=b, length=b-a, state=state,
                           evidence={'ends':visible,'closure':[r['id'] for r in outputs['pair'] if a < r['position'] < b]}))
    return result
