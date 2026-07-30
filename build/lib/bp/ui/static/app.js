/* Albatross — the browser half.
 *
 * Three rules this file keeps:
 *
 * 1. No logic. Every status, support set, frontier rank and diagnostic comes
 *    from the server, which gets it from the deterministic core. If this file
 *    ever needs to *decide* something about the mathematics, that decision
 *    belongs in Python.
 *
 * 2. Nothing blocks. Role calls return a job id and the page polls. The
 *    interface always says which agent is working.
 *
 * 3. No untrusted HTML, ever. Statements and proofs are LaTeX written by models
 *    and by the user. Prose goes in through textContent; mathematics goes
 *    through katex.renderToString, whose output is the only HTML this file
 *    inserts. In the terminal the same mistake was cosmetic — `\[` displayed as
 *    `[`. Here it would be script execution.
 */

'use strict';

const state = {
  graph: null,
  selected: null,
  collapsed: new Set(),   // view-only; the graph is never mutated by folding
  jobs: [],
  busy: new Set(),
  editing: null,          // 'statement' | 'proof' | null
  macros: {},             // parsed from preamble.tex, handed to KaTeX
  labels: {},             // label -> {node, section, number}: the xref index
  cy: null,
};

/* ---------------------------------------------------------------- plumbing */

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (e) { /* not json */ }
    throw new Error(detail);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('json') ? response.json() : response.text();
}

const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body || {}),
});

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === 'class') node.className = value;
    else if (key === 'onclick') node.onclick = value;
    else if (key === 'html') node.innerHTML = value;   // KaTeX output only
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

let toastTimer = null;
function toast(message, bad) {
  const box = document.getElementById('toast');
  box.textContent = message;
  box.className = 'toast' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add('hidden'), bad ? 7000 : 3200);
}

/* ------------------------------------------------------- mathematics as HTML */

// The delimiters mathematicians actually type. Besides $…$, $$…$$, \[…\] and
// \(…\), an `align` (or `equation`, `gather`, …) environment is very often
// written bare, with no dollar signs around it — that is standard LaTeX and
// KaTeX renders it directly. Missing them meant a displayed equation came out
// as literal source, which is how this list got longer.
const DISPLAY_ENVS = [
  'align', 'equation', 'gather', 'multline', 'alignat', 'flalign', 'eqnarray',
  'displaymath', 'CD',
].map((e) => e + '\\*?').join('|');
const MATH_RE = new RegExp(
  '(' +
  '\\$\\$[\\s\\S]*?\\$\\$' +                                  // $$ … $$
  '|\\\\\\[[\\s\\S]*?\\\\\\]' +                            // \[ … \]
  '|\\\\\\([\\s\\S]*?\\\\\\)' +                            // \( … \)
  '|\\\\begin\\{(?:' + DISPLAY_ENVS + ')\\}[\\s\\S]*?\\\\end\\{(?:' + DISPLAY_ENVS + ')\\}' +
  '|\\$[^$\\n]+?\\$' +                                        // $ … $
  ')',
  'g',
);
const REF_RE = /`([A-Za-z0-9][A-Za-z0-9._-]*)`/g;

/* --- the project's own macros ------------------------------------------------
 *
 * KaTeX takes a macro map but does NOT learn from a \newcommand it renders, so
 * the preamble has to be parsed. This is presentation only — it decides how your
 * notation is *drawn*, never anything about the graph — which is why it can live
 * in the browser at all.
 */

/** Read a balanced {...} group starting at `i` (which must be the brace). */
function readGroup(src, i) {
  if (src[i] !== '{') return null;
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '\\') { j++; continue; }
    if (src[j] === '{') depth++;
    else if (src[j] === '}') {
      depth--;
      if (depth === 0) return { body: src.slice(i + 1, j), end: j + 1 };
    }
  }
  return null;
}

/** \newcommand / \renewcommand / \providecommand / \def / \DeclareMathOperator. */
function parsePreamble(text) {
  const macros = {};
  const src = text.replace(/(^|[^\\])%.*$/gm, '$1');   // drop LaTeX comments
  const cmd = /\\(newcommand|renewcommand|providecommand|DeclareMathOperator)(\*?)\s*/g;
  let m;
  while ((m = cmd.exec(src)) !== null) {
    let i = m.index + m[0].length;
    let name;
    if (src[i] === '{') {
      const g = readGroup(src, i);
      if (!g) continue;
      name = g.body.trim(); i = g.end;
    } else if (src[i] === '\\') {
      const mm = /^\\[A-Za-z]+/.exec(src.slice(i));
      if (!mm) continue;
      name = mm[0]; i += mm[0].length;
    } else continue;
    if (!/^\\[A-Za-z]+$/.test(name)) continue;

    while (src[i] === ' ') i++;
    let argc = 0;
    if (src[i] === '[') {                      // [n] argument count
      const close = src.indexOf(']', i);
      const n = parseInt(src.slice(i + 1, close), 10);
      if (!isNaN(n)) argc = n;
      i = close + 1;
      if (src[i] === '[') {                    // an optional-arg default; KaTeX
        const g = readGroup(src, src.indexOf('[', i));   // has no equivalent, so
        i = src.indexOf(']', i) + 1;                     // it is skipped
      }
    }
    while (src[i] === ' ' || src[i] === '\n') i++;
    const body = readGroup(src, i);
    if (!body) continue;
    macros[name] = m[1] === 'DeclareMathOperator'
      ? '\\operatorname' + (m[2] || '') + '{' + body.body + '}'
      : body.body;
  }

  // \def\foo{...} — no argument spec supported, which covers the common case.
  const def = /\\def\s*(\\[A-Za-z]+)\s*/g;
  while ((m = def.exec(src)) !== null) {
    const body = readGroup(src, m.index + m[0].length);
    if (body) macros[m[1]] = body.body;
  }
  return macros;
}

async function loadMacros() {
  try {
    const text = await api('/api/preamble');
    state.macros = parsePreamble(text || '');
  } catch (e) { state.macros = {}; }
}

/** The cross-reference index, so `\\eqref` can be resolved before KaTeX sees it.
 *
 * Refreshed with the graph, because editing a statement can add or remove a label.
 * A failure here degrades display only: references fall back to showing the label
 * name, which is still better than the literal `\\eqrefeq:m` KaTeX produces. */
async function loadLabels() {
  try {
    state.labels = (await api('/api/labels')).labels || {};
  } catch (e) { state.labels = {}; }
}

function renderMath(tex, display) {
  try {
    return katex.renderToString(tex, {
      displayMode: display, throwOnError: false, macros: state.macros,
    });
  } catch (e) {
    return null;   // fall back to showing the source, escaped
  }
}

/* --- LaTeX cross-references ---------------------------------------------------
 *
 * KaTeX does not resolve `\ref`, `\eqref` or `\cref`. Worse than failing, it
 * renders them as literal garbage — `\eqref{eq:m}` comes out as `\eqrefeq:m`
 * with no error node at all, so `throwOnError: false` never sees it. So they are
 * pulled out of the text and replaced *before* anything reaches KaTeX.
 *
 * A resolved reference shows the number LaTeX assigned (read back from the last
 * compile's .aux — predicting it here would mean reimplementing LaTeX's counters)
 * and links to the node that defines it. An unresolved one is shown as broken,
 * because that is what it is: XRF001, and `??` in the PDF.
 */
const XREF_RE = new RegExp(
  '\\\\(ref|eqref|cref|Cref|cpageref|autoref|nameref|pageref|vref)\\s*\\{([^}]*)\\}',
  'g',
);

/** Replace one reference with a chip saying where it points. */
function xrefChip(command, name) {
  const known = state.labels && state.labels[name];
  if (!known) {
    return el('span', {
      class: 'xref broken',
      title: `\\${command}{${name}} — no node defines this label. The PDF prints ?? here (XRF001).`,
    }, `[?${name}]`);
  }
  // `\eqref` conventionally parenthesises; the others do not.
  const number = known.number
    ? (command === 'eqref' ? `(${known.number})` : known.number)
    : name;
  const chip = el('a', {
    class: 'xref' + (known.duplicate ? ' broken' : ''),
    title: known.duplicate
      ? `\\${command}{${name}} — defined in more than one node, so this may point at the wrong thing (XRF002).`
      : `\\${command}{${name}} — defined in the ${known.section} of ${known.node}`
        + (known.number ? '' : '. Build the PDF once to see its number.'),
    onclick: () => select(known.node),
  }, number);
  return chip;
}

/** Prose with node references and LaTeX cross-references linked.
 *
 * Everything goes in as text; the only markup anywhere in this file comes from
 * KaTeX. */
function proseWithRefs(text, into) {
  // Cross-references first: they are unambiguous and must not be handed to KaTeX.
  let cursor = 0;
  XREF_RE.lastIndex = 0;
  let xm;
  const chunks = [];
  while ((xm = XREF_RE.exec(text)) !== null) {
    if (xm.index > cursor) chunks.push({ text: text.slice(cursor, xm.index) });
    chunks.push({ chip: xrefChip(xm[1], xm[2].trim()) });
    cursor = xm.index + xm[0].length;
  }
  if (cursor < text.length) chunks.push({ text: text.slice(cursor) });

  for (const chunk of chunks) {
    if (chunk.chip) { into.append(chunk.chip); continue; }
    nodeRefsInto(chunk.text, into);
  }
}

