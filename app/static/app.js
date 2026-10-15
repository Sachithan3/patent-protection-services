const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
let patents = [];

function renderRecent(items) {
  $('recent').innerHTML = items.slice(0, 4).map((p) => `<div class="recent-item"><b>${escapeHtml(p.title)}</b><span>${escapeHtml(p.patent_id)} · ${escapeHtml(p.category)}</span></div>`).join('') || '<p class="quiet">No patents indexed yet.</p>';
}
function renderLibrary() {
  const category = $('category').value;
  const items = category ? patents.filter((p) => p.category === category) : patents;
  $('all-patents').innerHTML = items.map((p) => `<article class="patent-row"><span class="id">${escapeHtml(p.patent_id)}</span><div><h3>${escapeHtml(p.title)}</h3><p>${escapeHtml(p.abstract)}</p></div><span class="category">${escapeHtml(p.category)}</span></article>`).join('') || '<p class="quiet">No patents match this filter.</p>';
}
function reportPayload(data) {
  const report = data.llm_infringement_report || {};
  return report.structured ? report.report : null;
}
function renderList(id, items, emptyText) {
  const values = Array.isArray(items) ? items : [];
  $(id).innerHTML = values.map((item) => `<li>${escapeHtml(typeof item === 'string' ? item : item.overlap_explanation || JSON.stringify(item))}</li>`).join('') || `<li>${escapeHtml(emptyText)}</li>`;
}
function renderFinalReport(data) {
  const report = reportPayload(data);
  if (!report) {
    $('final-report').classList.add('report-unavailable');
    $('comparison').textContent = 'The model returned an unstructured report. Review the retrieved patent signals above.';
    return;
  }
  const risk = String(report.overall_infringement_risk || 'UNKNOWN').toUpperCase();
  $('risk-badge').textContent = risk;
  $('risk-badge').className = `risk-badge risk-${risk.toLowerCase()}`;
  $('risk-score').textContent = Number.isFinite(Number(report.risk_score)) ? Math.round(Number(report.risk_score)) : '—';
  $('comparison').textContent = report.cross_patent_comparison || 'No cross-patent comparison was returned.';
  $('risk-factors').innerHTML = (Array.isArray(report.risk_factors) ? report.risk_factors : []).map((factor) => `<div class="risk-factor"><div class="factor-label"><strong>${escapeHtml(factor.name || 'Risk factor')}</strong><span>${escapeHtml(factor.score ?? '—')} / 100 · ${escapeHtml(factor.weight ?? '—')}% weight</span></div><div class="factor-bar"><i style="width:${Math.max(0, Math.min(100, Number(factor.score) || 0))}%"></i></div><p>${escapeHtml(factor.rationale || '')}</p></div>`).join('') || '<p class="quiet">No factor breakdown was returned.</p>';
  renderList('overlapping-claims', report.overlapping_claims, 'No supported claim overlap identified.');
  renderList('technical-differences', report.technical_differences, 'No technical differences were returned.');
  renderList('design-arounds', report.design_around_recommendations, 'No recommendations were returned.');
  renderList('limitations', report.limitations, 'No limitations were returned.');
  $('verdict').textContent = report.final_legal_verdict_summary || '';
}
async function loadLibrary() {
  const [patentResponse, statResponse] = await Promise.all([fetch('/api/v1/patents?limit=4'), fetch('/api/v1/stats')]);
  if (!patentResponse.ok || !statResponse.ok) throw new Error('The patent library is not available yet.');
  const data = await patentResponse.json(); const stats = await statResponse.json();
  patents = data.patents; $('patent-count').textContent = stats.patent_count;
  $('category').insertAdjacentHTML('beforeend', data.categories.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join(''));
  renderRecent(patents); renderLibrary(); $('status').textContent = 'Library online · ready to explore';
}
async function analyze() {
  const draft = $('draft').value.trim(); $('error').textContent = '';
  if (draft.length < 20) { $('error').textContent = 'Add a little more technical detail (at least 20 characters).'; return; }
  $('analyze').disabled = true; $('analyze').firstChild.textContent = 'Searching… ';
  try {
    const response = await fetch('/api/v1/analyze?top_k=6', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_draft:draft})});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Analysis could not be completed.');
    $('results').classList.remove('hidden'); $('result-summary').textContent = `${data.matching_patents.length} related records`;
    $('matches').innerHTML = data.matching_patents.map((p) => `<article class="match"><span class="score">${Math.round((p.cosine_similarity || 0) * 100)}% signal</span><span class="id">${escapeHtml(p.patent_id)}</span><h3>${escapeHtml(p.title)}</h3><p>${escapeHtml(p.abstract)}</p></article>`).join('');
    renderFinalReport(data);
    $('results').scrollIntoView({behavior:'smooth', block:'start'});
  } catch (error) { $('error').textContent = error.message; } finally { $('analyze').disabled = false; $('analyze').firstChild.textContent = 'Find related patents '; }
}
$('draft').addEventListener('input', () => $('draft-count').textContent = `${$('draft').value.length} characters`);
$('analyze').addEventListener('click', analyze); $('category').addEventListener('change', renderLibrary);
loadLibrary().catch((error) => { $('status').textContent = 'Library unavailable'; $('error').textContent = error.message; });
