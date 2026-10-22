/* ClaimGuard AI – app.js v9
 * Handles: patent analysis, library, knowledge graph (Mode A + Mode B)
 * Dependencies: Cytoscape.js (loaded in HTML), cytoscape-cola layout (optional)
 */

'use strict';

/* ─────────────────────── Utilities ─────────────────────── */
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]
  ));

// FastAPI validation errors return `detail` as an array of objects. Passing
// that straight to `new Error()` renders as "[object Object]", hiding the real
// problem, so turn every payload shape into a readable message.
function apiErrorMessage(payload, fallback) {
  const detail = payload && payload.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') {
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== 'body' && part !== 'query').join('.')
          : '';
        const message = item.msg || item.message || '';
        if (message) return location ? `${location}: ${message}` : message;
        try { return JSON.stringify(item); } catch (_) { return String(item); }
      }
      return String(item);
    }).filter(Boolean);
    if (parts.length > 0) return parts.join('; ');
  }
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message;
    if (typeof detail.msg === 'string') return detail.msg;
    try { return JSON.stringify(detail); } catch (_) { /* fall through */ }
  }
  return fallback;
}

/* ─────────────────────── State ─────────────────────── */
let patents = [];
let lastAnalysisPatents = [];   // full patent objects from last /analyze
let lastAnalysisDraft = '';
let cy = null;
let graphMode = 'default';      // 'default' | 'focused'
let currentSimilarityThreshold = 0.45;  // calibrated to corpus
let graphLoading = false;
let selectedNodeId = null;      // the one node whose details are open
// Incremented for every graph request.  Only the response belonging to the
// latest request may render, so a slow "default" request can never overwrite a
// "focused" graph (or vice versa).
let graphRequestToken = 0;

/* ─────────────────────── Tab navigation ─────────────────────── */
let activeTab = 'home';

function tabFromHash() {
  return window.location.hash === '#graph' ? 'graph' : 'home';
}

function activateTab(name, { autoLoadGraph = true, updateHash = true } = {}) {
  const next = name === 'graph' ? 'graph' : 'home';
  const changed = next !== activeTab;
  activeTab = next;

  document.querySelectorAll('.topnav-link').forEach((el) => {
    const isActive = el.dataset.tab === next;
    el.classList.toggle('active', isActive);
    if (isActive) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  $('tab-home').classList.toggle('hidden', next !== 'home');
  $('tab-graph').classList.toggle('hidden', next !== 'graph');

  // Tabs are addressable: #graph deep-links straight into the explorer.
  if (updateHash && window.location.hash !== `#${next}`) {
    history.pushState({ tab: next }, '', `#${next}`);
  }
  if (changed && typeof window.scrollTo === 'function') {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }
  if (autoLoadGraph && next === 'graph' && cy === null && !graphLoading) {
    loadDefaultGraph();
  }
}

document.querySelectorAll('.topnav-link').forEach((link) => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    activateTab(link.dataset.tab);
  });
});

window.addEventListener('popstate', () => {
  activateTab(tabFromHash(), { updateHash: false });
});

// Keep manual hash edits and fragment navigations in sync as well.
window.addEventListener('hashchange', () => {
  const target = tabFromHash();
  if (target !== activeTab) activateTab(target, { updateHash: false });
});

/* ─────────────────────────────────────────────────────────────
   ANALYSIS / HOME tab  (unchanged)
   ───────────────────────────────────────────────────────────── */

function renderRecent(items) {
  $('recent').innerHTML = items.length
    ? items.slice(0, 4).map((p) =>
        `<div class="recent-item">
           <b>${escapeHtml(p.title)}</b>
           <span>${escapeHtml(p.patent_id)} · ${escapeHtml(p.category)}</span>
         </div>`
      ).join('')
    : `<div class="empty-state"><strong>No patents indexed</strong><p>The library seeds on first startup.</p></div>`;
}

function renderLibrary() {
  const category = $('category').value;
  const items = category ? patents.filter((p) => p.category === category) : patents;
  $('library-count').textContent = category
    ? `${items.length} of ${patents.length} patents`
    : `${patents.length} patents`;
  $('all-patents').innerHTML = items.length
    ? items.map((p) =>
        `<article class="patent-row">
           <span class="id">${escapeHtml(p.patent_id)}</span>
           <div><h3>${escapeHtml(p.title)}</h3><p>${escapeHtml(p.abstract)}</p></div>
           <span class="category">${escapeHtml(p.category)}</span>
         </article>`
      ).join('')
    : `<div class="empty-state"><strong>No patents match this filter</strong><p>Choose a different technology area to see indexed records.</p></div>`;
}

function reportPayload(data) {
  const report = data.llm_infringement_report || {};
  return report.structured ? report.report : null;
}

function renderList(id, items, emptyText) {
  const values = Array.isArray(items) ? items : [];
  $(id).innerHTML =
    values.map((item) =>
      `<li>${escapeHtml(typeof item === 'string' ? item : item.overlap_explanation || JSON.stringify(item))}</li>`
    ).join('') || `<li>${escapeHtml(emptyText)}</li>`;
}

