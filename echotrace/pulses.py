def extract_pulses(side, trace, threshold):
    for first,mid,last in zip(trace,trace[1:],trace[2:]):
        val=mid['value']
        if abs(val)<threshold or not(abs(val)>abs(first['value']) and abs(val)>abs(last['value'])):
            continue
        evidence=[f"{side}/{r['id']}" for r in (first,mid,last)]
        key=f"{side}/{mid['id']}"
        sign='positive' if val>0 else 'negative'
        yield dict(id=key,side=side,time=mid['time'],value=val,state=sign,evidence=evidence)
