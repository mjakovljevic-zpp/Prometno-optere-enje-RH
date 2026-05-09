/* Karta opterecenja - frontend logika
 * Ucitava sections.geojson, counters.geojson i summary.json,
 * crta linijsku kartu sa stilom temeljenim na PGDP/PLDP vrijednostima.
 */
(function () {
  'use strict';

  const DATA = {
    sections: 'data/sections.geojson',
    counters: 'data/counters.geojson',
    summary:  'data/summary.json',
  };

  // Boja po vrijednosti — stupnjevana paleta (slijedi CSS varijable iz style.css)
  const COLOR_STOPS = [
    { max: 1000,  color: getCss('--t1', '#fde7e7') },
    { max: 3000,  color: getCss('--t2', '#fad0c4') },
    { max: 6000,  color: getCss('--t3', '#ffb199') },
    { max: 10000, color: getCss('--t4', '#ff8a65') },
    { max: 15000, color: getCss('--t5', '#ef6c00') },
    { max: 22000, color: getCss('--t6', '#c8102e') },
    { max: Infinity, color: getCss('--t7', '#8b0000') },
  ];

  function getCss(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function colorFor(val) {
    if (val == null || isNaN(val)) return '#cccccc';
    for (const s of COLOR_STOPS) if (val <= s.max) return s.color;
    return COLOR_STOPS[COLOR_STOPS.length - 1].color;
  }

  function widthFor(val) {
    if (val == null || isNaN(val)) return 1.2;
    if (val <= 1000) return 1.5;
    if (val <= 3000) return 2.5;
    if (val <= 6000) return 3.5;
    if (val <= 10000) return 4.5;
    if (val <= 15000) return 5.8;
    if (val <= 22000) return 7;
    return 8.5;
  }

  const fmt = (x) => {
    if (x == null || isNaN(x)) return '–';
    return Number(x).toLocaleString('hr-HR');
  };
  const fmtFloat = (x, d = 1) => {
    if (x == null || isNaN(x)) return '–';
    return Number(x).toLocaleString('hr-HR', { minimumFractionDigits: d, maximumFractionDigits: d });
  };

  const state = {
    summary: null,
    sections: null,    // GeoJSON FeatureCollection
    counters: null,
    metric: 'pgdp',
    year: null,
    cats: new Set(['autocesta', 'državna cesta', 'županijska cesta', 'lokalna cesta']),
    confs: new Set(['high', 'medium', 'low']),
    pgdpRange: [null, null],
    pldpRange: [null, null],
    roadFilter: '',
    showCounters: false,
    onlyIssues: false,
  };

  // -------- Map setup --------------------------------------------------------
  const map = L.map('map', {
    zoomControl: true,
    preferCanvas: true,
  }).setView([45.1, 16.0], 7);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(map);

  let sectionsLayer = null;
  let countersLayer = null;

  function styleFor(feat) {
    const props = feat.properties || {};
    const val = props[`${state.metric}_${state.year}`];
    return {
      color: colorFor(val),
      weight: widthFor(val),
      opacity: 0.9,
    };
  }

  function passesFilters(props) {
    const val = props[`${state.metric}_${state.year}`];
    const conf = props[`conf_${state.year}`];

    if (val == null) return false;

    // Kategorija
    const cat = props.kategorija_full;
    if (cat && !state.cats.has(cat)) return false;

    // Pouzdanost
    if (conf && !state.confs.has(conf)) return false;

    // Raspon PGDP
    const pgdpVal = props[`pgdp_${state.year}`];
    if (state.pgdpRange[0] != null && (pgdpVal == null || pgdpVal < state.pgdpRange[0])) return false;
    if (state.pgdpRange[1] != null && (pgdpVal == null || pgdpVal > state.pgdpRange[1])) return false;

    // Raspon PLDP
    const pldpVal = props[`pldp_${state.year}`];
    if (state.pldpRange[0] != null && (pldpVal == null || pldpVal < state.pldpRange[0])) return false;
    if (state.pldpRange[1] != null && (pldpVal == null || pldpVal > state.pldpRange[1])) return false;

    // Oznaka ceste
    if (state.roadFilter) {
      const r = state.roadFilter.toLowerCase();
      const oz = (props.oznaka_ceste || '').toLowerCase();
      if (!oz.includes(r)) return false;
    }

    // Samo problematične (low confidence)
    if (state.onlyIssues && conf !== 'low') return false;

    return true;
  }

  function buildPopup(feat) {
    const p = feat.properties || {};
    const years = state.summary.years || [];
    let trendRows = years.map(y => {
      const pg = p[`pgdp_${y}`];
      const pl = p[`pldp_${y}`];
      const c = p[`conf_${y}`];
      const cls = c ? `conf-${c}` : 'conf-none';
      return `<tr>
        <td>${y}</td>
        <td class="num">${fmt(pg)}</td>
        <td class="num">${fmt(pl)}</td>
        <td><span class="confidence-pill ${cls}">${c || '–'}</span></td>
      </tr>`;
    }).join('');

    const len = p.seg_length_m ? (p.seg_length_m / 1000).toFixed(2) + ' km' : '–';
    const od = p[`od_${state.year}`] || p[`od_${years[years.length - 1]}`];
    const dod = p[`do_${state.year}`] || p[`do_${years[years.length - 1]}`];
    const cnt = p[`cnt_${state.year}`] || p[`cnt_${years[years.length - 1]}`];
    const conf = p[`conf_${state.year}`];

    const html = `
      <div class="popup-trend">
        <h4>${p.oznaka_ceste || '–'} <small style="color:var(--muted)">(${p.kategorija_full || ''})</small></h4>
        <div class="meta">
          <strong>Duljina segmenta:</strong> ${len}<br>
          <strong>Od → Do:</strong> ${od || '?'} → ${dod || '?'}<br>
          <strong>Brojač:</strong> ${cnt || '–'}
          ${conf ? `<span class="confidence-pill conf-${conf}">${conf}</span>` : ''}<br>
          ${p.opis_ceste ? `<span title="${p.opis_ceste}">${p.opis_ceste.length > 70 ? p.opis_ceste.substr(0, 70) + '…' : p.opis_ceste}</span>` : ''}
        </div>
        <table>
          <thead><tr><th>God.</th><th class="num">PGDP</th><th class="num">PLDP</th><th>Pouzd.</th></tr></thead>
          <tbody>${trendRows}</tbody>
        </table>
        <canvas></canvas>
      </div>`;
    return html;
  }

  function attachChart(popupEl, feat) {
    const canvas = popupEl.querySelector('canvas');
    if (!canvas || !window.Chart) return;
    const p = feat.properties || {};
    const years = state.summary.years || [];
    const pgdp = years.map(y => p[`pgdp_${y}`] ?? null);
    const pldp = years.map(y => p[`pldp_${y}`] ?? null);
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: years,
        datasets: [
          { label: 'PGDP', data: pgdp, borderColor: '#c8102e', backgroundColor: 'rgba(200,16,46,0.1)', tension: 0.25 },
          { label: 'PLDP', data: pldp, borderColor: '#1f3864', backgroundColor: 'rgba(31,56,100,0.1)', tension: 0.25 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
        scales: { y: { beginAtZero: true, ticks: { font: { size: 10 } } }, x: { ticks: { font: { size: 10 } } } },
      },
    });
  }

  function renderSections() {
    if (sectionsLayer) {
      map.removeLayer(sectionsLayer);
      sectionsLayer = null;
    }
    if (!state.sections) return;

    const filtered = {
      type: 'FeatureCollection',
      features: state.sections.features.filter(f => passesFilters(f.properties || {})),
    };

    sectionsLayer = L.geoJSON(filtered, {
      style: styleFor,
      onEachFeature: (feat, layer) => {
        const tooltip = (() => {
          const p = feat.properties || {};
          const v = p[`${state.metric}_${state.year}`];
          return `<strong>${p.oznaka_ceste || ''}</strong>
            <br>${state.metric.toUpperCase()} ${state.year}: <strong>${fmt(v)}</strong>`;
        })();
        layer.bindTooltip(tooltip, { sticky: true });
        layer.bindPopup(() => buildPopup(feat), { maxWidth: 320 });
        layer.on('popupopen', (e) => {
          const popup = e.popup.getElement();
          attachChart(popup, feat);
        });
      },
    }).addTo(map);

    updateDashboard(filtered);
  }

  function renderCounters() {
    if (countersLayer) {
      map.removeLayer(countersLayer);
      countersLayer = null;
    }
    if (!state.showCounters || !state.counters) return;

    countersLayer = L.geoJSON(state.counters, {
      pointToLayer: (feat, latlng) => L.circleMarker(latlng, {
        radius: 4, color: '#1f3864', fillColor: '#1f3864', fillOpacity: 0.7, weight: 1,
      }),
      onEachFeature: (feat, layer) => {
        const p = feat.properties || {};
        layer.bindTooltip(`<strong>Brojač ${p.counter_id}</strong> ${p.naziv || ''}<br>
          ${p.oznaka_ceste || ''} (${p.category || ''})<br>
          ${p.match_method || ''} · ${fmtFloat(p.dist_m, 0)} m`);
      },
    }).addTo(map);
  }

  function updateDashboard(filtered) {
    const features = filtered.features || [];
    const dash = document.getElementById('dashboard');
    const cnts = document.getElementById('cat-counts');
    const yr = state.year;

    const valKey = `${state.metric}_${yr}`;
    const pgdpKey = `pgdp_${yr}`;
    const pldpKey = `pldp_${yr}`;

    let totalLen = 0, sumPgdp = 0, sumPldp = 0, nPgdp = 0, nPldp = 0;
    let maxPgdp = -Infinity, maxPldp = -Infinity;
    const cats = {};
    const confs = {};

    for (const f of features) {
      const p = f.properties || {};
      if (p.seg_length_m) totalLen += p.seg_length_m;
      if (p[pgdpKey] != null) { sumPgdp += p[pgdpKey]; nPgdp++; if (p[pgdpKey] > maxPgdp) maxPgdp = p[pgdpKey]; }
      if (p[pldpKey] != null) { sumPldp += p[pldpKey]; nPldp++; if (p[pldpKey] > maxPldp) maxPldp = p[pldpKey]; }
      cats[p.kategorija_full || '?'] = (cats[p.kategorija_full || '?'] || 0) + 1;
      const c = p[`conf_${yr}`];
      if (c) confs[c] = (confs[c] || 0) + 1;
    }

    const tile = (label, value, sub) => `
      <div class="kpi compact">
        <div class="kpi-label">${label}</div>
        <div class="kpi-value">${value}</div>
        ${sub ? `<div class="kpi-sub">${sub}</div>` : ''}
      </div>`;

    dash.innerHTML = [
      tile('Dionica', fmt(features.length), `Godina ${yr}`),
      tile('Duljina', `${fmtFloat(totalLen / 1000, 0)} km`, 'Prikazane dionice'),
      tile('Prosj. PGDP', nPgdp ? fmt(Math.round(sumPgdp / nPgdp)) : '–', `${nPgdp} dionica`),
      tile('Prosj. PLDP', nPldp ? fmt(Math.round(sumPldp / nPldp)) : '–', `${nPldp} dionica`),
      tile('Max PGDP', maxPgdp > -Infinity ? fmt(maxPgdp) : '–'),
      tile('Max PLDP', maxPldp > -Infinity ? fmt(maxPldp) : '–'),
    ].join('');

    const catItem = (k, v) => `<div><strong>${v}</strong> <span style="color:var(--muted)">${k}</span></div>`;
    const confLabel = (k) => ({ high: 'Visoka', medium: 'Srednja', low: 'Niska' }[k] || k);
    const allRows = [];
    for (const [k, v] of Object.entries(cats)) allRows.push(catItem(k, v));
    for (const [k, v] of Object.entries(confs)) allRows.push(catItem(`Pouzd. ${confLabel(k)}`, v));
    cnts.innerHTML = allRows.join('') || '<em>Nema podataka</em>';

    document.getElementById('counts-line').textContent =
      `Prikazano ${fmt(features.length)} dionica`;
  }

  // -------- UI listeners -----------------------------------------------------

  function setupYearSelect() {
    const sel = document.getElementById('f-year');
    sel.innerHTML = '';
    const years = state.summary.years || [];
    years.forEach((y) => {
      const opt = document.createElement('option');
      opt.value = String(y);
      opt.textContent = String(y);
      sel.appendChild(opt);
    });
    state.year = years[years.length - 1];
    sel.value = String(state.year);
    sel.addEventListener('change', () => {
      state.year = parseInt(sel.value, 10);
      renderSections();
    });
  }

  function setupMetricToggle() {
    const wrap = document.getElementById('metric-toggle');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      wrap.querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
      state.metric = b.dataset.metric;
      renderSections();
    });
  }

  function setupCatSelect() {
    const sel = document.getElementById('f-cat');
    sel.addEventListener('change', () => {
      state.cats = new Set(Array.from(sel.selectedOptions).map((o) => o.value));
      renderSections();
    });
  }

  function setupRanges() {
    ['pgdp', 'pldp'].forEach((m) => {
      ['min', 'max'].forEach((k) => {
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
    el.addEventListener('input', () => {
      state.roadFilter = el.value.trim();
      renderSections();
    });
  }

  function setupConfChecks() {
    document.querySelectorAll('input[type="checkbox"][data-conf]').forEach((cb) => {
      cb.addEventListener('change', () => {
        state.confs = new Set(
          Array.from(document.querySelectorAll('input[type="checkbox"][data-conf]'))
            .filter((x) => x.checked).map((x) => x.dataset.conf)
        );
        renderSections();
      });
    });
  }

  function setupOtherChecks() {
    document.getElementById('f-show-counters').addEventListener('change', (e) => {
      state.showCounters = e.target.checked;
      renderCounters();
    });
    document.getElementById('f-only-issues').addEventListener('change', (e) => {
      state.onlyIssues = e.target.checked;
      renderSections();
    });
  }

  function setupReset() {
    document.getElementById('btn-reset').addEventListener('click', () => {
      document.getElementById('f-pgdp-min').value = '';
      document.getElementById('f-pgdp-max').value = '';
      document.getElementById('f-pldp-min').value = '';
      document.getElementById('f-pldp-max').value = '';
      document.getElementById('f-road').value = '';
      document.getElementById('f-show-counters').checked = false;
      document.getElementById('f-only-issues').checked = false;
      const sel = document.getElementById('f-cat');
      Array.from(sel.options).forEach((o) => (o.selected = true));
      document.querySelectorAll('input[type="checkbox"][data-conf]').forEach((cb) => (cb.checked = true));
      state.cats = new Set(['autocesta', 'državna cesta', 'županijska cesta', 'lokalna cesta']);
      state.confs = new Set(['high', 'medium', 'low']);
      state.pgdpRange = [null, null];
      state.pldpRange = [null, null];
      state.roadFilter = '';
      state.showCounters = false;
      state.onlyIssues = false;
      renderSections();
      renderCounters();
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
      if (!document.fullscreenElement) {
        card.requestFullscreen?.();
      } else {
        document.exitFullscreen?.();
      }
      setTimeout(() => map.invalidateSize(), 200);
    });
  }

  // -------- Init -------------------------------------------------------------

  async function init() {
    document.getElementById('gen-date').textContent = new Date().toLocaleDateString('hr-HR');

    const [s, sec, cnt] = await Promise.all([
      fetch(DATA.summary).then((r) => r.json()),
      fetch(DATA.sections).then((r) => r.json()),
      fetch(DATA.counters).then((r) => r.json()).catch(() => ({ type: 'FeatureCollection', features: [] })),
    ]);
    state.summary = s;
    state.sections = sec;
    state.counters = cnt;

    setupYearSelect();
    setupMetricToggle();
    setupCatSelect();
    setupRanges();
    setupRoadFilter();
    setupConfChecks();
    setupOtherChecks();
    setupReset();
    setupMapButtons();

    renderSections();
    if (sectionsLayer) {
      const b = sectionsLayer.getBounds();
      if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init().catch(err => {
      console.error(err);
      document.getElementById('counts-line').textContent = 'Greška pri učitavanju podataka.';
    }));
  } else {
    init().catch(err => console.error(err));
  }
})();
