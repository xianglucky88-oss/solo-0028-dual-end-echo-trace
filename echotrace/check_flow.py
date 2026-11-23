import argparse
import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .server import CONFIG, PREFIX, ROOT, serve


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


def audit_errata(port):
    sample = request(port, 'errata-sample')[0]
    first = request(port, 'errata-first')[0]
    second = request(port, 'errata-second')[0]
    number1, number2 = first['id'], second['id']

    original = request(port, 'evaluate', sample)[0]
    if original['outputs']['pair']:
        raise ValueError('恒速原档不应已有闭合')
    sealed = request(port, 'seal', sample)[0]
    if not sealed['created']:
        raise ValueError('恒速原档首次封存失败')

    issued = request(port, 'errata', first)[0]
    again = request(port, 'errata', first)[0]
    if not issued['created'] or again['created'] or again['sequence'] != issued['sequence'] or again['digest'] != issued['digest']:
        raise ValueError('同一份勘误因交接重试被重复签发')
    conflict = dict(first, segments=[dict(row, speed=0.15) for row in first['segments']])
    request(port, 'errata', conflict, status=409)
    request(port, 'errata', dict(first, left={'zero': 1}), status=400)
    listing = request(port, 'errata')[0]
    if [row['number'] for row in listing] != [number1] or listing[0]['digest'] != issued['digest']:
        raise ValueError('勘误登记簿没有如实反映已签发记录')
    sheet = request(port, 'errata/' + quote(number1))[0]
    if sheet != first:
        raise ValueError('按编号取回的勘误单与签发内容不一致')

    revised = request(port, 'revise', {'packet': sealed['digest'], 'errata': number1})[0]
    if not revised['created']:
        raise ValueError('首次修订没有产生新版本')
    r1 = request(port, 'packet/' + revised['digest'])[0]
    for key in ('id', 'length', 'speed', 'tolerance', 'left', 'right'):
        if r1['source'].get(key) != sample.get(key):
            raise ValueError(f'修订顺带改动了原档字段：{key}')
    if r1['source']['calibration']['errata'] != number1 or r1['source']['calibration']['digest'] != issued['digest']:
        raise ValueError('修订成果没有标明所依据的勘误单')
    observe(r1['outputs']['pair'], 'left/点7@right/点2', 'position', 80)
    observe(r1['outputs']['pair'], 'left/点7@right/点2', 'state', 'paired')
    observe(r1['outputs']['location'], 'left/点7', 'position', 80)
    observe(r1['outputs']['capture_gaps'], 'left/点4@点5', 'start', 49)
    observe(r1['outputs']['capture_gaps'], 'left/点4@点5', 'end', 69.5)
    gap = next(row for row in r1['outputs']['capture_gaps'] if row['id'] == 'left/点4@点5')
    if not gap['start'] < 60 < gap['end']:
        raise ValueError('采样空洞应横跨介质段界 60 米')
    revisit = next(row for row in r1['outputs']['revisit'] if row['id'] == 'left/点2')
    if revisit['state'] != 'blind' or revisit['evidence']['time'] != 1100 or revisit['evidence']['support'] is not False:
        raise ValueError('没有采样支撑的复测建议不得只凭几何窗口标为可证')

    changes = request(port, 'compare', {'left': sealed['digest'], 'right': revised['digest']})[0]
    if any(row['id'].startswith('wave/') for row in changes['rows']):
        raise ValueError('同一批原样点按身份核对失败：波形被当成改动')
    if not any(row['id'] == 'pair/left/点7@right/点2' and row['state'] == 'added' for row in changes['rows']):
        raise ValueError('版本比较没有报告新成立的闭合')
    if changes['calibration']['left'] is not None or changes['calibration']['right']['errata'] != number1:
        raise ValueError('版本比较没有标明两侧勘误身份')

    request(port, 'errata', second)
    revised2 = request(port, 'revise', {'packet': sealed['digest'], 'errata': number2})[0]
    if revised2['digest'] == revised['digest']:
        raise ValueError('来源独立的两份勘误不应合并身份')
    r2 = request(port, 'packet/' + revised2['digest'])[0]
    if r2['outputs'] != r1['outputs']:
        raise ValueError('等值勘误回算出的读数应保持一致')
    equal = request(port, 'compare', {'left': revised['digest'], 'right': revised2['digest']})[0]
    if equal['rows']:
        raise ValueError('等值勘误之间不应出现读数差异')
    if equal['calibration']['left']['errata'] != number1 or equal['calibration']['right']['errata'] != number2:
        raise ValueError('比较或下载时无法核对选的是哪份勘误')

    retry = request(port, 'revise', {'packet': sealed['digest'], 'errata': number1})[0]
    if retry['created'] or retry['digest'] != revised['digest']:
        raise ValueError('同一修订因交接重试被重复签发')
    bad_sum = {'id': '勘误-2026-丙', 'segments': [
        {'id': '段1', 'length': 50, 'speed': 0.2, 'source': '介质台账'},
        {'id': '段2', 'length': 40, 'speed': 0.1, 'source': '介质台账'}]}
    request(port, 'errata', bad_sum)
    request(port, 'revise', {'packet': sealed['digest'], 'errata': '勘误-2026-丙'}, status=400)
    request(port, 'revise', {'packet': sealed['digest'], 'errata': '勘误-不存在'}, status=404)
    request(port, 'revise', {'packet': revised['digest'], 'errata': number1}, status=409)

    forged = json.loads(json.dumps(r1['source']))
    forged['left']['trace'][2]['value'] = 0.6
    forged_seal = request(port, 'seal', forged)[0]
    exposed = request(port, 'compare', {'left': revised['digest'], 'right': forged_seal['digest']})[0]
    if not any(row['id'].startswith('wave/') for row in exposed['rows']):
        raise ValueError('另一批同名样点的波形不应充作标定勘误')

    probe = {
        'id': '线路-界', 'length': 100, 'speed': 0.2, 'tolerance': 0.5,
        'left': {'zero': 10, 'dead': 2, 'threshold': 0.3, 'trace': [
            {'id': '甲0', 'time': 0, 'value': 0}, {'id': '甲1', 'time': 590, 'value': 0},
            {'id': '甲2', 'time': 610, 'value': 0.8}, {'id': '甲3', 'time': 630, 'value': 0},
            {'id': '甲4', 'time': 1480, 'value': 0}, {'id': '甲5', 'time': 1500, 'value': 0.7},
            {'id': '甲6', 'time': 1520, 'value': 0}, {'id': '甲7', 'time': 1600, 'value': 0}]},
        'right': {'zero': 20, 'dead': 2, 'threshold': 0.3, 'trace': [
            {'id': '乙0', 'time': 20, 'value': 0}, {'id': '乙1', 'time': 800, 'value': 0},
            {'id': '乙2', 'time': 820, 'value': 0.9}, {'id': '乙3', 'time': 840, 'value': 0},
            {'id': '乙4', 'time': 1300, 'value': 0}]},
        'calibration': {'errata': number1, 'segments': first['segments']}}
    seen = request(port, 'evaluate', probe)[0]
    observe(seen['outputs']['pair'], 'left/甲2@right/乙2', 'position', 60)
    observe(seen['outputs']['pair'], 'left/甲2@right/乙2', 'gap', 0)
    observe(seen['outputs']['location'], 'left/甲5', 'state', 'outside')
    observe(seen['outputs']['location'], 'left/甲5', 'position', 104.5)

    exported, headers = request(port, 'export/' + sealed['digest'])
    if exported != original or 'attachment;' not in headers.get('Content-Disposition', ''):
        raise ValueError('原下载地址不能复现当时的原档')
    downloaded = request(port, 'export/' + revised['digest'])[0]
    if downloaded['source']['calibration']['errata'] != number1:
        raise ValueError('修订版下载没有标明所依据的勘误单')


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]+['seal','compare','export','errata'])
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        with serve(Path(directory)/'observations.sqlite', 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                if args.flow == 'errata':
                    audit_errata(server.server_port)
                else:
                    audit(server.server_port,args.flow)
            finally:
                server.shutdown()
                thread.join()
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()
