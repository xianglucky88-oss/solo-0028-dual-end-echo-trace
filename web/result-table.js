const $ = (id) => document.getElementById(id);

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function viewValue(value, model) {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.length ? value.map((part) => viewValue(part, model)).join('、') : '—';
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 5 }).format(value);
  return model.values[value] || String(value);
}

function traceTree(value, model) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const list = el('dl');
    for (const [k, v] of Object.entries(value)) {
      list.append(el('dt', model.columns[k] || k), el('dd'));
      list.lastChild.append(traceTree(v, model));
    }
    return list;
  }
  return el('span', viewValue(value, model));
}

export function renderRows(model, rows, columns, label = '', headings = model.columns) {
  const table = $('result');
  const header = el('thead');
  const headRow = el('tr');
  for (const key of columns) headRow.append(el('th', headings[key] || key));
  header.append(headRow);
  const body = el('tbody');
  $('row-count').textContent = `${rows.length} 条${label || ''}`;
  $('empty').hidden = rows.length !== 0;
  table.hidden = rows.length === 0;
  for (const row of rows) {
    const tr = el('tr');
    for (const [index, key] of columns.entries()) {
      const cell = el('td');
      if (index === 0) {
        const button = el('button', viewValue(row[key], model), 'rowlink');
        button.type = 'button';
        button.addEventListener('click', () => {
          $('detail-title').textContent = viewValue(row[key], model);
          $('detail-content').replaceChildren(traceTree(row, model));
          $('detail').showModal();
        });
        cell.append(button);
      } else {
        const value = row[key];
        cell.append(el('span', value !== null && typeof value === 'object' && !Array.isArray(value) ? '查看明细' : viewValue(value, model), key === 'state' ? 'state' : ''));
        if (key === 'state') cell.firstChild.dataset.state = value;
      }
      tr.append(cell);
    }
    body.append(tr);
  }
  table.replaceChildren(header, body);
}
