import math

from .contract import ContractError, ident, invariant, num, obj

SEGMENT_KEYS = {'id', 'length', 'speed', 'source'}
SHEET_KEYS = {'id', 'segments', 'source'}
CALIBRATION_KEYS = {'errata', 'segments', 'digest'}


def text(value, label):
    if not isinstance(value, str) or not 1 <= len(value) <= 120:
        raise ContractError(f'{label}应为 1–120 个字符')
    return value


def parse_segments(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise ContractError('勘误分段应含 1 至 200 段')
    seen, segments = set(), []
    for item in value:
        row = obj(item, '勘误分段')
        if set(row) - SEGMENT_KEYS:
            raise ContractError('勘误分段只能含标识、长度、速度与来源，不能顺带其他参数')
        tag = row.get('id')
        if tag is not None:
            ident(tag, '分段标识')
            if tag in seen:
                raise ContractError(f'勘误分段标识重复：{tag}')
            seen.add(tag)
        segment = dict(length=num(row.get('length'), '分段长度（米）', 1e-6, 1e5),
                       speed=num(row.get('speed'), '分段速度（米每纳秒）', 0.01, 0.3),
                       source=text(row.get('source'), '分段来源'))
        if tag is not None:
            segment['id'] = tag
        segments.append(segment)
    return segments


def parse_sheet(data):
    sheet = obj(data, '勘误单')
    if set(sheet) - SHEET_KEYS:
        raise ContractError('勘误单只登记编号、分段与来源，不能顺带修改波形、零点或盲区')
    result = dict(id=ident(sheet.get('id'), '勘误编号'), segments=parse_segments(sheet.get('segments')))
    if 'source' in sheet:
        result['source'] = text(sheet['source'], '勘误来源')
    return result


def parse_calibration(value, length):
    calibration = obj(value, '标定勘误')
    if set(calibration) - CALIBRATION_KEYS:
        raise ContractError('标定勘误只引用勘误编号、分段与摘要')
    number = ident(calibration.get('errata'), '勘误编号')
    digest = calibration.get('digest')
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                               or any(ch not in '0123456789abcdef' for ch in digest)):
        raise ContractError('勘误摘要应为 64 位十六进制')
    segments = parse_segments(calibration.get('segments'))
    total = sum(segment['length'] for segment in segments)
    invariant(math.isclose(total, length, rel_tol=0, abs_tol=1e-6), '分段长度合计必须等于原档缆长')
    return dict(errata=number, segments=segments)
