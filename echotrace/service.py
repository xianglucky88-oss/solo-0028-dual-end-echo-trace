from . import artifacts, domain, reconcile, rules
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
        raise ContractError('没有这个处理入口', 404)

    def read(self, key):
        if not isinstance(key, str) or len(key) != 64 or any(ch not in '0123456789abcdef' for ch in key):
            raise ContractError('成果标识应为 64 位摘要')
        packet = self.archive.read(key)
        if packet['project'] != self.config['namespace']:
            raise ContractError('该成果属于另一数据工作台', 409)
        return packet
