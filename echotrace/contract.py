import json
import math
import re


class ContractError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def decode(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f'字段重复：{key}')
            result[key] = value
        return result

    def bad_constant(_):
        raise ContractError('不支持非有限数值')

    try:
        return obj(json.loads(text, object_pairs_hook=unique, parse_constant=bad_constant), '数据包')
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError('无法读取 UTF-8 JSON 数据包') from exc


def canonical(data):
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('数据含非有限数值、非法文本或过深的层级') from exc


def obj(value, label):
    if not isinstance(value, dict):
        raise ContractError(f'{label}应为对象')
    return value


def ident(value, label='标识'):
    if not isinstance(value, str) or not re.fullmatch(r'[\w][\w.\-]{0,79}', value):
        raise ContractError(f'{label}应为 1–80 个字母、数字或标识字符')
    return value


def num(value, label, low=-1e9, high=1e9):
    if (type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value)):
        raise ContractError(f'{label}应为 {low} 至 {high} 之间的有限数值')
    return value


def enum(value, values, label):
    if not isinstance(value, str) or value not in values:
        raise ContractError(f'{label}不是允许的取值')
    return value


def records(value, label, count=600, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= count:
        raise ContractError(f'{label}应含 {minimum} 至 {count} 条记录')
    seen = set()
    for item in value:
        key = ident(obj(item, label).get('id'), f'{label}标识')
        if key in seen:
            raise ContractError(f'{label}存在重复标识：{key}')
        seen.add(key)
    return value


def interval(start, end, label, maximum=1e9):
    a = num(start, label, 0, maximum)
    b = num(end, label, 0, maximum)
    if a >= b:
        raise ContractError(f'{label}终点必须大于起点')
    return a, b


def unique_order(items, key, label):
    if any(a[key] >= b[key] for a, b in zip(items, items[1:])):
        raise ContractError(f'{label}必须严格递增且不能重复')


def invariant(condition, message):
    if not condition:
        raise ContractError(message)
