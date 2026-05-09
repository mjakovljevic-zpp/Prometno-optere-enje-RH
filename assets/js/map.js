/* Karta opterecenja - frontend logika */
(function () {
  'use strict';

  const DATA = {
    sections: 'data/sections.geojson',
    counters: 'data/counters.geojson',
    summary:  'data/summary.json',
  };

  const COLOR_STOPS = [
    { max: 1000,  color: getCss('--t1', '#fde7e7') },
    { max: 3000,  color: getCss('--t2', '#fad0c4') },
    { max: 6000,  color: getCss('--t3', '#ffb199') },
    { max: 10000, color: getCss('--t4', '#ff8a65') },
    { max: 15000, color: getCss('--t5', '#ef6c00') },
    { max: 22000, color: getCss('--t6', '#c8102e') },
    { max: Infinity, color: getCss('--t7', '#8b0000') },
  ];
  const SPEED_STOPS = [
    { max: 40, color: '#1a3a8e' },
    { max: 60, color: '#2c7da0' },
    { max: 80, color: '#5dbb63' },
    { max: 100, color: '#f9a825' },
    { max: 120, color: '#ef6c00' },
    { max: Infinity, color: '#c8102e' },
  ];

  function getCss(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function colorForTraffic(v) {
    if (v == null || isNaN(v)) return '#cccccc';
    for (const s of COLOR_STOPS) if (v <= s.max) return s.color;
    return COLOR_STOPS.at(-1).color;
  }
  function colorForSpeed(v) {
    if (v == null || isNaN(v)) return '#cccccc';
    for (const s of SPEED_STOPS) if (v <= s.max) return s.color;
    return SPEED_STOPS.at(-1).color;
  }
  function colorFor(v) {
    return state.metric === 'v_avg' ? colorForSpeed(v) : colorForTraffic(v);
  }
  function widthFor(v) {
    if (v == null || isNaN(v)) return 1.2;
    if (state.metric === 'v_avg') return 3.5;
    if (v <= 1000) return 1.5;
    if (v <= 3000) return 2.5;
    if (v <= 6000) return 3.5;
    if (v <= 10000) return 4.5;
    if (v <= 15000) return 5.8;
    if (v <= 22000) return 7;
    return 8.5;
  }
  const fmt = (x) => (x == null || isNaN(x)) ? '–' : Number(x).toLocaleString('hr-HR');
  const fmtFloat = (x, d=1) => (x == null || isNaN(x)) ? '–' :
    Number(x).toLocaleString('hr-HR', { minimumFractionDigits: d, maximumFractionDigits: d });

  const DEFAULT_CATS = ['autocesta', 'državna cesta', 'županijska cesta', 'lokalna cesta'];
  const DEFAULT_CONFS = ['high', 'medium', 'low'];

  const state = {
    summary: null,
    sections: null,
    counters: null,
    metric: 'pgdp',
    year: null,
    cats: new Set(DEFAULT_CATS),
    confs: new Set(DEFAULT_CONFS),
    pgdpRange: [null, null],
    pldpRange: [null, null],
    roadFilter: '',
    showCounters: false,
    onlyIssues: false,
    showLabels: false,
  };

  const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([45.1, 16.0], 7);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap',
  }).addTo(map);

  let sectionsLayer = null;
  let countersLayer = null;
  let labelsLayer = null;

  function metricVal(props) {
    let v = props[`${state.metric}_${state.year}`];
    if (state.metric === 'v_avg' && v == null) {
      for (const y of [2023, 2022, 2021]) {
        if (props[`v_avg_${y}`] != null) { v = props[`v_avg_${y}`]; break; }
      }
    }
    return v;
  }

  function styleFor(feat) {
    const v = metricVal(feat.properties || {});
    return { color: colorFor(v), weight: widthFor(v), opacity: 0.9 };
  }

  function passesFilters(props) {
    const v = metricVal(props);
    const conf = props[`conf_${state.year}`];
    if (v == null) return false;
    const cat = props.kategorija_full;
    if (cat && !state.cats.has(cat)) return false;
    if (conf && !state.confs.has(conf)) return false;
    const pg = props[`pgdp_${state.year}`];
    if (state.pgdpRange[0] != null && (pg == null || pg < state.pgdpRange[0])) return false;
    if (state.pgdpRange[1] != null && (pg == null || pg > state.pgdpRange[1])) return false;
    const pl = props[`pldp_${state.year}`];
    if (state.pldpRange[0] != null && (pl == null || pl < state.pldpRange[0])) return false;
    if (state.pldpRange[1] != null && (pl == null || pl > state.pldpRange[1])) return false;
    if (state.roadFilter) {
      const r = state.roadFilter.toLowerCase();
      if (!(props.oznaka_ceste || '').toLowerCase().includes(r)) return false;
    }
    if (state.onlyIssues && conf !== 'low') return false;
    return true;
  }

  function buildPopup(feat) {
    const p = feat.properties || {};
    const years = state.summary.years || [];
    let trendRows = years.map(y => {
      const pg = p[`pgdp_${y}`], pl = p[`pldp_${y}`];
      const pgo = p[`pgdp_other_${y}`], plo = p[`pldp_other_${y}`];
      const sm = p[`smjer_${y}`], smo = p[`smjer_other_${y}`];
      const v = p[`v_avg_${y}`];
      const c = p[`conf_${y}`];
      const cls = c ? `conf-${c}` : 'conf-none';
      const pgVal = pgo != null
        ? `${fmt(pg)} <small style="color:#666">(${sm||'-'})</small><br>${fmt(pgo)} <small style="color:#666">(${smo||'-'})</small>`
        : fmt(pg);
      const plVal = plo != null
        ? `${fmt(pl)} <small style="color:#666">(${sm||'-'})</small><br>${fmt(plo)} <small style="color:#666">(${smo||'-'})</small>`
        : fmt(pl);
      return `<tr><td>${y}</td><td class="num">${pgVal}</td><td class="num">${plVal}</td><td class="num">${fmt(v)}</td><td><span class="confidence-pill ${cls}">${c||'–'}</span></td></tr>`;
    }).join('');
    const len = p.seg_length_m ? (p.seg_length_m / 1000).toFixed(2) + ' km' : '–';
    const od = p[`od_${state.year}`] || p[`od_${years.at(-1)}`];
    const dod = p[`do_${state.year}`] || p[`do_${years.at(-1)}`];
    const cnt = p[`cnt_${state.year}`] || p[`cnt_${years.at(-1)}`];
    const conf = p[`conf_${state.year}`];
    return `
      <div class="popup-trend">
        <h4>${p.oznaka_ceste || '–'} <small style="color:var(--muted)">(${p.kategorija_full || ''})</small></h4>
        <div class="meta">
          <strong>Duljina segmenta:</strong> ${len}<br>
          <strong>Od → Do:</strong> ${od||'?'} → ${dod||'?'}<br>
          <strong>Brojač:</strong> ${cnt||'–'} ${conf?`<span class="confidence-pill conf-${conf}">${conf}</span>`:''}<br>
          ${p.opis_ceste ? `<span title="${p.opis_ceste}">${p.opis_ceste.length > 80 ? p.opis_ceste.slice(0,80)+'…' : p.opis_ceste}</span>` : ''}
        </div>
        <table>
          <thead><tr><th>God.</th><th class="num">PGDP</th><th class="num">PLDP</th><th class="num">v̄ (km/h)</th><th>Pouzd.</th></tr></thead>
          <tbody>${trendRows}</tbody>
        </table>
        <canvas></canvas>
      </div>`;
  }

  function attachChart(popupEl, feat) {
    const canvas = popupEl.querySelector('canvas');
    if (!canvas || !window.Chart) return;
    const p = feat.properties || {};
    const years = state.summary.years || [];
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: years,
        datasets: [
          { label: 'PGDP', data: years.map(y => p[`pgdp_${y}`] ?? null),
            borderColor: '#c8102e', backgroundColor: 'rgba(200,16,46,0.1)', tension: 0.25 },
          { label: 'PLDP', data: years.map(y => p[`pldp_${y}`] ?? null),
            borderColor: '#1f3864', backgroundColor: 'rgba(31,56,100,0.1)', tension: 0.25 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
        scales: { y: { beginAtZero: true, ticks: { font: { size: 10 } } }, x: { ticks: { font: { size: 10 } } } },
      },
    });
  }

  function renderSections() {
    if (sectionsLayer) { map.removeLayer(sectionsLayer); sectionsLayer = null; }
    if (!state.sections) return;
    const filtered = {
      type: 'FeatureCollection',
      features: state.sections.features.filter(f => passesFilters(f.properties || {})),
    };
    renderLabels();
    sectionsLayer = L.geoJSON(filtered, {
      style: styleFor,
      onEachFeature: (feat, layer) => {
        const p = feat.properties || {};
        const v = metricVal(p);
        const lbl = state.metric === 'v_avg' ? 'v̄ km/h' : state.metric.toUpperCase();
        const sm = p[`smjer_${state.year}`];
        const smInfo = sm ? `<br><small>smjer: ${sm}</small>` : '';
        layer.bindTooltip(`<strong>${p.oznaka_ceste||''}</strong><br>${lbl} ${state.year}: <strong>${fmt(v)}</strong>${smInfo}`, { sticky: true });
        layer.bindPopup(() => buildPopup(feat), { maxWidth: 340 });
        layer.on('popupopen', (e) => attachChart(e.popup.getElement(), feat));
      },
    }).addTo(map);
    updateDashboard(filtered);
  }

  // Pomocna: vrati centroid LineString-a
  function lineCenter(geom) {
    if (!geom) return null;
    let coords = geom.coordinates;
    if (geom.type === 'MultiLineString') {
      // uzmi najduzi LineString u Multi
      let best = coords[0];
      let bestLen = 0;
      for (const ls of coords) {
        let l = 0;
        for (let i = 1; i < ls.length; i++) {
          const dx = ls[i][0] - ls[i-1][0], dy = ls[i][1] - ls[i-1][1];
          l += Math.sqrt(dx*dx + dy*dy);
        }
        if (l > bestLen) { bestLen = l; best = ls; }
      }
      coords = best;
    }
    if (!coords || coords.length === 0) return null;
    // Sredina po duljini
    let total = 0;
    const segs = [];
    for (let i = 1; i < coords.length; i++) {
      const dx = coords[i][0] - coords[i-1][0], dy = coords[i][1] - coords[i-1][1];
      const l = Math.sqrt(dx*dx + dy*dy);
      segs.push(l);
      total += l;
    }
    let target = total / 2;
    let acc = 0;
    for (let i = 0; i < segs.length; i++) {
      if (acc + segs[i] >= target) {
        const t = (target - acc) / segs[i];
        return [
          coords[i][1] + t * (coords[i+1][1] - coords[i][1]), // lat
          coords[i][0] + t * (coords[i+1][0] - coords[i][0]), // lon
        ];
      }
      acc += segs[i];
    }
    return [coords[0][1], coords[0][0]];
  }

  function renderLabels() {
    if (labelsLayer) { map.removeLayer(labelsLayer); labelsLayer = null; }
    if (!state.showLabels || !state.sections) return;

    const zoom = map.getZoom();
    if (zoom < 9) return;  // ispod ovog zooma ne crtamo nista (previse linija)
    const minVal = zoom < 10 ? 12000 : (zoom < 12 ? 5000 : 0);

    const filtered = state.sections.features.filter(f => {
      if (!passesFilters(f.properties || {})) return false;
      const v = metricVal(f.properties);
      if (v == null || v < minVal) return false;
      return true;
    });

    // Za jako gusto, decimacija: na zoom 9-10 max 200 labela
    const maxLabels = zoom < 10 ? 150 : (zoom < 12 ? 400 : 1500);
    const sample = filtered
      .map(f => ({ f, v: metricVal(f.properties) }))
      .sort((a, b) => b.v - a.v)
      .slice(0, maxLabels);

    const big = zoom >= 12 ? 'zoom-large' : '';
    const layers = [];
    for (const { f, v } of sample) {
      const c = lineCenter(f.geometry);
      if (!c) continue;
      const txt = state.metric === 'v_avg' ? fmt(v) + ' km/h' : fmt(v);
      const icon = L.divIcon({
        className: '',
        html: `<div class="section-label metric-${state.metric} ${big}">${txt}</div>`,
        iconSize: null,
      });
      layers.push(L.marker(c, { icon, interactive: false }));
    }
    labelsLayer = L.layerGroup(layers).addTo(map);
  }

  function renderCounters() {
    if (countersLayer) { map.removeLayer(countersLayer); countersLayer = null; }
    if (!state.showCounters || !state.counters) return;
    countersLayer = L.geoJSON(state.counters, {
      pointToLayer: (f, ll) => L.circleMarker(ll, {
        radius: 4, color: '#1f3864', fillColor: '#1f3864', fillOpacity: 0.7, weight: 1,
      }),
      onEachFeature: (feat, layer) => {
        const p = feat.properties || {};
        layer.bindTooltip(`<strong>Brojač ${p.counter_id}</strong> ${p.naziv||''}<br>${p.oznaka_ceste||''} (${p.category||''})<br>${p.match_method||''} · ${fmtFloat(p.dist_m,0)} m`);
      },
    }).addTo(map);
  }

  function updateDashboard(filtered) {
    const features = filtered.features || [];
    const dash = document.getElementById('dashboard');
    const cnts = document.getElementById('cat-counts');
    const yr = state.year;
    let totalLen=0, sumPg=0, sumPl=0, sumV=0;
    let nPg=0, nPl=0, nV=0;
    let maxPg=-Infinity, maxPl=-Infinity, maxV=-Infinity;
    const cats = {}, confs = {};
    for (const f of features) {
      const p = f.properties || {};
      if (p.seg_length_m) totalLen += p.seg_length_m;
      const pg = p[`pgdp_${yr}`], pl = p[`pldp_${yr}`];
      const v = p[`v_avg_${yr}`] ?? p[`v_avg_2023`] ?? p[`v_avg_2022`] ?? p[`v_avg_2021`];
      if (pg != null) { sumPg += pg; nPg++; if (pg > maxPg) maxPg = pg; }
      if (pl != null) { sumPl += pl; nPl++; if (pl > maxPl) maxPl = pl; }
      if (v != null) { sumV += v; nV++; if (v > maxV) maxV = v; }
      cats[p.kategorija_full || '?'] = (cats[p.kategorija_full || '?'] || 0) + 1;
      const c = p[`conf_${yr}`]; if (c) confs[c] = (confs[c] || 0) + 1;
    }
    const tile = (label, value, sub) => `<div class="kpi compact"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>${sub?`<div class="kpi-sub">${sub}</div>`:''}</div>`;
    dash.innerHTML = [
      tile('Dionica', fmt(features.length), `Godina ${yr}`),
      tile('Duljina', `${fmtFloat(totalLen/1000, 0)} km`, 'Prikazane'),
      tile('Prosj. PGDP', nPg?fmt(Math.round(sumPg/nPg)):'–', `${nPg} dionica`),
      tile('Prosj. PLDP', nPl?fmt(Math.round(sumPl/nPl)):'–', `${nPl} dionica`),
      tile('Max PGDP', maxPg>-Infinity?fmt(maxPg):'–'),
      tile('Max PLDP', maxPl>-Infinity?fmt(maxPl):'–'),
      tile('Prosj. brzina', nV?fmt(Math.round(sumV/nV))+' km/h':'–', `${nV} dionica`),
      tile('Max brzina', maxV>-Infinity?fmt(maxV)+' km/h':'–'),
    ].join('');
    const item = (k, v) => `<div><strong>${v}</strong> <span style="color:var(--muted)">${k}</span></div>`;
    const confLab = (k) => ({ high: 'Visoka', medium: 'Srednja', low: 'Niska' }[k] || k);
    const rows = [];
    for (const [k, v] of Object.entries(cats)) rows.push(item(k, v));
    for (const [k, v] of Object.entries(confs)) rows.push(item(`Pouzd. ${confLab(k)}`, v));
    cnts.innerHTML = rows.join('') || '<em>Nema podataka</em>';
    document.getElementById('counts-line').textContent = `Prikazano ${fmt(features.length)} dionica`;
  }

  function setupYearSelect() {
    const sel = document.getElementById('f-year');
    sel.innerHTML = '';
    const years = state.summary.years || [];
    years.forEach((y) => {
      const opt = document.createElement('option'); opt.value = String(y); opt.textContent = String(y);
      sel.appendChild(opt);
    });
    state.year = years.at(-1);
    sel.value = String(state.year);
    sel.addEventListener('change', () => { state.year = parseInt(sel.value, 10); renderSections(); });
  }
  function setupMetricToggle() {
    const wrap = document.getElementById('metric-toggle');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      wrap.querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
      state.metric = b.dataset.metric;
      renderSections();
    });
  }
  function setupCatSelect() {
    const sel = document.getElementById('f-cat');
    sel.addEventListener('change', () => {
      state.cats = new Set(Array.from(sel.selectedOptions).map(o => o.value));
      renderSections();
    });
  }
  function setupRanges() {
    ['pgdp', 'pldp'].forEach(m => {
      ['min', 'max'].forEach(k => {
        const el = document.getElementById(`f-${m}-${k}`);
        el.addEventListener('input', () => {
          const idx = k === 'min' ? 0 : 1;
          const v = el.value === '' ? null : Number(el.value);
          state[`${m}Range`][idx] = isNaN(v) ? null : v;
          renderSections();
        });
      });
    });
  }
  function setupRoadFilter() {
    const el = document.getElementById('f-road');
    el.addEventListener('input', () => { state.roadFilter = el.value.trim(); renderSections(); });
  }
  function setupConfChecks() {
    document.querySelectorAll('input[type="checkbox"][data-conf]').forEach(cb => {
      cb.addEventListener('change', () => {
        state.confs = new Set(
          Array.from(document.querySelectorAll('input[type="checkbox"][data-conf]'))
            .filter(x => x.checked).map(x => x.dataset.conf)
        );
        renderSections();
      });
    });
  }
  function setupOtherChecks() {
    document.getElementById('f-show-counters').addEventListener('change', e => {
      state.showCounters = e.target.checked; renderCounters();
    });
    document.getElementById('f-only-issues').addEventListener('change', e => {
      state.onlyIssues = e.target.checked; renderSections();
    });
    document.getElementById('f-show-labels').addEventListener('change', e => {
      state.showLabels = e.target.checked; renderLabels();
    });
    map.on('zoomend moveend', () => {
      if (state.showLabels) renderLabels();
    });
  }
  function setupReset() {
    document.getElementById('btn-reset').addEventListener('click', () => {
      ['f-pgdp-min', 'f-pgdp-max', 'f-pldp-min', 'f-pldp-max', 'f-road'].forEach(id => {
        document.getElementById(id).value = '';
      });
      document.getElementById('f-show-counters').checked = false;
      document.getElementById('f-only-issues').checked = false;
      const lblCb = document.getElementById('f-show-labels');
      if (lblCb) lblCb.checked = false;
      Array.from(document.getElementById('f-cat').options).forEach(o => o.selected = true);
      document.querySelectorAll('input[type="checkbox"][data-conf]').forEach(cb => cb.checked = true);
      state.cats = new Set(DEFAULT_CATS);
      state.confs = new Set(DEFAULT_CONFS);
      state.pgdpRange = [null, null];
      state.pldpRange = [null, null];
      state.roadFilter = '';
      state.showCounters = false;
      state.onlyIssues = false;
      state.showLabels = false;
      if (labelsLayer) { map.removeLayer(labelsLayer); labelsLayer = null; }
      renderSections(); renderCounters();
    });
  }
  function setupMapButtons() {
    document.getElementById('btn-fit').addEventListener('click', () => {
      if (sectionsLayer) {
        const b = sectionsLayer.getBounds();
        if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });
      }
    });
    document.getElementById('btn-fullscreen').addEventListener('click', () => {
      const card = document.querySelector('.map-card');
      if (!document.fullscreenElement) card.requestFullscreen?.();
      else document.exitFullscreen?.();
      setTimeout(() => map.invalidateSize(), 200);
    });
    document.getElementById('btn-export-xlsx').addEventListener('click', exportXlsx);
    document.getElementById('btn-export-geojson').addEventListener('click', exportGeoJSON);
    document.getElementById('btn-export-csv').addEventListener('click', exportCSV);
  }

  function getFilteredFeatures() {
    if (!state.sections) return [];
    return state.sections.features.filter(f => passesFilters(f.properties || {}));
  }

  function flatRow(props) {
    const years = state.summary.years || [];
    const row = {
      seg_id: props.seg_id,
      oznaka_ceste: props.oznaka_ceste,
      kategorija: props.kategorija_full,
      duljina_km: props.seg_length_m ? +(props.seg_length_m / 1000).toFixed(3) : null,
      opis_ceste: props.opis_ceste,
    };
    for (const y of years) {
      row['pgdp_' + y] = props['pgdp_' + y] != null ? props['pgdp_' + y] : null;
      row['pldp_' + y] = props['pldp_' + y] != null ? props['pldp_' + y] : null;
      row['smjer_' + y] = props['smjer_' + y] != null ? props['smjer_' + y] : null;
      row['pgdp_drugi_smjer_' + y] = props['pgdp_other_' + y] != null ? props['pgdp_other_' + y] : null;
      row['pldp_drugi_smjer_' + y] = props['pldp_other_' + y] != null ? props['pldp_other_' + y] : null;
      row['brojac_' + y] = props['cnt_' + y] != null ? props['cnt_' + y] : null;
      row['pouzdanost_' + y] = props['conf_' + y] != null ? props['conf_' + y] : null;
      if (props['v_avg_' + y] != null) row['brzina_avg_' + y] = props['v_avg_' + y];
      if (props['v_max_' + y] != null) row['brzina_max_dop_' + y] = props['v_max_' + y];
    }
    return row;
  }

  function downloadBlob(data, filename, mime) {
    const blob = new Blob([data], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
  }

  function exportXlsx() {
    const feats = getFilteredFeatures();
    if (!feats.length) { alert('Nema dionica za export.'); return; }
    if (!window.XLSX) { alert('XLSX biblioteka jos nije ucitana, pricekaj sekundu.'); return; }
    const rows = feats.map(f => flatRow(f.properties));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Dionice');
    const ts = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, 'karta-opterecenja-' + ts + '.xlsx');
  }

  function exportGeoJSON() {
    const feats = getFilteredFeatures();
    if (!feats.length) { alert('Nema dionica za export.'); return; }
    const fc = { type: 'FeatureCollection', features: feats };
    const ts = new Date().toISOString().slice(0, 10);
    downloadBlob(JSON.stringify(fc), 'karta-opterecenja-' + ts + '.geojson', 'application/geo+json');
  }

  function exportCSV() {
    const feats = getFilteredFeatures();
    if (!feats.length) { alert('Nema dionica za export.'); return; }
    const rows = feats.map(f => flatRow(f.properties));
    const colSet = new Set();
    rows.forEach(r => Object.keys(r).forEach(k => colSet.add(k)));
    const cols = Array.from(colSet);
    const esc = (v) => v == null ? '' : (/[",\n;]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
    const header = cols.join(',');
    const lines = rows.map(r => cols.map(c => esc(r[c])).join(','));
    const csv = '﻿' + header + '\n' + lines.join('\n');
    const ts = new Date().toISOString().slice(0, 10);
    downloadBlob(csv, 'karta-opterecenja-' + ts + '.csv', 'text/csv;charset=utf-8');
  }

  async function init() {
    document.getElementById('gen-date').textContent = new Date().toLocaleDateString('hr-HR');
    const [s, sec, cnt] = await Promise.all([
      fetch(DATA.summary).then(r => r.json()),
      fetch(DATA.sections).then(r => r.json()),
      fetch(DATA.counters).then(r => r.json()).catch(() => ({ type: 'FeatureCollection', features: [] })),
    ]);
    state.summary = s; state.sections = sec; state.counters = cnt;
    setupYearSelect(); setupMetricToggle(); setupCatSelect();
    setupRanges(); setupRoadFilter(); setupConfChecks();
    setupOtherChecks(); setupReset(); setupMapButtons();
    renderSections();
    if (sectionsLayer) {
      const b = sectionsLayer.getBounds();
      if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init().catch(e => {
      console.error(e);
      document.getElementById('counts-line').textContent = 'Greska pri ucitavanju podataka.';
    }));
  } else {
    init().catch(e => console.error(e));
  }
})();
