// 月底盘点：资料员提交待查清单并固定封存截至点，每个对象只出现一次。
const $ = (id) => document.getElementById(id);

const STATE_TEXT = {
  no_seal: '没有封存',
  unreviewed: '已封存、未做采样支撑复核',
  review_closed: '已复核、获两端邻样支撑闭合',
  review_open: '已复核、未获闭合',
  unreadable: '证据不可读',
};

function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function parseChecklist(text) {
  const subjects = [];
  const seen = new Set();
  for (const line of text.split(/[\n,，;；]/)) {
    const value = line.trim();
    if (!value) continue;
    if (seen.has(value)) throw new Error(`清单存在重复对象：${value}`);
    seen.add(value);
    subjects.push(value);
  }
  if (!subjects.length) throw new Error('请先填写至少一个待查对象标识');
  if (subjects.length > 600) throw new Error('待查清单不能超过 600 个对象');
  return subjects.map((id) => ({ id }));
}

function renderSheet(sheet, model) {
  const head = $('inventory-result-head');
  head.replaceChildren();
  head.append(
    el('span', `单号 ${sheet.sheet}`),
    el('span', `截至点 #${sheet.cutoff_sequence}`),
    el('span', `对象 ${sheet.total}`),
    el('span', `快照 ${sheet.sheet_digest.slice(0, 12)}`),
  );
  const counts = Object.entries(sheet.counts)
    .filter(([, n]) => n > 0)
    .map(([state, n]) => `${STATE_TEXT[state] || state} ${n}`)
    .join('　');
  $('inventory-counts').textContent = counts;

  const table = $('inventory-table');
  table.replaceChildren(el('thead'));
  const headerRow = el('tr');
  ['对象', '盘点状态', '引用封存', '证据入口'].forEach((title) => headerRow.append(el('th', title)));
  table.firstChild.append(headerRow);
  const body = el('tbody');
  for (const entry of sheet.entries) {
    const tr = el('tr');
    tr.append(el('td', entry.id));
    const stateCell = el('td');
    const state = el('span', STATE_TEXT[entry.state] || entry.state, 'state');
    state.dataset.state = entry.state;
    stateCell.append(state);
    tr.append(stateCell);
    const evidence = entry.evidence;
    tr.append(el('td', evidence ? `#${evidence.sequence} · ${evidence.digest.slice(0, 12)}` : '—'));
    const linkCell = el('td');
    if (evidence) {
      const link = el('a', evidence.export, 'export-link');
      link.href = model.prefix + evidence.export;
      linkCell.append(link);
    } else {
      linkCell.textContent = '—';
    }
    tr.append(linkCell);
    body.append(tr);
  }
  table.append(body);
  $('inventory-empty').hidden = sheet.entries.length !== 0;
  table.hidden = sheet.entries.length === 0;
}

function renderLedger(records) {
  const select = $('inventory-reopen');
  select.replaceChildren(new Option('选择已签发盘点单', ''));
  records.forEach((record) => {
    select.append(new Option(`${record.sheet} · 截至点 #${record.cutoff_sequence} · ${record.issued_at}`, record.sheet));
  });
}

export function inventoryPanel(request, model) {
  model.prefix = document.body.dataset.prefix;

  async function refreshLedger() {
    renderLedger(await request('inventory-sheets'));
  }

  $('inventory-issue').addEventListener('click', async () => {
    const checklist = parseChecklist($('inventory-checklist').value);
    const rawCutoff = $('inventory-cutoff').value.trim();
    const body = { checklist };
    if (rawCutoff) body.cutoff_sequence = Number(rawCutoff);
    const sheet = await request('inventory', body);
    renderSheet(sheet, model);
    await refreshLedger();
    $('inventory-reopen').value = sheet.sheet;
    $('status').dataset.kind = '';
    $('status').textContent = `盘点单 ${sheet.sheet} 已按截至点 #${sheet.cutoff_sequence} 签发`;
  });

  $('inventory-reopen').addEventListener('change', async () => {
    const sheetNo = $('inventory-reopen').value;
    if (!sheetNo) return;
    const sheet = await request(`inventory/${sheetNo}`);
    renderSheet(sheet, model);
    const unreadable = Object.entries(sheet.evidence_state)
      .filter(([, ok]) => ok === false)
      .map(([id]) => id);
    $('status').dataset.kind = unreadable.length ? 'error' : '';
    $('status').textContent = unreadable.length
      ? `已按单号重开 ${sheetNo}：${unreadable.join('、')} 的证据现在不能复核，分类仍按签发时保留`
      : `已按单号重开 ${sheetNo}，引用证据当前均可复核`;
  });

  return { refreshLedger };
}