/** Backtick-quoted node ids become links to those nodes. */
function nodeRefsInto(text, into) {
  let last = 0;
  REF_RE.lastIndex = 0;
  let match;
  while ((match = REF_RE.exec(text)) !== null) {
    if (match.index > last) into.append(text.slice(last, match.index));
    const id = match[1];
    if (state.graph && state.graph.byId[id]) {
      into.append(el('a', { class: 'noderef', onclick: () => select(id) }, id));
    } else {
      into.append(el('code', {}, id));
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) into.append(text.slice(last));
}

/** Make a math fragment safe for KaTeX, and number it the way the PDF will.
 *
 * KaTeX supports neither `\label` nor `\eqref`, and does not number equations at
 * all — but it does support `\tag`. So a labelled display has its `\label` swapped
 * for a `\tag` carrying the number LaTeX actually assigned, which is how the
 * browser comes to show the same equation numbers as the document. Without a
 * compile there is no number yet, and the label is simply dropped.
 */
function sanitiseMath(tex) {
  const numberOf = (name) => (state.labels && state.labels[name] && state.labels[name].number) || '';

  let out = tex.replace(/\\label\s*\{([^}]*)\}/g, (_, name) => {
    const n = numberOf(name.trim());
    return n ? `\\tag{${n}}` : '';
  });

  out = out.replace(XREF_RE, (_, command, raw) => {
    const name = raw.trim();
    const n = numberOf(name);
    if (!n) return `\\text{[?${name}]}`;
    return command === 'eqref' ? `\\text{(${n})}` : `\\text{${n}}`;
  });
  return out;
}

/** Render LaTeX prose: text as text, mathematics through KaTeX. */
function mathProse(text) {
  const frag = document.createDocumentFragment();
  if (!text || !text.trim()) return frag;
  let last = 0;
  MATH_RE.lastIndex = 0;
  let match;
  while ((match = MATH_RE.exec(text)) !== null) {
    if (match.index > last) proseWithRefs(text.slice(last, match.index), frag);
    const token = match[0];
    let tex, display;
    if (token.startsWith('$$')) { tex = token.slice(2, -2); display = true; }
    else if (token.startsWith('\\[')) { tex = token.slice(2, -2); display = true; }
    else if (token.startsWith('\\(')) { tex = token.slice(2, -2); display = false; }
    else if (token.startsWith('\\begin{')) { tex = token; display = true; }  // KaTeX takes the whole env
    else { tex = token.slice(1, -1); display = false; }
    const html = renderMath(sanitiseMath(tex), display);
    if (html) frag.append(el('span', { html: html }));
    else frag.append(token);   // as text, not as markup
    last = match.index + token.length;
  }
  if (last < text.length) proseWithRefs(text.slice(last), frag);
  return frag;
}

/* --------------------------------------------------------------- the graph */

const STATUS_CLASS = (status) => {
  if (!status) return 'open';
  if (status === 'proved') return 'proved';
  if (status === 'proved_modulo') return 'proved_modulo';
  if (status === 'unsound') return 'unsound';
  if (status === 'open') return 'open';
  return 'blocked';
};

const FILL = {
  proved: '#dff0e4', proved_modulo: '#d7eded', blocked: '#fbead0',
  open: '#eceae6', unsound: '#f9dedc',
};
const STROKE = {
  proved: '#2e7d4f', proved_modulo: '#2a7d7d', blocked: '#b26a00',
  open: '#7a7a7a', unsound: '#b3261e',
};

function initCytoscape() {
  state.cy = cytoscape({
    container: document.getElementById('cy'),
    minZoom: 0.2,
    maxZoom: 2.5,
    wheelSensitivity: 0.25,
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'shape': 'round-rectangle',
          'width': 'label', 'height': 'label',
          'padding': '9px',
          'text-valign': 'center', 'text-halign': 'center',
          'text-wrap': 'wrap', 'text-max-width': '190px',
          'font-size': '11px',
          'font-family': 'ui-monospace, Menlo, monospace',
          'background-color': 'data(fill)',
          'border-color': 'data(stroke)',
          'border-width': 'data(borderWidth)',
          'border-style': 'data(borderStyle)',
          'color': '#222',
        },
      },
      {
        selector: 'node[?isTarget]',
        style: { 'font-weight': 'bold', 'font-size': '12px' },
      },
      {
        selector: 'node:selected',
        style: { 'border-width': 4, 'border-color': '#1b5e9c' },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.4, 'line-color': '#c8c2b8',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle', 'target-arrow-color': '#c8c2b8',
          'arrow-scale': 0.8,
        },
      },
    ],
  });

  state.cy.on('tap', 'node', (evt) => {
    const node = evt.target;
    // The chevron is the left edge of the node box. Tapping it folds the
    // subtree in the *view only* — no request, no mutation, nothing written.
    const box = node.renderedBoundingBox();
    const x = evt.renderedPosition ? evt.renderedPosition.x : box.x1 + 100;
    const hasChildren = (node.data('childCount') || 0) > 0;
    if (hasChildren && x < box.x1 + 22) {
      toggleCollapse(node.id());
      return;
    }
    select(node.id());
  });

  state.cy.on('tap', (evt) => { if (evt.target === state.cy) { /* keep selection */ } });
}

function hiddenByCollapse(graph) {
  // A node is hidden when every path to it from a root passes through a
  // collapsed node. Computed here rather than server-side because folding is
  // a property of this browser tab, not of the project.
  const visible = new Set();
  const roots = graph.nodes.filter((n) => !graph.hasParent[n.id]).map((n) => n.id);
  const seeds = roots.length ? roots : graph.nodes.map((n) => n.id);
  const queue = [...seeds];
  while (queue.length) {
    const id = queue.shift();
    if (visible.has(id)) continue;
    visible.add(id);
    if (state.collapsed.has(id)) continue;
    for (const child of (graph.byId[id] || { children: [] }).children) {
      if (graph.byId[child]) queue.push(child);
    }
  }
  return visible;
}

function drawGraph() {
  const graph = state.graph;
  const visible = hiddenByCollapse(graph);
  const elements = [];
  for (const node of graph.nodes) {
    if (!visible.has(node.id)) continue;
    const cls = STATUS_CLASS(node.global_status);
    const childCount = node.children.filter((c) => graph.byId[c]).length;
    const chevron = childCount ? (state.collapsed.has(node.id) ? '▸ ' : '▾ ') : '';
    const folded = state.collapsed.has(node.id) ? `  (+${countSubtree(node.id)})` : '';
    elements.push({
      data: {
        id: node.id,
        label: chevron + node.id + folded,
        fill: FILL[cls],
        stroke: STROKE[cls],
        borderWidth: node.flagged ? 3.5 : 1.6,
        borderStyle: node.stale ? 'dashed' : 'solid',
        isTarget: node.target ? 1 : 0,
        childCount: childCount,
      },
    });
  }
  for (const edge of graph.edges) {
    if (!visible.has(edge.source) || !visible.has(edge.target)) continue;
    if (state.collapsed.has(edge.source)) continue;
    elements.push({ data: { id: edge.source + '->' + edge.target, ...edge } });
  }

  const pan = state.cy.pan(), zoom = state.cy.zoom();
  const hadElements = state.cy.elements().length > 0;
  state.cy.elements().remove();
  state.cy.add(elements);
  state.cy.layout({
    name: 'breadthfirst',
    directed: true,
    roots: graph.target && visible.has(graph.target) ? [graph.target] : undefined,
    padding: 28,
    spacingFactor: 1.15,
    animate: false,
  }).run();
  if (hadElements) { state.cy.zoom(zoom); state.cy.pan(pan); }
  else state.cy.fit(undefined, 40);

  if (state.selected && visible.has(state.selected)) {
    state.cy.$id(state.selected).select();
  }
}

function countSubtree(id) {
  const graph = state.graph;
  const seen = new Set();
  const queue = [...(graph.byId[id] ? graph.byId[id].children : [])];
  while (queue.length) {
    const current = queue.shift();
    if (seen.has(current) || !graph.byId[current]) continue;
    seen.add(current);
    queue.push(...graph.byId[current].children);
  }
  return seen.size;
}

function toggleCollapse(id) {
  if (state.collapsed.has(id)) state.collapsed.delete(id);
  else state.collapsed.add(id);
  drawGraph();
}

/* ------------------------------------------------------------- data loading */

async function refresh(keepSelection) {
  await loadLabels();
  const data = await api('/api/graph');
  data.byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]));
  data.hasParent = {};
  for (const edge of data.edges) data.hasParent[edge.target] = true;
  state.graph = data;
  drawGraph();
  drawCertificate();
  if (state.selected && !data.byId[state.selected]) state.selected = null;
  if (state.selected && keepSelection !== false) await showDetail(state.selected);
  else if (!state.selected) {
    document.getElementById('detail').className = 'empty';
    document.getElementById('detail').textContent = 'Select a node.';
  }
}

function drawCertificate() {
  const cert = state.graph.certificate;
  const box = document.getElementById('certificate');
  box.textContent = '';
  if (!cert.target) { box.append('no target node marked'); return; }
  const counts = Object.entries(state.graph.counts)
    .map(([k, v]) => `${v} ${k}`).join(', ');
  if (cert.status === 'proved') {
    box.append(el('b', {}, cert.target), ' is proved.');
  } else if (cert.status === 'proved_modulo') {
    box.append(el('b', {}, cert.target), ` holds relative to ${cert.support.length} item(s).`);
  } else {
    box.append(el('b', {}, cert.target), ` is ${cert.status}.`);
  }
  box.append(el('span', { class: 'muted' }, `  ·  ${counts}`));
}

