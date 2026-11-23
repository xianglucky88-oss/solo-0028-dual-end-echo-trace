from collections import defaultdict


def competition_groups(pending):
    graph = {r['id']: set(r['evidence']) for r in pending if r['state'] == 'ambiguous'}
    remaining = set(graph)
    result = []
    while remaining:
        root = min(remaining)
        group, todo = set(), [root]
        while todo:
            node = todo.pop()
            if node not in group:
                group.add(node)
                todo.extend(graph.get(node, ()))
        remaining.difference_update(group)
        sides = {side: sorted(key for key in group if key.startswith(side+'/')) for side in ('left', 'right')}
        count = len(sides['left']) - len(sides['right'])
        result.append(dict(id=root, left_count=len(sides['left']), right_count=len(sides['right']),
                           state='unbalanced' if count else 'ambiguous', evidence=sides))
    return result


def polarity_conflicts(model, outputs):
    pending = {r['id'] for r in outputs['pending'] if r['state'] != 'ambiguous'}
    candidates = [r for r in outputs['location'] if r['state'] == 'candidate' and r['id'] in pending]
    lookup = defaultdict(list)
    for row in candidates:
        lookup[row['side']].append(row)
    return [dict(id=f"{l['id']}@{r['id']}", position=(l['position']+r['position'])/2,
                 gap=abs(l['position']-r['position']), state='opposed', evidence=[l['id'], r['id']])
            for l in lookup['left'] for r in lookup['right']
            if l['polarity'] != r['polarity'] and abs(l['position']-r['position']) <= model['tolerance']]


def closure_quality(pairs, support):
    flags = {r['id']: r['state'] for r in support}
    return [dict(id=r['id'], position=r['position'], gap=r['gap'],
                 state='sparse' if any(flags[key] == 'sparse' for key in r['evidence']) else 'supported',
                 evidence={key: flags[key] for key in r['evidence']}) for r in pairs]


def revisit_coverage(revisit, visibility, length):
    result = []
    for row in revisit:
        position = row['distance'] if row['side'] == 'left' else length-row['distance']
        region = next((r for r in visibility if r['start'] <= position < r['end']), None)
        state = 'supported' if region and row['side'] in region['evidence']['ends'] else 'blind'
        result.append(dict(id=row['id'], side=row['side'], position=position, state=state,
                           evidence={'region': region['id'] if region else None, 'original': row['state'], 'peaks': row['evidence']}))
    return result
