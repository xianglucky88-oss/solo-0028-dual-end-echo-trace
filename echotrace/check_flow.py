import argparse
import json
from math import isclose
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
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


def tamper_packet(db_path, digest):
    """破坏指定封存包的内容但保留索引与 JSON 形态，模拟成果后来不可读。

    等长替换一个数字字符，数据包仍能解析但完整性核对必然失败（409）。
    """
    with sqlite3.connect(db_path) as db:
        raw = bytearray(db.execute('SELECT payload FROM packets WHERE digest=?', (digest,)).fetchone()[0])
    index = next(i for i, byte in enumerate(raw) if 48 <= byte <= 57)
    raw[index] = 48 + ((raw[index] - 48 + 1) % 10)
    with sqlite3.connect(db_path) as db:
        db.execute('UPDATE packets SET payload=? WHERE digest=?', (bytes(raw), digest))


def audit_inventory(port, db_path):
    review_sample = request(port, 'review-sample')[0]
    review_alt = request(port, 'review-alternate')[0]
    plain = request(port, 'sample')[0]

    def with_id(data, new_id):
        return dict(data, id=new_id)

    # 对象甲：最新旧档将被挤出只列近 100 条的版本菜单。
    pushed = with_id(review_alt, '线缆-甲')
    first = request(port, 'seal', pushed)[0]
    # 对象丙：先封一份可读的旧档（无复核），稍后再封不可读的最新档。
    stale = with_id(plain, '线缆-丙')
    stale_seal = request(port, 'seal', stale)[0]
    # 对象乙：首张单截至点时尚未封存，盘点期间才完成复核封存。
    review_during = with_id(review_alt, '线缆-乙')
    # 用另一卷试验线反复重存，把线缆-甲挤出版本菜单（菜单仅近 100 条）。
    for index in range(101):
        request(port, 'seal', with_id(review_sample, f'试验线-{index:03d}'))
    menu = request(port, 'revisions')[0]
    if len(menu) != 100 or any(record['subject'] == '线缆-甲' for record in menu):
        raise ValueError('反复重存后线缆-甲应已被挤出版本菜单')

    checklist = [dict(id=subject) for subject in ('线缆-甲', '线缆-乙', '线缆-丙', '线缆-丁')]
    sheet_one = request(port, 'inventory', dict(checklist=checklist))[0]
    cutoff_one = sheet_one['cutoff_sequence']
    states_one = {row['id']: row['state'] for row in sheet_one['entries']}
    if states_one != {
        '线缆-甲': 'review_closed',
        '线缆-乙': 'no_seal',
        '线缆-丙': 'unreviewed',
        '线缆-丁': 'no_seal',
    }:
        raise ValueError(f'首张盘点单分类不符合截至点事实：{states_one}')
    if sheet_one['total'] != 4 or any(sheet_one['counts'][s] != n for s, n in (
            ('review_closed', 1), ('no_seal', 2), ('unreviewed', 1),
            ('review_open', 0), ('unreadable', 0))):
        raise ValueError('盘点单数量与状态计数不一致')
    jia = next(row for row in sheet_one['entries'] if row['id'] == '线缆-甲')
    if jia['evidence']['sequence'] != first['sequence'] or jia['evidence']['digest'] != first['digest']:
        raise ValueError('被挤出菜单的旧档仍应按截至点选为最新封存')
    # 每个对象只出现一次。
    if len({row['id'] for row in sheet_one['entries']}) != len(sheet_one['entries']):
        raise ValueError('盘点单出现重复对象')

    # 盘点期间继续正常封存：乙完成复核（获支撑闭合），丙的最新档不可读。
    second = request(port, 'seal', review_during)[0]
    bad_latest = request(port, 'seal', with_id(review_sample, '线缆-丙'))[0]
    tamper_packet(db_path, bad_latest['digest'])
    request(port, f'packet/{bad_latest["digest"]}', status=409)
    # 丙的上一份可读包仍在，但不准拿它顶替最新指定成果。
    request(port, f'packet/{stale_seal["digest"]}')

    # 重开旧单：按单号取回，分类与数量不随迟到封存变化，证据仍可从原入口核对。
    reopened = request(port, f'inventory/{sheet_one["sheet"]}')[0]
    if reopened['entries'] != sheet_one['entries'] or reopened['counts'] != sheet_one['counts']:
        raise ValueError('重开旧单改变了签发时的明细或计数')
    if reopened['cutoff_sequence'] != cutoff_one:
        raise ValueError('旧单截至点被迟到封存推动')
    jia_now = next(row for row in reopened['entries'] if row['id'] == '线缆-甲')
    if reopened['evidence_state']['线缆-甲'] is not True:
        raise ValueError('原成果仍可读时应明确证据可复核')
    if request(port, jia_now['evidence']['export'])[0]['digest'] != jia_now['evidence']['digest']:
        raise ValueError('引用原成果应仍可从原下载入口核对')

    # 再出一张新单：截至点推进，分类与旧单有可核对的差别。
    sheet_two = request(port, 'inventory', dict(checklist=checklist))[0]
    states_two = {row['id']: row['state'] for row in sheet_two['entries']}
    if states_two != {
        '线缆-甲': 'review_closed',
        '线缆-乙': 'review_closed',
        '线缆-丙': 'unreadable',
        '线缆-丁': 'no_seal',
    }:
        raise ValueError(f'新盘点单未反映盘点期间的封存变化：{states_two}')
    if sheet_two['sheet'] == sheet_one['sheet'] or sheet_two['cutoff_sequence'] <= cutoff_one:
        raise ValueError('新盘点单应有独立单号和更晚的截至点')
    bing = next(row for row in sheet_two['entries'] if row['id'] == '线缆-丙')
    if bing['evidence']['digest'] != bad_latest['digest'] or bing['evidence']['source_digest'] is not None:
        raise ValueError('证据不可读必须指向最新指定成果，且不得回退旧包')
    if sheet_two['sheet_digest'] == sheet_one['sheet_digest']:
        raise ValueError('两张盘点单的快照摘要应可区分')

    # 原成果后来不可读：重开新单保留签发分类，同时标注证据现在不能复核。
    reopened_two = request(port, f'inventory/{sheet_two["sheet"]}')[0]
    bing_reopened = next(row for row in reopened_two['entries'] if row['id'] == '线缆-丙')
    if bing_reopened['state'] != 'unreadable' or reopened_two['evidence_state']['线缆-丙'] is not False:
        raise ValueError('重开须保留签发分类并标明证据现在不可复核')
    if reopened_two['evidence_state']['线缆-甲'] is not True:
        raise ValueError('可读证据的当前状态也应明示')

    # 清单与截至点的合法拒绝。
    request(port, 'inventory', dict(checklist=[]), status=400)
    request(port, 'inventory', dict(checklist=[dict(id='线缆-甲'), dict(id='线缆-甲')]), status=400)
    request(port, 'inventory', dict(checklist=checklist, cutoff_sequence=cutoff_one + 100000), status=400)
    request(port, 'inventory', dict(checklist=checklist, cutoff_sequence=0), status=400)
    request(port, 'inventory/PD-9999', None, status=404)
    # 同一截至点与同一清单重出一张，截至摘要必须一致，但单号独立。
    sheet_rerun = request(port, 'inventory', dict(checklist=checklist, cutoff_sequence=cutoff_one))[0]
    if sheet_rerun['cutoff_digest'] != sheet_one['cutoff_digest'] or sheet_rerun['entries'] != sheet_one['entries']:
        raise ValueError('同截至点同清单的盘点口径应完全一致')
    if sheet_rerun['sheet'] == sheet_one['sheet'] or sheet_rerun['sheet_digest'] != sheet_one['sheet_digest']:
        raise ValueError('重出盘点单应有独立单号，但同截至点快照摘要必须一致')
    sheets = request(port, 'inventory-sheets')[0]
    if [item['sheet'] for item in sheets] != [sheet_one['sheet'], sheet_two['sheet'], sheet_rerun['sheet']]:
        raise ValueError('盘点单登记册未按单号列出全部已签发单')


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]+['seal','compare','export','inventory'])
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        db_path = Path(directory)/'observations.sqlite'
        with serve(db_path, 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                if args.flow == 'inventory':
                    audit_inventory(server.server_port, db_path)
                else:
                    audit(server.server_port, args.flow)
            finally:
                server.shutdown()
                thread.join()
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()