async function select(id) {
  state.selected = id;
  state.editing = null;
  if (state.cy.$id(id).length) { state.cy.$('node:selected').unselect(); state.cy.$id(id).select(); }
  await showDetail(id);
}

/* ------------------------------------------------------------ detail panel */

async function showDetail(id) {
  let node;
  try { node = await api('/api/node/' + encodeURIComponent(id)); }
  catch (e) { toast(e.message, true); return; }

  const panel = document.getElementById('detail');
  panel.className = '';
  panel.textContent = '';
  const busy = state.busy.has(id);

  panel.append(el('div', { class: 'node-id' }, node.id + (node.target ? '  ★' : '')));

  const pills = el('div', { class: 'pills' });
  pills.append(el('span', { class: 'pill status ' + STATUS_CLASS(node.global_status) },
                  node.global_status));
  pills.append(el('span', { class: 'pill' }, node.role));
  pills.append(el('span', { class: 'pill' }, node.difficulty));
  pills.append(el('span', { class: 'pill' }, 'local: ' + node.local_status));
  if (node.stale) pills.append(el('span', { class: 'pill blocked' }, 'stale'));
  panel.append(pills);

  // Status line: support and blocked_by spelled out, not left as ids.
  const status = el('div', { class: 'statusline' });
  const why = node.why[0];
  const whyRow = el('div', { class: 'row' });
  whyRow.append(mathProse(why ? why.text : ''));
  status.append(whyRow);
  if (node.support_detail.length) {
    const row = el('div', { class: 'row' });
    row.append(el('span', { class: 'label' }, 'rests on: '));
    node.support_detail.forEach((s, i) => {
      if (i) row.append(', ');
      row.append(el('a', { class: 'noderef', onclick: () => select(s.id) }, s.id));
      if (s.reason) row.append(el('span', { class: 'muted' }, ` (${s.local_status}: ${s.reason})`));
      else row.append(el('span', { class: 'muted' }, ` (${s.local_status})`));
    });
    status.append(row);
  }
  if (node.blocked_by.length) {
    const row = el('div', { class: 'row' });
    row.append(el('span', { class: 'label' }, 'blocked by: '));
    node.blocked_by.forEach((b, i) => {
      if (i) row.append(', ');
      row.append(el('a', { class: 'noderef', onclick: () => select(b) }, b));
    });
    status.append(row);
  }
  if (node.parents.length) {
    const row = el('div', { class: 'row' });
    row.append(el('span', { class: 'label' }, 'cited by: '));
    node.parents.forEach((p, i) => {
      if (i) row.append(', ');
      row.append(el('a', { class: 'noderef', onclick: () => select(p) }, p));
    });
    status.append(row);
  }
  status.append(el('div', { class: 'row small muted' },
    `hash ${node.statement_hash}` +
    (Object.keys(node.verified_against).length ? '  ·  has a verification certificate' : '')));
  panel.append(status);

  if (busy) {
    panel.append(el('div', { class: 'warnbox' },
      'An agent is working on this node. Buttons that would write to it are disabled.'));
  }

  // --- hypotheses
  if (node.hypotheses.length) {
    panel.append(el('h3', { class: 'section' }, 'Hypotheses'));
    const list = el('ul', { class: 'hyplist' });
    for (const h of node.hypotheses) {
      const li = el('li', {}, el('span', { class: 'hid' }, h.id));
      li.append(mathProse('$' + h.tex + '$'));
      list.append(li);
    }
    panel.append(list);
  }

  // --- statement
  panel.append(sectionHeading('Statement', 'statement', node, busy));
  if (state.editing === 'statement') {
    panel.append(editor(node.statement, (text) =>
      tidyThenSave(node.id, text, 'statement', (final) => saveStatement(node.id, final))));
  } else {
    const body = el('div', { class: 'prose' });
    body.append(mathProse(node.statement));
    panel.append(body);
  }

  // --- proof
  panel.append(sectionHeading('Proof', 'proof', node, busy));
  if (state.editing === 'proof') {
    panel.append(editor(node.proof, (text) =>
      tidyThenSave(node.id, text, 'proof', async (final) => {
        await post(`/api/node/${encodeURIComponent(node.id)}/proof`, { text: final });
        state.editing = null;
        toast('proof saved');
        await refresh();
      })));
  } else if (node.proof.trim()) {
    const body = el('div', { class: 'prose' });
    body.append(mathProse(node.proof));
    panel.append(body);
  } else {
    panel.append(el('div', { class: 'prose muted' }, 'No proof written.'));
  }

  // --- discharge table
  if (node.children.length || Object.keys(node.uses).length) {
    const head = el('h3', { class: 'section' }, 'Discharges');
    head.append(el('button', {
      ...(busy ? { disabled: 'disabled' } : {}),
      onclick: () => dischargeDialog(node),
    }, 'edit'));
    panel.append(head);
    const uses = el('div', { class: 'uses' });
    for (const [cid, use] of Object.entries(node.uses)) {
      const head = el('div', { class: 'child' });
      head.append(el('a', { class: 'noderef', onclick: () => select(cid) }, cid));
      if (use.applied_to) { head.append(' applied to '); head.append(mathProse('$' + use.applied_to + '$')); }
      uses.append(head);
      for (const [hid, src] of Object.entries(use.discharges).sort()) {
        const admitted = src.trim().startsWith('ADMITTED');
        const row = el('div', { class: 'dis' + (admitted ? ' admitted' : '') });
        row.append(el('span', { class: 'hid' }, hid), '← ');
        row.append(mathProse(src));
        uses.append(row);
      }
    }
    panel.append(uses);
  }

  // --- claim ledger
  //
  // The `uses` table covers the children's hypotheses. This covers what the
  // reduction claims on its own account, which is where premise smuggling lives.
  // Unsourced claims are called out, because those are the ones that are debt.
  if (node.claims.length || node.has_proof) {
    const head = el('h3', { class: 'section' }, 'Claim ledger');
    head.append(el('button', {
      ...(busy ? { disabled: 'disabled' } : {}),
      onclick: () => runJob('extract', node.id),
    }, node.claims.length ? 're-extract' : 'extract'));
    panel.append(head);
    if (!node.claims.length) {
      panel.append(el('div', { class: 'prose muted small' },
        'Not extracted. Extraction lists every load-bearing claim this proof makes ' +
        'with the source the prose offers, so LED001 can fire on the ones that have ' +
        'none. One cheap call.'));
    } else {
      if (node.ledger_stale) {
        panel.append(el('div', { class: 'warnbox' },
          'This ledger was extracted from an earlier version of the proof. Re-extract: ' +
          'until then the audit is describing text that is no longer here.'));
      }
      const list = el('div', { class: 'uses' });
      for (const claim of node.claims) {
        const unsourced = claim.source.kind === 'none';
        const row = el('div', { class: 'dis' + (unsourced ? ' admitted' : '') });
        row.append(el('span', { class: 'hid' }, claim.id));
        // A claim's text is a math-mode fragment, like a hypothesis `tex` — the
        // dollars are the renderer's job, not the model's.
        row.append(mathProse('$' + claim.text + '$'));
        row.append(el('span', { class: 'muted small' }, unsourced
          ? '  ← UNSOURCED'
          : `  ← ${claim.source.kind}${claim.source.ref ? ': ' + claim.source.ref : ''}`));
        list.append(row);
      }
      panel.append(list);
      for (const d of node.ledger_diagnostics) {
        panel.append(el('div', { class: d.severity === 'error' ? 'warnbox' : 'row small muted' },
          `${d.code}: ${d.message}`));
      }
    }
  }

  // --- has anybody read this statement?
  //
  // The layer that was missing entirely: a target theorem citing a section nobody
  // had written was decomposed into seven children before anyone noticed.
  if (node.target) {
    const box = el('div', { class: node.audited_against ? 'row small muted' : 'warnbox' });
    if (!node.audited_against) {
      box.append(el('div', {}, el('b', {}, 'This statement has never been audited. ')));
      box.append(el('div', { class: 'small' },
        'Everything in the project is built on it, so an ambiguity or a citation to ' +
        'nothing here is inherited by every child and much more expensive to find ' +
        'later. Four fixed questions, one call.'));
      box.append(el('button', {
        ...(busy ? { disabled: 'disabled' } : {}),
        onclick: () => runJob('audit', node.id),
      }, 'Audit the statement'));
    } else if (node.audited_against !== node.statement_hash) {
      box.append('Audited, but the statement has been edited since — the audit was ' +
                 'about different words.');
      box.append(el('button', {
        ...(busy ? { disabled: 'disabled' } : {}),
        onclick: () => runJob('audit', node.id),
      }, 'Audit again'));
    } else {
      box.append('Statement audited.');
    }
    panel.append(el('h3', { class: 'section' }, 'The statement itself'));
    panel.append(box);
  }

  // --- citations
  if ((node.refs || []).length) {
    panel.append(el('h3', { class: 'section' }, 'Citations'));
    const list = el('div', { class: 'uses' });
    for (const r of node.refs) {
      const known = state.labels && state.labels[r.name];
      const row = el('div', { class: 'dis' + (known ? '' : ' admitted') });
      row.append(el('span', { class: 'hid' }, '\\' + r.command));
      if (known) {
        row.append(el('a', { class: 'noderef', onclick: () => select(known.node) },
                      `${r.name} → ${known.node}`));
        row.append(el('span', { class: 'muted small' }, `  (in the ${r.section})`));
      } else {
        row.append(el('span', {}, `${r.name} → nothing defines this (XRF001)`));
      }
      list.append(row);
    }
    panel.append(list);
    if ((node.reference_obligations || []).length) {
      panel.append(el('div', { class: 'row small muted' },
        `${node.reference_obligations.length} citation(s) go to the verifier as ` +
        'individual questions at level standard: does the cited text say what this ' +
        'passage uses it for?'));
    }
  }

  // --- the verification record
  //
  // `verified` must not be an opaque flag: a node checked at `quick` and one
  // checked at `deep` are not making the same claim, and a colour with no
  // provenance is the thing most likely to be over-trusted.
  panel.append(el('h3', { class: 'section' }, 'Verification record'));
  panel.append(el('div', { class: 'row small' }, node.verification_summary));
  for (const reason of node.verification_reasons) {
    panel.append(el('div', { class: 'row small muted' }, 'flagged because: ' + reason));
  }
  if (node.verification && Object.keys(node.verification.models || {}).length) {
    panel.append(el('div', { class: 'row small muted' }, 'models: ' +
      Object.entries(node.verification.models).map(([k, v]) => `${k}=${v}`).join(', ')));
  }

  // --- objections
  if (node.flags.length) {
    panel.append(el('h3', { class: 'section' }, 'Objections'));
    for (const flag of node.flags) {
      const box = el('div', { class: 'flag' });
      box.append(el('div', { class: 'kind' }, flag.kind || 'objection'));
      const why = el('div', {});
      why.append(mathProse(flag.why || ''));
      box.append(why);
      if (flag.context) {
        // A graph fact the objection rests on — which node rests on which. Kept
        // separate from `why` because confirmation rewrites that sentence.
        const ctx = el('div', { class: 'small' });
        ctx.append(mathProse(flag.context));
        box.append(ctx);
      }
      if (flag.quote) {
        const quote = el('div', { class: 'quote' });
        quote.append(mathProse(flag.quote));
        box.append(quote);
      }
      if (flag.raised_by) box.append(el('div', { class: 'small muted' }, 'raised by ' + flag.raised_by));
      panel.append(box);
    }
  }

  // --- notes
  panel.append(el('h3', { class: 'section' }, 'Notes'));
  if (node.notes.trim()) {
    const body = el('div', { class: 'prose small' });
    body.append(mathProse(node.notes));
    panel.append(body);
  } else {
    panel.append(el('div', { class: 'prose muted small' }, 'None.'));
  }

  panel.append(el('h3', { class: 'section' }, 'Actions'));
  panel.append(actionButtons(node, busy));
}

