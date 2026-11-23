import { draw } from '/chart.js';
import { renderRows } from '/result-table.js';
import { versionPanel } from '/version-panel.js';

const $ = (id) => document.getElementById(id);
const base = document.body.dataset.prefix;
let model, packet, mode;
let busy = false;

async function request(path, data) {
  const options = data === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  };
  const response = await fetch(base + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作未完成');
  return result;
}

function note(text, kind = '') {
  $('status').textContent = text;
  $('status').dataset.kind = kind;
}

const stageButtons = () => document.querySelectorAll('#stages button, #review-stages button');

function renderOperation(next) {
  mode = next;
  const spec = model.operations.find((op) => op.id === mode);
  $('table-title').textContent = spec.label;
  for (const button of stageButtons()) button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  renderRows(model, packet.outputs[mode] ?? [], spec.columns);
}

function show(next) {
  packet = next;
  $('subject').textContent = next.subject;
  $('digest').textContent = next.digest.slice(0, 12);
  draw($('visual'), next, model);
  const review = Object.hasOwn(next.source, 'review');
  $('review-pane').hidden = !review;
  if (!review) $('review-pane').open = false;
  renderOperation(Object.hasOwn(next.outputs, mode) ? mode : model.defaultOperation);
}

function source() {
  try {
    return JSON.parse($('source').value);
  } catch {
    throw new Error('数据包不是有效的 JSON');
  }
}

async function guarded(action) {
  if (busy) return;
  busy = true;
  document.body.setAttribute('aria-busy', 'true');
  try {
    await action();
  } catch (error) {
    note(error.message === 'Failed to fetch' ? '无法连接本机服务' : error.message, 'error');
  } finally {
    busy = false;
    document.body.setAttribute('aria-busy', 'false');
  }
}

async function choose(path) {
  const data = await request(path);
  const next = await request('evaluate', data);
  $('source').value = JSON.stringify(data, null, 2);
  show(next);
  if (path === 'review-sample') {
    $('review-pane').open = true;
    renderOperation(model.operations.find((op) => op.optional).id);
  }
  note(({ sample:'样例已处理', alternate:'对照样例已处理', 'review-sample':'复核样例已处理' })[path]);
}

function bind(id, action, event = 'click') {
  $(id).addEventListener(event, () => guarded(action));
}

guarded(async () => {
  model = await request('config');
  const versions = versionPanel(request, base);
  for (const spec of model.operations) {
    const button = document.createElement('button');
    button.textContent = spec.label;
    button.dataset.mode = spec.id;
    button.addEventListener('click', () => packet && renderOperation(spec.id));
    $(spec.optional ? 'review-stages' : 'stages').append(button);
  }
  bind('sample', () => choose('sample'));
  bind('review-sample', () => choose('review-sample'));
  bind('alternate', () => choose('alternate'));
  bind('evaluate', async () => {
    show(await request('evaluate', source()));
    note('已完成数据归约');
  });
  bind('upload', async () => {
    const file = $('upload').files[0];
    if (!file) return;
    if (file.size > 512 * 1024) throw new Error('数据包大于 512 KiB');
    $('source-pane').open = true;
    $('source').value = await file.text();
    show(await request('evaluate', source()));
    note('文件已导入并处理');
  }, 'change');
  bind('seal', async () => {
    const { revision: result, packet: saved } = await versions.seal(source());
    show(saved);
    await versions.refresh(result.digest);
    note(result.created ? `已封存第 ${result.sequence} 版` : `与第 ${result.sequence} 版相同，未重复入库`);
  });
  bind('inspect', async () => {
    const saved = await versions.inspect();
    $('source').value = JSON.stringify(saved.source, null, 2);
    show(saved);
    note('已打开封存版本');
  });
  bind('compare', async () => {
    const { left, right, rows } = await versions.compare();
    for (const button of stageButtons()) button.setAttribute('aria-pressed', 'false');
    $('table-title').textContent = '版本差异';
    renderRows(model, rows, ['id', 'stage', 'state', 'before', 'after'], '差异', { ...model.columns, before: '参照版本', after: '目标版本' });
    note(`已比较 ${left.slice(0, 8)} 与 ${right.slice(0, 8)}`);
  });
  await versions.refresh();
  await choose('sample');
});
