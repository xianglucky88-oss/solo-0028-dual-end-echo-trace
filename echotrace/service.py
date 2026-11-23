from . import artifacts, domain, intake, reconcile, rules
from .artifacts import digest
from .contract import canonical, ContractError, ident, obj
from .intake_store import IntakeStore
from .review import analyze_review


class Workbench:
    def __init__(self, archive, config):
        self.archive = archive
        self.config = config
        self.intakes = IntakeStore(archive.connect)

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

    # ---- 分批收档 -----------------------------------------------------

    def _confirm_id(self, body):
        value = body.get('confirm')
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ContractError('确认标识应为 64 位十六进制串')
        return value

    def _basis(self, body):
        value = body.get('basis')
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ContractError('材料清单基准应为 64 位十六进制串')
        return value

    def register_intake(self, body):
        registration = intake.parse_registration(body)
        intake_id, current, existed = self.intakes.register(registration)
        return dict(intake=intake_id, registration=registration,
                    receipt=dict(receipt=intake_id, duplicate=existed),
                    snapshot=current)

    def submit_fragment(self, body):
        body = obj(body, '波形片段')
        intake_id = ident(body.get('intake'), '收档批次标识')
        registration = self.intakes.get_registration(intake_id)
        fragment, receipt_id = intake.parse_fragment(body, registration)
        fragment_digest = digest(canonical(fragment['samples']))
        current, receipt, duplicate = self.intakes.add_receipt(fragment, receipt_id, fragment_digest)
        return dict(intake=intake_id,
                    receipt=dict(receipt=receipt_id, side=fragment['side'],
                                 sequence=fragment['sequence'], origin=receipt['origin'],
                                 status=receipt['status'], duplicate=duplicate),
                    snapshot=current)

    def quarantine_fragment(self, body):
        body = obj(body, '隔离请求')
        intake_id = ident(body.get('intake'), '收档批次标识')
        receipt_id = ident(body.get('receipt'), '片段回执标识')
        reason = body.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
            raise ContractError('隔离原因应为 1 至 200 字的说明')
        current, already = self.intakes.quarantine(intake_id, receipt_id, reason.strip())
        return dict(intake=intake_id, receipt=receipt_id, duplicate=already, snapshot=current)

    def confirm_intake(self, body):
        body = obj(body, '归档确认')
        intake_id = ident(body.get('intake'), '收档批次标识')
        confirm_id = self._confirm_id(body)
        basis = self._basis(body)
        prior = self.intakes.find_confirmation(confirm_id)
        if prior is not None:
            # 响应丢失后的重试：直接查回同一份成果与实际使用的片段，不显示半成功
            if prior['intake'] != intake_id:
                raise ContractError('确认标识已用于另一收档批次', 409)
            packet = self.archive.read(prior['digest'])
            return dict(confirmation=prior, packet=packet, duplicate=True)
        registration = self.intakes.get_registration(intake_id)

        def build_packet(reg, receipts):
            # 严格拼装：缺号、冲突、非严格递增时标都会在此被拒绝，绝不丢点
            source, used, current = intake.assemble_source(reg, receipts)
            return self.analyze(source), used, current

        confirmation, _created = self.intakes.confirm(
            confirm_id, intake_id, basis, build_packet)
        packet = self.archive.read(confirmation['digest'])
        return dict(confirmation=confirmation, packet=packet,
                    used_receipts=confirmation['used_receipts'],
                    snapshot=self.intakes.snapshot(intake_id), duplicate=False)

    def execute(self, command, body):
        if command == 'evaluate':
            return self.analyze(body)
        if command == 'seal':
            return self.archive.seal(self.analyze(body))
        if command == 'compare':
            before = self.read(body.get('left'))
            after = self.read(body.get('right'))
            return artifacts.compare(before, after, self.config['operations'])
        if command == 'intake/register':
            return self.register_intake(body)
        if command == 'intake/fragment':
            return self.submit_fragment(body)
        if command == 'intake/quarantine':
            return self.quarantine_fragment(body)
        if command == 'intake/confirm':
            return self.confirm_intake(body)
        raise ContractError('没有这个处理入口', 404)

    def read(self, key):
        if not isinstance(key, str) or len(key) != 64 or any(ch not in '0123456789abcdef' for ch in key):
            raise ContractError('成果标识应为 64 位摘要')
        packet = self.archive.read(key)
        if packet['project'] != self.config['namespace']:
            raise ContractError('该成果属于另一数据工作台', 409)
        return packet
