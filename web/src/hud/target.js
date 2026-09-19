const F = {
  tau: 'τ = ρ·g·h·S', tau_c: 'τ_c = θ_c·(ρ_s−ρ)·g·D50, D50 = S^0.5', omega: 'ω = ρ·g·Q·S / w', M: 'M = τ / τ_c',
  D: 'D = (ω_oppstrøms − ω) / ω_oppstrøms', R: 'R = exp(−(ln M − ln 1,5)² / 2·0,6²)', sving: 'sving = |κ|·150 m',
  os: 'os = exp(−d/200 m)', foss: 'foss = exp(−d/300 m)', juv: 'juv = (w_Q − w_DTM)/w_Q', B: 'B = 0,5 + 0,7·f_berg + 0,2·e^(−d_Au/5 km)',
  h: 'Manning: Q = (1/n)·w·h·R^(2/3)·S^(1/2)', Q: 'middelflom (i dag)', w: 'w = 3·√Q (eller OSM)', S: 'fall fra DTM (±300 m)',
};
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);

export class TargetPanel {
  constructor(el, overlays) { this.el = el; this.ov = overlays; this.el.addEventListener('click', (e) => { if (e.target.classList.contains('close')) this.hide(); }); }
  hide() { this.el.classList.add('hidden'); }

  showCandidate(c) {
    const p = c.props; const a = this.ov.area; const base = a.base;
    const rows = [
      ['P (indeks 0–100)', fmt(p.P, 0), 'P = 100·(0,20D + 0,25R + 0,15sving + 0,15os + 0,15foss + 0,10juv)·port·B / maks'],
      ['τ skjærspenning', fmt(p.tau) + ' Pa', F.tau], ['τ_c terskel', fmt(p.tau_c) + ' Pa', F.tau_c], ['M = τ/τ_c', fmt(p.M, 2), F.M],
      ['ω strømeffekt', fmt(p.omega) + ' W/m²', F.omega], ['Q middelflom', fmt(p.Q, 0) + ' m³/s', F.Q], ['w bredde', fmt(p.w) + ' m', F.w],
      ['h dybde', fmt(p.h, 2) + ' m', F.h], ['S fall', fmt(p.S * 1000, 1) + ' ‰', F.S],
      ['D avsetning', fmt(p.D, 2), F.D], ['R retensjon', fmt(p.R, 2), F.R], ['sving', fmt(p.sving, 2), F.sving], ['os', fmt(p.os, 2), F.os],
      ['foss', fmt(p.foss, 2), F.foss], ['juv (innsnevring)', fmt(p.juv, 2), F.juv], ['B kilde', fmt(p.B, 2), F.B],
    ];
    if (p.s2_anomali !== undefined && p.s2_anomali !== null) rows.push(['Sentinel-2 anomali (z)', fmt(p.s2_anomali, 1), 'maks z av B4/B2, B11/B12, B11/B8 innen 100 m']);
    this.el.innerHTML = `
      <span class="close">✕</span>
      <h2><span class="badge ${c.klasse}">${c.klasse}</span>${c.rank}. ${p.navn}</h2>
      <div class="sub">${c.lat.toFixed(5)} N, ${c.lon.toFixed(5)} Ø · ${p.elv} km ${fmt(p.km)} · ${p.berg ? p.berg.split(' | ')[0] : ''}</div>
      <div class="bar"><i style="width:${Math.max(2, p.P)}%"></i></div>
      <div class="why">${p.hvorfor}</div>
      ${p.adkomst ? `<div class="why access">🚗 ${p.adkomst}</div>` : ''}
      ${this.hydroLine()}
      ${p.satsjekk ? `<div class="sub">${p.satsjekk}</div>` : ''}
      <table>${rows.map((r) => `<tr><td>${r[0]}<div class="formula">${r[2]}</div></td><td>${r[1]}</td></tr>`).join('')}</table>
      <img src="${base}satcheck_${c.rank}.jpg" alt="Satellittutsnitt" loading="lazy" onerror="this.remove()" />
      <div class="dl" style="margin-top:8px"><a href="${base}points.gpx" download>GPX ↓</a><a href="${base}points.kml" download>KML ↓</a><a href="${base}rapport.pdf" target="_blank">PDF ↓</a>
      <a href="https://www.norgeskart.no/#!?project=norgeskart&layers=1002&zoom=14&lat=${c.lat}&lon=${c.lon}&markerLat=${c.lat}&markerLon=${c.lon}" target="_blank" rel="noopener">Norgeskart ↗</a></div>`;
    this.el.classList.remove('hidden');
  }

