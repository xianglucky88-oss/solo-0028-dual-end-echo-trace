import argparse
import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .server import CONFIG, PREFIX, ROOT, serve
from .intake import registration_id


def request(port, route, body=None, status=200):
    url = f'http://127.0.0.1:{port}{PREFIX}{route}'
    opts = {} if body is None else dict(data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    response = None
    try:
        response = urlopen(Request(url, **opts), timeout=5)
    except HTTPError as failure:
        response = failure
    with response:
        if response.status != status:
            raise ValueError(f'{route}：状态码 {response.status}，预期 {status}；{response.read(300)!r}')
        return json.load(response), response.headers


def observe(rows, row_id, field, target):
    result = next((row for row in rows if row['id'] == row_id), None)
    if field is None:
        if result is not None:
            raise ValueError(f'{row_id} 不应出现在结果中')
        return
    actual = result.get(field) if result is not None else None
    ok = isclose(actual, target, abs_tol=1e-8) if type(target) is float and type(actual) in (int,float) else actual == target
    if not ok or result is None or field not in result:
        raise ValueError(f'{row_id}.{field} 为 {actual!r}，应为 {target!r}')


def post(port, route, body, status=200):
    return request(port, route, body, status)


def side_samples(trace, sequences):
    """把完整波形按序号切成片段。"""
    assert len(trace) == len(sequences)
    return {seq: [dict(trace[i])] for i, seq in enumerate(sequences)}


def fragment(intake_id, side, seq, samples, origin):
    return dict(intake=intake_id, side=side, sequence=seq,
                source=dict(origin=origin), samples=samples)


def make_registration(data):
    return dict(
        cable=data['id'], length=data['length'], speed=data['speed'],
        tolerance=data['tolerance'],
        # 甲端 8 条样点登记为 7 个序号：序号 1 的片段一次携带两条连续样点
        left=dict(sequence_start=0, sequence_end=6,
                  **{k: data['left'][k] for k in ('zero', 'dead', 'threshold')}),
        right=dict(sequence_start=0, sequence_end=7,
                   **{k: data['right'][k] for k in ('zero', 'dead', 'threshold')}))


def audit_batch_intake(port):
    data = json.loads((ROOT / 'examples' / 'sample.json').read_text(encoding='utf8'))
    right_seq = list(range(8))
    registration = make_registration(data)
    expected_intake = registration_id(registration)

    # 1) 先登记；重复登记只取回同一批次和原回执
    opened = post(port, 'intake/register', registration)[0]
    if opened['intake'] != expected_intake or opened['receipt']['duplicate']:
        raise ValueError('首次登记应返回内容寻址批次且不是重复回执')
    again = post(port, 'intake/register', registration)[0]
    if again['intake'] != expected_intake or not again['receipt']['duplicate']:
        raise ValueError('重复登记应得到同一批次并标记为重复')
    if any(snap['sides']['left']['missing'] != list(range(7)) for snap in (opened['snapshot'], again['snapshot'])):
        raise ValueError('刚登记时全部序号都应显示为缺口')
    if request(port, 'intake/' + '0' * 64, status=404)[0].get('error') is None:
        raise ValueError('未知批次应返回 404')

    left_parts = side_samples(data['left']['trace'], list(range(8)))
    right_parts = side_samples(data['right']['trace'], right_seq)

    # 甲端 7 个登记序号分配 8 条样点：序号 1 的片段一次携带点1、点2 两条连续
    # 样点；序号 2..6 顺延携带样点 3..7。每个序号一份片段，每条样点只出现一次，
    # 拼装按序号展开后与样例完整波形逐条一致，时标严格递增。
    left_points = {0: left_parts[0], 1: left_parts[1] + left_parts[2]}
    for seq, point_index in zip(range(2, 7), range(3, 8)):
        left_points[seq] = left_parts[point_index]

    def left_fragment(seq):
        return fragment(expected_intake, 'left', seq, left_points[seq], f'left-来源-{seq}')

    # 2) 交错到达、允许乱序：乙端先到、甲端穿插
    order = [('right', 0), ('left', 6), ('right', 3), ('left', 0), ('left', 5), ('right', 1)]
    receipts = {}
    for side, seq in order:
        body = left_fragment(seq) if side == 'left' else fragment(
            expected_intake, side, seq, right_parts[seq], f'right-来源-{seq}')
        out = post(port, 'intake/fragment', body)[0]
        receipts[(side, seq)] = out['receipt']['receipt']
        if out['receipt']['duplicate']:
            raise ValueError('首次提交的片段不应是重复回执')
    snap = request(port, f'intake/{expected_intake}')[0]
    if snap['sides']['left']['covered'] != [0, 5, 6] or snap['sides']['left']['missing'] != [1, 2, 3, 4]:
        raise ValueError('已收与缺口序号应按登记范围实时更新')
    if snap['sides']['right']['covered'] != [0, 1, 3] or snap['complete'] or snap['ready']:
        raise ValueError('两端未齐时批次不应显示可归档')

    # 多样点片段：序号 1 一次携带两条连续样点；重复交同一份只能得到原回执
    merged_body = left_fragment(1)
    first = post(port, 'intake/fragment', merged_body)[0]
    merged_receipt = first['receipt']['receipt']
    second = post(port, 'intake/fragment', merged_body)[0]
    if not second['receipt']['duplicate'] or second['receipt']['receipt'] != merged_receipt:
        raise ValueError('重复交同一份只能得到原回执')
    receipts[('left', 1)] = merged_receipt

    # 3) 完全重叠：同端同序号、原标识/时刻/幅值全相符 → 同一条证据，不算冲突
    overlap = fragment(expected_intake, 'left', 6, left_points[6], '另一导出人')
    same = post(port, 'intake/fragment', overlap)[0]
    if same['snapshot']['conflicts']:
        raise ValueError('原标识、时刻、幅值都相符的重叠样点应视为同一条证据')
    if same['receipt']['receipt'] == receipts[('left', 6)]:
        raise ValueError('不同来源的独立提交应保留各自回执，只共享证据读数')

    # 补齐剩余序号，每条样点仍只归属一份片段
    for side, seq in [('left', 2), ('left', 3), ('left', 4),
                      ('right', 2), ('right', 4), ('right', 5), ('right', 6), ('right', 7)]:
        body = left_fragment(seq) if side == 'left' else fragment(
            expected_intake, side, seq, right_parts[seq], f'right-来源-{seq}')
        post(port, 'intake/fragment', body)
    snap = request(port, f'intake/{expected_intake}')[0]
    if not snap['complete'] or not snap['ready'] or snap['conflicts']:
        raise ValueError('两端齐全且无冲突时才应可归档')

    # 4) 冲突片段恰好赶在确认前到达：同一序号不同读数，不默选最后一份
    conflict_point = dict(data['left']['trace'][4])
    conflict_point['value'] = 0.321
    conflict = fragment(expected_intake, 'left', 4, [conflict_point], '迟到的冲突来源')
    post(port, 'intake/fragment', conflict)
    snap = request(port, f'intake/{expected_intake}')[0]
    if not snap['conflicts'] or snap['ready']:
        raise ValueError('重叠片段读数不同应产生争议并阻止归档')
    row = snap['conflicts'][0]
    if row['side'] != 'left' or row['sequence'] != 4 or len(row['receipts']) != 2:
        raise ValueError('冲突应指出受影响序号及两份来源')
    origins = {r['origin'] for r in row['receipts']}
    if origins != {'left-来源-4', '迟到的冲突来源'}:
        raise ValueError('冲突来源清单应同时列出两份片段')
    confirm_id = 'a' * 64
    blocked = post(port, 'intake/confirm',
                   dict(intake=expected_intake, confirm=confirm_id, basis=snap['basis']), status=409)[0]
    if not blocked.get('snapshot') or not blocked['snapshot']['conflicts']:
        raise ValueError('有争议时确认应被拒绝并回带当前材料清单')

    # 5) 资料员核对后、确认前另一窗口改了清单 → 旧基准不能封存没见过的内容
    stale_basis = snap['basis']
    conflict_receipt = row['receipts'][-1]['receipt']
    post(port, 'intake/quarantine',
         dict(intake=expected_intake, receipt=conflict_receipt, reason='读数与台架原标识不符，隔离复核'))
    fresh = request(port, f'intake/{expected_intake}')[0]
    if fresh['basis'] == stale_basis or not fresh['ready']:
        raise ValueError('隔离改变材料清单后基准应更新并恢复可归档')
    stale = post(port, 'intake/confirm',
                 dict(intake=expected_intake, confirm='b' * 64, basis=stale_basis), status=409)[0]
    if stale.get('snapshot', {}).get('basis') != fresh['basis']:
        raise ValueError('过期基准确认应被拒绝并回带最新清单')

    # 6) 确认封存：响应丢失后用同一确认标识重试，查回同一份成果与实际片段
    result = post(port, 'intake/confirm',
                  dict(intake=expected_intake, confirm=confirm_id, basis=fresh['basis']))[0]
    if result['duplicate']:
        raise ValueError('首次确认不应标记为重复')
    retry = post(port, 'intake/confirm',
                 dict(intake=expected_intake, confirm=confirm_id, basis=fresh['basis']))[0]
    if not retry['duplicate'] or retry['packet']['digest'] != result['packet']['digest']:
        raise ValueError('重试同一次确认必须查回同一份成果，不能半成功')
    if retry['confirmation']['used_receipts'] != result['used_receipts']:
        raise ValueError('重试结果应保留实际使用的片段回执')

    # 封存成果与原有一次性接口对同一完整波形的结果完全一致
    one_shot = request(port, 'evaluate', data)[0]
    if retry['packet'] != one_shot:
        raise ValueError('分批收档成果必须通过原有校验并与一次性整包结果一致')
    revisions = request(port, 'revisions')[0]
    if not any(rev['digest'] == result['packet']['digest'] for rev in revisions):
        raise ValueError('封存成果应出现在原版本列表中，可比较和下载')
    if request(port, f"export/{result['packet']['digest']}")[0] != result['packet']:
        raise ValueError('分批成果应能通过原导出口下载完整快照')

    # 同一批材料再确认一次（新确认标识）得到同一内容寻址成果，不产生新版本
    second_confirm = post(port, 'intake/confirm',
                          dict(intake=expected_intake, confirm='c' * 64, basis=fresh['basis']))[0]
    if second_confirm['packet']['digest'] != result['packet']['digest'] or second_confirm['confirmation']['created_packet']:
        raise ValueError('相同材料重复归档应复用同一成果版本')
    if not second_confirm['confirmation'].get('created_confirmation'):
        raise ValueError('新的确认标识应留下独立的确认记录')

    # 7) 工作台重启：登记、回执、确认都持久化，不会换一套材料
    return result, data, registration


def audit_restart(db_path, port, sealed, data, registration):
    with serve(db_path, 0) as restarted:
        rp = restarted.server_port
        thread = Thread(target=restarted.serve_forever, daemon=True)
        thread.start()
        try:
            intake_id = registration_id(registration)
            snap = request(rp, f'intake/{intake_id}')[0]
            if snap['basis'] != sealed['snapshot']['basis']:
                raise ValueError('重启后材料清单应与重启前一致')
            retry = post(rp, 'intake/confirm',
                         dict(intake=intake_id, confirm='a' * 64, basis=sealed['snapshot']['basis']))[0]
            if not retry['duplicate'] or retry['packet']['digest'] != sealed['packet']['digest']:
                raise ValueError('重启后重试确认应查回原成果，不能换一套材料')
            if request(rp, 'evaluate', data)[0]['digest'] != sealed['packet']['digest']:
                raise ValueError('重启后归约口径应保持不变')
        finally:
            restarted.shutdown()
            thread.join()


def audit_intake_guards(port, data):
    bad_registration = make_registration(data)
    bad_registration['left'] = dict(bad_registration['left'], sequence_end=1)
    request(port, 'intake/register', bad_registration, status=400)
    registration = make_registration(data)
    registration['cable'] = '线路-守卫'
    intake_id = post(port, 'intake/register', registration)[0]['intake']
    # 序号超出登记范围
    out_of_range = fragment(intake_id, 'left', 9, [dict(data['left']['trace'][0])], '越界来源')
    request(port, 'intake/fragment', out_of_range, status=400)
    # 片段内时标必须严格递增，不能为凑序丢点
    bad_order = [dict(data['left']['trace'][0]), dict(data['left']['trace'][0])]
    bad_order[1]['id'] = '另一点'
    request(port, 'intake/fragment', fragment(intake_id, 'left', 0, bad_order, '乱序来源'), status=400)
    # 跨片段拼合后时标非严格递增同样拒绝（序号 1 的时刻早于序号 0），不丢点
    post(port, 'intake/fragment',
         fragment(intake_id, 'left', 0, [dict(data['left']['trace'][3])], 'guard-来源'))
    backwards = fragment(intake_id, 'left', 1, [dict(data['left']['trace'][1])], '倒流来源')
    request(port, 'intake/fragment', backwards, status=200)
    # 隔离未知回执
    request(port, 'intake/quarantine',
            dict(intake=intake_id, receipt='f' * 64, reason='测试'), status=404)
    # 只交两份片段就确认 → 缺号且时标倒流，被拒绝（409，绝不丢点凑档）
    request(port, 'intake/confirm',
            dict(intake=intake_id, confirm='d' * 64,
                 basis=request(port, f'intake/{intake_id}')[0]['basis']), status=409)
    # 确认标识格式
    request(port, 'intake/confirm',
            dict(intake=intake_id, confirm='zzz', basis='0' * 64), status=400)
    # 同一确认标识不能跨批次复用（'a'*64 已在主演练中被另一批次使用）
    other_registration = make_registration(data)
    other_registration['cable'] = '线路-守卫-乙'
    other_id = post(port, 'intake/register', other_registration)[0]['intake']
    request(port, 'intake/confirm',
            dict(intake=other_id, confirm='a' * 64, basis='0' * 64), status=409)
    # 分批流程不影响一次性整包导入
    request(port, 'seal', data)[0]


def audit(port, flow):
    review = any(op['id'] == flow and op.get('optional') for op in CONFIG['operations'])
    prefix = 'review-' if review else ''
    data = request(port, prefix+'sample')[0]
    alt = request(port, prefix+'alternate')[0]
    bad = json.loads((ROOT/'examples'/(prefix+'reject.json')).read_text(encoding='utf8'))
    original = request(port,'evaluate',data)[0]
    alternate = request(port,'evaluate',alt)[0]
    request(port,'evaluate',bad,status=400)
    if review:
        request(port, 'seal', bad, status=400)
        baselines = [request(port, 'evaluate', request(port, name)[0])[0] for name in ('sample', 'alternate')]
        for baseline, enhanced in zip(baselines, (original, alternate), strict=True):
            if flow in baseline['outputs'] or any(enhanced['outputs'][k] != v for k,v in baseline['outputs'].items()):
                raise ValueError('复核改变了基础口径')
    if flow in original['outputs']:
        cases = json.loads((ROOT/'examples'/(prefix+'observations.json')).read_text(encoding='utf8'))
        row, key, value, alt_row, alt_key, alt_value = cases[flow]
        observe(original['outputs'][flow],row,key,value)
        observe(alternate['outputs'][flow],alt_row,alt_key,alt_value)
        return
    request(port,'seal',bad,status=400)
    left = request(port,'seal',data)[0]
    again = request(port,'seal',data)[0]
    right = request(port,'seal',alt)[0]
    if not left['created'] or again['created'] or again['sequence'] != left['sequence'] or not right['created']:
        raise ValueError('版本去重或首写失败')
    if len(request(port,'revisions')[0]) != 2:
        raise ValueError('无效及重复记录不应该入库')
    if flow == 'seal':
        observed = request(port,f"packet/{left['digest']}")[0]
        if observed != original:
            raise ValueError('较新的归约改变了历史成果')
    elif flow == 'compare':
        versions = dict(left=left['digest'],right=right['digest'])
        changes = request(port,'compare',versions)[0]
        if not changes['rows'] or request(port,'compare',dict(left=left['digest'],right=left['digest']))[0]['rows']:
            raise ValueError('版本比对没有区分同版及异版')
        other = request(port,'seal',dict(alt,id='不同对象'))[0]
        request(port,'compare',dict(left=left['digest'],right=other['digest']),status=409)
        base = request(port, 'seal', request(port, 'review-sample')[0])[0]
        mixed = request(port, 'compare', dict(left=left['digest'], right=base['digest']))[0]
        stages = {op['label'] for op in CONFIG['operations'] if op.get('optional')}
        if not mixed['rows'] or any(row['stage'] not in stages or row['state'] != 'added' for row in mixed['rows']):
            raise ValueError('旧版比对只应报告新增的复核结果')
        if request(port, f"export/{base['digest']}")[0] != request(port, f"packet/{base['digest']}")[0]:
            raise ValueError('复核信息未完整保存')
    elif flow == 'export':
        payload, headers = request(port,f"export/{left['digest']}")
        if payload != original or 'attachment;' not in headers.get('Content-Disposition',''):
            raise ValueError('导出没有保留原版本或下载头')
        request(port,'export/' + '0'*64,status=404)
    else:
        raise ValueError(f'未知工作流：{flow}')


def main():
    flows = [op['id'] for op in CONFIG['operations']] + ['seal', 'compare', 'export', 'batch_intake']
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=flows)
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        db_path = Path(directory)/'observations.sqlite'
        with serve(db_path, 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                if args.flow == 'batch_intake':
                    sealed, data, registration = audit_batch_intake(server.server_port)
                    audit_intake_guards(server.server_port, data)
                else:
                    audit(server.server_port, args.flow)
            finally:
                server.shutdown()
                thread.join()
        if args.flow == 'batch_intake':
            audit_restart(db_path, server.server_port, sealed, data, registration)
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()
