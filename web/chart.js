const ns = 'http://www.w3.org/2000/svg';
function mark(svg, tag, attrs, text) {
  const node = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text !== undefined) node.textContent = text;
  svg.append(node);
  return node;
}
const line = (svg, x1, y1, x2, y2, cls = 'line') => mark(svg, 'line', { x1, y1, x2, y2, class: cls });
const rect = (svg, x, y, width, height, cls) => mark(svg, 'rect', { x, y, width, height, class: cls });
const dot = (svg, cx, cy, cls, r = 3) => mark(svg, 'circle', { cx, cy, r, class: cls });
const text = (svg, x, y, value) => mark(svg, 'text', { x, y }, value);
const path = (svg, points, cls) => mark(svg, 'polyline', { points: points.map((p) => p.join(',')).join(' '), class: cls });
function scale(lo, hi, a, b) { return (n) => a + (b - a) * (n - lo) / (hi - lo || 1); }
function range(values, fallback = [0, 1]) { return values.length ? [Math.min(...values), Math.max(...values)] : fallback; }
function grid(svg, a, b, unit) {
  for (let index = 0; index <= 5; index++) {
    const x = 58 + index * 122;
    line(svg, x, 30, x, 197);
    text(svg, x - 7, 217, Number((a + (b - a) * index / 5).toPrecision(4)));
  }
  text(svg, 686, 217, unit);
}

function render(svg, { outputs }) {
    const [a,b] = range(outputs.wave.map((p) => p.time));
    const x = scale(a,b,58,668);
    grid(svg,a,b,'纳秒');
    for (const [i,key] of ['left','right'].entries()) {
      const center = i ? 147 : 75;
      const y = (v) => center - v * 33;
      line(svg,58,center,668,center);
      text(svg,13,center + 5,i ? '乙端' : '甲端');
      path(svg,outputs.wave.filter((r) => r.side === key).map((r) => [x(r.time),y(r.value)]),i ? 'series secondary' : 'series');
    }
}

export function draw(svg, packet, config) {
  svg.replaceChildren();
  mark(svg, 'title', {}, config.plot);
  render(svg, packet);
}