function renderFinalReport(data) {
  const report = reportPayload(data);
  if (!report) {
    $('final-report').classList.add('report-unavailable');
    $('comparison').textContent =
      'The model returned an unstructured report. Review the retrieved patent signals above.';
    return;
  }
  const risk = String(report.overall_infringement_risk || 'UNKNOWN').toUpperCase();
  $('risk-badge').textContent = risk;
  $('risk-badge').className = `risk-badge risk-${risk.toLowerCase()}`;
  $('risk-score').textContent = Number.isFinite(Number(report.risk_score))
    ? Math.round(Number(report.risk_score)) : '—';
  $('comparison').textContent =
    report.cross_patent_comparison || 'No cross-patent comparison was returned.';
  $('risk-factors').innerHTML =
    (Array.isArray(report.risk_factors) ? report.risk_factors : [])
      .map((factor) =>
        `<div class="risk-factor">
           <div class="factor-label">
             <strong>${escapeHtml(factor.name || 'Risk factor')}</strong>
             <span>${escapeHtml(factor.score ?? '—')} / 100 · ${escapeHtml(factor.weight ?? '—')}% weight</span>
           </div>
           <div class="factor-bar"><i style="width:${Math.max(0, Math.min(100, Number(factor.score) || 0))}%"></i></div>
           <p>${escapeHtml(factor.rationale || '')}</p>
         </div>`
      ).join('') || '<p class="quiet">No factor breakdown was returned.</p>';
  renderList('overlapping-claims', report.overlapping_claims, 'No supported claim overlap identified.');
  renderList('technical-differences', report.technical_differences, 'No technical differences were returned.');
  renderList('design-arounds', report.design_around_recommendations, 'No recommendations were returned.');
  renderList('limitations', report.limitations, 'No limitations were returned.');
  $('verdict').textContent = report.final_legal_verdict_summary || '';
}

async function loadLibrary() {
  const [patentResponse, statResponse] = await Promise.all([
    fetch('/api/v1/patents?limit=4'),
    fetch('/api/v1/stats'),
  ]);
  if (!patentResponse.ok || !statResponse.ok)
    throw new Error('The patent library is not available yet.');
  const data = await patentResponse.json();
  const stats = await statResponse.json();
  patents = data.patents;
  $('patent-count').textContent = stats.patent_count;
  $('category').insertAdjacentHTML(
    'beforeend',
    data.categories.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')
  );
  renderRecent(patents);
  renderLibrary();
  $('status').dataset.state = 'online';
  $('status').textContent = `Online · ${stats.patent_count} patents indexed`;
}

async function analyze() {
  const draft = $('draft').value.trim();
  $('error').textContent = '';
  if (draft.length < 20) {
    $('error').textContent = 'Add a little more technical detail (at least 20 characters).';
    return;
  }
  $('analyze').disabled = true;
  $('analyze').firstChild.textContent = 'Searching… ';

  // A full analysis waits on the embedding model and Gemini, which can take
  // tens of seconds. Show elapsed progress so the UI never looks frozen.
  const progress = $('analyze-progress');
  const startedAt = Date.now();
  const updateProgress = () => {
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    const stage =
      elapsed < 8 ? 'Matching your draft against the indexed patents'
      : elapsed < 20 ? 'Ranking claim-level evidence'
      : 'Generating the grounded report — this is the slow step';
    progress.textContent = `${stage}… ${elapsed}s elapsed`;
  };
  progress.classList.remove('hidden');
  updateProgress();
  const progressTimer = setInterval(updateProgress, 1000);

  // Keep the browser waiting a little longer than the server-side Gemini
  // timeout so the API can return a proper error instead of a dropped request.
  const controller = new AbortController();
  const timeoutTimer = setTimeout(() => controller.abort(), 150000);

  try {
    const response = await fetch('/api/v1/analyze?top_k=6', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_draft: draft }),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiErrorMessage(data, `Analysis failed (HTTP ${response.status}).`));
    }

    // Store full patent objects for Mode B (including cosine_similarity)
    const matchedPatents = Array.isArray(data.matching_patents) ? data.matching_patents : [];
    lastAnalysisPatents = matchedPatents;
    lastAnalysisDraft = draft;

    $('results').classList.remove('hidden');
    $('result-summary').textContent = `${matchedPatents.length} related records · ranked by evidence`;
    // Always toggle, not just show: otherwise a zero-match analysis leaves the
    // button from the previous analysis visible and it opens a stale graph.
    $('explore-graph-btn').classList.toggle('hidden', lastAnalysisPatents.length === 0);

    $('matches').innerHTML = matchedPatents.length
      ? matchedPatents.map((p, index) => {
          const overlap = Math.max(0, Math.min(100, Math.round(Number(p.claim_overlap_score) || 0)));
          const semantic = Math.max(0, Math.min(100, Math.round((Number(p.cosine_similarity) || 0) * 100)));
          const evidence = p.evidence_type === 'title_abstract' ? 'Technical overlap' : 'Claim overlap';
          return `<article class="match">
             <div class="match-top">
               <span class="match-rank">${String(index + 1).padStart(2, '0')}</span>
               <span class="match-evidence">${escapeHtml(evidence)}</span>
             </div>
             <span class="id">${escapeHtml(p.patent_id || '')}</span>
             <h3>${escapeHtml(p.title || 'Untitled record')}</h3>
             <p>${escapeHtml(p.abstract || 'No abstract available.')}</p>
             <div class="match-meta">
               <span class="meter" aria-hidden="true"><i style="width:${overlap}%"></i></span>
               <small>${overlap}% evidence · ${semantic}% semantic</small>
             </div>
           </article>`;
        }).join('')
      : `<div class="empty-state"><strong>No matching patents</strong><p>Try a more specific technical description.</p></div>`;

    renderFinalReport(data);
    $('results').scrollIntoView({
      behavior: _prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'start',
    });
  } catch (error) {
    $('error').textContent =
      error.name === 'AbortError'
        ? 'The analysis timed out after 2.5 minutes. The report service may be busy — please try again.'
        : error.message;
  } finally {
    clearInterval(progressTimer);
    clearTimeout(timeoutTimer);
    progress.classList.add('hidden');
    $('analyze').disabled = false;
    $('analyze').firstChild.textContent = 'Find related patents ';
  }
}

