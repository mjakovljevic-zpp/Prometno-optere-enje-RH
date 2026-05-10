/* Karta nesreca — frontend logika */
(function () {
  'use strict';

  const POSLJ_COLOR = { P: '#c8102e', T: '#ef6c00', L: '#f9a825', M: '#6b7280' };
  const POSLJ_LABEL = { P: 'Smrtna', T: 'Teško ozlijeđeni', L: 'Lakše ozlijeđeni', M: 'Materijalna šteta' };
  const RT_LABEL = { high: 'Visoka', medium: 'Srednja', low: 'Niska', estimate_range: 'Raspon (procjena)', none: 'Bez podataka' };

  const state = {
    year: 2024,
    posljedice: new Set(['P', 'T', 'L', 'M']),
    kategorije: new Set(['autocesta', 'državna cesta', 'županijska cesta', 'lokalna cesta', '']),
    razine: new Set(['high', 'medium', 'low', 'estimate_range', 'none']),
    pgdp_min: null, pgdp_max: null,
    cestaText: '',
    data: null, // current FC
    cache: {},  // year -> FC
  };

  const fmt = (x) => (x == null || x === '' || isNaN(x)) ? '–' : Number(x).toLocaleString('hr-HR');
  const safeStr = (s) => s == null ? '' : String(s);

  const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([45.1, 16.0], 7);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap',
  }).addTo(map);

  let cluster = L.markerClusterGroup({
    chunkedLoading: true,
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    maxClusterRadius: 60,
  });
  map.addLayer(cluster);

  function popupHtml(p) {
    const c = POSLJ_COLOR[p.p] || '#444';
    const lbl = POSLJ_LABEL[p.p] || p.p || '–';
    const pgdp = p.pgdp ? fmt(p.pgdp) : '–';
    const pldp = p.pldp ? fmt(p.pldp) : '–';
    const rt = RT_LABEL[p.rt] || p.rt || '–';
    const rtCls = p.rt ? `conf-${p.rt === 'estimate_range' ? 'medium' : (p.rt === 'none' ? 'none' : p.rt)}` : 'conf-none';
    return `
      <div class="popup-trend" style="width:280px">
        <h4 style="color:${c}">● ${lbl}</h4>
        <div class="meta">
          <strong>Datum:</strong> ${safeStr(p.d)}<br>
          ${p.v ? `<strong>Vrsta:</strong> ${safeStr(p.v)}<br>` : ''}
          ${p.mjesto ? `<strong>Mjesto:</strong> ${safeStr(p.mjesto)}<br>` : ''}
          ${p.ulica ? `<strong>Ulica:</strong> ${safeStr(p.ulica)}<br>` : ''}
          ${p.c ? `<strong>Cesta (MUP):</strong> ${safeStr(p.c)}<br>` : ''}
          ${p.oz ? `<strong>Oznaka (mreža):</strong> ${safeStr(p.oz)} (${safeStr(p.kat)})<br>` : ''}
          ${p.n ? `<strong>U/van naselja:</strong> ${safeStr(p.n)}<br>` : ''}
        </div>
        <table style="width:100%;font-size:0.85rem;border-collapse:collapse">
          <tr><td><strong>PGDP:</strong></td><td class="num">${pgdp}</td></tr>
          <tr><td><strong>PLDP:</strong></td><td class="num">${pldp}</td></tr>
          <tr><td><strong>Pouzdanost:</strong></td><td><span class="confidence-pill ${rtCls}">${rt}</span></td></tr>
          ${p.br ? `<tr><td><strong>Brojač:</strong></td><td>${safeStr(p.br)}</td></tr>` : ''}
        </table>
      </div>`;
  }

  function passes(p) {
    if (!state.posljedice.has(p.p || 'M')) return false;
    if (!state.kategorije.has(p.kat || '')) return false;
    if (!state.razine.has(p.rt || 'none')) return false;
    const pg = p.pgdp != null ? +p.pgdp : null;
    if (state.pgdp_min != null) {
      if (pg == null || pg < state.pgdp_min) return false;
    }
    if (state.pgdp_max != null) {
      if (pg == null || pg > state.pgdp_max) return false;
    }
    if (state.cestaText) {
      const t = state.cestaText.toLowerCase();
      const hay = (p.oz || p.c || '').toLowerCase();
      if (!hay.includes(t)) return false;
    }
    return true;
  }

  function render() {
    cluster.clearLayers();
    if (!state.data) return;
    const markers = [];
    let n = 0;
    let stats = { P: 0, T: 0, L: 0, M: 0 };
    let rtStats = { high: 0, medium: 0, low: 0, estimate_range: 0, none: 0 };
    let totalPg = 0, nPg = 0;
    let totalPl = 0, nPl = 0;

    for (const f of state.data.features) {
      const p = f.properties || {};
      if (!passes(p)) continue;
      n++;
      const pp = p.p || 'M';
      stats[pp] = (stats[pp] || 0) + 1;
      const rt = p.rt || 'none';
      rtStats[rt] = (rtStats[rt] || 0) + 1;
      if (p.pgdp != null && !isNaN(+p.pgdp)) { totalPg += +p.pgdp; nPg++; }
      if (p.pldp != null && !isNaN(+p.pldp)) { totalPl += +p.pldp; nPl++; }

      const c = POSLJ_COLOR[pp] || '#444';
      const r = pp === 'P' ? 7 : (pp === 'T' ? 6 : (pp === 'L' ? 5 : 4));
      const m = L.circleMarker(
        [f.geometry.coordinates[1], f.geometry.coordinates[0]],
        { radius: r, color: c, fillColor: c, fillOpacity: 0.7, weight: 1 },
      );
      m.bindPopup(() => popupHtml(p));
      markers.push(m);
    }
    cluster.addLayers(markers);

    document.getElementById('counts-line').textContent =
      `Prikazano ${fmt(n)} nesreća`;
    updateDashboard(n, stats, rtStats, totalPg, nPg, totalPl, nPl);
  }

  function tile(label, value, sub) {
    return `<div class="kpi compact"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>${sub?`<div class="kpi-sub">${sub}</div>`:''}</div>`;
  }

  function updateDashboard(n, stats, rtStats, totalPg, nPg, totalPl, nPl) {
    const d = document.getElementById('dashboard');
    const avgPg = nPg ? Math.round(totalPg / nPg) : null;
    const avgPl = nPl ? Math.round(totalPl / nPl) : null;
    d.innerHTML = [
      tile('Nesreća', fmt(n), `Godina ${state.year}`),
      tile('Smrtne', fmt(stats.P || 0)),
      tile('Teško', fmt(stats.T || 0)),
      tile('Lakše', fmt(stats.L || 0)),
      tile('Mat. šteta', fmt(stats.M || 0)),
      tile('Prosj. PGDP', avgPg ? fmt(avgPg) : '–', `${nPg} s podacima`),
      tile('Prosj. PLDP', avgPl ? fmt(avgPl) : '–', `${nPl} s podacima`),
    ].join('');

    const item = (k, v) => `<div><strong>${v}</strong> <span style="color:var(--muted)">${k}</span></div>`;
    const pl = document.getElementById('posl-counts');
    pl.innerHTML = ['P','T','L','M'].map(k =>
      item(POSLJ_LABEL[k], fmt(stats[k] || 0))
    ).join('');
    const rt = document.getElementById('rt-counts');
    rt.innerHTML = ['high','medium','low','estimate_range','none'].map(k =>
      item(RT_LABEL[k], fmt(rtStats[k] || 0))
    ).join('');
  }

  async function loadYear(yr) {
    if (state.cache[yr]) {
      state.data = state.cache[yr];
      return;
    }
    document.getElementById('counts-line').textContent = 'Učitavam podatke…';
    const r = await fetch(`data/nesrece/nesrece_${yr}.geojson`);
    const g = await r.json();
    state.cache[yr] = g;
    state.data = g;
  }

  function setupHandlers() {
    document.getElementById('f-year').addEventListener('change', async (e) => {
      state.year = parseInt(e.target.value, 10);
      await loadYear(state.year);
      render();
    });
    document.querySelectorAll('input[type="checkbox"][data-p]').forEach(cb => {
      cb.addEventListener('change', () => {
        state.posljedice = new Set(
          Array.from(document.querySelectorAll('input[type="checkbox"][data-p]'))
            .filter(x => x.checked).map(x => x.dataset.p)
        );
        render();
      });
    });
    document.querySelectorAll('input[type="checkbox"][data-kat]').forEach(cb => {
      cb.addEventListener('change', () => {
        state.kategorije = new Set(
          Array.from(document.querySelectorAll('input[type="checkbox"][data-kat]'))
            .filter(x => x.checked).map(x => x.dataset.kat)
        );
        render();
      });
    });
    document.querySelectorAll('input[type="checkbox"][data-rt]').forEach(cb => {
      cb.addEventListener('change', () => {
        state.razine = new Set(
          Array.from(document.querySelectorAll('input[type="checkbox"][data-rt]'))
            .filter(x => x.checked).map(x => x.dataset.rt)
        );
        render();
      });
    });
    document.getElementById('f-pgdp-min').addEventListener('input', e => {
      const v = e.target.value === '' ? null : Number(e.target.value);
      state.pgdp_min = isNaN(v) ? null : v; render();
    });
    document.getElementById('f-pgdp-max').addEventListener('input', e => {
      const v = e.target.value === '' ? null : Number(e.target.value);
      state.pgdp_max = isNaN(v) ? null : v; render();
    });
    document.getElementById('f-cesta').addEventListener('input', e => {
      state.cestaText = e.target.value.trim(); render();
    });
    document.getElementById('btn-reset').addEventListener('click', () => {
      document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
      document.getElementById('f-pgdp-min').value = '';
      document.getElementById('f-pgdp-max').value = '';
      document.getElementById('f-cesta').value = '';
      state.posljedice = new Set(['P', 'T', 'L', 'M']);
      state.kategorije = new Set(['autocesta', 'državna cesta', 'županijska cesta', 'lokalna cesta', '']);
      state.razine = new Set(['high', 'medium', 'low', 'estimate_range', 'none']);
      state.pgdp_min = null; state.pgdp_max = null;
      state.cestaText = '';
      render();
    });
    document.getElementById('btn-fit').addEventListener('click', () => {
      if (cluster.getLayers().length) {
        const b = cluster.getBounds();
        if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });
      }
    });
    document.getElementById('btn-export-xlsx').addEventListener('click', exportXlsx);
    document.getElementById('btn-export-csv').addEventListener('click', exportCsv);
  }

  function flatRow(p, lat, lon) {
    return {
      datum: p.d, posljedica: POSLJ_LABEL[p.p] || p.p, vrsta: p.v,
      mjesto: p.mjesto, ulica: p.ulica, cesta_mup: p.c,
      oznaka_ceste: p.oz, kategorija: p.kat,
      lat: lat, lon: lon,
      PGDP: p.pgdp, PLDP: p.pldp,
      razina_tocnosti: RT_LABEL[p.rt] || p.rt,
      brojac: p.br, match_method: p.mm, broj_pn: p.id,
    };
  }
  function getFiltered() {
    if (!state.data) return [];
    const out = [];
    for (const f of state.data.features) {
      const p = f.properties || {};
      if (!passes(p)) continue;
      out.push(flatRow(p, f.geometry.coordinates[1], f.geometry.coordinates[0]));
    }
    return out;
  }
  function exportXlsx() {
    const rows = getFiltered();
    if (!rows.length) { alert('Nema nesreća za export.'); return; }
    if (!window.XLSX) { alert('XLSX biblioteka nije ucitana.'); return; }
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Nesrece');
    XLSX.writeFile(wb, `nesrece-${state.year}.xlsx`);
  }
  function exportCsv() {
    const rows = getFiltered();
    if (!rows.length) { alert('Nema nesreća za export.'); return; }
    const cols = Array.from(rows.reduce((s, r) => { Object.keys(r).forEach(k => s.add(k)); return s; }, new Set()));
    const esc = (v) => v == null ? '' : (/[",\n;]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
    const csv = '﻿' + cols.join(',') + '\n' + rows.map(r => cols.map(c => esc(r[c])).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nesrece-${state.year}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); }, 200);
  }

  async function init() {
    document.getElementById('gen-date').textContent = new Date().toLocaleDateString('hr-HR');
    setupHandlers();
    await loadYear(state.year);
    render();
    if (cluster.getLayers().length) {
      const b = cluster.getBounds();
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
