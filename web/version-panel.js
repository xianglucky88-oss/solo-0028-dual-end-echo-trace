export function versionPanel(request, base) {
  async function refresh(selected) {
    const list = await request('revisions');
    for (const id of ['left-version', 'right-version']) {
      const select = document.getElementById(id);
      const previous = select.value;
      select.replaceChildren(new Option('选择封存版本', ''));
      list.forEach((record) => select.append(new Option(`${record.sequence} · ${record.subject} · ${record.digest.slice(0, 8)}`, record.digest)));
      select.value = id === 'right-version' && selected ? selected : previous;
      if (select.selectedIndex < 0) select.selectedIndex = 0;
    }
    document.getElementById('archive-count').textContent = `${list.length} 份`;
    updateExport();
  }

  function updateExport() {
    const selected = document.getElementById('right-version').value;
    const link = document.getElementById('export');
    link.hidden = !selected;
    if (selected) link.href = `${base}export/${selected}`;
  }

  async function seal(source) {
    const revision = await request('seal', source);
    const packet = await request(`packet/${revision.digest}`);
    return { revision, packet };
  }

  async function inspect() {
    const digest = document.getElementById('right-version').value;
    if (!digest) throw new Error('先选择一份封存版本');
    return request(`packet/${digest}`);
  }

  async function compare() {
    const left = document.getElementById('left-version').value, right = document.getElementById('right-version').value;
    if (!left || !right) throw new Error('先选择两个版本');
    const result = await request('compare', { left, right });
    return { left, right, rows: result.rows };
  }

  document.getElementById('right-version').addEventListener('change', updateExport);
  return { refresh, seal, inspect, compare };
}