// Mode B entry point
$('explore-graph-btn').addEventListener('click', () => {
  graphMode = 'focused';
  // Skip the tab's automatic default-graph load so only the focused graph is
  // requested.  If an overview request is already running it is superseded.
  activateTab('graph', { autoLoadGraph: false });
  loadFocusedGraph(lastAnalysisPatents, lastAnalysisDraft);
});

$('draft').addEventListener('input', () => {
  $('draft-count').textContent = `${$('draft').value.length} characters`;
});
$('analyze').addEventListener('click', analyze);
$('category').addEventListener('change', renderLibrary);

// Example drafts give first-time users a concrete starting point.
const EXAMPLE_DRAFTS = {
  tree: 'A method compresses data stored in a tree structure by leaving root-child node data uncompressed, compressing leaf-child node data, and querying the structure sequentially from the root through its child nodes.',
  robot: 'A warehouse robot uses an event camera and LiDAR to build a sparse 3D map, then plans collision-free routes on an edge processor.',
  crypto: 'A post-quantum digital signature generates lattice-based keys, applies Gaussian noise, and uses rejection sampling to produce compact signatures.',
};

document.querySelectorAll('.example-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    const text = EXAMPLE_DRAFTS[chip.dataset.example];
    if (!text) return;
    const draft = $('draft');
    draft.value = text;
    draft.dispatchEvent(new Event('input', { bubbles: true }));
    draft.focus();
  });
});

loadLibrary().catch((error) => {
  $('status').dataset.state = 'offline';
  $('status').textContent = 'Library unavailable';
  $('error').textContent = error.message;
});

/* ─────────────────────────────────────────────────────────────
   KNOWLEDGE GRAPH – Cytoscape.js integration
   Patent-only: no concept nodes, no concept edges.
   Connections are real embedding cosine similarities from pgvector.
   ───────────────────────────────────────────────────────────── */

