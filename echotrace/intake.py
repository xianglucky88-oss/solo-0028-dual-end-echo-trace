"""分批收档的领域逻辑：登记、片段回执、缺口/冲突快照与严格拼装。

该模块只做纯数据处理，不接触数据库和 HTTP；持久化在 intake_store 中，
编排与封存入口在 service 中。
"""
from .contract import ContractError, canonical, digest, enum, ident, invariant, num, obj, records, unique_order

SIDES = ('left', 'right')
RECEIVED, QUARANTINED = 'received', 'quarantined'
MAX_SEQ_SPAN = 600


def registration_id(registration):
    """登记内容寻址：同一份登记重复提交只得到同一个收档批次。"""
    return digest(canonical(registration))


def _side_plan(body, side):
    data = obj(body.get(side), f'{side} 端登记')
    start = num(data.get('sequence_start'), f'{side} 端起始采样序号', 0, 1e9)
    end = num(data.get('sequence_end'), f'{side} 端截止采样序号', 0, 1e9)
    invariant(float(start).is_integer() and float(end).is_integer(), f'{side} 端采样序号应为整数')
    start, end = int(start), int(end)
    invariant(start <= end, f'{side} 端截止序号不能小于起始序号')
    count = end - start + 1
    invariant(count <= MAX_SEQ_SPAN, f'{side} 端序号范围不能超过 {MAX_SEQ_SPAN} 个')
    invariant(3 <= count, '每端波形至少需要 3 个采样序号')
    plan = dict(sequence_start=start, sequence_end=end,
                zero=num(data.get('zero'), '端头零点（纳秒）', 0),
                dead=num(data.get('dead'), '端头盲区（米）', 0),
                threshold=num(data.get('threshold'), '脉冲幅值门限', 0.001, 1))
    return plan


def parse_registration(body):
    """解析一次台架采集登记：所属线缆、两端序号范围与完整档所需标定。"""
    body = obj(body, '分批登记')
    cable = ident(body.get('cable'), '所属线缆标识')
    length = num(body.get('length'), '长度（米）', 1, 1e5)
    speed = num(body.get('speed'), '传播速度（米每纳秒）', 0.01, 0.3)
    tolerance = num(body.get('tolerance'), '闭合容差（米）', 0.001, length)
    registration = dict(cable=cable, length=length, speed=speed, tolerance=tolerance)
    for side in SIDES:
        plan = _side_plan(body, side)
        invariant(0 <= plan['dead'] <= length, f'{side} 端盲区不能超出线缆长度')
        registration[side] = plan
    return registration


def receipt_key(intake_id, side, seq, origin, fragment_digest):
    """回执内容寻址键：同一来源重复提交同一份片段只取回同一张回执；
    不同来源即使读数完全相同，也各自保留回执（证据读数仍按指纹判同）。"""
    return digest(canonical([intake_id, side, seq, origin, fragment_digest]))


def parse_fragment(body, registration):
    """解析逐份提交的带序号波形片段，并校验是否落在登记范围内。"""
    body = obj(body, '波形片段')
    intake_id = ident(body.get('intake'), '收档批次标识')
    side = enum(body.get('side'), SIDES, '波形端头')
    seq = num(body.get('sequence'), '采样序号', 0, 1e9)
    invariant(float(seq).is_integer(), '采样序号应为整数')
    seq = int(seq)
    source = obj(body.get('source'), '片段来源')
    origin = ident(source.get('origin'), '片段来源标识')
    samples = records(body.get('samples'), '波形样点', 600, 1)
    points = [dict(id=ident(r.get('id'), '样点原标识'),
                   time=num(r.get('time'), '采样时刻（纳秒）', 0),
                   value=num(r.get('value'), '归一化幅值', -1, 1)) for r in samples]
    unique_order(points, 'time', '片段内波形时标')
    plan = registration[side]
    invariant(plan['sequence_start'] <= seq <= plan['sequence_end'], '片段序号不在登记范围内')
    fragment = dict(intake=intake_id, side=side, sequence=seq,
                    source=dict(origin=origin), samples=points)
    return fragment, receipt_key(intake_id, side, seq, origin, digest(canonical(fragment['samples'])))


def _reading_fingerprint(samples):
    """同端同序号的样点，原标识、时刻、幅值全部相符才是同一条证据。"""
    return digest(canonical(samples))


