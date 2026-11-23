// 分批收档面板：登记批次、逐份收片段、查看缺口与争议、隔离冲突并按基准封存。
const $ = (id) => document.getElementById(id);

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  node.append(...children.flat().filter((c) => c !== undefined && c !== null));
  return node;
}

function short(id) {
  return typeof id === 'string' && id.length >= 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

export function intakePanel(request, base, onSealed) {
  let current = null;       // 最近一次快照
  let confirmId = null;     // 本次确认使用的标识（用于丢失响应后重试）

  async function call(route, body, expectedStatus = 200) {
    const response = await fetch(base + route, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const result = await response.json();
    if (response.status !== expectedStatus) {
      const error = new Error(result.error || '操作未完成');
      error.snapshot = result.snapshot;
      throw error;
    }
    return result;
  }

  function readJson(id) {
    try {
      return JSON.parse($(id).value);
    } catch {
      throw new Error('内容不是有效的 JSON');
    }
  }

  async function refresh(intakeId) {
    if (!intakeId) {
      const list = await request('intakes');
      renderList(list.intakes);
      return;
    }
    current = await request(`intake/${intakeId}`);
    renderSnapshot(current);
  }

  function renderList(intakes) {
    const box = $('intake-list');
    box.replaceChildren();
    if (!intakes.length) {
      box.append(h('p', { class: 'muted', text: '还没有登记过收档批次。' }));
      return;
    }
    for (const item of intakes) {
      box.append(h('button', {
        class: 'rowlink', type: 'button',
        text: `${item.cable} · ${short(item.intake)}`,
        onclick: () => refresh(item.intake),
      }));
    }
  }

  function seqChips(side) {
    const data = current.sides[side];
    const covered = new Set(data.covered);
    const quarantined = new Set(data.quarantined);
    const chips = [];
    for (let seq = data.sequence_start; seq <= data.sequence_end; seq += 1) {
      const state = quarantined.has(seq) ? 'chip-quarantine' : covered.has(seq) ? 'chip-covered' : 'chip-missing';
      chips.push(h('span', { class: `seq-chip ${state}`, text: String(seq), title: covered.has(seq) ? '已收' : '缺口' }));
    }
    return h('div', { class: 'seq-strip', 'aria-label': `${side} 端序号覆盖` }, ...chips);
  }

  function renderSnapshot(snap) {
    $('intake-id').textContent = snap.intake;
    $('intake-cable').textContent = snap.cable;
    $('intake-basis').textContent = snap.basis;
    const state = $('intake-state');
    state.textContent = snap.ready ? '两端齐全且无冲突，可以归档'
      : snap.has_conflict ? '存在读数争议，需先隔离冲突片段'
      : snap.complete ? '序号已齐，但仍有未处理事项' : '尚有缺口序号';
    state.dataset.state = snap.ready ? 'ready' : 'blocked';
    state.className = `state state-${snap.ready ? 'ready' : 'blocked'}`;

    for (const side of ['left', 'right']) {
      const data = snap.sides[side];
      $(`intake-${side}-summary`).replaceChildren(
        h('div', { class: 'side-head' },
          h('strong', { text: side === 'left' ? '甲端' : '乙端' }),
          h('span', { class: 'muted', text: `序号 ${data.sequence_start}–${data.sequence_end} · 已收 ${data.covered.length} · 缺口 ${data.missing.length}` })),
        seqChips(side),
        h('div', { class: 'muted small', text: data.missing.length ? `缺口序号：${data.missing.join('、')}` : '登记序号已全部收齐' }),
        renderReceipts(data.receipts));
    }

    const conflictBox = $('intake-conflicts');
    conflictBox.replaceChildren();
    if (snap.conflicts.length) {
      for (const conflict of snap.conflicts) {
        const sideName = conflict.side === 'left' ? '甲端' : '乙端';
        conflictBox.append(h('div', { class: 'conflict-card' },
          h('strong', { text: `${sideName} 序号 ${conflict.sequence} 存在不同读数` }),
          h('ul', {}, ...conflict.receipts.map((r) => h('li', {},
            h('span', { text: `来源「${r.origin}」 回执 ${short(r.receipt)}` }),
            h('button', {
              class: 'quarantine-btn', type: 'button', text: '隔离这份',
              onclick: () => quarantine(r.receipt),
            })))),
          h('p', { class: 'muted small', text: '系统不会默认采用最后到达的一份；请核对后隔离错误来源。' })));
      }
    }
    $('intake-confirm').disabled = !snap.ready;
    $('fragment-intake').value = snap.intake;
  }

  function renderReceipts(receipts) {
    if (!receipts.length) return h('p', { class: 'muted small', text: '暂未收到片段' });
    return h('ul', { class: 'receipt-list' }, ...receipts.map((r) => h('li', {
      class: r.status === 'quarantined' ? 'is-quarantined' : '',
    },
      h('span', { text: `#${r.sequence} · ${r.origin} · ${short(r.receipt)}` }),
      h('span', { class: `state state-${r.status}`, text: r.status === 'quarantined' ? '已隔离' : '已收' }))));
  }

  async function register() {
    const body = readJson('intake-registration');
    const result = await call('intake/register', body);
    await refresh(result.intake);
    note(result.receipt.duplicate ? '该批次已登记，取回原登记回执' : '收档批次已登记，可以开始交片段');
  }

  async function submitFragment() {
    const body = readJson('intake-fragment');
    const result = await call('intake/fragment', body);
    await refresh(result.intake);
    note(result.receipt.duplicate
      ? `重复提交，取回原回执 ${short(result.receipt.receipt)}`
      : `片段已收下，回执 ${short(result.receipt.receipt)}`);
  }

  async function quarantine(receipt) {
    const reason = prompt('请填写隔离该片段的原因：');
    if (!reason || !reason.trim()) return;
    const result = await call('intake/quarantine', {
      intake: current.intake, receipt, reason: reason.trim(),
    });
    await refresh(result.intake);
    note(result.duplicate ? '该回执此前已隔离' : '冲突片段已隔离，材料清单基准已更新');
  }

  async function confirm() {
    if (!current || !current.ready) return;
    confirmId = confirmId || (await cryptoRandomId());
    try {
      const result = await call('intake/confirm', {
        intake: current.intake, confirm: confirmId, basis: current.basis,
      });
      note(result.duplicate
        ? `响应曾丢失，已查回同一份成果（第 ${result.confirmation.sequence} 版）`
        : `已封存第 ${result.confirmation.sequence} 版，材料清单与实际片段已固定`);
      confirmId = null;
      await onSealed?.(result.packet.digest);
      await refresh(current.intake);
    } catch (error) {
      if (error.snapshot) {
        current = error.snapshot;
        renderSnapshot(current);
        note(`材料清单在核对后发生变化：${error.message}。请按最新回执重新核对后再确认。`, true);
        confirmId = null;
      } else {
        note(error.message, true);
      }
    }
  }

  function note(text, isError = false) {
    const node = $('intake-status');
    node.textContent = text;
    node.dataset.kind = isError ? 'error' : '';
  }

  async function cryptoRandomId() {
    const buffer = new Uint8Array(32);
    crypto.getRandomValues(buffer);
    return Array.from(buffer, (b) => b.toString(16).padStart(2, '0')).join('');
  }

  function mount() {
    const app = $('intake-app');
    const registerCard = h('section', { class: 'intake-card' },
      h('h3', { text: '1. 登记台架采集' }),
      h('p', { class: 'muted small', text: '登记所属线缆、两端采样序号范围与完整档所需标定；登记后长期保存，可随时离开页面。' }),
      h('textarea', { id: 'intake-registration', rows: '12', spellcheck: 'false' }),
      h('div', { class: 'card-actions' },
        h('button', { type: 'button', text: '登记批次', onclick: register }),
        h('button', { type: 'button', text: '填入样例登记', onclick: fillSampleRegistration })));
    const fragmentCard = h('section', { class: 'intake-card' },
      h('h3', { text: '2. 逐份交带序号波形片段' }),
      h('p', { class: 'muted small', text: '允许乱序到达；同一份重复提交只取回原回执，读数完全相同的重叠片段视为同一条证据。' }),
      h('textarea', { id: 'intake-fragment', rows: '10', spellcheck: 'false' }),
      h('div', { class: 'card-actions' },
        h('button', { type: 'button', text: '提交片段', onclick: submitFragment })));
    const progressCard = h('section', { class: 'intake-card intake-progress' },
      h('h3', { text: '3. 收档进度与归档确认' }),
      h('div', { class: 'intake-meta' },
        h('label', {}, h('span', { class: 'muted', text: '批次' }), h('code', { id: 'intake-id', text: '—' })),
        h('label', {}, h('span', { class: 'muted', text: '线缆' }), h('strong', { id: 'intake-cable', text: '—' })),
        h('label', {}, h('span', { class: 'muted', text: '材料基准' }), h('code', { id: 'intake-basis', text: '—' }))),
      h('p', { id: 'intake-state', class: 'state', 'data-state': 'blocked', text: '尚未选择批次' }),
      h('div', { class: 'side-progress' },
        h('div', { id: 'intake-left-summary' }),
        h('div', { id: 'intake-right-summary' })),
      h('div', { id: 'intake-conflicts' }),
      h('div', { class: 'card-actions' },
        h('button', { id: 'intake-confirm', class: 'primary', type: 'button', text: '按当前核对的回执封存', onclick: confirm, disabled: true }),
        h('button', { type: 'button', text: '刷新进度', onclick: () => current && refresh(current.intake) })),
      h('p', { id: 'intake-status', class: 'intake-note', role: 'status', 'aria-live': 'polite' }));
    const listCard = h('section', { class: 'intake-card' },
      h('h3', { text: '已登记批次' }),
      h('div', { id: 'intake-list', class: 'intake-list' }),
      h('input', { id: 'fragment-intake', type: 'hidden' }));
    app.append(
      h('div', { class: 'intake-grid' }, registerCard, fragmentCard),
      progressCard,
      listCard);
  }

  async function fillSampleRegistration() {
    const sample = await request('sample');
    $('intake-registration').value = JSON.stringify({
      cable: sample.id,
      length: sample.length,
      speed: sample.speed,
      tolerance: sample.tolerance,
      left: {
        sequence_start: 0, sequence_end: 6,
        zero: sample.left.zero, dead: sample.left.dead, threshold: sample.left.threshold,
      },
      right: {
        sequence_start: 0, sequence_end: 7,
        zero: sample.right.zero, dead: sample.right.dead, threshold: sample.right.threshold,
      },
    }, null, 2);
  }

  mount();
  refresh();
  return { refresh };
}