// ── Cytoscape stylesheet ──────────────────────────────────────
const GRAPH_STYLE = [
  // ── Default patent node ───────────────────────────────
  {
    selector: 'node[type="patent"]',
    style: {
      'background-color': '#13251d',
      'border-width': 2,
      'border-color': '#3f9c7a',
      'label': 'data(label)',
      'color': '#d5e8de',
      'font-size': 10,
      'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif',
      'font-weight': 600,
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'ellipsis',
      'text-max-width': 60,
      'width': 54,
      'height': 54,
      'shape': 'ellipse',
      'transition-property': 'border-color, border-width, background-color',
      'transition-duration': '150ms',
    },
  },
  // Highlighted patent (direct analysis match)
  {
    selector: 'node[type="patent"][?highlighted]',
    style: {
      'background-color': '#2a1e0c',
      'border-color': '#d9a441',
      'border-width': 2.5,
      'color': '#f3dfb6',
      'width': 62,
      'height': 62,
    },
  },
  // ── Your Invention (query) node ───────────────────────
  {
    selector: 'node[type="query"]',
    style: {
      'background-color': '#2a1e0c',
      'border-width': 2.5,
      'border-color': '#e0b054',
      'label': 'data(label)',
      'color': '#f6e4c0',
      'font-size': 10.5,
      'font-weight': 700,
      'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif',
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'wrap',
      'text-max-width': 74,
      'width': 76,
      'height': 76,
      'shape': 'ellipse',
      'transition-property': 'border-color, border-width',
      'transition-duration': '150ms',
    },
  },
  // ── Patent–Patent similarity edges ───────────────────
  {
    selector: 'edge[type="PATENT_SIMILAR"]',
    style: {
      // width: thin for weak links, thicker for strong
      'width': 'mapData(weight, 0.3, 0.9, 1, 3)',
      // muted teal, visually clear on the dark spruce canvas
      'line-color': '#347d63',
      'curve-style': 'bezier',
      'opacity': 'mapData(weight, 0.3, 0.9, 0.35, 0.8)',
      'transition-property': 'opacity, width, line-color',
      'transition-duration': '150ms',
    },
  },
  // ── Query → matched patent edges ─────────────────────
  {
    selector: 'edge[type="QUERY_MATCH"]',
    style: {
      'width': 'mapData(weight, 0.3, 0.8, 1.5, 3.5)',
      'line-color': '#b9803a',
      'target-arrow-color': '#b9803a',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.65,
      'curve-style': 'bezier',
      'opacity': 'mapData(weight, 0.3, 0.8, 0.5, 0.9)',
      'transition-property': 'opacity, line-color',
      'transition-duration': '150ms',
    },
  },
  // ── Hover: brighten the hovered node ─────────────────
  {
    selector: 'node.hovered',
    style: {
      'border-color': '#9be4c1',
      'border-width': 2.5,
      'color': '#f2fbf6',
    },
  },
  // ── Hover: brighten edges connected to hovered node ──
  {
    selector: 'edge.hovered',
    style: {
      'line-color': '#58c79a',
      'opacity': 1,
      'width': 2.5,
    },
  },
  // ── Selected node ─────────────────────────────────────
  {
    selector: '.selected',
    style: {
      'border-width': 3,
      'border-color': '#e8c87e',
      'background-color': '#1c3a2d',
      'overlay-opacity': 0,
    },
  },
  // ── Selected query node ───────────────────────────────
  {
    selector: 'node[type="query"].selected',
    style: {
      'border-color': '#f0d28a',
      'background-color': '#2a1e0c',
    },
  },
  // ── Search matches (distinct from the one selected node) ──
  {
    selector: 'node.matched',
    style: {
      'border-width': 2.5,
      'border-color': '#8fd6b8',
      'background-color': '#1c3a2d',
    },
  },
  {
    selector: 'node[type="query"].matched',
    style: {
      'border-color': '#f0d28a',
      'background-color': '#2a1e0c',
    },
  },
  // ── Faded (non-neighbourhood) ─────────────────────────
  {
    selector: '.faded',
    style: {
      'opacity': 0.12,
    },
  },
  // ── Highlighted (neighbourhood) ───────────────────────
  {
    selector: '.highlighted',
    style: {
      'opacity': 1,
    },
  },
  // ── Highlighted edges (connected to selection) ────────
  {
    selector: 'edge.highlighted',
    style: {
      'line-color': '#58c79a',
      'opacity': 0.9,
      'width': 2,
    },
  },
  // suppress Cytoscape's default active flash
  {
    selector: 'node:active',
    style: { 'overlay-opacity': 0 },
  },
];

// ── Cola layout detection ─────────────────────────────────────
function _colaAvailable() {
  try { return typeof window.cola !== 'undefined'; } catch (_) { return false; }
}

