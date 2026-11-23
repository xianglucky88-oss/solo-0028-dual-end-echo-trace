from .contract import invariant, num, obj, records, unique_order
from .propagation import capture_window, locate
from .pulses import extract_pulses


def parse(source):
    length=num(source.get('length'),'长度（米）',1,1e5)
    speed=num(source.get('speed'),'传播速度（米每纳秒）',0.01,0.3)
    tolerance=num(source.get('tolerance'),'闭合容差（米）',0.001,length)
    sides={}
    for side in ('left','right'):
        data=obj(source.get(side),'端头数据')
        trace=[dict(id=r['id'],time=num(r.get('time'),'采样时刻（纳秒）',0),value=num(r.get('value'),'归一化幅值',-1,1))
               for r in records(data.get('trace'),'波形样点',600,3)]
        unique_order(trace,'time','波形时标')
        sides[side]=dict(trace=trace,zero=num(data.get('zero'),'端头零点（纳秒）',0),
                         dead=num(data.get('dead'),'端头盲区（米）',0,length),
                         threshold=num(data.get('threshold'),'脉冲幅值门限',0.001,1))
    return dict(length=length,speed=speed,tolerance=tolerance,sides=sides)


def evaluate(model):
    raw,peaks,locations,windows=[],[],[],[]
    for side,data in model['sides'].items():
        trace=data['trace']
        raw.extend(dict(id=f"{side}/{r['id']}",side=side,time=r['time'],value=r['value'],state='observed') for r in trace)
        windows.append(capture_window(model, side))
        for peak in extract_pulses(side, trace, data['threshold']):
            peaks.append(peak)
            locations.append(locate(model, peak))
    return dict(wave=raw,peak=peaks,location=locations,window=windows)
