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

// $$…$$, \[…\], \(…\), $…$ — the delimiters that actually appear in the corpus.
const MATH_RE = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]+?\$)/g;
const REF_RE = /`([A-Za-z0-9][A-Za-z0-9._-]*)`/g;

function renderMath(tex, display) {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: false });
  } catch (e) {
    return null;   // fall back to showing the source, escaped
  }
}

/** Prose with node references linked. Everything goes in as text. */
function proseWithRefs(text, into) {
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
    else { tex = token.slice(1, -1); display = false; }
    const html = renderMath(tex, display);
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
    panel.append(editor(node.statement, async (text) => saveStatement(node.id, text)));
  } else {
    const body = el('div', { class: 'prose' });
    body.append(mathProse(node.statement));
    panel.append(body);
  }

  // --- proof
  panel.append(sectionHeading('Proof', 'proof', node, busy));
  if (state.editing === 'proof') {
    panel.append(editor(node.proof, async (text) => {
      await post(`/api/node/${encodeURIComponent(node.id)}/proof`, { text });
      state.editing = null;
      toast('proof saved');
      await refresh();
    }));
  } else if (node.proof.trim()) {
    const body = el('div', { class: 'prose' });
    body.append(mathProse(node.proof));
    panel.append(body);
  } else {
    panel.append(el('div', { class: 'prose muted' }, 'No proof written.'));
  }

  // --- discharge table
  if (Object.keys(node.uses).length) {
    panel.append(el('h3', { class: 'section' }, 'Discharges'));
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

  // --- objections
  if (node.flags.length) {
    panel.append(el('h3', { class: 'section' }, 'Objections'));
    for (const flag of node.flags) {
      const box = el('div', { class: 'flag' });
      box.append(el('div', { class: 'kind' }, flag.kind || 'objection'));
      const why = el('div', {});
      why.append(mathProse(flag.why || ''));
      box.append(why);
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
  if (node.has_proof) add('Verify', () => runJob('verify', node.id));

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
  } else if (job.kind === 'verify') {
    body.append(el('p', {},
      el('b', {}, result.verdict),
      ` — ${result.obligations_checked} obligation(s) checked ` +
      `(${result.obligations_cached} from cache), ${result.panel_ran} panel member(s) answered.`));
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

async function recompileSheet() {
  const body = el('div', {});
  body.append(el('div', { class: 'spinner-row' }, 'Working out what it would cost…'));
  sheet('Recompile', body, [{ label: 'Close', onClick: closeSheet }]);
  let plan;
  try { plan = await api('/api/recompile/plan'); }
  catch (e) { body.textContent = e.message; return; }

  body.textContent = '';
  body.append(el('pre', { class: 'tex' }, plan.text));
  const actions = [{ label: 'Cancel', onClick: closeSheet }];
  if (plan.tasks.length) {
    actions.push({
      label: `Run ${plan.calls} call(s)`, primary: true,
      onClick: () => { closeSheet(); runJob('recompile', null, {}); },
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

  const reload = async () => {
    const query = `?clean=${clean.checked}&audit=${audit.checked}`;
    pre.textContent = 'rendering…';
    try { pre.textContent = await api('/api/render' + query); }
    catch (e) { pre.textContent = e.message; }
  };
  clean.onchange = reload; audit.onchange = reload;
  sheet('The document', body, [
    { label: 'Close', onClick: closeSheet },
    {
      label: 'Download .tex',
      onClick: () => { window.location = `/api/render.tex?clean=${clean.checked}&audit=${audit.checked}`; },
    },
    {
      label: 'Open PDF', primary: true,
      onClick: () => { window.open(`/api/render.pdf?clean=${clean.checked}&audit=${audit.checked}`, '_blank'); },
    },
  ]);
  await reload();
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
  document.getElementById('btn-recompile').onclick = guard(recompileSheet);
  document.getElementById('btn-render').onclick = guard(renderSheet);
  document.getElementById('btn-check').onclick = guard(checkSheet);
  document.getElementById('btn-history').onclick = guard(historySheet);
  document.getElementById('btn-agents').onclick = guard(agentsSheet);

  const legend = document.getElementById('legend');
  document.getElementById('legend-toggle').onclick = () => {
    legend.classList.toggle('folded');
    document.getElementById('legend-toggle').textContent =
      legend.classList.contains('folded') ? '+' : '–';
  };

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