function _prefersReducedMotion() {
  try {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (_) {
    return false;
  }
}

function _makeLayoutConfig(randomize = false, isRadial = false) {
  const animate = !_prefersReducedMotion();
  const animationDuration = animate ? 600 : 0;
  // Mode B: concentric rings — query at centre, matches in middle, context outside
  if (isRadial) {
    return {
      name: 'concentric',
      fit: true,
      padding: 80,
      startAngle: -Math.PI / 2,   // top of circle
      sweep: 2 * Math.PI,
      clockwise: false,
      equidistant: true,
      minNodeSpacing: 50,
      animate,
      animationDuration,
      animationEasing: 'ease-out-cubic',
      concentric(node) {
        if (node.data('type') === 'query')       return 100;
        if (node.data('highlighted'))             return 60;
        return 20;
      },
      levelWidth() { return 1; },
    };
  }
  // Mode A: force-directed with cola (preferred) or cose fallback
  if (_colaAvailable()) {
    return {
      name: 'cola',
      animate,
      animationDuration,
      animationEasing: 'ease-out-cubic',
      fit: true,
      padding: 70,
      nodeSpacing: 40,          // generous breathing room
      edgeLengthVal: 190,       // longer edges spread the graph naturally
      maxSimulationTime: 4500,
      randomize,
      convergenceThreshold: 0.004,
      handleDisconnected: true,  // keep isolated patents from stacking in a corner
    };
  }
  return {
    name: 'cose',
    animate,
    animationDuration,
    animationEasing: 'ease-out-cubic',
    fit: true,
    padding: 70,
    nodeRepulsion: 16000,       // push nodes apart strongly
    edgeElasticity: 100,
    idealEdgeLength: 190,
    numIter: 1400,
    gravity: 0.15,              // slight pull to centre keeps graph from exploding
    randomize,
    componentSpacing: 100,      // space between disconnected components
    nestingFactor: 1.2,
  };
}

// ── Graph init ────────────────────────────────────────────────
function initCytoscape(elements, useRadial = false) {
  if (typeof cytoscape === 'undefined') {
    $('graph-error-msg').textContent =
      'Cytoscape.js failed to load. Check your internet connection and reload the page.';
    showGraphOverlay('error');
    graphLoading = false;
    return;
  }
  if (cy) { cy.destroy(); cy = null; }
  selectedNodeId = null;
  resetDetailPanel();

  const layoutConfig = _makeLayoutConfig(false, useRadial);

  const instance = cytoscape({
    container: $('graph-canvas'),
    elements,
    style: GRAPH_STYLE,
    layout: layoutConfig,
    wheelSensitivity: 0.3,
    minZoom: 0.1,
    maxZoom: 5,
  });
  cy = instance;

  instance.on('layoutstop', () => {
    // A superseded instance must not clear the loading state of a newer one.
    if (cy !== instance) return;
    graphLoading = false;
    showGraphOverlay(null);
  });

  instance.on('tap', 'node', (evt) => {
    // Tapping the selected node again closes its details.  Without this the
    // only way out was a background click, which is hard to hit on a dense map.
    selectNode(evt.target, { toggle: true });
  });

  instance.on('tap', (evt) => {
    if (evt.target === instance) deselectNode();
  });

  instance.on('mouseover', 'node', (evt) => {
    document.body.style.cursor = 'pointer';
    const node = evt.target;
    node.addClass('hovered');
    node.connectedEdges().addClass('hovered');
    showTooltip(node, evt.renderedPosition);
  });

  instance.on('mouseout', 'node', (evt) => {
    document.body.style.cursor = '';
    evt.target.removeClass('hovered');
    evt.target.connectedEdges().removeClass('hovered');
    hideTooltip();
  });

  instance.on('mousemove', (evt) => {
    if (_tooltip && _tooltip.style.display !== 'none') {
      _moveTooltip(evt.renderedPosition);
    }
  });
}

// ── Tooltip ───────────────────────────────────────────────────
let _tooltip = null;

function _ensureTooltip() {
  if (_tooltip) return _tooltip;
  _tooltip = document.createElement('div');
  _tooltip.id = 'graph-tooltip';
  _tooltip.className = 'graph-tooltip';
  document.body.appendChild(_tooltip);
  return _tooltip;
}

function _moveTooltip(pos) {
  const canvas = $('graph-canvas');
  const rect = canvas.getBoundingClientRect();
  const x = rect.left + pos.x + 14;
  const y = rect.top  + pos.y - 10;
  // keep inside viewport
  const tw = _tooltip.offsetWidth || 220;
  const th = _tooltip.offsetHeight || 60;
  _tooltip.style.left = `${Math.min(x, window.innerWidth  - tw  - 12)}px`;
  _tooltip.style.top  = `${Math.max(y - th, 8)}px`;
}

function showTooltip(node, renderedPos) {
  const d = node.data();
  const tip = _ensureTooltip();
  if (d.type === 'query') {
    tip.innerHTML =
      `<div class="tip-label">Your Invention</div>` +
      `<div class="tip-sub">Temporary · not stored</div>`;
  } else {
    const simLine = d.cosine_similarity != null
      ? `<div class="tip-sim">${Math.round(d.cosine_similarity * 100)}% match</div>`
      : '';
    tip.innerHTML =
      `<div class="tip-label">${escapeHtml(d.patent_id || d.label || '')}</div>` +
      `<div class="tip-title">${escapeHtml((d.title || '').slice(0, 90))}${(d.title || '').length > 90 ? '…' : ''}</div>` +
      simLine;
  }
  tip.style.display = 'block';
  _moveTooltip(renderedPos);
}

function hideTooltip() {
  if (_tooltip) _tooltip.style.display = 'none';
}

// ── API helpers ───────────────────────────────────────────────
async function fetchDefaultGraph(maxPatents, threshold) {
  const params = new URLSearchParams({ max_patents: maxPatents, similarity_threshold: threshold });
  const res = await fetch(`/api/v1/graph?${params}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(apiErrorMessage(e, `Graph API ${res.status}`));
  }
  return res.json();
}

async function fetchFocusedGraph(patentIds, threshold, queryLabel, querySimilarities) {
  const body = {
    patent_ids: patentIds,
    similarity_threshold: threshold,
    expand_neighbours: true,
    query_label: queryLabel || null,
    query_similarities: querySimilarities || null,
  };
  const res = await fetch('/api/v1/graph/focused', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(apiErrorMessage(e, `Graph API ${res.status}`));
  }
  return res.json();
}

async function fetchExpandNode(patentId, threshold) {
  const params = new URLSearchParams({ similarity_threshold: threshold });
  const res = await fetch(`/api/v1/graph/expand/${encodeURIComponent(patentId)}?${params}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(apiErrorMessage(e, `Expand API ${res.status}`));
  }
  return res.json();
}

// ── Convert API data → Cytoscape elements ────────────────────
function graphDataToElements(data) {
  const nodes = (data.nodes || []).map((n) => ({
    group: 'nodes',
    data: {
      id: n.id,
      type: n.type,
      label: n.type === 'query' ? 'Your Invention' : (n.patent_id || n.label || n.id),
      patent_id:        n.patent_id || null,
      title:            n.title || '',
      abstract:         n.abstract || '',
      category:         n.category || '',
      claims:           n.claims || [],
      highlighted:      n.highlighted ? true : undefined,
      cosine_similarity: n.cosine_similarity || null,
      note:             n.note || '',
    },
  }));

  const edges = (data.edges || []).map((e) => ({
    group: 'edges',
    data: {
      id:         e.id,
      source:     e.source,
      target:     e.target,
      type:       e.type,
      weight:     typeof e.weight === 'number' ? e.weight : 0.5,
      similarity: e.similarity || null,
      label:      e.label || '',
    },
  }));

  return [...nodes, ...edges];
}

// ── Overlay management ────────────────────────────────────────
function showGraphOverlay(which) {
  $('graph-canvas').setAttribute('aria-busy', which === 'loading' ? 'true' : 'false');
  $('graph-loading').classList.toggle('hidden', which !== 'loading');
  $('graph-empty').classList.toggle('hidden', which !== 'empty');
  $('graph-error').classList.toggle('hidden', which !== 'error');
}

// ── Stats bar ─────────────────────────────────────────────────
function updateStatsBar(meta) {
  const patentsCount = meta.patent_count || 0;
  const edgesCount = meta.total_edge_count || 0;
  $('gs-patents').textContent = `${patentsCount} ${patentsCount === 1 ? 'patent' : 'patents'}`;
  $('gs-edges').textContent = `${edgesCount} ${edgesCount === 1 ? 'connection' : 'connections'}`;
}

// ── Mode badge ────────────────────────────────────────────────
function setModeBadge(show, label) {
  let badge = $('graph-mode-badge');
  if (!show) { if (badge) badge.remove(); return; }
  if (!badge) {
    badge = document.createElement('div');
    badge.id = 'graph-mode-badge';
    badge.className = 'graph-mode-badge';
    const desc = document.querySelector('.graph-desc');
    if (desc) desc.insertAdjacentElement('afterend', badge);
  }
  badge.innerHTML =
    `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-network"></use></svg>
     <span>Focused: ${escapeHtml(label)}</span>
     <button class="mode-clear" id="mode-clear-btn" type="button" aria-label="Clear focus and return to the full graph">Clear</button>`;
  $('mode-clear-btn').addEventListener('click', () => {
    graphMode = 'default';
    setModeBadge(false);
    loadDefaultGraph();
  });
}

// ── Graph loaders ─────────────────────────────────────────────
async function loadDefaultGraph() {
  // A newer graph request always supersedes the previous one instead of
  // bailing out: the auto-loaded overview must never swallow a click on
  // "Explore in Knowledge Graph".
  const token = ++graphRequestToken;
  graphLoading = true;
  graphMode = 'default';
  showGraphOverlay('loading');
  setModeBadge(false);
  try {
    const data = await fetchDefaultGraph(30, currentSimilarityThreshold);
    if (token !== graphRequestToken) return;   // a newer request owns the canvas
    if (!data.nodes || data.nodes.length === 0) {
      showGraphOverlay('empty'); graphLoading = false; return;
    }
    initCytoscape(graphDataToElements(data), false);
    updateStatsBar(data.meta || {});
  } catch (err) {
    if (token !== graphRequestToken) return;
    graphLoading = false;
    $('graph-error-msg').textContent = err.message;
    showGraphOverlay('error');
  }
}

// patentObjects = full patent objects with cosine_similarity from /analyze
async function loadFocusedGraph(patentObjects, draftText) {
  if (!patentObjects || patentObjects.length === 0) { loadDefaultGraph(); return; }

  // Only real, non-empty identifiers are valid seeds for the API.
  const patentIds = patentObjects
    .map((p) => p.patent_id)
    .filter((id) => typeof id === 'string' && id.trim());
  if (patentIds.length === 0) { loadDefaultGraph(); return; }

  const token = ++graphRequestToken;
  graphLoading = true;
  graphMode = 'focused';
  showGraphOverlay('loading');

  // Build similarity map: patent_id → cosine_similarity (from /analyze)
  const querySimilarities = {};
  patentObjects.forEach((p) => {
    if (p.cosine_similarity != null && patentIds.includes(p.patent_id)) {
      querySimilarities[p.patent_id] = p.cosine_similarity;
    }
  });

  const shortLabel = draftText
    ? (draftText.length > 55 ? draftText.slice(0, 55) + '…' : draftText)
    : `${patentIds.length} patents`;
  setModeBadge(true, shortLabel);

  try {
    const data = await fetchFocusedGraph(
      patentIds,
      currentSimilarityThreshold,
      draftText || null,
      querySimilarities
    );
    if (token !== graphRequestToken) return;   // a newer request owns the canvas
    if (!data.nodes || data.nodes.length === 0) {
      showGraphOverlay('empty'); graphLoading = false; return;
    }
    // Use concentric (radial) layout when there's a query node at centre
    const hasQuery = data.nodes.some((n) => n.type === 'query');
    initCytoscape(graphDataToElements(data), hasQuery);
    updateStatsBar(data.meta || {});
  } catch (err) {
    if (token !== graphRequestToken) return;
    graphLoading = false;
    $('graph-error-msg').textContent = err.message;
    showGraphOverlay('error');
  }
}

async function expandPatentNode(patentId) {
  const token = ++graphRequestToken;
  graphLoading = true;
  showGraphOverlay('loading');
  try {
    const data = await fetchExpandNode(patentId, currentSimilarityThreshold);
    if (token !== graphRequestToken) return;   // a newer request owns the canvas
    if (!data.nodes || data.nodes.length === 0) {
      showGraphOverlay('empty'); graphLoading = false; return;
    }
    initCytoscape(graphDataToElements(data), false);
    updateStatsBar(data.meta || {});
    setModeBadge(true, `${patentId} · neighbours`);
    graphMode = 'focused';
  } catch (err) {
    if (token !== graphRequestToken) return;
    graphLoading = false;
    $('graph-error-msg').textContent = err.message;
    showGraphOverlay('error');
  }
}

// ── Node detail panel ─────────────────────────────────────────
function showNodeDetail(node) {
  const d = node.data();
  const detail = $('graph-detail');
  detail.classList.remove('hidden');

  const typeBadge = $('detail-type-badge');
  typeBadge.className = 'detail-badge badge-' + (d.type || 'patent');
  typeBadge.textContent = d.type === 'query' ? 'YOUR INVENTION' : 'PATENT';

  $('detail-title').textContent =
    d.type === 'patent' ? (d.title || d.patent_id || 'Patent')
    : d.type === 'query' ? 'Your Invention (draft)'
    : d.title || d.label;

  const body    = $('detail-body');
  const actions = $('detail-actions');
  actions.innerHTML = '';

  if (d.type === 'patent') {
    const simPct = d.cosine_similarity != null
      ? `<div class="detail-field"><strong>Similarity to draft</strong><span>${Math.round(d.cosine_similarity * 100)}%</span></div>`
      : '';
    const nbHtml = buildConnectedPatentsHtml(node);
    body.innerHTML = `
      <div class="detail-field"><strong>Patent ID</strong><span>${escapeHtml(d.patent_id || '')}</span></div>
      ${simPct}
      <div class="detail-field"><strong>Abstract</strong><span>${escapeHtml((d.abstract || '').slice(0, 420))}${(d.abstract || '').length > 420 ? '…' : ''}</span></div>
      ${nbHtml}
    `;
    const expandBtn = document.createElement('button');
    expandBtn.type = 'button';
    expandBtn.className = 'btn-secondary';
    expandBtn.innerHTML =
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-expand"></use></svg> Expand neighbourhood';
    expandBtn.addEventListener('click', () => expandPatentNode(d.patent_id));
    actions.appendChild(expandBtn);

  } else if (d.type === 'query') {
    body.innerHTML = `
      <div class="detail-field"><strong>Status</strong><span>Temporary — not stored in the database</span></div>
      <div class="detail-field"><strong>Draft</strong><span>${escapeHtml((d.title || '').slice(0, 420))}</span></div>
    `;
  }
}

function buildConnectedPatentsHtml(node) {
  if (!cy) return '';
  const neighbours = node.neighborhood('node[type="patent"]');
  if (neighbours.length === 0) return '';
  const tags = neighbours.slice(0, 8).map((n) =>
    `<button class="connected-tag" type="button" data-node-id="${escapeHtml(n.id())}">${escapeHtml(n.data('patent_id') || n.data('label'))}</button>`
  ).join('');
  return `<div class="detail-field"><strong>Connected patents (${neighbours.length})</strong><div class="connected-list">${tags}</div></div>`;
}

function hideDetail() { $('graph-detail').classList.add('hidden'); }

function resetDetailPanel() {
  const detail = $('graph-detail');
  if (!detail) return;
  $('detail-type-badge').className = 'detail-badge';
  $('detail-type-badge').textContent = '—';
  $('detail-title').textContent = 'Select a node';
  $('detail-body').innerHTML =
    '<p class="quiet">Select a patent node to inspect its title, abstract, and connections.</p>';
  $('detail-actions').innerHTML = '';
}

$('graph-detail').addEventListener('click', (e) => {
  const tag = e.target.closest('.connected-tag');
  if (!tag || !cy) return;
  const node = cy.getElementById(tag.dataset.nodeId);
  if (node.length) {
    cy.animate({
      fit: { eles: node.neighborhood().union(node), padding: 60 },
      duration: _prefersReducedMotion() ? 0 : 400,
    });
    selectNode(node);
  }
});

$('detail-close').addEventListener('click', () => deselectNode());

// Escape mirrors the close button: leave the graph tab's focus on the map.
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || activeTab !== 'graph') return;
  const target = e.target;
  const typing = target && (
    target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' || target.isContentEditable
  );
  if (typing) return;   // inputs handle their own Escape (e.g. clear search)
  if (selectedNodeId) { deselectNode(); return; }
  if (cy && cy.nodes('.matched').length) {
    $('graph-search').value = '';
    applySearch('');
  }
});