function sectionHeading(title, key, node, busy) {
  const head = el('h3', { class: 'section' }, title);
  if (state.editing === key) {
    head.append(el('button', {
      onclick: () => { state.editing = null; showDetail(node.id); },
    }, 'cancel'));
  } else {
    head.append(el('button', {
      ...(busy ? { disabled: 'disabled' } : {}),
      onclick: () => { state.editing = key; showDetail(node.id); },
    }, 'edit'));
  }
  return head;
}

function editor(initial, onSave) {
  const box = el('div', {});
  const area = el('textarea', {});
  area.value = initial || '';
  const row = el('div', { class: 'editrow' });
  row.append(el('button', { class: 'primary', onclick: () => onSave(area.value) }, 'Save'));
  row.append(el('span', { class: 'small muted' },
    'LaTeX. You write the source and read it typeset — there is no rich-text editor.'));
  box.append(area, row);
  return box;
}

/** Ask the proof-reader, then show the rewrite beside the original.
 *
 * Nothing is written until the author picks one. The agent may fix syntax; it
 * may not touch the mathematics, and the only way to be sure of that is to let
 * the person who wrote it look. */
async function tidyThenSave(id, text, kind, commit) {
  const body = el('div', {});
  body.append(el('div', { class: 'spinner-row' }, 'Checking the LaTeX…'));
  sheet('Checking ' + kind, body, [{ label: 'Skip and save', onClick: () => { closeSheet(); commit(text); } }]);

  let tidy;
  try { tidy = await post('/api/tidy', { text, kind }); }
  catch (e) {
    // A proof-reader that cannot run must never block a save.
    closeSheet(); toast('LaTeX check unavailable — saving as typed'); commit(text); return;
  }

  if (!tidy.changed && !(tidy.concerns || []).length) {
    closeSheet(); commit(text); return;
  }

  body.textContent = '';
  if (tidy.changed) {
    body.append(el('p', { class: 'small muted' },
      'The LaTeX below did not look like it would typeset. Proposed corrections ' +
      'are syntax only — if any of these changes the mathematics, reject it and ' +
      'tell me, because that is a bug.'));
    const list = el('ul', { class: 'small' });
    for (const change of tidy.changes) list.append(el('li', {}, change));
    body.append(list);

    const cols = el('div', { class: 'diffcols' });
    const left = el('div', {});
    left.append(el('h3', { class: 'section' }, 'As you typed it'));
    left.append(el('pre', { class: 'tex' }, text));
    const right = el('div', {});
    right.append(el('h3', { class: 'section' }, 'Proposed'));
    right.append(el('pre', { class: 'tex' }, tidy.text));
    cols.append(left, right);
    body.append(cols);

    body.append(el('h3', { class: 'section' }, 'Proposed, typeset'));
    const preview = el('div', { class: 'prose' });
    preview.append(mathProse(tidy.text));
    body.append(preview);
  }
  if ((tidy.concerns || []).length) {
    const warn = el('div', { class: 'warnbox' });
    warn.append(el('b', {}, 'It also has concerns about the mathematics. '),
                'These were NOT changed:');
    const list = el('ul', {});
    for (const c of tidy.concerns) list.append(el('li', {}, c));
    warn.append(list);
    body.append(warn);
  }

  const actions = [
    { label: 'Keep mine', onClick: () => { closeSheet(); commit(text); } },
  ];
  if (tidy.changed) {
    actions.push({
      label: 'Use the correction', primary: true,
      onClick: () => { closeSheet(); commit(tidy.text); },
    });
  }
  sheet('LaTeX check — ' + kind, body, actions);
}

/** Editing a statement moves its hash, so say what that invalidates first. */
async function saveStatement(id, text) {
  let radius = { radius: [] };
  try { radius = await api(`/api/node/${encodeURIComponent(id)}/stale-radius`); }
  catch (e) { /* fall through to the plain save */ }

  const body = el('div', {});
  if (radius.radius.length) {
    const warn = el('div', { class: 'warnbox' });
    warn.append(el('b', {}, 'This edit invalidates verification.'), ' ');
    warn.append(`Changing this statement moves its hash, which makes ${radius.radius.length} ` +
                'node(s) stale — this one, and every node whose verification cited it:');
    const list = el('ul', {});
    for (const item of radius.radius) {
      list.append(el('li', {}, `${item.id} (${item.local_status}, now ${item.global_status})`));
    }
    warn.append(list);
    body.append(warn);
  } else {
    body.append(el('div', { class: 'small muted' },
      'No verification anywhere cites this statement yet, so nothing goes stale.'));
  }

  sheet('Save statement?', body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Save anyway', primary: true, onClick: async () => {
        closeSheet();
        const result = await post(`/api/node/${encodeURIComponent(id)}/statement`, { text });
        state.editing = null;
        toast(result.staled.length
          ? `saved — ${result.staled.length} node(s) went stale`
          : 'statement saved');
        await refresh();
      },
    },
  ]);
}

function actionButtons(node, busy) {
  const box = el('div', { class: 'actions' });
  const add = (label, handler, opts) => {
    const options = opts || {};
    box.append(el('button', {
      class: options.primary ? 'primary' : (options.danger ? 'danger' : ''),
      ...((busy && !options.alwaysOn) ? { disabled: 'disabled' } : {}),
      onclick: handler,
    }, label));
  };

  if (!node.children.length) {
    add('Expand', () => expandDialog(node, false), { primary: true });
  } else {
    add('Redo', () => expandDialog(node, true));
    add('Check decomposition', () => runJob('check-decomp', node.id));
  }
  if (!node.children.length) add('Generate proof', () => runJob('prove', node.id));
  if (node.has_proof) add('Verify', () => verifyDialog(node), { primary: !node.children.length });
  if (node.has_proof) add('Extract claims', () => runJob('extract', node.id));
  add('Audit statement', () => runJob('audit', node.id));

  add('Add child', () => addChildDialog(node));
  add('Add note', () => noteDialog(node));
  add('Mark admitted', () => reasonDialog(node, 'admit', 'Mark admitted'));
  add('Mark assumption', () => reasonDialog(node, 'assume', 'Mark an assumption'));
  add('Relabel', () => relabelDialog(node));
  add('Why?', () => whySheet(node.id), { alwaysOn: true });
  if (!node.target) add('Archive', () => archiveDialog(node), { danger: true });
  return box;
}

/* ------------------------------------------------------------ sheets/dialogs */

function sheet(title, body, actions) {
  document.getElementById('sheet-title').textContent = title;
  const bodyBox = document.getElementById('sheet-body');
  bodyBox.textContent = '';
  bodyBox.append(body);
  const actionBox = document.getElementById('sheet-actions');
  actionBox.textContent = '';
  for (const action of actions || []) {
    actionBox.append(el('button', {
      class: action.primary ? 'primary' : (action.danger ? 'danger' : ''),
      onclick: action.onClick,
    }, action.label));
  }
  document.getElementById('overlay').classList.remove('hidden');
}

function closeSheet() { document.getElementById('overlay').classList.add('hidden'); }

