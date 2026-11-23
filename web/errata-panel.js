export function errataPanel(request) {
  const select = document.getElementById('errata-list');

  async function refresh() {
    const list = await request('errata');
    const previous = select.value;
    select.replaceChildren(new Option('选择已签发勘误单', ''));
    for (const record of list) select.append(new Option(`${record.number} · ${record.digest.slice(0, 8)}`, record.number));
    select.value = previous;
    if (select.selectedIndex < 0) select.selectedIndex = 0;
    document.getElementById('errata-count').textContent = `${list.length} 份`;
  }

  async function register(sheet) {
    const result = await request('errata', sheet);
    await refresh();
    select.value = result.number;
    return result;
  }

  function selected() {
    return select.value;
  }

  return { refresh, register, selected };
}