  hydroLine() {
    const h = this.ov.area?.hydro; if (!h || !h.stations?.length) return '';
    const st = h.stations.filter((x) => x.q_last != null)[0]; if (!st) return '';
    return `<div class="sub">💧 NVE ${st.name} (${st.river || ''}): ${Number(st.q_last).toFixed(1)} m³/s døgnmiddel ${String(st.t_last).slice(0, 10)} · <a href="${st.url}" target="_blank" rel="noopener">Sildre ↗</a></div>`;
  }

  showLode(props) {
    const p = props;
    const z = (v) => (v === null || v === undefined) ? '—' : Number(v).toFixed(1);
    this.el.innerHTML = `<span class="close">✕</span><h2><span class="badge ${p.type === 'gull' ? '' : 'C'}">${p.type === 'gull' ? 'Au' : 'Cu/Zn/S'}</span>${p.name || (p.type === 'gull' ? 'Gullforekomst' : 'Basemetall-mineralisering')}</h2>
      <div class="sub">${p.objtype || ''} · NGU · lodegull-modus</div>
      <div class="why">Fast fjell: kvartsganger og sulfidsoner registrert av NGU. Sentinel-2 hydroksyl-anomali (leire/serisitt-omvandling) og jernoksid-anomali (gossan) innen 300 m indikerer omvandlingssone rundt mineraliseringen.</div>
      <table><tr><td>Hydroksyl B11/B12 (z)</td><td>${z(p.s2_oh_z)}</td></tr><tr><td>Jernoksid B4/B2 (z)</td><td>${z(p.s2_feox_z)}</td></tr></table>
      ${p.faktaark ? `<div class="dl" style="margin-top:8px"><a href="${p.faktaark}" target="_blank" rel="noopener">NGU faktaark ↗</a></div>` : ''}`;
    this.el.classList.remove('hidden');
  }

  showSegment(props) {
    const p = props;
    const rows = [['P', fmt(p.P, 0)], ['τ / τ_c', `${fmt(p.tau)} / ${fmt(p.tau_c)} Pa`], ['M', fmt(p.M, 2)], ['ω', fmt(p.omega) + ' W/m²'], ['Q', fmt(p.Q, 0) + ' m³/s'],
      ['w / h', `${fmt(p.w)} / ${fmt(p.h, 2)} m`], ['S', fmt(p.S * 1000, 1) + ' ‰'], ['D / R', `${fmt(p.D, 2)} / ${fmt(p.R, 2)}`], ['sving / os / foss', `${fmt(p.sving, 2)} / ${fmt(p.os, 2)} / ${fmt(p.foss, 2)}`], ['B', fmt(p.B, 2)]];
    this.el.innerHTML = `<span class="close">✕</span><h2>SEGMENT · ${p.elv || ''} km ${fmt(p.km)}</h2>
      <div class="bar"><i style="width:${Math.max(2, p.P)}%"></i></div>
      <table>${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}</table>
      <div class="sub" style="margin-top:8px">Klikk på et nummerert punkt for full begrunnelse og satellittsjekk.</div>`;
    this.el.classList.remove('hidden');
  }

  showNgu(props) {
    const p = props;
    this.el.innerHTML = `<span class="close">✕</span><h2><span class="badge ngu">NGU</span>${p.name || 'Gullforekomst'}</h2>
      <div class="sub">${p.objtype || ''} · NGU mineralressursdatabase</div>
      <div class="why">Registrert gullforekomst/-prospekt/-registrering hos Norges geologiske undersøkelse. Brukes som treningsdata for det nasjonale potensialkartet og som kildescore (B) for elvene.</div>
      ${p.faktaark ? `<div class="dl"><a href="${p.faktaark}" target="_blank" rel="noopener">NGU faktaark ↗</a></div>` : ''}`;
    this.el.classList.remove('hidden');
  }

  showNational(meta, lat, lon) {
    this.el.innerHTML = `<span class="close">✕</span><h2>NASJONALT POTENSIAL</h2>
      <div class="sub">${lat.toFixed(4)} N, ${lon.toFixed(4)} Ø</div>
      <div class="why">${meta?.description || 'Weights-of-evidence over 1 km-grid trent på NGUs gullpunkter.'}</div>`;
    this.el.classList.remove('hidden');
  }
}