function expandDialog(node, isRedo) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' }, isRedo
    ? 'The current subtree is copied to attempts/ before anything is archived. ' +
      'The previous attempt\'s problems are sent to the decomposer as negative context.'
    : 'One level. 3–7 children. The leaves are expected to be hard and unproved.'));
  body.append(el('label', { class: 'small muted' }, 'Hint for the decomposer'));
  const area = el('textarea', {});
  area.value = node.strategy || '';
  body.append(area);
  sheet(isRedo ? 'Redo ' + node.id : 'Expand ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: isRedo ? 'Archive and decompose' : 'Decompose', primary: true,
      onClick: () => { closeSheet(); runJob(isRedo ? 'redo' : 'expand', node.id, { hint: area.value }); },
    },
  ]);
}

/** Pick the level to verify at.
 *
 * The level is the cost knob, and it is also part of what the verdict *means* —
 * so it is a deliberate choice rather than a default the user never sees.
 */
const LEVEL_BLURB = {
  quick: 'Deterministic checks and the whole-proof pass. Fast; for iterating.',
  standard: 'Adds claim extraction, the ledger audit and every discharge obligation. ' +
            'Routine work.',
  deep: 'Adds a check on every sourced claim and a statement audit. Roughly fifteen ' +
        'calls on a ten-claim proof — run it before trusting a subtree.',
};

function verifyDialog(node) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'Three jobs, cached separately: every discharge obligation, every ledger claim, ' +
    'and the whole proof read by two models. Then a confirmation pass over every ' +
    'objection. What ran is recorded on the node — a node verified at quick and one ' +
    'verified at deep are not the same claim.'));
  const select_ = el('select', {});
  for (const level of ['quick', 'standard', 'deep']) {
    const option = el('option', { value: level }, level);
    if (level === 'standard') option.setAttribute('selected', 'selected');
    select_.append(option);
  }
  const blurb = el('div', { class: 'small muted' }, LEVEL_BLURB.standard);
  select_.addEventListener('change', () => { blurb.textContent = LEVEL_BLURB[select_.value]; });
  body.append(el('label', { class: 'small muted' }, 'Level'), select_, blurb);
  sheet('Verify ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Verify', primary: true,
      onClick: () => {
        closeSheet();
        runJob('verify', node.id, { level: select_.value, batch: 1 });
      },
    },
  ]);
}

