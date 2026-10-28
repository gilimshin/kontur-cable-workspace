// Расчёт кабельных линий по исполнительному чертежу (PDF) — окно импорта в «Кабельные линии».
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const f2 = v => (v==null||v==='') ? '' : Number(v).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
const KIND = {ground:'в земле', pipe:'в трубе', gnb:'ГНБ'};
const COLOR = {ground:'#d7262b', pipe:'#1f5fd6', gnb:'#0b8f8a'};

export function openKlImport({modal, notify, project, onApply}) {
  let R = null, file = null, sel = null, view = {s:1,x:0,y:0};
  const dlg = document.querySelector('#modal');
  dlg.classList.add('kl-wide');
  const restore = () => dlg.classList.remove('kl-wide');
  dlg.addEventListener('close', restore, {once:true});

  modal(`<div class="eyebrow">КАБЕЛЬНЫЕ ЛИНИИ · ИСПОЛНИТЕЛЬНЫЙ ЧЕРТЁЖ</div>
    <h2>Расчёт длин по исполнительному чертежу</h2>
    <p>Загрузите PDF чертежа КЛ. Красные линии — кабель в земле, синие — трубы и ГНБ. Маршрут каждой КЛ подбирается по точкам из спецификации и сверяется с её длиной.</p>
    <div class="kl-drop" id="kl-drop"><b>Перетащите PDF сюда</b> или нажмите, чтобы выбрать файл<input type="file" id="kl-file" accept="application/pdf" hidden></div>
    <div class="kl-params">
      <label>Заводка, начало, м<input type="number" id="kl-zf" value="5" step="0.5" min="0"></label>
      <label>Заводка, конец, м<input type="number" id="kl-zt" value="5" step="0.5" min="0"></label>
      <label>Коэф. в земле<input type="number" id="kl-kg" value="1.02" step="0.01" min="0"></label>
      <label>Коэф. в трубе<input type="number" id="kl-kp" value="1.01" step="0.01" min="0"></label>
      <span id="kl-status" class="muted"></span>
    </div>
    <div id="kl-result"></div>`);

  const $ = s => dlg.querySelector(s);
  const drop = $('#kl-drop'), inp = $('#kl-file');
  drop.onclick = () => inp.click();
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) run(e.dataTransfer.files[0]); };
  inp.onchange = () => inp.files[0] && run(inp.files[0]);
  ['#kl-kg','#kl-kp','#kl-zf','#kl-zt'].forEach(id => $(id).onchange = () => {
    if (!R) return;
    if (id==='#kl-zf'||id==='#kl-zt') R.table.forEach(r => { r.zav_from = +$('#kl-zf').value; r.zav_to = +$('#kl-zt').value; });
    renderTable();
  });

  async function run(f) {
    file = f; sel = null;
    $('#kl-status').innerHTML = '<span class="kl-spin"></span> Считаю «' + esc(f.name) + '»…';
    $('#kl-result').innerHTML = '';
    const qs = new URLSearchParams({zav_from:$('#kl-zf').value, zav_to:$('#kl-zt').value, k_ground:$('#kl-kg').value, k_pipe:$('#kl-kp').value});
    try {
      const h = await fetch('/api/kl/health').then(x => x.ok ? x.json() : null).catch(() => null);
      const local = ['localhost','127.0.0.1'].includes(location.hostname);
      if (!h) throw new Error(local ? 'Сервер запущен в старой версии или не отвечает. Закройте окно сервиса и запустите start_kl.bat в папке cable-workspace, затем обновите страницу.' : 'Расчёт по чертежу на сайте временно недоступен. Обновите страницу и попробуйте ещё раз.');
      if (h.maxPdf && f.size > h.maxPdf) throw new Error('Файл больше 4 МБ — на сайте такой чертёж не принимается. Уменьшите PDF или посчитайте в локальной версии (start_kl.bat).');
      if (!h.kl) throw new Error(h.error || 'Не установлены библиотеки для чтения PDF. Запустите start_kl.bat.');
      const r = await fetch('/api/kl/parse?' + qs, {method:'POST', headers:{'Content-Type':'application/pdf'}, body:f});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
      R = j;
      const ok = R.cables.filter(c => c.status==='ok').length;
      $('#kl-status').innerHTML = `${esc(R.address || f.name)} · совпало со спецификацией <b>${ok} из ${R.cables.length}</b> КЛ`;
      layout();
    } catch (e) {
      $('#kl-status').innerHTML = '<span class="kl-err">' + esc(e.message) + '</span>';
    }
  }

  function layout() {
    $('#kl-result').innerHTML = `
      <div class="kl-grid">
        <div class="kl-card">
          <div class="kl-head"><strong>Чертёж</strong><span class="muted" id="kl-sel"></span>
            <span class="kl-tools"><button class="button" id="kl-fit">Вся трасса</button></span></div>
          <div class="kl-viewer" id="kl-viewer"><div class="kl-stage" id="kl-stage"><img id="kl-bg" alt=""><svg id="kl-ov"></svg></div></div>
          <div class="kl-legend"><span><i style="background:${COLOR.ground}"></i>в земле</span><span><i style="background:${COLOR.pipe}"></i>в трубе</span><span><i style="background:${COLOR.gnb}"></i>ГНБ</span><span>колесо — масштаб, мышь — сдвиг</span></div>
        </div>
        <div class="kl-card">
          <div class="kl-head"><strong>Сверка со спецификацией</strong></div>
          <div class="table-wrap"><table id="kl-cables"></table></div>
          <div id="kl-route" class="kl-steps"></div>
          <div class="kl-head" style="margin-top:14px"><strong>Контрольные суммы</strong></div>
          <table id="kl-checks"></table>
          <div id="kl-warn"></div>
        </div>
      </div>
      <div class="kl-card">
        <div class="kl-head"><strong>Таблица «кВ»</strong><span class="muted">в земле × ${R.params.k_ground} + ГНБ + в трубе × ${R.params.k_pipe} + заводка</span></div>
        <div class="table-wrap"><table id="kl-table"></table></div>
      </div>
      <div class="kl-grid">
        <div class="kl-card"><div class="kl-head"><strong>Общие данные трассы</strong></div><table id="kl-sum"></table></div>
        <div class="kl-card"><div class="kl-head"><strong>Трубы (длина × количество)</strong></div><div id="kl-pipes"></div></div>
      </div>
      <div class="kl-actions">
        <button class="button" id="kl-xlsx">Скачать Excel (формат «кВ»)</button>
        <span class="muted" id="kl-apply-note"></span>
        <button class="button" id="kl-append">Добавить к линиям объекта</button>
        <button class="button primary" id="kl-replace">Заменить линии объекта (${project.cables.length})</button>
      </div>`;
    renderDrawing(); renderChecks(); renderTable(); renderSummary();
    $('#kl-fit').onclick = () => { sel = null; renderChecks(); draw(); fit(); };
    $('#kl-xlsx').onclick = downloadXlsx;
    $('#kl-append').onclick = () => apply(false);
    $('#kl-replace').onclick = () => apply(true);
    const bad = R.cables.filter(c => c.status !== 'ok').length;
    $('#kl-apply-note').textContent = bad ? `Внимание: ${bad} КЛ не совпали со спецификацией — проверьте перед переносом.` : 'Все КЛ совпали со спецификацией чертежа.';
  }

  // ---------- чертёж
  function renderDrawing() {
    const im = R.image || {}, bg = $('#kl-bg');
    if (im.src) { bg.src = im.src; Object.assign(bg.style, {left:im.x0+'px', top:im.y0+'px', width:(im.x1-im.x0)+'px', height:(im.y1-im.y0)+'px'}); }
    else bg.hidden = true;
    const ov = $('#kl-ov');
    ov.setAttribute('width', R.page.w); ov.setAttribute('height', R.page.h); ov.setAttribute('viewBox', `0 0 ${R.page.w} ${R.page.h}`);
    const viewer = $('#kl-viewer'), stage = $('#kl-stage');
    viewer.addEventListener('wheel', e => {
      e.preventDefault();
      const r = viewer.getBoundingClientRect(), mx = e.clientX-r.left, my = e.clientY-r.top, k = e.deltaY<0 ? 1.15 : 1/1.15;
      view.x = mx-(mx-view.x)*k; view.y = my-(my-view.y)*k; view.s *= k; applyView();
    }, {passive:false});
    let drag = null;
    viewer.onmousedown = e => { e.preventDefault(); drag = {x:e.clientX-view.x, y:e.clientY-view.y}; };
    viewer.onmousemove = e => { if (drag) { view.x = e.clientX-drag.x; view.y = e.clientY-drag.y; applyView(); } };
    viewer.onmouseup = viewer.onmouseleave = () => drag = null;
    ov.addEventListener('mousemove', e => { const t = e.target.getAttribute && e.target.getAttribute('data-tip'); viewer.title = t || ''; });
    draw(); requestAnimationFrame(fit);
  }
  function applyView() { $('#kl-stage').style.transform = `translate(${view.x}px,${view.y}px) scale(${view.s})`; }
  function fitBox(x0,y0,x1,y1) {
    const v = $('#kl-viewer'), W = v.clientWidth, H = v.clientHeight, s = Math.min(W/(x1-x0), H/(y1-y0))*0.96;
    view = {s, x:(W-(x1-x0)*s)/2-x0*s, y:(H-(y1-y0)*s)/2-y0*s}; applyView();
  }
  function fit() {
    if (sel != null) {
      const ps = R.cables[sel].path.map(n => R.points[n]).filter(Boolean), xs = ps.map(p=>p[0]), ys = ps.map(p=>p[1]);
      return fitBox(Math.min(...xs)-25, Math.min(...ys)-25, Math.max(...xs)+25, Math.max(...ys)+25);
    }
    const [x0,y0,x1,y1] = R.bbox; fitBox(x0+30, y0+30, x1-30, y1-30);
  }
  function draw() {
    const route = sel!=null ? new Set(R.cables[sel].steps.map(s => [s.frm,s.to].sort().join('|'))) : null;
    const [bx0,by0,bx1,by1] = R.bbox;
    let h = `<rect x="${bx0}" y="${by0}" width="${bx1-bx0}" height="${by1-by0}" fill="#fff" opacity="0.5"/>`;
    for (const s of R.spans) {
      const on = !route || route.has([s.a,s.b].sort().join('|'));
      const d = 'M' + s.pts.map(p => p[0].toFixed(2)+' '+p[1].toFixed(2)).join(' L');
      const tip = `т.${s.a} – т.${s.b}: ${s.len} м, ${KIND[s.kind]}${s.pipes ? `, ${s.pipes} тр ${s.ptype||''} d=${s.d||'?'}` : ''}${s.gnb ? ' ('+s.gnb+', Lпр)' : ''}`;
      h += `<path d="${d}" fill="none" stroke="${COLOR[s.kind]}" stroke-width="${on?2.6:1.2}" stroke-linecap="round" stroke-linejoin="round" opacity="${on?0.95:0.25}"/>`;
      h += `<path d="${d}" fill="none" stroke="transparent" stroke-width="7" data-tip="${esc(tip)}"/>`;
    }
    const pts = route ? new Set(R.cables[sel].path) : null;
    for (const [n,[x,y]] of Object.entries(R.points)) {
      const on = !pts || pts.has(n);
      h += `<circle cx="${x}" cy="${y}" r="${on?1.8:1.1}" fill="#fff" stroke="#3b2a6b" stroke-width="0.6" opacity="${on?1:.4}"/>`;
      if (on && pts) h += `<text x="${x+2.2}" y="${y-2.2}" font-size="5.5" font-weight="700" fill="#3b2a6b" style="paint-order:stroke" stroke="#fff" stroke-width="1.6">${esc(n)}</text>`;
    }
    $('#kl-ov').innerHTML = h;
  }

  // ---------- сверка
  function badge(c) {
    if (c.status==='ok') return '<span class="kl-badge ok">✓ совпадает</span>';
    if (c.status==='ambiguous') return '<span class="kl-badge warn">выбрать маршрут</span>';
    if (c.status==='mismatch') return `<span class="kl-badge warn">${c.diff>0?'+':''}${f2(c.diff)} м</span>`;
    if (c.status==='nospec') return '<span class="kl-badge warn">нет спецификации</span>';
    return '<span class="kl-badge err">ошибка</span>';
  }
  function renderChecks() {
    let h = '<thead><tr><th>КЛ</th><th class="kl-n">Спец., м</th><th class="kl-n">Маршрут, м</th><th class="kl-n">Земля</th><th class="kl-n">ГНБ</th><th class="kl-n">Труба</th><th></th></tr></thead><tbody>';
    R.cables.forEach((c,i) => {
      h += `<tr class="kl-click ${sel===i?'kl-sel':''}" data-i="${i}"><td>${c.count}× ${esc(c.frm)} <span class="muted">(т.${esc(c.a)})</span> → ${esc(c.to)} <span class="muted">(т.${esc(c.b)})</span></td>
        <td class="kl-n">${f2(c.spec_len)}</td><td class="kl-n">${f2(c.route_len)}</td><td class="kl-n">${f2(c.ground)}</td><td class="kl-n">${f2(c.gnb)}</td><td class="kl-n">${f2(c.pipe)}</td><td>${badge(c)}</td></tr>`;
    });
    $('#kl-cables').innerHTML = h + '</tbody>';
    dlg.querySelectorAll('tr.kl-click').forEach(tr => tr.onclick = () => { const i = +tr.dataset.i; sel = sel===i ? null : i; renderChecks(); draw(); fit(); });
    const c = sel!=null ? R.cables[sel] : null;
    $('#kl-sel').textContent = c ? `— ${c.frm} → ${c.to}` : '';
    $('#kl-route').innerHTML = c
      ? `<b>Маршрут ${esc(c.frm)} → ${esc(c.to)}:</b> ` + (c.steps||[]).map(s => `<span style="background:${COLOR[s.kind]}" title="${KIND[s.kind]}">т.${esc(s.frm)}–${esc(s.to)}: ${s.len}</span>`).join('') + (c.msg ? `<div class="kl-err">${esc(c.msg)}</div>` : '')
      : '<span class="muted">Нажмите на КЛ — маршрут подсветится на чертеже, появится разбивка по участкам.</span>';
    let ch = '<thead><tr><th>Показатель</th><th class="kl-n">На чертеже</th><th class="kl-n">Расчёт</th><th></th></tr></thead><tbody>';
    for (const x of R.checks) ch += `<tr><td>${esc(x.name)}</td><td class="kl-n">${f2(x.drawing)}</td><td class="kl-n">${f2(x.calc)}</td><td>${x.ok ? '<span class="kl-badge ok">✓</span>' : '<span class="kl-badge warn">≠</span>'}</td></tr>`;
    $('#kl-checks').innerHTML = ch + '</tbody>';
    $('#kl-warn').innerHTML = R.warnings.length ? '<ul class="kl-warn">' + R.warnings.map(w => `<li>${esc(w)}</li>`).join('') + '</ul>' : '';
  }

  // ---------- таблица кВ
  function recalc() {
    const kg = +$('#kl-kg').value, kp = +$('#kl-kp').value;
    R.params.k_ground = kg; R.params.k_pipe = kp;
    for (const r of R.table) { r.total = r.ground*kg + r.gnb + r.pipe*kp + (+r.zav_from) + (+r.zav_to); r.rounded = Math.round(r.total); }
  }
  function renderTable() {
    recalc();
    let h = '<thead><tr><th>Каб. журнал</th><th>Кабель</th><th>Сечение</th><th class="kl-n">в земле</th><th class="kl-n">в ГНБ (профиль)</th><th class="kl-n">в трубе</th><th>Заводка</th><th class="kl-n">Итоговая длина</th><th class="kl-n">Округл.</th><th></th></tr></thead><tbody>';
    R.table.forEach((r,i) => {
      h += `<tr><td>${esc(r.name)}</td><td>${esc(r.mark)}</td><td>${esc(r.section)}</td>
        <td class="kl-n" title="${esc(r.ground_parts.join(' + '))}">${f2(r.ground)}</td><td class="kl-n">${f2(r.gnb)}</td>
        <td class="kl-n" title="${esc(r.pipe_parts.join(' + '))}">${f2(r.pipe)}</td>
        <td class="kl-zav"><input type="number" step="0.5" min="0" value="${r.zav_from}" data-i="${i}" data-k="zav_from"> + <input type="number" step="0.5" min="0" value="${r.zav_to}" data-i="${i}" data-k="zav_to"></td>
        <td class="kl-n">${r.total.toFixed(4).replace('.',',')}</td><td class="kl-n"><b>${r.rounded}</b></td><td>${badge(R.cables[r.cable])}</td></tr>`;
    });
    const sum = R.table.reduce((a,r) => a+r.rounded, 0), g = R.table.reduce((a,r) => a+r.ground, 0);
    h += `</tbody><tfoot><tr><td colspan="3">Итого</td><td class="kl-n">${f2(g)}</td><td></td><td></td><td></td><td></td><td class="kl-n">${sum}</td><td></td></tr></tfoot>`;
    $('#kl-table').innerHTML = h;
    dlg.querySelectorAll('#kl-table input').forEach(el => el.onchange = () => { R.table[+el.dataset.i][el.dataset.k] = Math.max(0, +el.value || 0); renderTable(); });
  }
  function renderSummary() {
    const s = R.summary;
    const rows = [['L без ГНБ (траншея по исп.)', s.trench_no_gnb], ['Траншея без труб (в земле)', s.trench_ground], ['Участки в трубах', s.trench_pipe], ['ГНБ (по профилю)', s.gnb_prof]];
    for (const [k,v] of Object.entries(s.pipes)) rows.push([k+', всего труб', v.total]);
    rows.push(['Кол-во КЛ', R.table.length]);
    $('#kl-sum').innerHTML = '<tbody>' + rows.map(([k,v]) => `<tr><td>${esc(k)}</td><td class="kl-n">${Number.isInteger(v) ? v : f2(v)}</td></tr>`).join('') + '</tbody>';
    let p = '';
    for (const [k,v] of Object.entries(s.pipes)) {
      p += `<table class="kl-pipe"><thead><tr><th>${esc(k)}</th><th class="kl-n">Длина</th><th class="kl-n">Кол-во</th><th class="kl-n">Общая длина</th></tr></thead><tbody>` +
        v.rows.map(r => `<tr><td class="muted">${esc(r.span)}</td><td class="kl-n">${f2(r.len)}</td><td class="kl-n">${r.count || '<span class="kl-err">?</span>'}</td><td class="kl-n">${f2(r.total)}</td></tr>`).join('') +
        `</tbody><tfoot><tr><td colspan="3">Итого</td><td class="kl-n">${f2(v.total)}</td></tr></tfoot></table>`;
    }
    $('#kl-pipes').innerHTML = p || '<span class="muted">Трубы не найдены</span>';
  }

  async function downloadXlsx() {
    const r = await fetch('/api/kl/excel', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({result:R, rows:R.table})});
    if (!r.ok) { notify('Не удалось сформировать Excel'); return; }
    const b = await r.blob(), a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = (file?.name || 'КЛ').replace(/\.pdf$/i,'') + ' — расчёт КЛ.xlsx'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function apply(replace) {
    recalc();
    const r2 = v => Math.round(v*100)/100;
    const lines = R.table.map(r => ({
      id: crypto.randomUUID(), direction: r.name, brand: r.mark, section: r.section,
      ground: r2(r.ground), hdd: r2(r.gnb), pipe: r2(r.pipe), entry: r2((+r.zav_from) + (+r.zav_to)),
      drawing: {file: file?.name || '', ground_parts: r.ground_parts, pipe_parts: r.pipe_parts, gnb_parts: r.gnb_parts,
                spec_len: R.cables[r.cable].spec_len, route: R.cables[r.cable].path, status: R.cables[r.cable].status},
    }));
    onApply({lines, replace, summary: {file: file?.name || '', address: R.address, trench: R.summary.trench_no_gnb,
      trench_ground: R.summary.trench_ground, gnb: R.summary.gnb_prof,
      pipes: Object.fromEntries(Object.entries(R.summary.pipes).map(([k,v]) => [k, v.total]))}});
    restore(); dlg.close();
  }
}
