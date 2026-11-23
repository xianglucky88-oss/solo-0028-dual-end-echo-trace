from . import artifacts, domain, errata, reconcile, rules
from .artifacts import digest
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
        if 'review' in source or 'calibration' in source:
            outputs.update(analyze_review(model, compiled, outputs))
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
        if command == 'errata':
            return self.register_errata(body)
        if command == 'revise':
            return self.revise(body)
        raise ContractError('没有这个处理入口', 404)

    def register_errata(self, body):
        sheet = errata.parse_sheet(body)
        record = self.archive.seal_errata(sheet['id'], sheet)
        return dict(number=sheet['id'], **record)

    def errata_sheet(self, number):
        return self.archive.read_errata(ident(number, '勘误编号'))

    def revise(self, body):
        body = obj(body, '修订请求')
        packet = self.read(body.get('packet'))
        sheet = self.archive.read_errata(ident(body.get('errata'), '勘误编号'))
        source = packet['source']
        if 'calibration' in source:
            raise ContractError('该成果已是标定修订版，应回到恒速原档重新指定勘误', 409)
        calibration = dict(errata=sheet['id'], digest=digest(sheet), segments=sheet['segments'])
        revised = dict(source, calibration=calibration)
        if 'review' in body:
            revised['review'] = obj(body['review'], '复核数据')
        return self.archive.seal(self.analyze(revised))

    def read(self, key):
        if not isinstance(key, str) or len(key) != 64 or any(ch not in '0123456789abcdef' for ch in key):
            raise ContractError('成果标识应为 64 位摘要')
        packet = self.archive.read(key)
        if packet['project'] != self.config['namespace']:
            raise ContractError('该成果属于另一数据工作台', 409)
        return packet
