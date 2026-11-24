from datetime import datetime, timezone

from . import artifacts, domain, reconcile, rules
from . import inventory
from .review import analyze_review
from .contract import ContractError, ident, obj


class Workbench:
    def __init__(self, archive, config):
        self.archive = archive
        self.config = config

    def analyze(self, source):
        source = obj(source, '观测数据')
        ident(source.get('id'), '对象标识')
        model = domain.parse(source)
        compiled = domain.evaluate(model)
        outputs = rules.decide(model, compiled)
        outputs[self.config['reconciliation']] = reconcile.summarize(model, compiled, outputs)
        if 'review' in source:
            review = obj(source['review'], '复核数据')
            outputs.update(analyze_review(review, model, compiled, outputs))
        return artifacts.make_packet(self.config['namespace'], source, outputs)

    def execute(self, command, body):
        if command == 'evaluate':
            return self.analyze(body)
        if command == 'seal':
            return self.archive.seal(self.analyze(body))
        if command == 'compare':
            before = self.read(body.get('left'))
            after = self.read(body.get('right'))
            return artifacts.compare(before, after, self.config['operations'])
        if command == 'inventory':
            return self.issue_inventory(body)
        raise ContractError('没有这个处理入口', 404)

    def read(self, key):
        if not isinstance(key, str) or len(key) != 64 or any(ch not in '0123456789abcdef' for ch in key):
            raise ContractError('成果标识应为 64 位摘要')
        packet = self.archive.read(key)
        if packet['project'] != self.config['namespace']:
            raise ContractError('该成果属于另一数据工作台', 409)
        return packet

    def _verified(self, key):
        """完整性核对回调；失败转成盘点模块的不可读信号，不回退旧包。"""
        try:
            return self.read(key)
        except ContractError as exc:
            if exc.status == 409:
                raise inventory.UnreadableEvidence(key) from exc
            raise

    def issue_inventory(self, body):
        subjects, requested = inventory.checklist(body)
        head = self.archive.head_sequence()
        if head is None:
            raise ContractError('成果库尚无封存，不能确定盘点截至点')
        cutoff = head if requested is None else requested
        if cutoff > head:
            raise ContractError('截至点不能晚于最新封存序号')
        latest = self.archive.latest_at_cutoff(subjects, cutoff)
        issued_at = datetime.now(timezone.utc).isoformat()
        # 单号在登记册事务内确定；先按预估序号构造，archive 写入时原子核对。
        sheet_no = f'{inventory.NUMBER_PREFIX}-{self.archive.sheet_count() + 1:04d}'
        sheet = inventory.build_sheet(sheet_no, subjects, cutoff, latest, self._verified)
        self.archive.issue_sheet(sheet, issued_at)
        return self.archive.read_sheet(sheet_no)

    def reopen_inventory(self, sheet_no):
        ident(sheet_no, '盘点单号')
        stored = self.archive.read_sheet(sheet_no)
        return inventory.reopen(stored, self._verified)
