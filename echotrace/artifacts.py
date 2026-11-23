import hashlib
from .contract import canonical, ContractError


VERSION = 1


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def make_packet(namespace, source, outputs):
    packet = dict(project=namespace, schema=VERSION, subject=source['id'],
                  source=source, source_digest=digest(source), outputs=outputs)
    return dict(packet, digest=digest(packet))


def verify_packet(packet):
    data = {key: value for key, value in packet.items() if key != 'digest'}
    if digest(data) != packet['digest'] or digest(data['source']) != data['source_digest']:
        raise ContractError('封存数据的完整性核对失败', 409)
    return packet


def rows_for(packet, operation):
    outputs = packet['outputs']
    key = operation['id']
    return outputs.get(key, []) if operation.get('optional') else outputs[key]


def compare(left, right, operations):
    if left['subject'] != right['subject']:
        raise ContractError('两份成果不属于同一对象，不能直接比对', 409)
    if left['schema'] != right['schema']:
        raise ContractError('两份成果的口径版本不一致', 409)
    output = []
    for spec in operations:
        key = spec['id']
        earlier = {row['id']: row for row in rows_for(left, spec)}
        later = {row['id']: row for row in rows_for(right, spec)}
        for row_id in sorted(earlier.keys() | later.keys()):
            before, after = earlier.get(row_id), later.get(row_id)
            if before == after:
                continue
            state = 'added' if before is None else 'removed' if after is None else 'changed'
            output.append(dict(id=f'{key}/{row_id}', stage=spec['label'], state=state, before=before, after=after))
    return dict(subject=left['subject'], left=left['digest'], right=right['digest'], rows=output)