def snapshot(registration, receipts):
    """按登记范围给出每端已收/缺口、重叠冲突、隔离记录和材料清单基准。"""
    sides = {}
    conflicts = []
    for side in SIDES:
        plan = registration[side]
        sequences = list(range(plan['sequence_start'], plan['sequence_end'] + 1))
        covered, missing, quarantined = [], [], []
        by_seq = {seq: [] for seq in sequences}
        for receipt in receipts:
            if receipt['side'] != side:
                continue
            if receipt['status'] == QUARANTINED:
                quarantined.append(receipt['sequence'])
                continue
            by_seq[receipt['sequence']].append(receipt)
        for seq in sequences:
            group = by_seq[seq]
            if not group:
                missing.append(seq)
            else:
                covered.append(seq)
            if len({_reading_fingerprint(r['samples']) for r in group}) > 1:
                conflicts.append(dict(
                    side=side, sequence=seq,
                    receipts=[dict(receipt=r['receipt'], origin=r['origin'],
                                   fragment_digest=r['fragment_digest']) for r in group]))
        sides[side] = dict(sequence_start=plan['sequence_start'], sequence_end=plan['sequence_end'],
                           covered=covered, missing=missing,
                           quarantined=sorted(quarantined),
                           receipts=[dict(receipt=r['receipt'], sequence=r['sequence'],
                                          origin=r['origin'], status=r['status'],
                                          fragment_digest=r['fragment_digest'])
                                     for r in sorted((x for x in receipts if x['side'] == side),
                                                     key=lambda r: (r['sequence'], r['recv_order']))])
    view = dict(sides={side: dict(sequence_start=v['sequence_start'], sequence_end=v['sequence_end'],
                                  covered=v['covered'], missing=v['missing'],
                                  quarantined=v['quarantined'])
                       for side, v in sides.items()},
                conflicts=conflicts)
    return dict(intake=registration_id(registration), cable=registration['cable'],
                sides=sides, conflicts=conflicts,
                complete=all(not v['missing'] for v in view['sides'].values()),
                has_conflict=bool(conflicts),
                ready=all(not v['missing'] for v in view['sides'].values()) and not conflicts,
                basis=digest(canonical(view)), view=view)


def assemble_source(registration, receipts):
    """把各份片段严格拼成原有一次性接口所需的完整来源包。

    不丢点、不重排时标：序号缺失、同序号读数冲突、跨片段时标非严格递增或
    跨片段原标识重复都直接报错，由调用方以 409 拒绝归档。
    """
    current = snapshot(registration, receipts)
    if current['conflicts']:
        raise ContractError('存在同序号不同读数的重叠片段，不能归档', 409,
                            dict(snapshot=current))
    source = dict(id=registration['cable'], length=registration['length'],
                  speed=registration['speed'], tolerance=registration['tolerance'])
    used = {}
    for side in SIDES:
        plan = registration[side]
        chosen = {}
        for receipt in receipts:
            if receipt['side'] == side and receipt['status'] == RECEIVED:
                chosen.setdefault(receipt['sequence'], receipt)
        missing = [seq for seq in range(plan['sequence_start'], plan['sequence_end'] + 1)
                   if seq not in chosen]
        if missing:
            raise ContractError(f'{side} 端还有 {len(missing)} 个序号未收齐，不能归档', 409,
                                dict(snapshot=current))
        trace, side_used, seen_ids = [], [], set()
        for seq in range(plan['sequence_start'], plan['sequence_end'] + 1):
            receipt = chosen[seq]
            for point in receipt['samples']:
                if point['id'] in seen_ids:
                    raise ContractError(
                        f'{side} 端序号 {seq} 的原标识 {point["id"]} 与其他片段重复，不能合并',
                        409, dict(snapshot=current))
                seen_ids.add(point['id'])
                trace.append(dict(point))
            side_used.append(receipt['receipt'])
        try:
            unique_order(trace, 'time', '合并后波形时标')
        except ContractError:
            raise ContractError(
                '合并后波形时标不是严格递增；按规则不得丢点凑序，请核对片段',
                409, dict(snapshot=current))
        source[side] = dict(zero=plan['zero'], dead=plan['dead'], threshold=plan['threshold'],
                            trace=trace)
        used[side] = side_used
    return source, used, current