function noteDialog(node) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'Notes are fed to agents as context on every later attempt at this node.'));
  const area = el('textarea', {});
  body.append(area);
  sheet('Add a note to ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Add', primary: true, onClick: async () => {
        try {
          await post(`/api/node/${encodeURIComponent(node.id)}/note`, { text: area.value });
          closeSheet(); toast('note added'); await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

function reasonDialog(node, kind, title) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' }, kind === 'admit'
    ? 'Admitted means believed but not argued. The node enters its own support set and ' +
      'the reason is printed in the certificate, so it has to say something usable.'
    : 'An assumption is taken as given for this project, by choice rather than omission.'));
  body.append(el('label', { class: 'small muted' }, 'Reason (required)'));
  const input = el('textarea', {});
  body.append(input);
  sheet(title + ': ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Mark', primary: true, onClick: async () => {
        try {
          await post(`/api/node/${encodeURIComponent(node.id)}/${kind}`, { reason: input.value });
          closeSheet(); toast('marked'); await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

function relabelDialog(node) {
  const body = el('div', {});
  const select_ = el('select', {});
  for (const d of ['routine', 'standard', 'hard', 'unknown']) {
    const option = el('option', { value: d }, d);
    if (d === node.difficulty) option.setAttribute('selected', 'selected');
    select_.append(option);
  }
  body.append(el('p', { class: 'small muted' },
    'The prover runs on routine and standard leaves only — a failed attempt on those ' +
    'is a cheap falsification test on the strategy.'), select_);
  sheet('Relabel ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Relabel', primary: true, onClick: async () => {
        try {
          await post(`/api/node/${encodeURIComponent(node.id)}/relabel`, { difficulty: select_.value });
          closeSheet(); toast('relabelled'); await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

function addChildDialog(node) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'A lemma you state yourself. It is attached to this node as a child; the discharge ' +
    'table will then report its hypotheses as undischarged until you fill them in.'));
  const prefix = node.id.includes('.') ? node.id.split('.')[0] : node.id;
  body.append(el('label', { class: 'small muted' }, 'Node id'));
  const idInput = el('input', { type: 'text', value: prefix + '.' });
  idInput.value = prefix + '.';
  body.append(idInput);
  body.append(el('label', { class: 'small muted' }, 'Statement (LaTeX)'));
  const area = el('textarea', {});
  body.append(area);
  const roleSelect = el('select', {});
  for (const r of ['lemma', 'proposition', 'definition', 'assumption', 'theorem']) {
    roleSelect.append(el('option', { value: r }, r));
  }
  const diffSelect = el('select', {});
  for (const d of ['unknown', 'routine', 'standard', 'hard']) {
    diffSelect.append(el('option', { value: d }, d));
  }
  const row = el('div', { class: 'editrow' });
  row.append(roleSelect, diffSelect);
  body.append(row);

  sheet('Add a child of ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Create', primary: true, onClick: async () => {
        try {
          await post(`/api/node/${encodeURIComponent(node.id)}/child`, {
            id: idInput.value.trim(),
            statement: area.value,
            role: roleSelect.value,
            difficulty: diffSelect.value,
          });
          closeSheet(); toast('child created'); await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

/** Edit the discharge table: one input per hypothesis of each cited child.
 *
 * The form is generated from the children's *actual* hypotheses, so the rows you
 * have to fill in are exactly the rows the discharge check will ask about. There
 * is no way to leave one out by forgetting it exists. */
async function dischargeDialog(node) {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'For every hypothesis of every lemma this proof cites, say where it comes from. ' +
    'The check verifies that a source is named — not that it entails the hypothesis; ' +
    'that question goes to the verifier, one obligation at a time.'));

  const forms = {};
  for (const cid of node.children) {
    let child;
    try { child = await api('/api/node/' + encodeURIComponent(cid)); }
    catch (e) { continue; }
    const use = node.uses[cid] || { applied_to: '', discharges: {} };

    body.append(el('h3', { class: 'section' }, cid));
    const applied = el('input', { type: 'text', placeholder: 'applied to … (LaTeX, optional)' });
    applied.value = use.applied_to || '';
    body.append(applied);

    const rows = {};
    if (!child.hypotheses.length) {
      body.append(el('p', { class: 'small muted' }, 'No hypotheses — nothing to discharge.'));
    }
    for (const h of child.hypotheses) {
      const label = el('label', { class: 'small' });
      label.append(el('span', { class: 'hid' }, h.id), ' ');
      label.append(mathProse('$' + h.tex + '$'));
      body.append(label);
      const input = el('input', {
        type: 'text',
        placeholder: 'hypothesis:H1 | child:some.id | proof:… | literature:… | ADMITTED: …',
      });
      input.value = (use.discharges || {})[h.id] || '';
      body.append(input);
      rows[h.id] = input;
    }
    forms[cid] = { applied, rows };
  }

  sheet('Discharges for ' + node.id, body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Save', primary: true, onClick: async () => {
        const uses = {};
        for (const [cid, form] of Object.entries(forms)) {
          const discharges = {};
          for (const [hid, input] of Object.entries(form.rows)) {
            if (input.value.trim()) discharges[hid] = input.value.trim();
          }
          uses[cid] = { applied_to: form.applied.value, discharges: discharges };
        }
        try {
          await post(`/api/node/${encodeURIComponent(node.id)}/uses`, { uses });
          closeSheet(); toast('discharge table saved'); await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

function archiveDialog(node) {
  const body = el('div', {});
  body.append(el('div', { class: 'warnbox' },
    'Archiving never deletes. The file stays, its text stays, and it leaves the active ' +
    'graph. Descendants that this orphans are archived too; anything still cited from ' +
    'elsewhere stays active. Citations to it are removed from its parents and recorded ' +
    'in the event log.'));
  sheet('Archive ' + node.id + '?', body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Archive', danger: true, onClick: async () => {
        try {
          const result = await post(`/api/node/${encodeURIComponent(node.id)}/archive`, { cascade: true });
          closeSheet();
          toast('archived: ' + result.archived.join(', '));
          state.selected = null;
          await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

async function whySheet(id) {
  const body = el('div', { class: 'whychain' });
  try {
    const data = await api('/api/why/' + encodeURIComponent(id));
    for (const line of data.lines) {
      const row = el('div', { class: 'line', style: `margin-left:${line.depth * 18}px` });
      row.append(mathProse(line.text));
      body.append(row);
    }
    body.append(el('p', { class: 'small muted' },
      'No model is involved in this answer. It is read straight off the derived fields, ' +
      'so it is always correct.'));
  } catch (e) {
    body.append(el('div', {}, e.message));
  }
  sheet('Why is ' + id + ' that colour?', body, [{ label: 'Close', onClick: closeSheet }]);
}

/* ----------------------------------------------------------------- job flow */

const JOB_LABEL = {
  expand: 'Decomposing', redo: 'Redoing', 'check-decomp': 'Checking the decomposition',
  extract: 'Extracting the claim ledger', audit: 'Auditing the statement',
  verify: 'Verifying', prove: 'Writing a proof', recompile: 'Recompiling', resume: 'Resuming',
};

async function runJob(kind, nodeId, body) {
  try {
    const path = nodeId
      ? `/api/jobs/${kind}/${encodeURIComponent(nodeId)}`
      : `/api/jobs/${kind}`;
    const job = await post(path, body);
    toast(`${JOB_LABEL[kind] || kind} started — this can take minutes.`);
    await pollJobs();
    watchJob(job.id);
  } catch (e) {
    toast(e.message, true);
  }
}

const watched = new Set();
function watchJob(jobId) { watched.add(jobId); }

async function pollJobs() {
  let data;
  try { data = await api('/api/jobs'); } catch (e) { return; }
  const previous = new Map(state.jobs.map((j) => [j.id, j.status]));
  state.jobs = data.jobs;
  state.busy = new Set(data.busy);
  drawJobStrip();

  for (const job of data.jobs) {
    const before = previous.get(job.id);
    if (before && before !== job.status && (job.status === 'done' || job.status === 'failed')) {
      await refresh();
      if (job.status === 'failed') toast(`${job.kind} failed: ${job.error}`, true);
      else if (watched.has(job.id)) { watched.delete(job.id); showJobResult(job); }
      else toast(`${job.kind} finished`);
    }
  }
}

function drawJobStrip() {
  const strip = document.getElementById('jobstrip');
  strip.textContent = '';
  const active = state.jobs.filter((j) => j.status === 'queued' || j.status === 'running');
  if (!active.length) return;
  const job = active[0];
  strip.append(el('span', { class: 'running' },
    el('i', { class: 'dot' }),
    `${JOB_LABEL[job.kind] || job.kind}${job.node ? ' ' + job.node : ''} — ${job.step}`));
  if (active.length > 1) strip.append(el('span', { class: 'muted' }, `  (+${active.length - 1} queued)`));
}

function showJobResult(job) {
  const result = job.result || {};
  const body = el('div', {});
  if ((job.kind === 'expand' || job.kind === 'redo') && result.declined) {
    body.append(el('div', { class: 'warnbox' },
      el('b', {}, 'Not decomposed. '),
      `The decomposer judged this ${result.assessed_difficulty} and `,
      result.verdict === 'already-atomic'
        ? 'a single step — splitting it would add bookkeeping, not structure.'
        : 'clear enough to write out directly.'));
    const why = el('div', { class: 'prose' });
    why.append(mathProse(result.assessment || ''));
    body.append(why);
    body.append(el('p', { class: 'small muted' },
      'Nothing was written; the assessment has been added as a note. It is your ' +
      'call — the decomposer is guessing at difficulty just as you are.'));
    sheet('Assessment — ' + job.node, body, [
      { label: 'Close', onClick: closeSheet },
      {
        label: 'Decompose anyway',
        onClick: () => { closeSheet(); runJob('expand', job.node, { force: true }); },
      },
      {
        label: 'Write the proof', primary: true,
        onClick: async () => {
          closeSheet();
          // Take its difficulty judgement, so the prover's routine/standard
          // guard is satisfied by the assessment rather than bypassed.
          if (['routine', 'standard'].includes(result.assessed_difficulty)) {
            try {
              await post(`/api/node/${encodeURIComponent(job.node)}/relabel`,
                         { difficulty: result.assessed_difficulty });
            } catch (e) { /* keep going; prove will say if it objects */ }
          }
          runJob('prove', job.node);
        },
      },
    ]);
    return;
  }
  if (job.kind === 'expand' || job.kind === 'redo') {
    if (result.archived_to) {
      body.append(el('div', { class: 'small muted' }, 'Previous attempt archived to ' + result.archived_to));
    }
    body.append(el('p', {}, `${result.children.length} child(ren), in ${result.rounds} round(s).`));
    const list = el('ul', {});
    for (const id of result.children) {
      list.append(el('li', {}, el('a', { class: 'noderef', onclick: () => { closeSheet(); select(id); } }, id)));
    }
    body.append(list);
    if (result.strategy) {
      body.append(el('p', { class: 'small' }, el('b', {}, 'Strategy: '), result.strategy));
    }
    if (result.notes) {
      body.append(el('h3', { class: 'section' }, "The decomposer's reservations"));
      const notes = el('div', { class: 'prose small' });
      notes.append(mathProse(result.notes));
      body.append(notes);
    }
    body.append(diagnosticList(result.diagnostics));
  } else if (job.kind === 'check-decomp') {
    for (const answer of result.answers) {
      body.append(el('h3', { class: 'section' }, answer.question));
      if (answer.problems.length) {
        for (const problem of answer.problems) {
          const box = el('div', { class: 'flag' });
          box.append(el('div', { class: 'kind' }, (problem.confidence || '') + ' confidence'));
          const where = el('div', {}); where.append(el('b', {}, problem.where + ': '));
          where.append(mathProse(problem.why));
          box.append(where);
          if (problem.quote) {
            const quote = el('div', { class: 'quote' });
            quote.append(mathProse(problem.quote));
            box.append(quote);
          }
          body.append(box);
        }
      } else {
        body.append(el('p', { class: 'small muted' }, 'None found, having checked:'));
        const list = el('ul', { class: 'small' });
        for (const item of answer.checked) list.append(el('li', {}, item));
        body.append(list);
      }
    }
  } else if (job.kind === 'extract') {
    body.append(el('p', {},
      el('b', {}, `${result.claims} claim(s)`),
      ` extracted, ${(result.unsourced || []).length} with no source.`));
    if ((result.unsourced || []).length) {
      body.append(el('div', { class: 'warnbox' },
        'LED001 fires on ' + result.unsourced.join(', ') + '. An unsourced load-bearing ' +
        'claim is a premise the proof is smuggling in — justify it, or decompose it out ' +
        'into its own node.'));
    } else {
      body.append(el('p', { class: 'small muted' },
        'Every load-bearing claim names a source. Whether each source actually gives its ' +
        'claim is a separate, narrower question — run Verify at level deep.'));
    }
    for (const d of result.diagnostics || []) {
      body.append(el('div', { class: d.severity === 'error' ? 'warnbox' : 'row small muted' },
        `${d.code}: ${d.message}`));
    }
    if (result.omitted) {
      body.append(el('p', { class: 'small muted' }, 'Deliberately omitted: ' + result.omitted));
    }
  } else if (job.kind === 'audit') {
    body.append(el('p', {}, el('b', {}, 'Statement audit: ' + result.verdict)));
    body.append(el('p', { class: 'small muted' },
      'This role stands in for the deterministic vacuity and constant-scope checks that ' +
      'v0 defers, and is weaker than both. Its answers are prompts for your attention, ' +
      'not checks — nothing here changed a status.'));
    const w = result.non_vacuous || {};
    const vac = el('div', { class: w.verdict === 'exhibited' ? 'row small' : 'warnbox' });
    if (w.verdict === 'exhibited') {
      vac.append(el('span', { class: 'label' }, 'witness: '));
      vac.append(mathProse(w.witness || ''));
    } else if (w.verdict === 'not_found') {
      vac.append('No instance satisfying every hypothesis at once was found. ');
      if (w.conflict) vac.append(mathProse(w.conflict));
    } else {
      vac.append('Whether the hypotheses can hold together was judged out of reach from ' +
                 'the statement alone.');
    }
    body.append(vac);
    for (const key of ['well_posed', 'quantifiers', 'constants']) {
      const block = result[key];
      if (!block) continue;
      body.append(el('div', { class: 'row small' + (block.ok ? ' muted' : '') },
        `${key.replace('_', '-')}: ${block.ok ? 'clean' : 'SUSPECT'}` +
        (block.checked ? ' — ' + block.checked : '')));
      for (const entry of block.constants || []) {
        body.append(el('div', { class: 'row small muted' }, '  ' + entry));
      }
    }
    for (const finding of result.findings || []) {
      const box = el('div', { class: 'flag' });
      box.append(el('div', { class: 'kind' }, `${finding.where} · ${finding.confidence}`));
      const why = el('div', {}); why.append(mathProse(finding.why)); box.append(why);
      if (finding.quote) {
        const q = el('div', { class: 'quote' }); q.append(mathProse(finding.quote)); box.append(q);
      }
      body.append(box);
    }
  } else if (job.kind === 'verify') {
    body.append(el('p', {},
      el('b', {}, result.verdict),
      ` at level ${result.level}.`));
    body.append(el('div', { class: 'row small muted' }, result.summary || ''));
    for (const reason of result.reasons || []) {
      body.append(el('div', { class: 'row small' }, 'flagged because: ' + reason));
    }
    for (const flag of result.flags || []) {
      const box = el('div', { class: 'flag' });
      box.append(el('div', { class: 'kind' }, flag.kind));
      const why = el('div', {}); why.append(mathProse(flag.why)); box.append(why);
      if (flag.quote) { const q = el('div', { class: 'quote' }); q.append(mathProse(flag.quote)); box.append(q); }
      body.append(box);
    }
    if ((result.withdrawn || []).length) {
      body.append(el('h3', { class: 'section' }, 'Withdrawn on confirmation'));
      const list = el('ul', { class: 'small muted' });
      for (const w of result.withdrawn) list.append(el('li', {}, `${w.kind}: ${w.resolved}`));
      body.append(list);
    }
    if (!(result.flags || []).length) {
      body.append(el('h3', { class: 'section' }, 'Checked'));
      const list = el('ul', { class: 'small' });
      for (const item of (result.checked || []).slice(0, 30)) list.append(el('li', {}, item));
      body.append(list);
    }
  } else if (job.kind === 'prove') {
    if (!result.attempted) {
      body.append(el('div', { class: 'warnbox' },
        el('b', {}, 'The prover declined. '), result.reason));
      body.append(el('p', { class: 'small muted' },
        'That is a result, not a failure — it is usually a fact about the decomposition ' +
        'rather than about the lemma. It has been added as a note.'));
    } else {
      body.append(el('p', {}, 'A proof was written. The prover never sets a status: ' +
        'run Verify to have it checked by someone who does not know who wrote it.'));
      for (const gap of result.gaps || []) {
        body.append(el('div', { class: 'warnbox' }, el('b', {}, 'Named gap: '), gap));
      }
    }
  } else if (job.kind === 'recompile' || job.kind === 'resume') {
    body.append(el('p', {},
      `verified: ${(result.verified || []).join(', ') || 'none'}`, el('br', {}),
      `flagged: ${(result.flagged || []).join(', ') || 'none'}`, el('br', {}),
      `skipped (already done): ${(result.skipped || []).join(', ') || 'none'}`));
    if (result.stopped) {
      body.append(el('div', { class: 'warnbox' },
        el('b', {}, 'Stopped: '), result.stopped,
        el('div', { class: 'small' }, 'Use Recompile → Resume to continue; completed nodes are not re-queried.')));
    }
  } else {
    body.append(el('pre', { class: 'tex' }, JSON.stringify(result, null, 2)));
  }
  sheet(`${JOB_LABEL[job.kind] || job.kind}${job.node ? ' — ' + job.node : ''}`,
        body, [{ label: 'Close', onClick: closeSheet }]);
}

function diagnosticList(diagnostics) {
  const box = el('div', {});
  if (!diagnostics || !diagnostics.length) return box;
  box.append(el('h3', { class: 'section' }, 'What the checks said'));
  for (const d of diagnostics) {
    const row = el('div', { class: 'diag ' + d.severity });
    row.append(el('span', { class: 'code' }, d.code), ' ');
    row.append(mathProse(d.message));
    if (d.hint) row.append(el('div', { class: 'hint' }, d.hint));
    box.append(row);
  }
  return box;
}

/* ------------------------------------------------------------- action bar */

async function frontierSheet() {
  const data = await api('/api/frontier');
  const body = el('div', {});
  if (!data.items.length) {
    body.append(el('p', { class: 'muted' }, 'Nothing is waiting on a decision.'));
  } else {
    body.append(el('p', { class: 'small muted' },
      'Nodes where work is possible now — unfinished, with everything beneath them ' +
      'finished. Shallow first, then by how many nodes each one gates.'));
    const table = el('table', { class: 'plain' });
    table.append(el('tr', {},
      el('th', {}, 'node'), el('th', {}, 'needs'), el('th', {}, 'difficulty'),
      el('th', {}, 'gates'), el('th', {}, 'depth')));
    for (const item of data.items) {
      const row = el('tr', { class: 'clickable', onclick: () => { closeSheet(); select(item.node); } },
        el('td', {}, el('span', { class: 'mono' }, item.node)),
        el('td', {}, item.needs),
        el('td', {}, item.difficulty),
        el('td', {}, String(item.gates)),
        el('td', {}, String(item.depth)));
      table.append(row);
    }
    body.append(table);
  }
  sheet('Frontier', body, [{ label: 'Close', onClick: closeSheet }]);
}

async function recompileSheet(level) {
  const chosen = level || 'standard';
  const body = el('div', {});
  body.append(el('div', { class: 'spinner-row' }, 'Working out what it would cost…'));
  sheet('Recompile', body, [{ label: 'Close', onClick: closeSheet }]);
  let plan;
  try { plan = await api('/api/recompile/plan?level=' + encodeURIComponent(chosen)); }
  catch (e) { body.textContent = e.message; return; }

  body.textContent = '';
  // The level picker re-prices as you change it, so the bill for `deep` is
  // something you see before you agree to it rather than after.
  const select_ = el('select', {});
  for (const l of ['quick', 'standard', 'deep']) {
    const option = el('option', { value: l }, l);
    if (l === chosen) option.setAttribute('selected', 'selected');
    select_.append(option);
  }
  select_.addEventListener('change', () => recompileSheet(select_.value));
  body.append(el('label', { class: 'small muted' }, 'Level'), select_);
  body.append(el('div', { class: 'small muted' }, LEVEL_BLURB[chosen]));
  body.append(el('pre', { class: 'tex' }, plan.text));
  const actions = [{ label: 'Cancel', onClick: closeSheet }];
  if (plan.tasks.length) {
    actions.push({
      label: `Run ${plan.calls} call(s)`, primary: true,
      onClick: () => { closeSheet(); runJob('recompile', null, { level: chosen, batch: 1 }); },
    });
  }
  actions.push({
    label: 'Resume interrupted',
    onClick: () => { closeSheet(); runJob('resume', null, {}); },
  });
  const actionBox = document.getElementById('sheet-actions');
  actionBox.textContent = '';
  for (const action of actions) {
    actionBox.append(el('button', {
      class: action.primary ? 'primary' : '', onclick: action.onClick,
    }, action.label));
  }
}

async function renderSheet() {
  const body = el('div', {});
  const options = el('div', { class: 'editrow' });
  const clean = el('input', { type: 'checkbox', id: 'opt-clean' });
  const audit = el('input', { type: 'checkbox', id: 'opt-audit' });
  options.append(el('label', { class: 'small' }, clean, ' clean (omit every marker — this is the paper)'));
  options.append(el('label', { class: 'small' }, audit, ' audit (include the discharge tables)'));
  body.append(options);
  const pre = el('pre', { class: 'tex' }, 'rendering…');
  body.append(pre);

  // Where a compile problem is reported. It has to appear *here*, in the sheet
  // the user is looking at: opening the PDF is a navigation, and a navigation
  // that fails lands in a new tab showing raw JSON, which reads as "the tool is
  // broken" when the real answer is usually one `tlmgr install` away.
  const status = el('div', {});
  body.append(status);

  const reload = async () => {
    const query = `?clean=${clean.checked}&audit=${audit.checked}`;
    pre.textContent = 'rendering…';
    status.textContent = '';
    try { pre.textContent = await api('/api/render' + query); }
    catch (e) { pre.textContent = e.message; }
  };
  clean.onchange = reload; audit.onchange = reload;

  const openPdf = async () => {
    const query = `?clean=${clean.checked}&audit=${audit.checked}`;
    status.textContent = '';
    status.append(el('div', { class: 'spinner-row' }, 'compiling — two pdflatex passes…'));
    let report;
    try { report = await api('/api/render/compile' + query); }
    catch (e) { status.textContent = ''; status.append(compileProblem({ message: e.message })); return; }
    status.textContent = '';
    // The deterministic view first: it names the node responsible, which a LaTeX
    // warning never does.
    for (const d of report.xref_diagnostics || []) {
      status.append(el('div', { class: 'warnbox' }, `${d.code} on ${d.node}: ${d.message}`));
    }
    for (const w of report.warnings || []) {
      status.append(el('div', { class: 'warnbox' }, w));
    }
    if (!report.ok) {
      status.append(compileProblem(report.problem || {}));
      return;
    }
    // `built=1`: the artifact this compile just produced, rather than a fresh
    // compile — so one click is two pdflatex passes, not four, and the warnings
    // above describe the file that opens.
    //
    // A real link rather than window.open after an await: a popup opened from an
    // async continuation is blocked by default in most browsers.
    const href = '/api/render.pdf' + query + '&built=1';
    const link = el('a', {
      class: 'noderef', href: href, target: '_blank', rel: 'noopener',
    }, 'Open the PDF ▸');
    status.append(el('div', {}, link));
    link.click();
  };

  sheet('The document', body, [
    { label: 'Close', onClick: closeSheet },
    {
      label: 'Download .tex',
      onClick: () => { window.location = `/api/render.tex?clean=${clean.checked}&audit=${audit.checked}`; },
    },
    { label: 'Open PDF', primary: true, onClick: openPdf },
  ]);
  await reload();
}

/** A classified LaTeX failure, shown where the user is looking.
 *
 * Everything here goes in as textContent: a pdflatex log is full of backslashes
 * and braces, and the one place in this file allowed to touch innerHTML takes
 * KaTeX output and nothing else.
 */
function compileProblem(problem) {
  const box = el('div', { class: 'warnbox' });
  box.append(el('div', {}, el('b', {}, 'The document did not compile. ')));
  if (problem.message) box.append(el('div', {}, problem.message));
  if (problem.hint) box.append(el('div', { class: 'small' }, problem.hint));
  if (problem.excerpt) {
    box.append(el('pre', { class: 'tex small' }, problem.excerpt));
  }
  box.append(el('div', { class: 'small muted' },
    'This is a fact about the LaTeX, not a failure of the graph — the source is ' +
    'still available from Download .tex, and everything else in the interface is ' +
    'unaffected.'));
  return box;
}

/** The archive: nodes that are still on disk but out of the active graph.
 *
 * They are excluded from the graph view on purpose — they are not part of the
 * argument any more — but excluding them everywhere left "nothing is destroyed"
 * as a promise about the filesystem and nothing else. This is the way back.
 */
async function archiveSheet() {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'Archived nodes keep their file, their text and their history; they are only ' +
    'out of the active graph. Bringing one back does NOT restore the citations ' +
    'archiving removed from its parents — re-citing is a decision, and History ' +
    'records which ones were stripped.'));
  let data;
  try { data = await api('/api/archived'); }
  catch (e) { body.append(el('div', { class: 'warnbox' }, e.message)); data = { nodes: [] }; }

  if (!data.nodes.length) {
    body.append(el('p', {}, 'Nothing is archived.'));
  }
  for (const n of data.nodes) {
    const row = el('div', { class: 'flag' });
    const head = el('div', {});
    head.append(el('span', { class: 'hid' }, n.id));
    head.append(el('span', { class: 'pill' }, n.role));
    head.append(el('span', { class: 'pill' }, n.local_status));
    if (n.children.length) {
      head.append(el('span', { class: 'muted small' }, ` ${n.children.length} child(ren)`));
    }
    row.append(head);
    const headline = el('div', { class: 'small muted' });
    headline.append(mathProse(n.headline || '(no statement)'));
    row.append(headline);
    row.append(el('button', {
      onclick: async () => {
        try {
          const r = await post(`/api/node/${encodeURIComponent(n.id)}/unarchive`);
          closeSheet();
          toast(r.orphan
            ? `${n.id} is back, but nothing cites it yet — add it to a parent's children.`
            : `${n.id} is back in the graph.`);
          await refresh();
        } catch (e) { toast(e.message, true); }
      },
    }, 'Bring back'));
    body.append(row);
  }
  sheet('Archive', body, [{ label: 'Close', onClick: closeSheet }]);
}

async function checkSheet() {
  const data = await api('/api/check');
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    `${data.errors} error(s), ${data.warnings} warning(s), ${data.notes} note(s). ` +
    'No model is involved in any of these.'));
  if (!data.diagnostics.length) body.append(el('p', {}, 'Nothing to report.'));
  for (const d of data.diagnostics) {
    const row = el('div', { class: 'diag ' + d.severity });
    row.append(el('span', { class: 'code' }, d.code), ' ');
    if (d.node) {
      row.append(el('a', { class: 'noderef', onclick: () => { closeSheet(); select(d.node); } }, d.node), ' ');
    }
    row.append(mathProse(d.message));
    if (d.hint) row.append(el('div', { class: 'hint' }, d.hint));
    body.append(row);
  }
  sheet('Checks', body, [{ label: 'Close', onClick: closeSheet }]);
}

async function historySheet() {
  const data = await api('/api/events');
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'The event log is append-only. Nothing in the system rewrites it.'));
  const table = el('table', { class: 'plain' });
  table.append(el('tr', {}, el('th', {}, 'when'), el('th', {}, 'what'),
                            el('th', {}, 'node'), el('th', {}, 'who')));
  for (const event of data.events) {
    table.append(el('tr', {},
      el('td', { class: 'mono small' }, (event.ts || '').replace('T', ' ').replace('+00:00', '')),
      el('td', {}, event.kind),
      el('td', {}, event.node
        ? el('a', { class: 'noderef', onclick: () => { closeSheet(); select(event.node); } }, event.node)
        : ''),
      el('td', { class: 'small muted' }, event.actor || '')));
  }
  body.append(table);
  sheet('History', body, [{ label: 'Close', onClick: closeSheet }]);
}

async function preambleSheet() {
  const body = el('div', {});
  body.append(el('p', { class: 'small muted' },
    'Your own LaTeX preamble — \\newcommand, \\DeclareMathOperator, packages. ' +
    'It is injected verbatim into the rendered document, shown to every agent as ' +
    'context so they can read your notation, and parsed here so KaTeX draws it. ' +
    'Stored as preamble.tex in the project.'));
  const area = el('textarea', {});
  area.style.minHeight = '320px';
  try { area.value = await api('/api/preamble'); } catch (e) { area.value = ''; }
  body.append(area);
  const count = el('p', { class: 'small muted' },
    Object.keys(state.macros).length + ' macro(s) currently in use: ' +
    (Object.keys(state.macros).join(' ') || 'none'));
  body.append(count);

  // What the renderer adds around your file. Shown because you cannot avoid a
  // collision you cannot see — and because the ordering guarantee ("yours wins") is
  // only reassuring once you know what it is winning against.
  body.append(el('h3', { class: 'section' }, 'What the renderer adds'));
  try {
    const facts = await api('/api/preamble/defaults');
    body.append(el('p', { class: 'small muted' },
      'Your file is injected BEFORE the options and the theorem environments below, ' +
      'so anything you define or load yourself wins: your \\newtheorem{lemma}, your ' +
      '\\usepackage[hidelinks]{hyperref}, your own margins. The base packages are ' +
      'loaded before your file so that \\DeclareMathOperator and friends work in it.'));

    const pkgs = el('div', { class: 'uses' });
    pkgs.append(el('div', { class: 'child' }, 'Packages'));
    for (const p of facts.packages) {
      const row = el('div', { class: 'dis' });
      row.append(el('span', { class: 'hid' }, p.name));
      if (p.options) row.append(el('span', { class: 'muted small' }, `[${p.options}]`));
      if (p.optional) {
        row.append(el('span', { class: 'muted small' },
          '  — only if your TeX has it; an unguarded \\usepackage of a missing ' +
          'package in YOUR file is a hard error'));
      }
      pkgs.append(row);
    }
    pkgs.append(el('div', { class: 'child' }, 'Theorem environments'));
    for (const e of facts.environments) {
      const row = el('div', { class: 'dis' });
      row.append(el('span', { class: 'hid' }, e.name));
      row.append(el('span', { class: 'muted small' }, `prints as “${e.printed_as}”, ` +
        'defined only if you have not defined it yourself'));
      pkgs.append(row);
    }
    pkgs.append(el('div', { class: 'child' }, 'Macros the renderer defines'));
    pkgs.append(el('div', { class: 'dis' },
      el('span', { class: 'muted small' },
        facts.macros.join('  ') + '  — do not redefine these; they draw the status ' +
        'apparatus and are omitted entirely by --clean')));
    body.append(pkgs);

    // The generated preamble in full, so nothing is hidden and it can be copied out
    // to reproduce the build by hand.
    const details = el('details', {});
    details.append(el('summary', { class: 'small muted' },
      'The generated preamble in full, exactly as the document gets it'));
    details.append(el('pre', { class: 'tex small' }, facts.text));
    body.append(details);
  } catch (e) {
    body.append(el('div', { class: 'warnbox' },
      'Could not read the renderer defaults: ' + e.message));
  }

  sheet('Preamble', body, [
    { label: 'Cancel', onClick: closeSheet },
    {
      label: 'Save', primary: true, onClick: async () => {
        try {
          await post('/api/preamble', { text: area.value });
          await loadMacros();
          closeSheet();
          toast(Object.keys(state.macros).length + ' macro(s) loaded');
          await refresh();
        } catch (e) { toast(e.message, true); }
      },
    },
  ]);
}

async function agentsSheet() {
  const data = await api('/api/agents');
  const body = el('div', {});
  const table = el('table', { class: 'plain' });
  table.append(el('tr', {}, el('th', {}, 'role'), el('th', {}, 'backend'),
                            el('th', {}, 'model'), el('th', {}, 'usable')));
  for (const role of data.roles) {
    table.append(el('tr', {},
      el('td', {}, role.role), el('td', {}, role.backend), el('td', {}, role.model),
      el('td', {}, role.usable ? 'yes' : 'no — ' + role.note)));
  }
  body.append(table);
  body.append(el('p', { class: 'small muted' },
    `Budget: $${data.budget.per_recompile_usd} and ` +
    `${data.budget.max_calls_per_recompile} call(s) per recompile. ` +
    `${data.calls_logged} call(s) in the log.` +
    (data.replay ? '  Running with --replay: calls resolve from the log, never the network.' : '')));
  body.append(el('p', { class: 'small muted' },
    'Edit bp.yaml to change which model plays which role. The two verifiers should be ' +
    'from different families — that is the whole reason there are two of them.'));
  sheet('Agents', body, [{ label: 'Close', onClick: closeSheet }]);
}

/* ------------------------------------------------------------------- boot */

function guard(handler) {
  return async () => { try { await handler(); } catch (e) { toast(e.message, true); } };
}

async function boot() {
  initCytoscape();
  document.getElementById('sheet-close').onclick = closeSheet;
  document.getElementById('overlay').onclick = (evt) => {
    if (evt.target.id === 'overlay') closeSheet();
  };
  document.addEventListener('keydown', (evt) => {
    if (evt.key === 'Escape') closeSheet();
  });
  document.getElementById('btn-frontier').onclick = guard(frontierSheet);
  // Bound through a wrapper: `onclick` would pass the MouseEvent as the level.
  document.getElementById('btn-recompile').onclick = guard(() => recompileSheet());
  document.getElementById('btn-render').onclick = guard(renderSheet);
  document.getElementById('btn-check').onclick = guard(checkSheet);
  document.getElementById('btn-archive').onclick = guard(archiveSheet);
  document.getElementById('btn-history').onclick = guard(historySheet);
  document.getElementById('btn-agents').onclick = guard(agentsSheet);
  document.getElementById('btn-preamble').onclick = guard(preambleSheet);

  const legend = document.getElementById('legend');
  document.getElementById('legend-toggle').onclick = () => {
    legend.classList.toggle('folded');
    document.getElementById('legend-toggle').textContent =
      legend.classList.contains('folded') ? '+' : '–';
  };

  await loadMacros();
  try {
    await refresh();
    // Open on the target. An empty panel on load wastes half the screen, and the
    // theorem is what the user came to look at.
    if (!state.selected && state.graph && state.graph.target) await select(state.graph.target);
  } catch (e) { toast(e.message, true); }
  await pollJobs();
  setInterval(pollJobs, 2000);
}

boot();