// ── Selection ─────────────────────────────────────────────────
function selectNode(node, { toggle = false } = {}) {
  if (!cy || !node || node.length === 0) return;
  if (toggle && selectedNodeId === node.id()) { deselectNode(); return; }
  selectedNodeId = node.id();
  highlightNeighbourhood(node);
  showNodeDetail(node);
}

function deselectNode() {
  selectedNodeId = null;
  clearHighlight();
  hideDetail();
}

function highlightNeighbourhood(node) {
  if (!cy) return;
  // Clear the previous selection explicitly; stale `.selected` classes left
  // earlier nodes looking selected after a new node was chosen.
  cy.elements().removeClass('selected');
  cy.elements().addClass('faded');
  const neighbourhood = node.closedNeighborhood();
  neighbourhood.removeClass('faded').addClass('highlighted');
  node.addClass('selected');
}

function clearHighlight() {
  if (!cy) return;
  cy.elements().removeClass('faded highlighted selected matched hovered');
}

// ── Toolbar controls ──────────────────────────────────────────
$('graph-fit').addEventListener('click', () => cy && cy.fit(undefined, 50));
$('graph-reset').addEventListener('click', () => {
  if (!cy) return;
  // For focused graphs with a query node, re-run concentric; else force-directed
  const hasQuery = cy.nodes('[type="query"]').length > 0;
  cy.layout(_makeLayoutConfig(true, hasQuery)).run();
});
$('graph-default').addEventListener('click', () => {
  graphMode = 'default';
  setModeBadge(false);
  loadDefaultGraph();
});
$('graph-retry').addEventListener('click', loadDefaultGraph);
$('graph-error-retry').addEventListener('click', () => {
  if (graphMode === 'focused' && lastAnalysisPatents.length > 0) {
    loadFocusedGraph(lastAnalysisPatents, lastAnalysisDraft);
  } else {
    loadDefaultGraph();
  }
});

