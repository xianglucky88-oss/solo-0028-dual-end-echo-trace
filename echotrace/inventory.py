"""按月底盘点截至点编制盘点单。

盘点单只信任封存库：每个待查对象取截至点之前（含截至点）已封存的
最新一份成果，不看样点时标，也不看工作台只列近批的版本菜单。对象在
同一张单上只出现一次；最新指定成果通不过完整性核对时单列为证据不可读，
不允许回退捡较旧的可读包。
"""
from copy import deepcopy

from .contract import ContractError, canonical, ident, obj
from .artifacts import digest

# 盘点状态：未获闭合不是“无异常”，而是需要继续处理的复核结论。
NO_SEAL = 'no_seal'                 # 没有封存
SEALED_UNREVIEWED = 'unreviewed'    # 已有封存、未做采样支撑复核
REVIEW_CLOSED = 'review_closed'     # 已复核且有至少一条两端邻样支撑闭合
REVIEW_OPEN = 'review_open'         # 已复核但没有获得这种闭合
EVIDENCE_UNREADABLE = 'unreadable'  # 最新指定成果完整性核对失败

STATES = (NO_SEAL, SEALED_UNREVIEWED, REVIEW_CLOSED, REVIEW_OPEN, EVIDENCE_UNREADABLE)
STATE_LABELS = {
    NO_SEAL: '没有封存',
    SEALED_UNREVIEWED: '已封存未做采样支撑复核',
    REVIEW_CLOSED: '已复核且获两端邻样支撑闭合',
    REVIEW_OPEN: '已复核但未获闭合',
    EVIDENCE_UNREADABLE: '证据不可读',
}
NUMBER_PREFIX = 'PD'


class UnreadableEvidence(Exception):
    """截至点上最新指定成果无法通过完整性核对。"""

    def __init__(self, key):
        super().__init__('封存数据的完整性核对失败')
        self.digest = key


def checklist(value):
    body = obj(value, '盘点请求')
    items = body.get('checklist')
    if not isinstance(items, list) or not 1 <= len(items) <= 600:
        raise ContractError('待查清单应含 1 至 600 个对象')
    subjects, seen = [], set()
    for item in items:
        key = ident(obj(item, '待查对象').get('id'), '待查对象标识')
        if key in seen:
            raise ContractError(f'待查清单存在重复对象：{key}')
        seen.add(key)
        subjects.append(key)
    cutoff = body.get('cutoff_sequence')
    if cutoff is not None:
        if type(cutoff) is not int or cutoff <= 0:
            raise ContractError('截至点必须为正整数封存序号')
    return subjects, cutoff


def classify(packet):
    """依据一份可读的截至点最新成果给出盘点状态。"""
    if 'closure_quality' not in packet['outputs']:
        return SEALED_UNREVIEWED
    if any(row.get('state') == 'supported' for row in packet['outputs']['closure_quality']):
        return REVIEW_CLOSED
    return REVIEW_OPEN


def evidence_for(row, packet):
    return {
        'sequence': row['sequence'],
        'digest': row['digest'],
        'subject': row['subject'],
        'source_digest': packet['source_digest'],
        'export': f"export/{row['digest']}",
    }


def build_sheet(sheet_no, subjects, cutoff_sequence, latest_rows, reader):
    """按同一截至点为每个待查对象编制一条盘点明细。

    latest_rows：截至点之前每个对象序号最大的封存索引行。
    reader：按摘要读取并完成完整性核对的回调；失败抛 UnreadableEvidence。
    """
    entries, counts = [], {state: 0 for state in STATES}
    for subject in subjects:
        row = latest_rows.get(subject)
        if row is None:
            entry = dict(id=subject, state=NO_SEAL, evidence=None)
        else:
            try:
                packet = reader(row['digest'])
            except UnreadableEvidence:
                # 最新指定成果不可读即单列，不回退到较旧的可读包。
                entry = dict(id=subject, state=EVIDENCE_UNREADABLE,
                             evidence={'sequence': row['sequence'], 'digest': row['digest'],
                                       'subject': row['subject'], 'source_digest': None,
                                       'export': f"export/{row['digest']}"})
            else:
                entry = dict(id=subject, state=classify(packet),
                             evidence=evidence_for(row, packet))
        counts[entry['state']] += 1
        entries.append(entry)
    sheet = dict(
        sheet=sheet_no,
        cutoff_sequence=cutoff_sequence,
        cutoff_digest=digest({'cutoff_sequence': cutoff_sequence, 'subjects': subjects}),
        checklist=list(subjects),
        counts=counts,
        total=len(subjects),
        entries=entries,
    )
    sheet['sheet_digest'] = digest(canonical_snapshot(sheet))
    return sheet


def canonical_snapshot(sheet):
    # 快照摘要只覆盖截至点口径与明细，不含单号：同截至点同清单必然同摘要。
    return {key: sheet[key] for key in
            ('cutoff_sequence', 'cutoff_digest', 'checklist', 'counts', 'total', 'entries')}


def reopen(stored, reader):
    """按单号重开已签发盘点单。

    数量、对象明细与签发时分类保持不变，不随迟到封存变化；只重新核对
    引用证据此刻是否仍可读，结果放在独立的 evidence_state 中，不回写明细。
    """
    sheet = deepcopy(stored)
    evidence_state = {}
    for entry in sheet['entries']:
        evidence = entry['evidence']
        if evidence is None:
            evidence_state[entry['id']] = None
            continue
        try:
            reader(evidence['digest'])
        except UnreadableEvidence:
            evidence_state[entry['id']] = False
        else:
            evidence_state[entry['id']] = True
    sheet['reopened'] = True
    sheet['evidence_state'] = evidence_state
    return sheet
