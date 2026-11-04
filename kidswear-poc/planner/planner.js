(function () {
  'use strict';
  let B = JSON.parse(document.getElementById('bundle').textContent);
  const $ = (id) => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const C = { ink: '#1A1917', muted: '#6B6560', line: '#E5E0D8', line2: '#CFC9C0', cardinal: '#8C1515', gold: '#B8962E', goldBg: '#FBF3DC', good: '#2E7D32', warn: '#B26A00', bad: '#C62828' };

  /* ---------------- helpers ---------------- */
  function h(tag, attrs, parent, text) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) { if (k === 'class') e.className = attrs[k]; else if (k === 'style') e.style.cssText = attrs[k]; else e.setAttribute(k, attrs[k]); }
    if (text !== undefined && text !== null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function s(tag, attrs, parent, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  const pct = (v, d) => (v === null || v === undefined || !isFinite(v) ? '–' : (v * 100).toFixed(d === undefined ? 1 : d) + '%');
  const spct = (v, d) => (!isFinite(v) ? '–' : (v > 0 ? '+' : '') + pct(v, d));
  const int = (v) => (isFinite(v) ? Math.round(v).toLocaleString('en') : '–');
  const rand = (v) => { if (!isFinite(v)) return '–'; const a = Math.abs(v), sg = v < 0 ? '−' : ''; return sg + (a >= 1e6 ? 'R' + (a / 1e6).toFixed(2) + 'm' : a >= 1e3 ? 'R' + (a / 1e3).toFixed(0) + 'k' : 'R' + a.toFixed(0)); };
  const srand = (v) => (v > 0 ? '+' : '') + rand(v);
  const compact = (v) => { const a = Math.abs(v); return a >= 1e6 ? (v / 1e6).toFixed(1) + 'm' : a >= 1e3 ? (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k' : String(Math.round(v)); };
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  function niceStep(max, n) { const raw = max / n || 1, p = Math.pow(10, Math.floor(Math.log10(raw))); const m = raw / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p; }
  function svgIn(el, W, H, label) { el.replaceChildren(); return s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label }, el); }
  function tip(el) {
    const t = h('div', { class: 'tip hidden' }, el);
    return {
      show(x, y, head, lines) {
        t.replaceChildren(); h('div', { class: 'h' }, t, head);
        lines.forEach(([n, v]) => { const r = h('div', null, t, n + ' '); h('b', null, r, v); });
        t.classList.remove('hidden');
        t.style.left = Math.max(0, Math.min(el.clientWidth - t.offsetWidth, x + 14)) + 'px';
        t.style.top = Math.max(0, y - t.offsetHeight - 10) + 'px';
      },
      hide() { t.classList.add('hidden'); },
    };
  }
  function kpi(box, l, v, sub, cls) { const e = h('div', { class: 'kpi' }, box); h('div', { class: 'l' }, e, l); h('div', { class: 'v ' + (cls || '') }, e, v); const ss = h('div', { class: 's' }, e); if (sub instanceof Node) ss.appendChild(sub); else ss.textContent = sub || ''; return e; }
  function was(old, now) { const f = document.createDocumentFragment(); f.append('Today '); h('s', null, f, old); f.append(' · ' + now); return f; }
  function table(box, cols, rows, opt) {
    opt = opt || {};
    const tb = h('div', { class: 'tablebox' }, box); if (opt.maxHeight) tb.style.maxHeight = opt.maxHeight;
    const t = h('table', null, tb), hr = h('tr', null, h('thead', null, t));
    cols.forEach((c) => h('th', { class: c.num ? 'n' : '' }, hr, c.label));
    const body = h('tbody', null, t);
    rows.forEach((r, i) => {
      const tr = h('tr', { class: opt.onClick ? 'click' : '' }, body);
      if (opt.onClick) { tr.tabIndex = 0; tr.addEventListener('click', () => opt.onClick(r, tr)); tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') opt.onClick(r, tr); }); }
      if (opt.selected && opt.selected(r)) tr.classList.add('sel');
      cols.forEach((c) => { const td = h('td', { class: c.num ? 'n' : '' }, tr); const v = c.render ? c.render(r, td, i) : r[c.key]; if (v instanceof Node) td.appendChild(v); else if (v !== undefined && v !== null) td.textContent = v; });
    });
    return t;
  }
  function bars(el, rows, opt) {
    // horizontal bars: rows [{label, value, color, note}]
    const W = Math.max(300, el.clientWidth || 600), row = 30, m = { l: opt.labelW || 210, r: 70 }, H = rows.length * row + 8;
    const max = opt.max || Math.max(...rows.map((r) => r.value)) || 1;
    const g = svgIn(el, W, H, opt.label || 'bar chart');
    rows.forEach((r, i) => {
      const y = i * row + 6, w = Math.max(2, r.value / max * (W - m.l - m.r));
      s('text', { x: m.l - 8, y: y + 14, 'text-anchor': 'end', 'font-size': 12.5, fill: C.ink }, g, r.label);
      s('rect', { x: m.l, y: y + 3, width: w, height: 16, rx: 2, fill: r.color || C.line2 }, g);
      s('text', { x: m.l + w + 6, y: y + 15, 'font-size': 12, fill: C.muted }, g, opt.fmt ? opt.fmt(r.value) : r.value);
    });
  }
  const pathColor = (d) => { const t = Math.min(1, d / 0.6); const r = Math.round(249 + (140 - 249) * t), gg = Math.round(232 + (21 - 232) * t), b = Math.round(200 + (21 - 200) * t); return `rgb(${r},${gg},${b})`; };
  function pathChips(path) { const p = h('span', { class: 'path', 'aria-label': 'discount by week: ' + path.map((d) => Math.round(d * 100) + '%').join(', ') }); path.forEach((d) => { const i = h('i', null, p, Math.round(d * 100)); i.style.background = pathColor(d); i.style.color = d > 0.25 ? '#fff' : C.ink; }); return p; }
  const store = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } } };
  function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: type || 'text/csv' })); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500); }
  const csvCell = (v) => (/[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));

  /* ---------------- tabs ---------------- */
  const TABS = [['overview', 'Overview & roadmap'], ['forecast', 'Forecasts & overrides'], ['sizes', 'Size curves & allocation'], ['markdown', 'Markdown & scenarios'],
    ['quality', 'Quality gaps'], ['trial', 'Store trial'], ['ops', 'Model operations'], ['depts', 'Departments']];
  let current = 'overview';
  function renderTabs() {
    const nav = $('tabs'); nav.replaceChildren();
    TABS.forEach(([id, label]) => {
      const b = h('button', { class: 'tab', role: 'tab', 'aria-selected': id === current ? 'true' : 'false', id: 'tab-' + id }, nav, label);
      b.addEventListener('click', () => { current = id; renderTabs(); render(); try { history.replaceState(null, '', '#' + id); } catch (e) { /* ignore */ } });
    });
  }
  function render() {
    const m = $('main'); m.replaceChildren();
    ({ overview, forecast, sizes, markdown, quality, trial, ops, depts })[current](m);
  }

  /* ---------------- overview ---------------- */
  function overview(m) {
    const H = B.headline;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Forecast error (test weeks)', pct(H.forecast_wape), was(pct(H.rule_wape), 'planner rule'));
    kpi(k, 'Units sent in the wrong size', pct(H.wrong_size), was(pct(H.wrong_size_chain), 'chain curve'));
    kpi(k, 'Clearance gross profit', srand(H.markdown_gp_uplift), 'vs today at the same sell-through (' + spct(H.markdown_gp_uplift / H.markdown_gp_actual, 0) + ')');
    kpi(k, 'Replenishment margin', spct(H.margin_uplift, 0), 'vs the best-tuned planner rule');
    kpi(k, 'Defective lines found', pct(H.defects_found, 0), 'from return comments');
    kpi(k, 'Inter-store transfers', rand(H.transfers_net), 'net benefit at clearance start');
    const intro = h('div', { class: 'card' }, m);
    h('h2', null, intro, 'Roadmap: 25 features, five iterations');
    h('p', { class: 'sub' }, intro, 'Every feature in the roadmap is built and scored on held-out data. Each line shows what was built, the result, and where it lives in the code (kidswear-poc/ in this site\'s repository).');
    B.roadmap.forEach((it) => {
      const row = h('div', { class: 'iter' }, intro);
      const n = h('div', { class: 'iter-n' }, row, String(it.iteration)); h('small', null, n, 'ITERATION');
      const body = h('div', null, row);
      h('h3', null, body, it.title);
      it.features.forEach((f) => {
        const r = h('div', { class: 'feat' }, body);
        const nm = h('div', { class: 'nm' }, r, f.name); h('span', { class: 'chip good' }, nm, 'Built');
        const rs = h('div', null, r); h('div', { class: 'rs' }, rs, f.result); h('div', { class: 'fl' }, rs, f.file);
      });
    });
    h('p', { class: 'note' }, m, B.meta.note + ' Department: ' + B.meta.department + '. Test window: ' + B.meta.test_weeks + '. Data version ' + B.meta.data_version + ', model run ' + B.meta.model_run + ', built ' + B.meta.generated + '.');
  }

  /* ---------------- forecasts ---------------- */
  let selStyle = null;
  function forecast(m) {
    const F = B.forecast, M = F.metrics;
    const styles = F.styles.slice().sort((a, b) => a.style_id.localeCompare(b.style_id));
    if (!selStyle) selStyle = styles[0].style_id;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Final forecast error', pct(F.ensemble.segments.all.stacked), was(pct(M.planner_rule_wape), 'planner rule'));
    kpi(k, 'Style by week error', pct(M.style_week_model_wape), 'planner rule ' + pct(M.style_week_rule_wape));
    kpi(k, 'Inside the P10–P90 range', pct(M.p10_p90_coverage, 0), 'target 80%');
    kpi(k, 'Bias', spct(M.model_bias), M.model_bias < 0 ? 'forecast below demand' : 'forecast above demand');
    kpi(k, 'External feeds', spct(-M.external_features_gain_pts / 100, 1), 'error change from weather, events, competitor, macro');

    const c = h('div', { class: 'card' }, m);
    h('h3', null, c, 'Forecast by style');
    h('p', { class: 'sub' }, c, 'Unconstrained demand history (black) and sales (grey) for the chain, then the test weeks: forecast with its P10–P90 range, the planner rule, and what demand turned out to be.');
    const ctl = h('div', { class: 'ctl' }, c); const w1 = h('div', null, ctl); h('label', { for: 'f-style' }, w1, 'Style');
    const sel = h('select', { id: 'f-style' }, w1);
    styles.forEach((st) => { const o = h('option', { value: st.style_id }, sel, `${st.style_id} · ${st.category} · ${st.fit} ${st.fabric}`); if (st.style_id === selStyle) o.selected = true; });
    sel.addEventListener('change', () => { selStyle = sel.value; render(); });
    const lg = h('div', { class: 'legend' }, c);
    [['Demand (unconstrained)', C.ink], ['Sales', C.line2], ['Forecast', C.cardinal], ['P10–P90', C.gold], ['Planner rule', C.muted]].forEach(([n, col]) => { const sp = h('span', null, lg); h('i', null, sp).style.background = col; sp.append(n); });
    const ch = h('div', { class: 'chart' }, c);
    const g2 = h('div', { class: 'grid2' }, m);
    const dc = h('div', { class: 'card' }, g2);
    h('h3', null, dc, 'What drives this style\'s forecast');
    h('p', { class: 'sub' }, dc, 'Average SHAP effect over the test weeks. +0.10 lifts the forecast by about 10%.');
    driverCard(dc, B.drivers.styles[selStyle]);
    const gc = h('div', { class: 'card' }, g2);
    h('h3', null, gc, 'Drivers across all forecasts');
    h('p', { class: 'sub' }, gc, 'Average size of each input\'s effect (SHAP), plain-English names.');
    const gch = h('div', { class: 'chart' }, gc);
    requestAnimationFrame(() => {
      drawStyleChart(ch, F.series[selStyle]);
      bars(gch, B.drivers.global_importance.slice(0, 10).map((d, i) => ({ label: d.driver, value: d.mean_abs_shap, color: i < 3 ? C.cardinal : C.line2 })), { fmt: (v) => v.toFixed(2), labelW: 200, label: 'driver importance' });
    });
    overridesCard(m);
    const g3 = h('div', { class: 'grid2' }, m);
    const ec = h('div', { class: 'card' }, g3);
    h('h3', null, ec, 'Ensemble and cold start');
    h('p', { class: 'sub' }, ec, 'Foundation models: ' + B.forecast.ensemble.status.chronos + '. Stacking weights were learned on validation weeks.');
    const seg = F.ensemble.segments;
    table(ec, [{ label: 'Segment', key: 'seg' }, { label: 'LightGBM', key: 'l', num: true }, { label: 'Zero-shot', key: 'z', num: true }, { label: 'Stacked', key: 's', num: true }, { label: 'Planner rule', key: 'r', num: true }],
      [['All styles', seg.all], ['New styles (cold start)', seg.new_styles], ['Established', seg.established]].map(([n, v]) => ({ seg: n, l: pct(v.lightgbm), z: pct(v.zero_shot), s: pct(v.stacked), r: pct(v.planner_rule) })));
    h('p', { class: 'note' }, ec, 'The planner rule uses last week\'s sales; the models forecast 8 weeks ahead, so the rule has fresher information for brand-new styles.');
    const hc = h('div', { class: 'card' }, g3);
    h('h3', null, hc, 'Hierarchy reconciliation');
    h('p', { class: 'sub' }, hc, 'Error at each level of chain → category → category × store → style × store. Reconciled forecasts add up exactly; recommended: ' + F.hierarchy.recommended.replace('_', '-') + '.');
    const HR = F.hierarchy.results;
    table(hc, [{ label: 'Method', key: 'm' }, { label: 'Chain', key: 't', num: true }, { label: 'Category', key: 'c', num: true }, { label: 'Cat × store', key: 'cs', num: true }, { label: 'Style × store', key: 'ss', num: true }, { label: 'Adds up', key: 'a' }],
      Object.keys(HR).map((k2) => ({ m: { base: 'Base (unreconciled)', bottom_up: 'Bottom-up', top_down: 'Top-down', mint_wls: 'MinT (WLS)' }[k2], t: pct(HR[k2].total), c: pct(HR[k2].category), cs: pct(HR[k2].category_store), ss: pct(HR[k2].style_store), a: HR[k2].max_coherence_gap_units < 0.01 ? 'Yes' : 'No' })));
  }
  function driverCard(box, card) {
    if (!card) { h('p', { class: 'muted' }, box, 'No driver card for this style.'); return; }
    const all = card.up.concat(card.down), max = Math.max(...all.map((d) => Math.abs(d.effect)), 0.01);
    const g = h('div', { class: 'drv' }, box);
    [['Pushing the forecast up', card.up, C.good], ['Pulling it down', card.down, C.bad]].forEach(([title, list, col]) => {
      h('div', { style: 'grid-column:1/-1;font-weight:700;margin-top:6px' }, g, title);
      if (!list.length) h('div', { class: 'muted', style: 'grid-column:1/-1' }, g, 'None');
      list.forEach((d) => { h('div', null, g, d.driver + ' (' + (d.effect > 0 ? '+' : '') + d.effect.toFixed(2) + ')'); const b = h('div', { class: 'b' }, g); b.style.width = Math.round(Math.abs(d.effect) / max * 100) + '%'; b.style.background = col; b.style.opacity = '.75'; });
    });
  }
  function drawStyleChart(el, d) {
    if (!d) { el.replaceChildren(); return; }
    const hw = d.hist_weeks.slice(-34), dem = d.demand.slice(-34), sl = d.sales.slice(-34);
    const weeks = hw.concat(d.test_weeks), n = weeks.length, nh = hw.length;
    const W = Math.max(320, el.clientWidth || 800), Ht = W < 560 ? 260 : 320, m = { t: 22, r: 14, b: 28, l: 46 };
    const max = Math.max(...dem, ...d.p90, ...d.actual, ...d.rule) * 1.05 || 1, step = niceStep(max, 4), top = Math.ceil(max / step) * step;
    const x = (i) => m.l + i / (n - 1) * (W - m.l - m.r), y = (v) => Ht - m.b - v / top * (Ht - m.t - m.b);
    const g = svgIn(el, W, Ht, 'Style demand history and test-week forecast');
    s('rect', { x: x(nh) - (x(1) - x(0)) / 2, y: m.t, width: W - m.r - x(nh) + (x(1) - x(0)) / 2, height: Ht - m.t - m.b, fill: 'rgba(184,150,46,.08)' }, g);
    s('text', { x: (x(nh) + W - m.r) / 2, y: m.t - 7, 'text-anchor': 'middle', 'font-size': 11.5, 'font-weight': 700, fill: C.muted }, g, 'Test weeks');
    for (let v = 0; v <= top + 1e-9; v += step) { s('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: C.line }, g); s('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: C.muted }, g, compact(v)); }
    const every = Math.max(1, Math.ceil(n / (W < 560 ? 5 : 10)));
    weeks.forEach((w, i) => { if (i % every === 0) s('text', { x: x(i), y: Ht - 8, 'text-anchor': 'middle', 'font-size': 11, fill: C.muted }, g, 'W' + (((w - 1) % 52) + 1)); });
    const line = (pts, col, wd, dash) => s('polyline', { points: pts.map(([i, v]) => `${x(i)},${y(v)}`).join(' '), fill: 'none', stroke: col, 'stroke-width': wd, 'stroke-dasharray': dash || '', 'stroke-linejoin': 'round' }, g);
    const band = d.p90.map((v, k) => [nh + k, v]).concat(d.p10.map((v, k) => [nh + k, v]).reverse());
    s('polygon', { points: band.map(([i, v]) => `${x(i)},${y(v)}`).join(' '), fill: 'rgba(184,150,46,.3)' }, g);
    line(sl.map((v, i) => [i, v]), C.line2, 1.6);
    line(dem.map((v, i) => [i, v]), C.ink, 1.8);
    line(d.rule.map((v, k) => [nh + k, v]), C.muted, 1.8, '5 4');
    line(d.forecast.map((v, k) => [nh + k, v]), C.cardinal, 2.6);
    d.actual.forEach((v, k) => s('circle', { cx: x(nh + k), cy: y(v), r: 3.5, fill: C.ink }, g));
    const t = tip(el), rule = s('line', { y1: m.t, y2: Ht - m.b, stroke: C.ink, 'stroke-opacity': 0, 'stroke-dasharray': '2 3' }, g);
    const hit = s('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: Ht - m.t - m.b, fill: 'transparent' }, g);
    hit.addEventListener('pointermove', (ev) => {
      const b = el.getBoundingClientRect(), px = (ev.clientX - b.left) * W / el.clientWidth;
      const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
      rule.setAttribute('x1', x(i)); rule.setAttribute('x2', x(i)); rule.setAttribute('stroke-opacity', 0.5);
      const L = i < nh ? [['Demand', int(dem[i])], ['Sales', int(sl[i])]] : [['Forecast', int(d.forecast[i - nh])], ['Range', int(d.p10[i - nh]) + ' – ' + int(d.p90[i - nh])], ['Planner rule', int(d.rule[i - nh])], ['Actual demand', int(d.actual[i - nh])]];
      t.show(x(i) * el.clientWidth / W, ev.clientY - b.top, 'Week ' + weeks[i] + ' (FY week ' + (((weeks[i] - 1) % 52) + 1) + ')', L);
    });
    hit.addEventListener('pointerleave', () => { rule.setAttribute('stroke-opacity', 0); t.hide(); });
  }
  function overridesCard(m) {
    const F = B.forecast, c = h('div', { class: 'card' }, m);
    h('h3', null, c, 'Planner overrides');
    h('p', { class: 'sub' }, c, 'Change a store forecast and give a reason. The feedback loop has learned how much to trust each reason; the final value blends the model and your override. Export the list to feed the next model run (12_overrides.py reads this exact format).');
    const ov = store.get('kwp.overrides', []);
    const sf = F.store_forecast[selStyle] || {};
    const storesList = Object.keys(sf).sort();
    const ctl = h('div', { class: 'ctl' }, c);
    const field = (lbl, el) => { const w = h('div', null, ctl); h('label', null, w, lbl); w.appendChild(el); return el; };
    const sSel = field('Store', h('select')); storesList.forEach((st) => h('option', { value: st }, sSel, st));
    const wSel = field('Week', h('select')); B.forecast.series[selStyle].test_weeks.forEach((w, i) => h('option', { value: String(i) }, wSel, 'Week ' + w));
    const mod = h('div', { class: 'muted', style: 'min-width:150px;align-self:center' }, ctl);
    const val = field('Your forecast', h('input', { type: 'number', min: '0', step: '1', style: 'width:110px' }));
    const rSel = field('Reason', h('select')); Object.keys(F.override_reasons).forEach((r) => h('option', { value: r, title: F.override_reasons[r] }, rSel, r));
    const add = h('button', { class: 'btn primary', type: 'button', style: 'align-self:flex-end' }, ctl, 'Add override');
    const upd = () => { const v = (sf[sSel.value] || [])[+wSel.value]; mod.textContent = 'Model: ' + (isFinite(v) ? v.toFixed(1) : '–'); val.placeholder = isFinite(v) ? v.toFixed(0) : ''; };
    sSel.addEventListener('change', upd); wSel.addEventListener('change', upd); upd();
    const msg = h('div', null, c);
    add.addEventListener('click', () => {
      msg.replaceChildren();
      const mv = (sf[sSel.value] || [])[+wSel.value], nv = parseFloat(val.value);
      if (!isFinite(nv) || nv < 0) { h('div', { class: 'err', role: 'alert' }, msg, 'Enter a forecast of 0 or more.'); return; }
      const wk = B.forecast.series[selStyle].test_weeks[+wSel.value];
      ov.push({ style_id: selStyle, store_id: sSel.value, week_index: wk, model_forecast: +mv.toFixed(2), override_value: nv, reason: rSel.value, planner: 'planner.app', timestamp: new Date().toISOString() });
      store.set('kwp.overrides', ov); val.value = ''; render();
    });
    const trust = F.override_learned_trust;
    if (!ov.length) { h('p', { class: 'muted' }, c, 'No overrides yet. Learned trust by reason: ' + Object.entries(trust).map(([k2, v]) => k2 + ' ' + Math.round(v * 100) + '%').join(' · ') + '.'); }
    else {
      table(c, [{ label: 'Style', key: 'style_id' }, { label: 'Store', key: 'store_id' }, { label: 'Week', key: 'week_index', num: true }, { label: 'Model', num: true, render: (r) => r.model_forecast.toFixed(1) },
        { label: 'Override', num: true, render: (r) => r.override_value.toFixed(1) }, { label: 'Reason', key: 'reason' }, { label: 'Trust', num: true, render: (r) => Math.round((trust[r.reason] ?? 0.5) * 100) + '%' },
        { label: 'Final', num: true, render: (r) => (r.model_forecast + (trust[r.reason] ?? 0.5) * (r.override_value - r.model_forecast)).toFixed(1) },
        { label: '', render: (r, td, i) => { const b = h('button', { class: 'btn', type: 'button' }, null, 'Remove'); b.addEventListener('click', () => { ov.splice(i, 1); store.set('kwp.overrides', ov); render(); }); return b; } }], ov);
      const row = h('div', { class: 'ctl', style: 'margin-top:10px' }, c);
      const ex = h('button', { class: 'btn primary', type: 'button' }, row, 'Export overrides (CSV)');
      ex.addEventListener('click', () => download('overrides.csv', [F.override_columns.join(',')].concat(ov.map((o) => F.override_columns.map((k2) => csvCell(o[k2])).join(','))).join('\n')));
    }
    const R = F.override_results;
    h('p', { class: 'note' }, c, `Last learning run: ${R.learning_overrides} overrides to learn from, ${R.evaluation_overrides} to test. Error on overridden forecasts: model alone ${pct(R.overall.model_only_wape)}, accepting every override ${pct(R.overall.accept_all_wape)}, learned trust ${pct(R.overall.learned_wape)}.`);
  }

  /* ---------------- sizes ---------------- */
  function sizes(m) {
    const S = B.sizes, A = B.allocation, V = S.variants;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Wrong-size units', pct(V.E_dynamic_plus_fit), was(pct(V.A_chain_flat), 'chain curve'));
    kpi(k, 'Stores re-clustered', String(S.stores_reassigned.length), 'customer mix changed: ' + S.stores_reassigned.map((x) => x.store_id).join(', '));
    kpi(k, 'Updating every 8 weeks', pct(S.update_cadence.every_8_weeks_mean), 'once a season ' + pct(S.update_cadence.once_a_season_mean));
    kpi(k, 'Allocation fill rate', pct(A.allocation_split.forecast_and_size_curves), was(pct(A.allocation_split.current_practice), 'same units'));
    kpi(k, 'Transfers at clearance', rand(A.transfers.net_benefit_rand), A.transfers.moves + ' moves, ' + int(A.transfers.units_moved) + ' units');
    const g = h('div', { class: 'grid2' }, m);
    const c1 = h('div', { class: 'card' }, g); h('h3', null, c1, 'Which size curve wastes least');
    h('p', { class: 'sub' }, c1, 'Same total units per style and store, split by each curve; share of units that end up in the wrong size (test weeks).');
    const names = { A_chain_flat: 'One chain curve (today)', B_master_cluster_season_start: 'Store clusters, set at season start', C_master_cluster_all_history: 'Store clusters, all history (v1)', D_dynamic_clusters: 'Re-clustered stores, recent weeks', E_dynamic_plus_fit: '+ fit-aware curves' };
    const ch1 = h('div', { class: 'chart' }, c1);
    const c2 = h('div', { class: 'card' }, g); h('h3', null, c2, 'Learned curves by store cluster');
    h('p', { class: 'sub' }, c2, 'Bars: share of demand by size for the cluster and category. Line: the single chain curve used today.');
    const cats = [...new Set(Object.keys(S.curves.cluster_category).map((x) => x.split('|')[1]))];
    const ctl = h('div', { class: 'ctl' }, c2); const w = h('div', null, ctl); h('label', { for: 'sz-cat' }, w, 'Category'); const cs = h('select', { id: 'sz-cat' }, w); cats.forEach((x) => h('option', { value: x }, cs, x));
    const mult = h('div', { style: 'display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))' }, c2);
    const drawCurves = () => {
      mult.replaceChildren();
      const keys = Object.keys(S.curves.cluster_category).filter((x) => x.endsWith('|' + cs.value));
      keys.forEach((key) => {
        const box = h('div', { class: 'chart' }, mult), v = S.curves.cluster_category[key], ch = S.curves.chain;
        const W = 220, Ht = 150, max = Math.max(...v, ...ch) * 1.15, bw = W / v.length, y = (u) => Ht - 22 - u / max * (Ht - 44);
        const g2 = svgIn(box, W, Ht, key);
        s('text', { x: 0, y: 13, 'font-size': 12.5, 'font-weight': 700, fill: C.ink }, g2, key.split('|')[0].replace(/^[A-Z]_/, '').replace(/_/g, ' '));
        v.forEach((u, i) => { s('rect', { x: i * bw + bw * 0.15, y: y(u), width: bw * 0.7, height: y(0) - y(u), rx: 2, fill: C.cardinal, opacity: 0.85 }, g2); s('line', { x1: i * bw + 2, x2: (i + 1) * bw - 2, y1: y(ch[i]), y2: y(ch[i]), stroke: C.ink, 'stroke-width': 2 }, g2); s('text', { x: i * bw + bw / 2, y: Ht - 6, 'text-anchor': 'middle', 'font-size': 10, fill: C.muted }, g2, S.curves.sizes[i]); });
      });
    };
    cs.addEventListener('change', drawCurves);
    const g3 = h('div', { class: 'grid2', style: 'margin-top:16px' }, m);
    const c3 = h('div', { class: 'card' }, g3); h('h3', null, c3, 'Stores whose customers changed');
    h('p', { class: 'sub' }, c3, 'Re-clustering on each store\'s recent size mix moves stores whose shoppers changed. The store master still lists the old cluster.');
    table(c3, [{ label: 'Store', key: 'store_id' }, { label: 'Store master says', render: (r) => r.master_cluster.replace(/^[A-Z]_/, '').replace(/_/g, ' ') }, { label: 'Size mix now says', render: (r) => r.current_cluster.replace(/^[A-Z]_/, '').replace(/_/g, ' ') }], S.stores_reassigned);
    h('p', { class: 'note' }, c3, 'Stores that truly changed (hidden truth, used only to check): ' + S.stores_that_truly_changed.join(', ') + '.');
    const c4 = h('div', { class: 'card' }, g3); h('h3', null, c4, 'How often to update curves');
    h('p', { class: 'sub' }, c4, 'Wrong-size share through FY2026 with curves set once at season start versus refreshed every 8 weeks from the last 26.');
    table(c4, [{ label: 'Weeks', key: 'weeks' }, { label: 'Once a season', num: true, render: (r) => pct(r.once_a_season) }, { label: 'Every 8 weeks', num: true, render: (r) => pct(r.every_8_weeks) }], S.update_cadence.blocks);
    requestAnimationFrame(() => {
      bars(ch1, Object.keys(names).filter((x) => x in V).map((x) => ({ label: names[x], value: V[x], color: x === S.best ? C.cardinal : C.line2 })), { fmt: (v) => pct(v), labelW: 230, label: 'wrong-size share by curve' });
      drawCurves();
    });
  }

  /* ---------------- markdown ---------------- */
  let selMd = null;
  function markdown(m) {
    const MD = B.markdown, MT = MD.metrics.matched_sell_through, P = MD.pack, SC = MD.scenarios;
    if (!selMd) selMd = P.styles[0].style_id;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Gross profit vs today', srand(MT.uplift_vs_actual.v2_quality_linked), 'at today\'s sell-through of ' + pct(MT.sell_through, 0));
    kpi(k, 'Today\'s clearance profit', rand(MT.actual_gross_profit), 'replayed on true demand');
    kpi(k, 'Two-step grid (v1)', srand(MT.uplift_vs_actual.v1_grid), 'same comparison');
    kpi(k, 'Quality lines: leftovers', int(MD.metrics.flagged_leftover_units.v2_quality_linked), was(int(MD.metrics.flagged_leftover_units.actual), 'units'));
    const c = h('div', { class: 'card' }, m);
    h('h3', null, c, 'Profit versus how much stock clears');
    h('p', { class: 'sub' }, c, 'Each line is an optimiser run at planning targets of 75–90% sell-through, replayed on true demand. Up and to the right is better; the black dot is today\'s plan.');
    const fch = h('div', { class: 'chart' }, c);
    const c2 = h('div', { class: 'card' }, m);
    h('h3', null, c2, 'Recommendation pack');
    h('p', { class: 'sub' }, c2, `Weekly discount path for each style (weeks ${P.weeks[0]}–${P.weeks[P.weeks.length - 1]}), expected cash with its P10–P90 range, today's plan, and constraint checks. Select a style to test scenarios.`);
    table(c2, [
      { label: 'Style', key: 'style_id' }, { label: 'Category', key: 'category' }, { label: 'Stock', num: true, render: (r) => int(r.stock_units) },
      { label: 'Recommended path (% off)', render: (r) => pathChips(r.recommended_path) }, { label: 'Today\'s path', render: (r) => pathChips(r.current_path) },
      { label: 'Expected cash', num: true, render: (r) => rand(r.expected_cash) }, { label: 'P10–P90', num: true, render: (r) => rand(r.cash_p10) + '–' + rand(r.cash_p90) },
      { label: 'vs today', num: true, render: (r) => srand(r.expected_cash - r.current_plan_cash) }, { label: 'Sell-through', num: true, render: (r) => pct(r.expected_sell_through, 0) },
      { label: 'Checks', render: (r) => { const sp = h('span'); const cn = r.constraints; [['Target', cn.sell_through_target_met], ['Never lowers', cn.never_decreases], ['≤60%', cn.max_depth_ok]].forEach(([n, ok]) => h('span', { class: 'chip ' + (ok ? 'good' : 'warn'), style: 'margin-right:3px' }, sp, n)); if (cn.quality_exit_early) h('span', { class: 'chip bad' }, sp, 'Quality exit'); return sp; } },
    ], P.styles, { onClick: (r) => { selMd = r.style_id; render(); setTimeout(() => $('scenario') && $('scenario').scrollIntoView({ behavior: 'smooth' }), 50); }, selected: (r) => r.style_id === selMd, maxHeight: '440px' });
    scenarioCard(m, SC, selMd);
    requestAnimationFrame(() => drawFrontier(fch, MD.metrics.frontier));
  }
  function drawFrontier(el, fr) {
    const W = Math.max(320, el.clientWidth || 700), Ht = 300, m = { t: 14, r: 20, b: 40, l: 60 };
    const meth = [['v1_grid', 'Two-step grid (v1)', C.line2], ['v2_multistep', 'Multi-step (v2)', C.gold], ['v2_quality_linked', 'Multi-step + quality (v2)', C.cardinal]];
    const pts = fr.flatMap((f) => meth.map(([k]) => f[k])).concat([fr[0].actual]);
    const xs = pts.map((p) => p.sell_through), ys = pts.map((p) => p.gross_profit);
    const x0 = Math.min(...xs) - 0.01, x1 = Math.max(...xs) + 0.01, ymax = Math.max(...ys) * 1.1, step = niceStep(ymax, 4), top = Math.ceil(ymax / step) * step;
    const x = (v) => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r), y = (v) => Ht - m.b - Math.max(0, v) / top * (Ht - m.t - m.b);
    const g = svgIn(el, W, Ht, 'Gross profit against sell-through for each optimiser');
    for (let v = 0; v <= top + 1e-9; v += step) { s('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: C.line }, g); s('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: C.muted }, g, rand(v)); }
    for (let v = Math.ceil(x0 * 50) / 50; v <= x1; v += 0.02) s('text', { x: x(v), y: Ht - m.b + 16, 'text-anchor': 'middle', 'font-size': 11, fill: C.muted }, g, pct(v, 0));
    s('text', { x: (m.l + W - m.r) / 2, y: Ht - 6, 'text-anchor': 'middle', 'font-size': 11.5, fill: C.muted }, g, 'Sell-through (realised)');
    meth.forEach(([k, name, col], i) => {
      const p = fr.map((f) => f[k]).sort((a, b) => a.sell_through - b.sell_through);
      s('polyline', { points: p.map((q) => `${x(q.sell_through)},${y(q.gross_profit)}`).join(' '), fill: 'none', stroke: col, 'stroke-width': 2.4 }, g);
      p.forEach((q) => s('circle', { cx: x(q.sell_through), cy: y(q.gross_profit), r: 3.5, fill: col }, g));
      const last = p[0];
      s('text', { x: x(last.sell_through) + 6, y: y(last.gross_profit) - 8 - i * 13, 'font-size': 11.5, 'font-weight': 700, fill: col === C.line2 ? C.muted : col }, g, name);
    });
    const a = fr[0].actual;
    s('circle', { cx: x(a.sell_through), cy: y(a.gross_profit), r: 6, fill: C.ink }, g);
    s('text', { x: x(a.sell_through) + 9, y: y(a.gross_profit) + 16, 'font-size': 12, 'font-weight': 700, fill: C.ink }, g, 'Today\'s plan');
  }
  function scenarioCard(m, SC, sid) {
    const D = SC.styles[sid], L = SC.levels, c = h('div', { class: 'card', id: 'scenario' }, m);
    h('h3', null, c, 'Scenario: ' + sid);
    h('p', { class: 'sub' }, c, 'Change the weekly discounts, the stock you hold or the size mix of demand; results update instantly. Chain-level approximation from the demand model\'s price response.');
    const st = { path: D.recommended.slice(), stock: 100, tilt: 0 };
    const grid = h('div', { class: 'sim-grid' }, c);
    const sels = D.recommended.map((lv, k) => { const w = h('div', null, grid); h('label', { for: 'sim-' + k }, w, 'Week ' + (k + 1)); const sl = h('select', { id: 'sim-' + k }, w); L.forEach((d, i) => h('option', { value: String(i) }, sl, Math.round(d * 100) + '% off')); sl.value = String(lv); sl.addEventListener('change', () => { st.path[k] = +sl.value; out(); }); return sl; });
    const ctl = h('div', { class: 'ctl' }, c);
    const sw = h('div', { style: 'min-width:220px' }, ctl); h('label', { for: 'sim-stock' }, sw, 'Stock held'); const sr = h('input', { type: 'range', id: 'sim-stock', min: '50', max: '150', value: '100', style: 'width:100%' }, sw); const so = h('div', { class: 'muted' }, sw);
    const tw = h('div', { style: 'min-width:220px' }, ctl); h('label', { for: 'sim-tilt' }, tw, 'Size mix of demand'); const tr = h('input', { type: 'range', id: 'sim-tilt', min: '-40', max: '40', value: '0', style: 'width:100%' }, tw); const to = h('div', { class: 'muted' }, tw);
    sr.addEventListener('input', () => { st.stock = +sr.value; out(); }); tr.addEventListener('input', () => { st.tilt = +tr.value; out(); });
    const b1 = h('button', { class: 'btn', type: 'button' }, ctl, 'Use recommended'); const b2 = h('button', { class: 'btn', type: 'button' }, ctl, 'Use today\'s path');
    b1.addEventListener('click', () => { st.path = D.recommended.slice(); sels.forEach((x, k) => { x.value = String(st.path[k]); }); out(); });
    b2.addEventListener('click', () => { st.path = D.current.slice(); sels.forEach((x, k) => { x.value = String(st.path[k]); }); out(); });
    const res = h('div', { class: 'cmp' }, c), chart = h('div', { class: 'chart', style: 'margin-top:10px' }, c);
    function simulate(path, stockPct, tilt) {
      const Z = D.stock_by_size.length;
      let sh = D.size_share.map((v, z) => v * Math.exp((tilt / 100) * (z / (Z - 1) * 2 - 1))); const t = sum(sh); sh = sh.map((v) => v / t);
      const stock = D.stock_by_size.map((v) => v * stockPct / 100); let rev = 0, sold = 0; const left = stock.slice();
      path.forEach((lv, k) => { const dem = D.demand[lv][k]; for (let z = 0; z < Z; z++) { const u = Math.min(dem * sh[z], left[z]); left[z] -= u; sold += u; rev += u * D.full_price * (1 - L[lv]); } });
      const salv = sum(left) * D.unit_cost * SC.salvage_ratio;
      return { cash: rev + salv, rev, sold, st: sold / Math.max(sum(stock), 1e-9), left, leftTotal: sum(left), gp: rev - sold * D.unit_cost };
    }
    function out() {
      so.textContent = st.stock + '% of current stock (' + int(sum(D.stock_by_size) * st.stock / 100) + ' units)';
      to.textContent = st.tilt === 0 ? 'As forecast' : st.tilt < 0 ? 'Younger sizes ' + -st.tilt + '% stronger' : 'Older sizes ' + st.tilt + '% stronger';
      const a = simulate(st.path, st.stock, st.tilt), r = simulate(D.recommended, st.stock, st.tilt), cu = simulate(D.current, st.stock, st.tilt);
      res.replaceChildren();
      kpi(res, 'Cash recovered', rand(a.cash), 'recommended ' + rand(r.cash) + ' · today ' + rand(cu.cash));
      kpi(res, 'Gross profit', rand(a.gp), 'recommended ' + rand(r.gp) + ' · today ' + rand(cu.gp));
      kpi(res, 'Sell-through', pct(a.st, 0), 'recommended ' + pct(r.st, 0) + ' · today ' + pct(cu.st, 0));
      kpi(res, 'Leftover units', int(a.leftTotal), 'recommended ' + int(r.leftTotal) + ' · today ' + int(cu.leftTotal));
      const W = Math.max(300, chart.clientWidth || 600), Ht = 150, Z = a.left.length, bw = (W - 40) / Z, mx = Math.max(...D.stock_by_size.map((v) => v * st.stock / 100), 1);
      const g = svgIn(chart, W, Ht, 'Leftover units by size');
      s('text', { x: 0, y: 12, 'font-size': 12, 'font-weight': 700, fill: C.ink }, g, 'Stock (outline) and leftover (filled) by size');
      a.left.forEach((v, z) => { const sv = D.stock_by_size[z] * st.stock / 100, y = (u) => Ht - 22 - u / mx * (Ht - 44); s('rect', { x: 40 + z * bw + bw * 0.15, y: y(sv), width: bw * 0.7, height: y(0) - y(sv), fill: 'none', stroke: C.line2 }, g); s('rect', { x: 40 + z * bw + bw * 0.15, y: y(v), width: bw * 0.7, height: y(0) - y(v), fill: C.cardinal, opacity: 0.8 }, g); s('text', { x: 40 + z * bw + bw / 2, y: Ht - 6, 'text-anchor': 'middle', 'font-size': 11, fill: C.muted }, g, SC.sizes[z]); s('text', { x: 40 + z * bw + bw / 2, y: y(v) - 4, 'text-anchor': 'middle', 'font-size': 10.5, fill: C.ink }, g, int(v)); });
    }
    requestAnimationFrame(out);
  }

  /* ---------------- quality ---------------- */
  let qFilter = 'all';
  function quality(m) {
    const Q = B.quality, L = Q.metrics.continuous_learning;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Defective lines found', pct(Q.metrics.recall_at_n, 0), 'return rate alone: ' + pct(Q.metrics.baseline_return_rate_only_recall_at_n, 0));
    kpi(k, 'Top 10 precision', pct(Q.metrics.precision_at_10, 0), 'confirmed defects in the top 10');
    kpi(k, 'Quality-driven returns', rand(Q.metrics.fy2026_quality_return_value_rand), 'FY2026, at full price');
    kpi(k, 'Model refresh', '+' + L.refresh_gain_pts.toFixed(1) + ' pts', 'F1 after retraining on this season\'s comments');
    const c = h('div', { class: 'card' }, m);
    h('h3', null, c, 'Lines losing money to quality');
    h('p', { class: 'sub' }, c, 'Ranked by return rate × share of returns about fit, fabric or durability. Themes are the phrases customers use most for that line.');
    const ctl = h('div', { class: 'ctl' }, c);
    ['all', 'fit', 'fabric', 'durability'].forEach((f) => { const b = h('button', { class: 'btn' + (qFilter === f ? ' primary' : ''), type: 'button' }, ctl, f === 'all' ? 'All issues' : f[0].toUpperCase() + f.slice(1)); b.addEventListener('click', () => { qFilter = f; render(); }); });
    const rows = Q.dashboard.filter((r) => r.top_issue !== 'none' && (qFilter === 'all' || r.top_issue === qFilter)).slice(0, 25);
    const max = Math.max(...rows.map((r) => r.quality_return_value_rand), 1);
    table(c, [{ label: 'Rank', key: 'rank', num: true }, { label: 'Style', key: 'style_id' }, { label: 'Category', key: 'category' }, { label: 'Supplier', key: 'supplier' },
      { label: 'Return rate', num: true, render: (r) => pct(r.return_rate) }, { label: 'Quality share', num: true, render: (r) => pct(r.quality_share, 0) },
      { label: 'Issue', render: (r) => h('span', { class: 'chip ' + r.top_issue }, null, r.top_issue) }, { label: 'What customers say', render: (r) => (r.themes || []).join('; ') },
      { label: 'Quality returns', num: true, render: (r) => { const f = document.createDocumentFragment(); h('span', { class: 'bar' }, f).style.width = Math.max(2, r.quality_return_value_rand / max * 60) + 'px'; f.append(rand(r.quality_return_value_rand)); return f; } },
      { label: 'Suggested action', render: (r) => h('span', { style: 'display:inline-block;min-width:240px;font-size:12.5px' }, null, r.suggested_action) },
      { label: 'Confirmed', render: (r) => h('span', { class: r.confirmed_defect === 'Yes' ? 'ok' : 'no' }, null, r.confirmed_defect) }], rows, { maxHeight: '520px' });
    h('p', { class: 'note' }, c, '"Confirmed" checks the ranking against the hidden truth of the sample data; it would not exist on real data.');
    const c2 = h('div', { class: 'card' }, m);
    h('h3', null, c2, 'Continuous learning from returns');
    h('p', { class: 'sub' }, c2, 'Customers started describing problems in new words this season. A model frozen on last season misses them; the automatically refreshed model catches up.');
    const ch = h('div', { class: 'chart' }, c2);
    requestAnimationFrame(() => bars(ch, [{ label: 'Frozen: all comments', value: L.frozen.test_macro_f1, color: C.line2 }, { label: 'Refreshed: all comments', value: L.refreshed.test_macro_f1, color: C.cardinal },
      { label: 'Frozen: new phrasing', value: L.frozen.test_macro_f1_new_phrasing, color: C.line2 }, { label: 'Refreshed: new phrasing', value: L.refreshed.test_macro_f1_new_phrasing, color: C.cardinal }], { max: 1, fmt: (v) => 'F1 ' + v.toFixed(2), labelW: 200, label: 'text model accuracy' }));
  }

  /* ---------------- trial ---------------- */
  function trial(m) {
    const T = B.trial, P = T.prereg, R = T.results;
    const sig = R.permutation_p_one_sided < 0.05 && R.ci95_rand[0] > 0;
    const bn = h('div', { class: 'banner ' + (sig ? 'ok' : 'warn') }, m);
    h('strong', null, bn, R.decision);
    bn.append(`Simulated ${R.simulated_season}: treatment stores made ${srand(R.effect_per_store_rand)} gross profit per store (${spct(R.effect_pct_of_control)}), 95% CI ${rand(R.ci95_rand[0])} to ${rand(R.ci95_rand[1])}, p = ${R.permutation_p_one_sided}. Treatment won ${R.pairs_treatment_won} of ${R.pairs} pairs.`);
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Minimum detectable effect', pct(P.power.minimum_detectable_effect_pct, 0), rand(P.power.minimum_detectable_effect_rand_per_store) + ' per store, 80% power');
    kpi(k, 'Expected effect', rand(P.power.expected_effect_rand_per_store), 'per store, from the markdown replay');
    kpi(k, 'Pairs needed', String(P.power.pairs_needed_for_expected_effect), 'to detect the expected effect; trial has ' + P.power.pairs);
    kpi(k, 'Prediction calibration', R.closed_loop.calibration_ratio.toFixed(2), 'realised ÷ predicted cash (treatment)');
    const g = h('div', { class: 'grid2' }, m);
    const c1 = h('div', { class: 'card' }, g); h('h3', null, c1, 'Pre-registration');
    h('p', { class: 'sub' }, c1, 'Fixed before any outcome existed; its hash is in the audit trail: ' + P.registration_hash + '.');
    const ul = h('ul', { class: 'list' }, c1);
    [['Primary metric', P.primary_metric], ['Hypothesis', P.hypothesis], ['Treatment', P.treatment], ['Control', P.control], ['Analysis', P.analysis], ['Stop rules', P.stop_rules.join('; ')], ['Power', P.power.note]].forEach(([a, b]) => { const li = h('li', null, ul); h('b', null, li, a + ': '); li.append(b); });
    const c2 = h('div', { class: 'card' }, g); h('h3', null, c2, 'Effect per store');
    h('p', { class: 'sub' }, c2, 'Paired difference and difference-in-differences against last season, with 95% bootstrap intervals. The dashed line is the minimum detectable effect.');
    const ch = h('div', { class: 'chart' }, c2);
    const c3 = h('div', { class: 'card' }, m); h('h3', null, c3, 'Matched pairs and outcomes');
    const st = {}; T.stores.forEach((x) => { st[x.store_id] = x; });
    table(c3, [{ label: 'Pair', render: (r, td, i) => String(i + 1) }, { label: 'Treatment store', render: (r) => (r.a_arm === 'treatment' ? r.a : r.b) }, { label: 'Control store', render: (r) => (r.a_arm === 'control' ? r.a : r.b) },
      { label: 'Treatment GP', num: true, render: (r) => rand(st[r.a_arm === 'treatment' ? r.a : r.b].gross_profit) }, { label: 'Control GP', num: true, render: (r) => rand(st[r.a_arm === 'control' ? r.a : r.b].gross_profit) },
      { label: 'Difference', num: true, render: (r) => srand(st[r.a_arm === 'treatment' ? r.a : r.b].gross_profit - st[r.a_arm === 'control' ? r.a : r.b].gross_profit) }], P.pairs);
    requestAnimationFrame(() => {
      const W = Math.max(300, ch.clientWidth || 500), Ht = 170, m2 = { l: 170, r: 20 };
      const rows = [['Paired difference', R.effect_per_store_rand, R.ci95_rand], ['Difference-in-differences', R.did_effect_rand, R.did_ci95_rand]];
      const lo = Math.min(0, ...rows.map((r) => r[2][0])) * 1.1, hi = Math.max(P.power.minimum_detectable_effect_rand_per_store, ...rows.map((r) => r[2][1])) * 1.1;
      const x = (v) => m2.l + (v - lo) / (hi - lo) * (W - m2.l - m2.r), g2 = svgIn(ch, W, Ht, 'trial effect with confidence intervals');
      s('line', { x1: x(0), x2: x(0), y1: 10, y2: Ht - 30, stroke: C.ink }, g2); s('text', { x: x(0), y: Ht - 14, 'text-anchor': 'middle', 'font-size': 11, fill: C.muted }, g2, 'R0');
      const mde = P.power.minimum_detectable_effect_rand_per_store;
      s('line', { x1: x(mde), x2: x(mde), y1: 10, y2: Ht - 30, stroke: C.gold, 'stroke-dasharray': '4 3', 'stroke-width': 1.5 }, g2); s('text', { x: x(mde), y: Ht - 14, 'text-anchor': 'middle', 'font-size': 11, fill: C.gold_d || C.muted }, g2, 'MDE ' + rand(mde));
      rows.forEach(([n, v, ci], i) => { const y = 40 + i * 50; s('text', { x: m2.l - 10, y: y + 4, 'text-anchor': 'end', 'font-size': 12.5, fill: C.ink }, g2, n); s('line', { x1: x(ci[0]), x2: x(ci[1]), y1: y, y2: y, stroke: C.cardinal, 'stroke-width': 2.5 }, g2); s('circle', { cx: x(v), cy: y, r: 6, fill: C.cardinal }, g2); s('text', { x: x(v), y: y - 11, 'text-anchor': 'middle', 'font-size': 11.5, 'font-weight': 700, fill: C.ink }, g2, srand(v)); });
    });
  }

  /* ---------------- operations ---------------- */
  async function sha256(text) { const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)); return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, '0')).join(''); }
  function ops(m) {
    const O = B.operations, G = O.governance, Mo = G.monitoring;
    const k = h('div', { class: 'kpis' }, m);
    kpi(k, 'Data contracts', O.validation.passed ? 'Passed' : 'Failed', O.validation.errors + ' errors · self-test caught ' + O.validation.self_test.defects_caught.length + '/' + O.validation.self_test.defects_injected.length, O.validation.passed ? '' : '');
    kpi(k, 'Test error', pct(Mo.test_wape), 'bias ' + spct(Mo.bias));
    kpi(k, 'Range coverage', pct(Mo.p10_p90_coverage, 0), 'share of actuals inside P10–P90');
    kpi(k, 'Inputs drifting', String(Mo.drift_shifted.length), Mo.drift_shifted.join(', ') || 'none');
    kpi(k, 'Retraining', O.retrain_policy.policy, 'chosen from a week-by-week replay');
    kpi(k, 'Audit trail', G.audit_chain.ok ? 'Intact' : 'Broken', G.audit_chain.entries + ' entries · tamper test ' + (G.tamper_test.detected ? 'caught' : 'missed'));
    const g = h('div', { class: 'grid2' }, m);
    const c1 = h('div', { class: 'card' }, g); h('h3', null, c1, 'Input drift');
    h('p', { class: 'sub' }, c1, O.drift.rule);
    const fs = O.drift.features.filter((f) => !f.calendar).slice(0, 14);
    table(c1, [{ label: 'Input', key: 'feature' }, { label: 'PSI vs same weeks last year', num: true, render: (r) => r.psi_same_weeks_last_year.toFixed(3) },
      { label: 'Status', render: (r) => { const v = r.psi_same_weeks_last_year; return h('span', { class: 'chip ' + (v > 0.25 ? 'bad' : v > 0.1 ? 'warn' : 'good') }, null, v > 0.25 ? 'Shifted' : v > 0.1 ? 'Watch' : 'Stable'); } }], fs);
    const c2 = h('div', { class: 'card' }, g); h('h3', null, c2, 'How often to retrain');
    h('p', { class: 'sub' }, c2, 'FY2026 replayed week by week; each policy forecasts the next four weeks. Chosen: ' + O.retrain_policy.policy + ' (lowest error with a small cost per retrain). Triggers: error 15% worse than at training, or input PSI above 0.25.');
    const rch = h('div', { class: 'chart' }, c2);
    const g2 = h('div', { class: 'grid2', style: 'margin-top:16px' }, m);
    const c3 = h('div', { class: 'card' }, g2); h('h3', null, c3, 'Lineage of the current forecast');
    h('p', { class: 'sub' }, c3, 'Every published number traces back to the exact data, features and model that produced it.');
    const fl = h('div', { class: 'flow' }, c3), L = G.lineage;
    [['Data version', L.data_version], ['Features', L.feature_version], ['Model', L.model_version], ['Markdown pack', L.markdown_pack_version]].forEach(([a, b], i) => { if (i) h('span', { class: 'arr' }, fl, '→'); const n = h('div', { class: 'node' }, fl); h('b', null, n, a); h('code', null, n, b || '–'); });
    h('p', { class: 'note' }, c3, 'Model run ' + L.model_run + ', trained on ' + L.training_window + '.');
    table(c3, [{ label: 'Registered run', key: 'run_id' }, { label: 'Kind', key: 'kind' }, { label: 'When (UTC)', key: 'ts' }], G.registry.slice(-8).reverse(), { maxHeight: '260px' });
    const c4 = h('div', { class: 'card' }, g2); h('h3', null, c4, 'Audit trail');
    h('p', { class: 'sub' }, c4, 'Append-only and hash-chained: each entry includes the hash of the one before. Verify it here, in your browser.');
    const vb = h('button', { class: 'btn primary', type: 'button' }, c4, 'Verify the chain'); const vr = h('span', { class: 'muted', style: 'margin-left:10px' }, c4);
    vb.addEventListener('click', async () => {
      vr.textContent = 'Checking…';
      try {
        let prev = null, okc = 0;
        for (const line of O.audit_lines) {
          const e = JSON.parse(line), body = line.replace('"hash":"' + e.hash + '",', '');
          if ((prev !== null && e.prev !== prev) || (await sha256(body)) !== e.hash) { vr.textContent = 'Broken at entry ' + (okc + 1); vr.className = 'no'; return; }
          prev = e.hash; okc++;
        }
        vr.textContent = okc + ' entries verified, chain intact.'; vr.className = 'ok';
      } catch (err) { vr.textContent = 'Verification needs a secure page (https).'; }
    });
    const ev = O.audit_lines.slice(-14).reverse().map((l) => JSON.parse(l));
    table(c4, [{ label: 'When (UTC)', render: (r) => r.ts.replace('T', ' ').replace('Z', '') }, { label: 'Event', key: 'event' }, { label: 'Hash', render: (r) => h('span', { class: 'audit' }, null, r.hash.slice(0, 12) + '…') }], ev, { maxHeight: '300px' });
    const g3 = h('div', { class: 'grid2', style: 'margin-top:16px' }, m);
    const c5 = h('div', { class: 'card' }, g3); h('h3', null, c5, 'Data contracts and adapters');
    h('p', { class: 'sub' }, c5, 'Every extract is checked for types, ranges, empty values, unknown stores or styles, duplicates and rules such as "sales never exceed stock". The pipeline stops on any error.');
    table(c5, [{ label: 'Table', key: 't' }, { label: 'Rows', num: true, render: (r) => int(r.rows) }, { label: 'Findings', num: true, key: 'findings' }], Object.entries(O.validation_tables).map(([t, v]) => ({ t, rows: v.rows, findings: v.findings })));
    h('p', { class: 'note' }, c5, `Adapters: POS (${int(O.adapters.source_rows.pos_daily)} daily lines), inventory, ERP items and prices rebuilt ${int(O.adapters.rebuilt_rows)} weekly rows; exact match: ${O.adapters.passed ? 'yes' : 'no'}. Column mappings live in config/source_mappings.json.`);
    const c6 = h('div', { class: 'card' }, g3); h('h3', null, c6, 'Learned trust in planner overrides');
    h('p', { class: 'sub' }, c6, 'Share of a planner\'s change the model keeps, learned per reason from past overrides against actual sales.');
    const och = h('div', { class: 'chart' }, c6);
    requestAnimationFrame(() => {
      bars(rch, O.retrain.policies.map((p) => ({ label: p.policy + ' (' + p.retrains + ' fits)', value: p.wape, color: p.policy === O.retrain_policy.policy ? C.cardinal : C.line2 })), { fmt: (v) => pct(v), labelW: 170, label: 'error by retraining policy' });
      bars(och, Object.entries(B.forecast.override_learned_trust).map(([k2, v]) => ({ label: k2, value: v, color: v >= 0.3 ? C.cardinal : C.line2 })), { max: 1, fmt: (v) => Math.round(v * 100) + '%', labelW: 190, label: 'learned trust by reason' });
    });
  }

  /* ---------------- departments ---------------- */
  function depts(m) {
    const c = h('div', { class: 'card' }, m);
    h('h2', null, c, 'One pipeline, many departments');
    h('p', { class: 'sub' }, c, 'Sizes, size curves, categories, seasonality and price ranges come from a department config, so the same code runs Kidswear and Babywear. Run any step with DEPT=<name>.');
    table(c, [{ label: 'Department', key: 'department' }, { label: 'Sizes', render: (r) => r.sizes.join(' · ') }, { label: 'Styles', num: true, key: 'styles' },
      { label: 'Forecast error', num: true, render: (r) => pct(r.model_wape) }, { label: 'Planner rule', num: true, render: (r) => pct(r.planner_rule_wape) },
      { label: 'Range coverage', num: true, render: (r) => pct(r.coverage, 0) }, { label: 'Demand estimate error (EM vs v1)', num: true, render: (r) => pct(r.unconstraining_wape_em) + ' vs ' + pct(r.unconstraining_wape_v1) },
      { label: 'Wrong-size units (best vs chain)', num: true, render: (r) => pct(r.wrong_size_best) + ' vs ' + pct(r.wrong_size_chain) }, { label: 'Stores re-clustered', render: (r) => (r.stores_reassigned || []).join(', ') || '–' }], B.departments);
    B.departments.forEach((d) => { const p = h('p', { class: 'note' }, c); h('b', null, p, d.department + ': '); p.append(Object.entries(d.categories).map(([k, v]) => k + ' (' + v + ')').join(', ')); });
  }

  /* ---------------- bundle load / download ---------------- */
  $('load-bundle').addEventListener('change', (e) => {
    const f = e.target.files[0]; if (!f) return;
    const rd = new FileReader();
    rd.onload = () => { try { const nb = JSON.parse(rd.result); if (!nb.meta || !nb.roadmap || !nb.forecast) throw new Error('x'); B = nb; selStyle = selMd = null; renderTabs(); render(); } catch (err) { alert('That file is not a planner results bundle.'); } };
    rd.readAsText(f);
  });
  $('dl-bundle').addEventListener('click', () => download('planner_bundle.json', JSON.stringify(B), 'application/json'));
  const hash = (location.hash || '').slice(1); if (TABS.some(([id]) => id === hash)) current = hash;
  renderTabs(); render();
  let lw = window.innerWidth, timer;
  window.addEventListener('resize', () => { if (window.innerWidth === lw) return; lw = window.innerWidth; clearTimeout(timer); timer = setTimeout(render, 200); });
})();