// ── Search ────────────────────────────────────────────────────
let searchDebounce = null;
$('graph-search').addEventListener('input', (e) => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => applySearch(e.target.value.trim()), 180);
});
$('graph-search').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // First Escape clears the query; a second one (empty field) closes the
    // selected node, matching Escape elsewhere on the graph tab.
    if (!e.target.value && selectedNodeId) {
      e.target.blur();
      deselectNode();
      return;
    }
    e.target.value = '';
    applySearch('');
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    const query = e.target.value.trim();
    applySearch(query);
    const node = firstMatchingNode(query);
    if (node) selectNode(node);
  }
});

function firstMatchingNode(query) {
  if (!cy || !query) return null;
  const q = query.toLowerCase();
  const matches = cy.nodes().filter((n) => {
    const d = n.data();
    return (
      (d.label || '').toLowerCase().includes(q) ||
      (d.patent_id || '').toLowerCase().includes(q) ||
      (d.title || '').toLowerCase().includes(q)
    );
  });
  return matches.length > 0 ? matches[0] : null;
}

function applySearch(query) {
  if (!cy) return;
  if (!query) {
    const searchStatus = $('graph-search-status');
    if (searchStatus) searchStatus.textContent = '';
    clearHighlight();
    // Clearing the search must not clear the node the reader picked.
    const selected = selectedNodeId && cy.getElementById(selectedNodeId);
    if (selected && selected.length) highlightNeighbourhood(selected);
    return;
  }
  const q = query.toLowerCase();
  const matched = cy.nodes().filter((n) => {
    const d = n.data();
    return (
      (d.label || '').toLowerCase().includes(q) ||
      (d.patent_id || '').toLowerCase().includes(q) ||
      (d.title || '').toLowerCase().includes(q)
    );
  });
  const searchStatus = $('graph-search-status');
  if (searchStatus) {
    searchStatus.textContent = matched.length > 0
      ? `${matched.length} ${matched.length === 1 ? 'patent matches' : 'patents match'} “${query}”`
      : `No patents match “${query}”`;
  }
  cy.elements().removeClass('matched');
  if (matched.length === 0) { cy.elements().addClass('faded'); return; }
  cy.elements().addClass('faded');
  matched.closedNeighborhood().removeClass('faded').addClass('highlighted');
  matched.addClass('matched');
  cy.animate({
    fit: { eles: matched.closedNeighborhood(), padding: 60 },
    duration: _prefersReducedMotion() ? 0 : 400,
  });
}

// ── Similarity threshold slider ───────────────────────────────
// Sync slider initial position to match JS default (0.45 → 45)
document.addEventListener('DOMContentLoaded', () => {
  const slider = $('sim-threshold');
  if (slider) {
    slider.value = Math.round(currentSimilarityThreshold * 100);
    $('sim-value').textContent = `${slider.value}%`;
  }
});

let simSliderDebounce = null;
$('sim-threshold').addEventListener('input', (e) => {
  const val = Number(e.target.value);
  $('sim-value').textContent = `${val}%`;
  currentSimilarityThreshold = val / 100;
  clearTimeout(simSliderDebounce);
  simSliderDebounce = setTimeout(() => {
    if (graphMode === 'focused' && lastAnalysisPatents.length > 0) {
      loadFocusedGraph(lastAnalysisPatents, lastAnalysisDraft);
    } else {
      loadDefaultGraph();
    }
  }, 800);
});

// Support deep links such as /app/#graph on first paint.
activateTab(tabFromHash(), { updateHash: false });
