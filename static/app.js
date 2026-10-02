/* Pestañas de finca + asistente. Reutiliza $, fmt y esc definidos en index.html */
'use strict';
const N = (n, d = 0) => n == null || isNaN(n) ? '–' : Number(n).toLocaleString('es-CO', { maximumFractionDigits: d });
const hoyISO = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const opt = (arr, val, txt, sel) => arr.map(x => `<option value="${esc(x[val])}" ${String(x[val]) === String(sel) ? 'selected' : ''}>${esc(typeof txt === 'function' ? txt(x) : x[txt])}</option>`).join('');
const VARIEDADES = ['Tomate chonto', 'Tomate larga vida'];
const DESTINOS = ['Garzón', 'Cali', 'Bogotá', 'Neiva', 'Otro'];

async function api(url, body, method) {
    const o = { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json' } };
    if (body) o.body = JSON.stringify(body);
    const r = await fetch(url, o);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || j.mensaje || 'Error ' + r.status);
    return j;
}
function toast(msg, ok = true) {
    let t = document.getElementById('toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 z-[60] px-4 py-2 rounded-lg text-sm shadow-lg'; document.body.appendChild(t); }
    t.textContent = msg; t.style.background = ok ? '#065f46' : '#9f1239'; t.style.color = '#fff'; t.style.display = 'block';
    clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 3500);
}
const costosApp = () => ({
    finca: $('cFinca').value, merma: $('cMerma').value, flete: $('cFleteDef').value, kg: $('sfKg').value || $('cKg').value,
    fletes, usar_real: $('chkReal').checked
});
const leer = (root, sel = '[data-f]') => Object.fromEntries([...root.querySelectorAll(sel)].map(e => [e.dataset.f, e.type === 'checkbox' ? e.checked : e.value]));
const campo = (etq, html) => `<div><label class="lbl">${etq}</label>${html}</div>`;

let FD = { invernaderos: [], lotes: [], categorias: {} };
async function cargarDatos() { FD = await api('/api/finca/datos'); }
const lotesActivos = () => FD.lotes.filter(l => l.estado === 'activo');

/* ---------- navegación ---------- */
const TABS = ['hoy', 'ventas', 'prediccion', 'finca', 'registros', 'balance', 'insumos', 'siembra', 'alertas'];
const RENDER = {};
function mostrar(tab) {
    if (!TABS.includes(tab)) tab = 'hoy';
    TABS.forEach(t => $('tab-' + t).classList.toggle('hidden', t !== tab));
    document.querySelectorAll('.tabbtn').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    try { localStorage.setItem('tomateTab', tab); } catch (e) { }
    if (tab === 'ventas') { if (typeof chart !== 'undefined' && chart) chart.applyOptions({ width: $('chartContainer').clientWidth }); cargarSemaforo(); }
    else if (RENDER[tab]) RENDER[tab]().catch(e => toast(e.message, false));
}
document.querySelectorAll('.tabbtn').forEach(b => b.onclick = () => mostrar(b.dataset.tab));
const irA = t => { cerrarChat(); mostrar(t); window.scrollTo(0, 0); };

/* ---------- Ventas: costo real + semáforo ---------- */
async function aplicarCostoReal() {
    let j = { disponible: false };
    try { j = await api('/api/costo_real'); } catch (e) { }
    window.costoReal = j;
    const usar = $('chkReal').checked && j.disponible;
    $('cFinca').disabled = usar;
    if (usar) $('cFinca').value = j.costo_kg;
    $('lblReal').innerHTML = j.disponible
        ? `${usar ? '✅' : '⚠️'} Real: <b>${fmt(j.costo_kg)}</b>/kg (${N(j.kg_base)} kg, ${esc(j.lotes.join(', '))})${j.parcial ? ' · parcial' : ''}`
        : 'Aún no hay cosechas con costos: usa tu estimación manual.';
    if (typeof render === 'function' && typeof datos !== 'undefined' && datos.length) render();
    cargarSemaforo();
}
let _sfT;
function cargarSemaforo() {
    clearTimeout(_sfT);
    _sfT = setTimeout(async () => {
        if ($('tab-ventas').classList.contains('hidden')) return;
        try {
            const s = await api('/api/semaforo', { costos: costosApp(), kg: $('sfKg').value, mercados: [...seleccion] });
            $('sfVeredicto').innerHTML = `${esc(s.veredicto || '')} <span class="text-zinc-500 text-xs">Costo ${fmt(s.costo_kg)}/kg (${s.origen_costo === 'real' ? 'real de tu finca' : 'estimado manual'}).</span>`;
            const col = { verde: 'border-emerald-600 bg-emerald-950/40', amarillo: 'border-amber-600 bg-amber-950/30', rojo: 'border-rose-600 bg-rose-950/30' };
            const ico = { verde: '🟢', amarillo: '🟡', rojo: '🔴' };
            $('sfCards').innerHTML = s.mercados.map(m => `<div class="border rounded-xl p-3 ${col[m.color]}">
                <div class="text-xs text-zinc-300">${ico[m.color]} ${esc(m.mercado)}${m.es_referencia ? ' <span class="text-zinc-500">(referencia)</span>' : ''}</div>
                <div class="text-lg font-bold">${fmt(m.margen_kg)}<span class="text-xs font-normal text-zinc-400">/kg</span></div>
                <div class="text-xs text-zinc-300">Carga: <b>${fmt(m.utilidad_carga)}</b></div>
                <div class="text-[10px] text-zinc-500">Precio prom. ${fmt(m.precio_prom_kg)} · ${m.dias_con_dato} días con dato</div></div>`).join('')
                || '<div class="text-xs text-zinc-500">Sin precios en los últimos 7 días.</div>';
        } catch (e) { $('sfVeredicto').textContent = '⚠️ ' + e.message; }
    }, 250);
}
$('sfKg').addEventListener('input', cargarSemaforo);
['cMerma', 'cFleteDef', 'cFinca'].forEach(id => $(id).addEventListener('input', cargarSemaforo));
$('chkReal').addEventListener('change', aplicarCostoReal);

/* ---------- gráficos SVG simples ---------- */
function barras(vals, etiquetas, { alto = 150, base = 1 } = {}) {
    const W = 640, pad = 22, n = vals.length, w = W / n, ok = vals.filter(v => v != null);
    const max = Math.max(...ok, base * 1.1), min = Math.min(...ok, base * 0.9);
    const y = v => 8 + (max - v) / (max - min) * (alto - 16);
    return `<svg viewBox="0 0 ${W} ${alto + pad}" class="w-full h-auto" style="max-width:760px">
        <line x1="0" x2="${W}" y1="${y(base)}" y2="${y(base)}" stroke="#52525b" stroke-dasharray="4 4"/>
        <text x="2" y="${y(base) - 3}" font-size="10" fill="#71717a">promedio</text>` +
        vals.map((v, i) => v == null ? '' : `<rect x="${i * w + w * .15}" width="${w * .7}" y="${Math.min(y(v), y(base))}" height="${Math.max(1, Math.abs(y(v) - y(base)))}" rx="2" fill="${v >= base ? '#34d399' : '#fb7185'}" opacity=".85"/>
        <text x="${i * w + w / 2}" y="${(v >= base ? y(v) - 3 : y(v) + 11)}" font-size="10" text-anchor="middle" fill="#d4d4d8">${((v - 1) * 100 >= 0 ? '+' : '') + ((v - 1) * 100).toFixed(0)}%</text>
        <text x="${i * w + w / 2}" y="${alto + 14}" font-size="11" text-anchor="middle" fill="#a1a1aa">${etiquetas[i]}</text>`).join('') + '</svg>';
}
function linea(pts, { alto = 140, color = '#34d399', marcas = [] } = {}) {
    if (pts.length < 2) return '';
    const W = 640, xs = pts.map(p => p.x), ys = pts.map(p => p.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const X = x => 4 + (x - x0) / (x1 - x0 || 1) * (W - 8), Y = y => alto - 8 - (y - y0) / (y1 - y0 || 1) * (alto - 16);
    return `<svg viewBox="0 0 ${W} ${alto}" class="w-full h-auto" style="max-width:760px">
        <polyline fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" points="${pts.map(p => `${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ')}"/>` +
        marcas.map(m => `<circle cx="${X(m.x)}" cy="${Y(m.y)}" r="5" fill="${m.c || '#fbbf24'}"/>`).join('') + '</svg>';
}

/* ---------- HOY ---------- */
RENDER.hoy = async function () {
    await cargarDatos();
    const cont = $('tab-hoy');
    if (!FD.invernaderos.length) {
        cont.innerHTML = `<div class="card space-y-3"><h2 class="text-lg font-semibold text-emerald-400">👋 Empecemos por tu finca</h2>
            <p class="text-sm text-zinc-300">En 3 pasos tendrás el costo real de cada kilo y el margen antes de cargar el carro:</p>
            <ol class="text-sm text-zinc-300 list-decimal ml-5 space-y-1"><li><b>Finca:</b> crea tu invernadero (área, plantas, inversión) y su primer lote.</li>
            <li><b>Registros:</b> anota costos, cosechas y ventas. Puedes escribirlos o mandar una foto al asistente.</li>
            <li><b>Balance y Ventas:</b> el sistema calcula tu costo real por kg y te dice a dónde llevar el tomate.</li></ol>
            <div class="flex gap-2"><button class="btn" onclick="irA('finca')">Crear mi invernadero</button>
            <button class="btn2" onclick="abrirChat('registrar')">📝 Registrar con texto o foto</button></div></div>
            <div id="hoyAlertas"></div>`;
        return pintarAlertasHoy();
    }
    const h = await api('/api/hoy', { costos: costosApp(), mercados: [...seleccion] });
    const k = h.kpis, s = h.semaforo;
    const kg = k.stock_por_vender.reduce((a, x) => a + x.kg, 0);
    const kpi = (t, v, sub, c = '') => `<div class="card"><div class="text-[11px] text-zinc-400">${t}</div><div class="text-2xl font-bold ${c}">${v}</div><div class="text-[11px] text-zinc-500">${sub}</div></div>`;
    cont.innerHTML = `
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        ${kpi('Utilidad últimos 30 días', fmt(k.ultimos_30d.utilidad), `Ingresos ${fmt(k.ultimos_30d.ingreso)}`, k.ultimos_30d.utilidad >= 0 ? 'text-emerald-400' : 'text-rose-400')}
        ${kpi('Costo real por kg', k.costo_real.disponible ? fmt(k.costo_real.costo_kg) : '–', k.costo_real.disponible ? (k.costo_real.parcial ? 'lotes activos (parcial)' : 'lotes cerrados') : 'registra costos y cosechas')}
        ${kpi('Tomate por vender', kg ? N(kg) + ' kg' : '–', k.stock_por_vender.map(x => esc(x.lote)).join(', ') || 'sin stock registrado')}
        ${kpi('Lotes activos', k.lotes_activos, `${FD.invernaderos.length} invernadero(s)`)}
      </div>
      <div class="card space-y-2"><div class="flex justify-between items-center"><h2 class="font-semibold">🚦 Hoy conviene</h2><button class="btn2" onclick="irA('ventas')">Ver comparador</button></div>
        <div class="text-sm">${esc(s.veredicto || 'Sin precios recientes.')}</div>
        <div class="text-[11px] text-zinc-500">Costo ${fmt(s.costo_kg)}/kg (${s.origen_costo === 'real' ? 'real' : 'manual'}) · precios al ${s.hasta}</div></div>
      <div class="card space-y-2"><div class="flex justify-between items-center"><h2 class="font-semibold text-emerald-400">🤖 Resumen del día</h2>
        <button id="btnBrief" class="btn">Generar resumen</button></div>
        <div id="briefTxt" class="text-sm text-zinc-200 whitespace-pre-wrap">Una llamada corta a la IA (se guarda por día; si nada cambió no vuelve a cobrar).</div>
        <div id="briefCosto" class="text-[11px] text-zinc-500"></div></div>
      <div id="hoyAlertas"></div>`;
    pintarUso(h.uso, null, 'briefCosto');
    $('btnBrief').onclick = async () => {
        $('btnBrief').disabled = true; $('briefTxt').textContent = 'Pensando…';
        try { const j = await api('/api/briefing2', { costos: costosApp() }); $('briefTxt').textContent = j.texto; pintarUso(j.uso, j.usd, 'briefCosto'); }
        catch (e) { $('briefTxt').textContent = '⚠️ ' + e.message; } finally { $('btnBrief').disabled = false; }
    };
    pintarAlertasHoy();
};
function pintarUso(u, usd, id) {
    const t = (usd != null ? `Esta consulta: US$${usd.toFixed(4)}${usd === 0 ? ' (caché)' : ''} · ` : '') + `Este mes: ${u.llamadas} llamadas, US$${u.usd.toFixed(3)} (≈ $${N(u.cop)} COP)`;
    [id, 'chatUso'].forEach(i => { const e = document.getElementById(i); if (e) e.textContent = t; });
}
async function pintarAlertasHoy() {
    const al = await api('/api/alertas');
    pintarBadge(al);
    const cont = $('hoyAlertas'); if (!cont) return;
    cont.innerHTML = `<div class="card space-y-2"><div class="flex justify-between items-center"><h2 class="font-semibold">🔔 Lo más importante</h2><button class="btn2" onclick="irA('alertas')">Ver todas (${al.length})</button></div>` +
        (al.slice(0, 4).map(alertaHTML).join('') || '<div class="text-sm text-zinc-500">Todo tranquilo. Sin alertas.</div>') + '</div>';
}
function pintarBadge(al) {
    const n = al.filter(a => a.nivel === 'rojo' || a.nivel === 'amarillo').length, b = $('badgeAlertas');
    b.textContent = n; b.classList.toggle('hidden', !n);
}
const NIV = { rojo: ['🔴', 'border-rose-700 bg-rose-950/30'], amarillo: ['🟡', 'border-amber-700 bg-amber-950/20'], verde: ['🟢', 'border-emerald-700 bg-emerald-950/30'], info: ['ℹ️', 'border-zinc-700 bg-zinc-900'] };
function alertaHTML(a, conAcciones = false) {
    const [i, c] = NIV[a.nivel] || NIV.info;
    return `<div class="border rounded-lg p-2.5 text-sm ${c}"><div class="flex justify-between gap-2"><div><b>${i} ${esc(a.titulo)}</b><div class="text-xs text-zinc-300">${esc(a.detalle)}</div></div>
        <div class="flex gap-1 shrink-0 items-start">${a.tab ? `<button class="btn2" onclick="irA('${a.tab}')">Ir</button>` : ''}${conAcciones ? `<button class="btn2" onclick="descartarAlerta('${esc(a.clave)}')">Ocultar 7d</button>` : ''}</div></div></div>`;
}
async function descartarAlerta(k) { await api('/api/alertas', { clave: k, dias: 7 }); RENDER.alertas(); }

/* ---------- ALERTAS ---------- */
RENDER.alertas = async function () {
    const al = await api('/api/alertas'); pintarBadge(al);
    $('tab-alertas').innerHTML = `<div class="card space-y-2"><h2 class="font-semibold">🔔 Alertas y riesgos</h2>
        <p class="text-[11px] text-zinc-500">Se calculan con reglas sobre tus datos (sin costo de IA). Pregúntale al asistente «¿qué riesgos veo?» para que las interprete.</p>
        ${al.map(a => alertaHTML(a, true)).join('') || '<div class="text-sm text-zinc-500">Sin alertas activas.</div>'}</div>`;
};

/* ---------- FINCA ---------- */
RENDER.finca = async function () {
    await cargarDatos();
    const inv = FD.invernaderos, lts = FD.lotes;
    $('tab-finca').innerHTML = `
    <div class="card space-y-3"><h2 class="font-semibold">🏭 Invernaderos</h2>
      <div id="fInv" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${campo('Nombre', '<input class="inp w-full" data-f="nombre" placeholder="Invernadero 1">')}
        ${campo('Área (m²)', '<input type="number" class="inp w-full" data-f="area_m2">')}
        ${campo('Plantas', '<input type="number" class="inp w-full" data-f="plantas">')}
        ${campo('Inversión ($)', '<input type="number" class="inp w-full" data-f="inversion" placeholder="estructura, riego, plástico">')}
        ${campo('Vida útil (años)', '<input type="number" class="inp w-full" data-f="vida_util_anios" value="8">')}
        ${campo('En operación desde', '<input type="date" class="inp w-full" data-f="fecha_inicio">')}
        ${campo('Cultivo', '<input class="inp w-full" data-f="cultivo" value="Tomate">')}
        <div class="flex items-end"><button class="btn w-full" id="btnInv">Guardar invernadero</button></div></div>
      <p class="text-[11px] text-zinc-500">La inversión se reparte en el tiempo (depreciación) para que el costo por kg incluya el desgaste de la estructura.</p>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Nombre</th><th>Área</th><th>Plantas</th><th>Inversión</th><th>Vida útil</th><th>Desde</th><th></th></tr></thead><tbody>
      ${inv.map(i => `<tr><td>${esc(i.nombre)}</td><td>${N(i.area_m2)} m²</td><td>${N(i.plantas)}</td><td>${fmt(i.inversion)}</td><td>${i.vida_util_anios} a</td><td>${i.fecha_inicio || '–'}</td>
      <td><button class="btn2" onclick='editInv(${JSON.stringify(i).replace(/'/g, "&#39;")})'>Editar</button> <button class="btn2" onclick="borrarReg('invernaderos',${i.id},'Se borrarán también sus lotes, costos, cosechas y ventas.')">🗑</button></td></tr>`).join('') || '<tr><td colspan="7" class="text-zinc-500">Aún no hay invernaderos.</td></tr>'}</tbody></table></div></div>
    <div class="card space-y-3"><h2 class="font-semibold">🌿 Lotes de producción <span class="text-xs text-zinc-500 font-normal">(una siembra en un invernadero)</span></h2>
      ${inv.length ? `<div id="fLote" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${campo('Invernadero', `<select class="inp w-full" data-f="invernadero_id">${opt(inv, 'id', 'nombre')}</select>`)}
        ${campo('Nombre del lote', '<input class="inp w-full" data-f="nombre" placeholder="Ciclo oct-2026">')}
        ${campo('Variedad', `<select class="inp w-full" data-f="variedad">${VARIEDADES.map(v => `<option>${v}</option>`).join('')}</select>`)}
        ${campo('Fecha de siembra', `<input type="date" class="inp w-full" data-f="fecha_siembra" value="${hoyISO()}">`)}
        ${campo('Plantas', '<input type="number" class="inp w-full" data-f="plantas">')}
        ${campo('Estado', '<select class="inp w-full" data-f="estado"><option value="activo">Activo</option><option value="cerrado">Cerrado</option></select>')}
        ${campo('Fecha de cierre', '<input type="date" class="inp w-full" data-f="fecha_cierre">')}
        <div class="flex items-end"><button class="btn w-full" id="btnLoteG">Guardar lote</button></div></div>` : '<p class="text-sm text-zinc-500">Primero crea un invernadero.</p>'}
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Lote</th><th>Invernadero</th><th>Variedad</th><th>Siembra</th><th>Plantas</th><th>Estado</th><th></th></tr></thead><tbody>
      ${lts.map(l => `<tr><td>${esc(l.nombre)}</td><td>${esc(l.invernadero)}</td><td>${esc(l.variedad)}</td><td>${l.fecha_siembra || ''}</td><td>${N(l.plantas)}</td>
      <td>${l.estado === 'activo' ? '🟢 activo' : '⚪ cerrado ' + (l.fecha_cierre || '')}</td>
      <td>${l.estado === 'activo' ? `<button class="btn2" onclick="cerrarLote(${l.id})">Cerrar</button> ` : ''}<button class="btn2" onclick='editLote(${JSON.stringify(l).replace(/'/g, "&#39;")})'>Editar</button> <button class="btn2" onclick="borrarReg('lotes',${l.id},'Se borrarán sus costos, cosechas y ventas.')">🗑</button></td></tr>`).join('') || '<tr><td colspan="7" class="text-zinc-500">Aún no hay lotes.</td></tr>'}</tbody></table></div></div>`;
    $('btnInv').onclick = async () => guardar('invernaderos', leer($('fInv')), () => RENDER.finca());
    if ($('btnLoteG')) $('btnLoteG').onclick = async () => guardar('lotes', leer($('fLote')), () => RENDER.finca());
};
async function guardar(tabla, d, despues) {
    try { await api('/api/finca/' + tabla, d); toast('✅ Guardado'); await cargarDatos(); if (despues) await despues(); }
    catch (e) { toast(e.message, false); }
}
function setForm(root, obj) { root.querySelectorAll('[data-f]').forEach(e => { if (obj[e.dataset.f] != null) e.value = obj[e.dataset.f]; }); root.dataset.id = obj.id || ''; }
function editInv(i) { setForm($('fInv'), i); $('fInv').scrollIntoView({ behavior: 'smooth' }); const b = $('btnInv'); b.textContent = 'Actualizar invernadero'; b.onclick = () => guardar('invernaderos', { ...leer($('fInv')), id: i.id }, () => RENDER.finca()); }
function editLote(l) { setForm($('fLote'), l); $('fLote').scrollIntoView({ behavior: 'smooth' }); const b = $('btnLoteG'); b.textContent = 'Actualizar lote'; b.onclick = () => guardar('lotes', { ...leer($('fLote')), id: l.id }, () => RENDER.finca()); }
async function cerrarLote(id) {
    const l = FD.lotes.find(x => x.id === id);
    if (!confirm(`¿Cerrar el lote «${l.nombre}»? Se usará su balance final para calcular el costo real por kg.`)) return;
    guardar('lotes', { ...l, estado: 'cerrado', fecha_cierre: hoyISO() }, () => RENDER.finca());
}
async function borrarReg(tabla, id, aviso) {
    if (!confirm('¿Eliminar este registro? ' + (aviso || ''))) return;
    try { await api(`/api/finca/${tabla}?id=${id}`, null, 'DELETE'); toast('Eliminado'); await cargarDatos(); const t = localStorage.getItem('tomateTab'); (RENDER[t] || RENDER.finca)(); }
    catch (e) { toast(e.message, false); }
}

/* ---------- REGISTROS ---------- */
let subReg = 'costos';
RENDER.registros = async function () {
    await cargarDatos();
    const cont = $('tab-registros');
    if (!FD.lotes.length) { cont.innerHTML = `<div class="card text-sm">Primero crea un invernadero y un lote en <a class="text-emerald-400 underline cursor-pointer" onclick="irA('finca')">Finca</a>.</div>`; return; }
    const tabs = [['costos', '💸 Costos'], ['cosechas', '🧺 Cosechas'], ['ventas', '🛒 Ventas']];
    cont.innerHTML = `<div class="flex gap-2 items-center flex-wrap">${tabs.map(([k, t]) => `<button class="${subReg === k ? 'btn' : 'btn2'}" onclick="subReg='${k}';RENDER.registros()">${t}</button>`).join('')}
        <button class="btn2 ml-auto" onclick="abrirChat('registrar')">📝 Registrar con texto o foto</button></div><div id="regCont" class="space-y-4"></div>`;
    await REG[subReg]();
};
const loteOpts = (sel) => FD.lotes.map(l => `<option value="${l.id}" ${l.id == sel ? 'selected' : ''}>${esc(l.invernadero)} · ${esc(l.nombre)}${l.estado === 'cerrado' ? ' (cerrado)' : ''}</option>`).join('');
const primerActivo = () => (lotesActivos()[0] || FD.lotes[0]).id;
const REG = {};
REG.costos = async function () {
    const filas = await api('/api/finca/costos');
    const cats = Object.keys(FD.categorias);
    const subs = c => (FD.categorias[c] || []).map(s => `<option>${esc(s)}</option>`).join('');
    $('regCont').innerHTML = `<div class="card space-y-3"><h3 class="font-semibold">Nuevo costo</h3>
      <div id="fCosto" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${campo('Fecha', `<input type="date" class="inp w-full" data-f="fecha" value="${hoyISO()}">`)}
        ${campo('Pertenece a', `<select class="inp w-full" data-f="destino"><optgroup label="Lote">${FD.lotes.map(l => `<option value="l${l.id}" ${l.id == primerActivo() ? 'selected' : ''}>${esc(l.invernadero)} · ${esc(l.nombre)}</option>`).join('')}</optgroup>
            <optgroup label="Todo el invernadero (se reparte entre lotes)">${FD.invernaderos.map(i => `<option value="i${i.id}">${esc(i.nombre)} (general)</option>`).join('')}</optgroup></select>`)}
        ${campo('Categoría', `<select class="inp w-full" data-f="categoria" id="selCat">${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select>`)}
        ${campo('Subcategoría', `<select class="inp w-full" data-f="subcategoria" id="selSub">${subs(cats[0])}</select>`)}
        ${campo('Tipo', '<select class="inp w-full" data-f="tipo"><option value="directo">Directo del cultivo</option><option value="indirecto">Indirecto / general</option><option value="mantenimiento">Mantenimiento invernadero</option></select>')}
        ${campo('Monto ($)', '<input type="number" class="inp w-full" data-f="monto">')}
        ${campo('Descripción', '<input class="inp w-full" data-f="descripcion" placeholder="opcional">')}
        <div class="flex items-end"><button class="btn w-full" id="btnCosto">Guardar costo</button></div></div></div>
      <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Fecha</th><th>Lote / invernadero</th><th>Categoría</th><th>Tipo</th><th>Descripción</th><th>Monto</th><th></th></tr></thead><tbody>
      ${filas.slice(0, 200).map(c => `<tr><td>${c.fecha}</td><td>${esc(c.lote || (c.invernadero + ' (general)'))}</td><td>${esc(c.categoria)}${c.subcategoria ? ' · ' + esc(c.subcategoria) : ''}</td><td>${c.tipo}</td><td>${esc(c.descripcion)}</td><td>${fmt(c.monto)}</td>
      <td><button class="btn2" onclick="borrarReg('costos',${c.id})">🗑</button></td></tr>`).join('') || '<tr><td colspan="7" class="text-zinc-500">Sin costos aún.</td></tr>'}</tbody></table></div>`;
    $('selCat').onchange = e => $('selSub').innerHTML = subs(e.target.value);
    $('btnCosto').onclick = () => {
        const d = leer($('fCosto')), dest = d.destino; delete d.destino;
        if (dest[0] === 'l') d.lote_id = +dest.slice(1); else d.invernadero_id = +dest.slice(1);
        guardar('costos', d, () => REG.costos());
    };
};
REG.cosechas = async function () {
    const filas = await api('/api/finca/cosechas');
    $('regCont').innerHTML = `<div class="card space-y-3"><h3 class="font-semibold">Nueva cosecha</h3>
      <div id="fCos" class="grid grid-cols-2 md:grid-cols-5 gap-3">
        ${campo('Fecha', `<input type="date" class="inp w-full" data-f="fecha" value="${hoyISO()}">`)}
        ${campo('Lote', `<select class="inp w-full" data-f="lote_id">${loteOpts(primerActivo())}</select>`)}
        ${campo('Kg cosechados', '<input type="number" class="inp w-full" data-f="kg">')}
        ${campo('Kg descarte', '<input type="number" class="inp w-full" data-f="kg_descarte" value="0">')}
        <div class="flex items-end"><button class="btn w-full" id="btnCos">Guardar</button></div></div></div>
      <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Fecha</th><th>Lote</th><th>Kg</th><th>Descarte</th><th></th></tr></thead><tbody>
      ${filas.slice(0, 200).map(c => `<tr><td>${c.fecha}</td><td>${esc(c.lote)}</td><td>${N(c.kg, 1)}</td><td>${N(c.kg_descarte, 1)}</td><td><button class="btn2" onclick="borrarReg('cosechas',${c.id})">🗑</button></td></tr>`).join('') || '<tr><td colspan="5" class="text-zinc-500">Sin cosechas aún.</td></tr>'}</tbody></table></div>`;
    $('btnCos').onclick = () => guardar('cosechas', leer($('fCos')), () => REG.cosechas());
};
REG.ventas = async function () {
    const filas = await api('/api/finca/ventas');
    $('regCont').innerHTML = `<div class="card space-y-3"><h3 class="font-semibold">Nueva venta</h3>
      <div id="fVen" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${campo('Fecha', `<input type="date" class="inp w-full" data-f="fecha" value="${hoyISO()}">`)}
        ${campo('Lote', `<select class="inp w-full" data-f="lote_id">${loteOpts(primerActivo())}</select>`)}
        ${campo('Destino', `<select class="inp w-full" data-f="destino">${DESTINOS.map(d => `<option>${d}</option>`).join('')}</select>`)}
        ${campo('Kg vendidos', '<input type="number" class="inp w-full" data-f="kg">')}
        ${campo('Precio ($/kg)', '<input type="number" class="inp w-full" data-f="precio_kg">')}
        ${campo('Flete total ($)', '<input type="number" class="inp w-full" data-f="flete" value="0">')}
        ${campo('Comisión total ($)', '<input type="number" class="inp w-full" data-f="comision" value="0">')}
        <div class="flex items-end"><button class="btn w-full" id="btnVen">Guardar venta</button></div></div>
      <p class="text-[11px] text-zinc-500">Las ventas a Garzón actualizan automáticamente «Garzón (mi precio)» en el comparador (promedio ponderado del día).</p></div>
      <div class="card overflow-x-auto"><table class="tbl"><thead><tr><th>Fecha</th><th>Lote</th><th>Destino</th><th>Kg</th><th>$/kg</th><th>Total</th><th></th></tr></thead><tbody>
      ${filas.slice(0, 200).map(v => `<tr><td>${v.fecha}</td><td>${esc(v.lote)}</td><td>${esc(v.destino)}</td><td>${N(v.kg, 1)}</td><td>${fmt(v.precio_kg)}</td><td>${fmt(v.kg * v.precio_kg)}</td><td><button class="btn2" onclick="borrarReg('ventas',${v.id})">🗑</button></td></tr>`).join('') || '<tr><td colspan="7" class="text-zinc-500">Sin ventas aún.</td></tr>'}</tbody></table></div>`;
    $('btnVen').onclick = () => guardar('ventas', leer($('fVen')), () => REG.ventas());
};

/* ---------- BALANCE ---------- */
let perBal = 'todo';
RENDER.balance = async function () {
    const hoy = new Date(); const ago = d => { const x = new Date(hoy); x.setDate(x.getDate() - d); return x.toISOString().slice(0, 10); };
    const rango = { todo: '', '30': '?desde=' + ago(30), '90': '?desde=' + ago(90), '365': '?desde=' + ago(365) }[perBal];
    const [b, cats] = await Promise.all([api('/api/balance' + rango), api('/api/balance/categorias' + rango)]);
    const f = b.finca;
    if (!b.lotes.length) { $('tab-balance').innerHTML = `<div class="card text-sm">Aún no hay lotes. Crea uno en <a class="text-emerald-400 underline cursor-pointer" onclick="irA('finca')">Finca</a> y registra costos y ventas.</div>`; return; }
    const c = (v, pos) => `<span class="${v >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${fmt(v)}</span>`;
    const totalCat = cats.reduce((a, x) => a + x[1], 0) || 1;
    $('tab-balance').innerHTML = `
    <div class="flex gap-2 text-xs items-center"><span class="text-zinc-400">Periodo:</span>${[['todo', 'Todo'], ['30', '30 días'], ['90', '90 días'], ['365', '1 año']].map(([k, t]) => `<button class="${perBal === k ? 'btn' : 'btn2'}" onclick="perBal='${k}';RENDER.balance()">${t}</button>`).join('')}</div>
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <div class="card"><div class="text-[11px] text-zinc-400">Ingresos</div><div class="text-2xl font-bold">${fmt(f.ingreso)}</div></div>
      <div class="card"><div class="text-[11px] text-zinc-400">Costos (incluye depreciación)</div><div class="text-2xl font-bold">${fmt(f.costo_total)}</div></div>
      <div class="card"><div class="text-[11px] text-zinc-400">Utilidad</div><div class="text-2xl font-bold">${c(f.utilidad)}</div></div>
      <div class="card"><div class="text-[11px] text-zinc-400">Costo por kg</div><div class="text-2xl font-bold">${fmt(f.costo_kg)}</div><div class="text-[11px] text-zinc-500">${N(f.kg_cosechados)} kg cosechados</div></div></div>
    <div class="card space-y-2"><h2 class="font-semibold">🏭 Por invernadero — ¿es rentable?</h2><div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Invernadero</th><th>Kg</th><th>kg/m²</th><th>Ingresos</th><th>Costos</th><th>Mantenimiento</th><th>Utilidad</th><th>$/m²</th><th>Costo/kg</th><th>ROI</th><th>Recupera inversión en</th></tr></thead><tbody>
      ${b.invernaderos.map(i => `<tr><td>${esc(i.nombre)}</td><td>${N(i.kg_cosechados)}</td><td>${i.kg_m2 ?? '–'}</td><td>${fmt(i.ingreso)}</td><td>${fmt(i.costo_total)}</td><td>${fmt(i.costo_mantenimiento)}</td><td>${c(i.utilidad)}</td><td>${i.utilidad_m2 != null ? fmt(i.utilidad_m2) : '–'}</td><td>${fmt(i.costo_kg)}</td>
      <td>${i.roi_pct != null ? i.roi_pct + '%' : '–'}</td><td>${i.recuperacion_meses ? i.recuperacion_meses + ' meses' : 'aún sin utilidad'}<div class="bg-zinc-800 rounded h-1.5 mt-1"><div class="bg-emerald-500 h-1.5 rounded" style="width:${Math.min(100, i.recuperado_pct || 0)}%"></div></div><div class="text-[10px] text-zinc-500">${i.recuperado_pct || 0}% recuperado</div></td></tr>`).join('')}</tbody></table></div>
      <p class="text-[11px] text-zinc-500">ROI y recuperación usan la utilidad antes de depreciación sobre la inversión, proyectada al ritmo mensual actual. Con pocos meses de datos son solo una guía.</p></div>
    <div class="card space-y-2"><h2 class="font-semibold">🌿 Por lote</h2><div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Lote</th><th>Estado</th><th>Días</th><th>Kg cosechados</th><th>kg/planta</th><th>Merma</th><th>Precio prom.</th><th>Costo/kg</th><th>Ingresos</th><th>Costos</th><th>Utilidad</th><th>Margen</th><th>Por vender</th></tr></thead><tbody>
      ${b.lotes.map(l => `<tr><td>${esc(l.nombre)}<div class="text-[10px] text-zinc-500">${esc(l.invernadero)}</div></td><td>${l.estado}</td><td>${l.dias}</td><td>${N(l.kg_cosechados)}</td><td>${l.kg_por_planta ?? '–'}</td><td>${l.merma_pct != null ? l.merma_pct + '%' : '–'}</td><td>${fmt(l.precio_prom_kg)}</td><td>${fmt(l.costo_kg)}</td><td>${fmt(l.ingreso)}</td><td>${fmt(l.costo_total)}</td><td>${c(l.utilidad)}</td><td>${l.margen_pct != null ? l.margen_pct + '%' : '–'}</td><td>${N(l.por_vender_kg)} kg</td></tr>`).join('')}</tbody></table></div></div>
    <div class="card space-y-2"><h2 class="font-semibold">¿En qué se va el dinero?</h2>
      ${cats.map(([k, v]) => `<div class="text-xs"><div class="flex justify-between"><span>${esc(k)}</span><span>${fmt(v)} · ${(v / totalCat * 100).toFixed(0)}%</span></div><div class="bg-zinc-800 rounded h-2"><div class="bg-emerald-600 h-2 rounded" style="width:${v / totalCat * 100}%"></div></div></div>`).join('') || '<div class="text-sm text-zinc-500">Sin costos en el periodo.</div>'}
      <p class="text-[11px] text-zinc-500">Solo costos registrados (no incluye depreciación).</p></div>`;
};

/* ---------- INSUMOS ---------- */
RENDER.insumos = async function () {
    const ins = await api('/api/finca/insumos');
    $('tab-insumos').innerHTML = `
    <div class="card space-y-3"><h2 class="font-semibold">🧪 Registrar precio de un insumo</h2>
      <p class="text-[11px] text-zinc-500">Cada compra o cotización queda en el historial. El sistema compara precio por unidad, por kg de nutriente/ingrediente activo y avisa cuándo está barato. No recomienda productos ni dosis: eso es del agrónomo.</p>
      <div id="fIns" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${campo('Insumo', `<input class="inp w-full" list="dlIns" data-f="nombre" placeholder="Ej: Nitrato de calcio"><datalist id="dlIns">${ins.map(i => `<option value="${esc(i.nombre)}">`).join('')}</datalist>`)}
        ${campo('Categoría', '<select class="inp w-full" data-f="categoria"><option>Nutrición</option><option>Sanidad</option><option>Otro</option></select>')}
        ${campo('Unidad', '<select class="inp w-full" data-f="unidad"><option>kg</option><option>L</option><option>bulto</option><option>unidad</option></select>')}
        ${campo('% activo / nutriente (opcional)', '<input class="inp w-full" data-f="contenido" placeholder="Ej: 15.5 % N">')}
        ${campo('Proveedor', '<input class="inp w-full" data-f="proveedor">')}
        ${campo('Cantidad comprada', '<input type="number" step="any" class="inp w-full" data-f="cantidad">')}
        ${campo('Precio total ($)', '<input type="number" class="inp w-full" data-f="precio">')}
        ${campo('Fecha', `<input type="date" class="inp w-full" data-f="fecha" value="${hoyISO()}">`)}</div>
      <button class="btn" id="btnIns">Guardar precio</button></div>
    <div class="card overflow-x-auto space-y-2"><h2 class="font-semibold">Comparativo de precios</h2><table class="tbl"><thead><tr><th>Insumo</th><th>Último $/unid</th><th>Promedio</th><th>Vs. promedio</th><th>$/kg activo</th><th>Más barato en</th><th>Fecha</th><th></th></tr></thead><tbody>
      ${ins.map(i => { const v = i.var_vs_prom_pct; const cv = v == null ? '' : v >= 10 ? 'text-rose-400' : v <= -10 ? 'text-emerald-400' : '';
        return `<tr><td>${esc(i.nombre)}<div class="text-[10px] text-zinc-500">${esc(i.categoria)} · ${esc(i.unidad)} ${esc(i.contenido || '')}</div></td><td>${i.ultimo_precio_unidad != null ? fmt(i.ultimo_precio_unidad) : '–'}</td><td>${i.prom_unidad != null ? fmt(i.prom_unidad) : '–'}</td><td class="${cv}">${v != null ? (v > 0 ? '+' : '') + v + '%' : '–'}</td><td>${i.precio_por_kg_activo ? fmt(i.precio_por_kg_activo) : '–'}</td><td>${esc(i.proveedor_barato || '–')}</td><td>${i.ultima_fecha || ''}</td>
        <td><button class="btn2" onclick="verHist(${i.id})">Historial</button> <button class="btn2" onclick="borrarReg('insumos',${i.id},'Se borra todo su historial.')">🗑</button></td></tr>
        <tr id="h${i.id}" class="hidden"><td colspan="8" class="text-left">${linea(i.historial.slice().reverse().map((h, k) => ({ x: k, y: h.precio_unidad })), { alto: 90 })}
        ${i.historial.map(h => `<span class="text-[11px] text-zinc-400 mr-3">${h.fecha} · ${fmt(h.precio_unidad)}/${esc(i.unidad)} · ${esc(h.proveedor || 's/prov.')}</span>`).join('')}</td></tr>`; }).join('') || '<tr><td colspan="8" class="text-zinc-500">Registra los precios que consigues: con 3 o más datos por insumo el sistema empieza a avisarte cuándo comprar.</td></tr>'}</tbody></table></div>`;
    $('btnIns').onclick = () => guardar('insumo_precios', leer($('fIns')), () => RENDER.insumos());
};
const verHist = id => $('h' + id).classList.toggle('hidden');

/* ---------- SIEMBRA ---------- */
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
RENDER.siembra = async function () {
    const dc = localStorage.getItem('tomateDC') || 85, dd = localStorage.getItem('tomateDD') || 120;
    const [e, c] = await Promise.all([api('/api/estacionalidad'), api(`/api/calendario?dias_a_cosecha=${dc}&dias_cosecha=${dd}`)]);
    if (e.error || c.error) { $('tab-siembra').innerHTML = `<div class="card text-sm">${esc(e.error || c.error)}</div>`; return; }
    const mejores = c.mejores.map((m, i) => `<div class="card ${i === 0 ? 'border-emerald-600' : ''}"><div class="text-[11px] text-zinc-400">${i === 0 ? '⭐ Mejor ventana' : 'Alternativa ' + (i + 1)}</div><div class="text-lg font-bold">Sembrar ~ ${m.siembra}</div>
        <div class="text-xs text-zinc-300">Cosecha ${m.cosecha_desde} → ${m.cosecha_hasta}</div><div class="text-xs ${m.indice >= 1 ? 'text-emerald-400' : 'text-rose-400'}">Precio típico ${m.indice >= 1 ? '+' : ''}${((m.indice - 1) * 100).toFixed(0)}% vs. promedio del año</div></div>`).join('');
    $('tab-siembra').innerHTML = `
    <div class="card space-y-2"><div class="flex flex-wrap justify-between gap-2"><h2 class="font-semibold">🌱 ¿Cuándo sembrar?</h2><span class="text-xs px-2 py-1 rounded border ${e.confianza === 'alta' ? 'border-emerald-700 text-emerald-300' : 'border-amber-600 text-amber-300'}">Confianza ${e.confianza}: ${e.anios_datos.join(', ')}</span></div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">${mejores}</div>
      <div class="flex flex-wrap gap-3 items-end text-xs pt-2">${campo('Días trasplante → 1ª cosecha', `<input type="number" id="sDC" class="inp w-28" value="${dc}">`)}${campo('Duración de la cosecha (días)', `<input type="number" id="sDD" class="inp w-28" value="${dd}">`)}<button class="btn2" id="btnCiclo">Recalcular</button></div>
      <p class="text-[11px] text-zinc-500">${esc(c.nota)}</p></div>
    <div class="card space-y-1"><h3 class="font-semibold text-sm">Precio típico de la cosecha según fecha de siembra (próximos 365 días)</h3>
      ${linea(c.curva.map((p, i) => ({ x: i, y: p.indice })), { alto: 150, marcas: c.mejores.map(m => ({ x: c.curva.findIndex(p => p.siembra === m.siembra), y: m.indice })) })}
      <div class="flex justify-between text-[10px] text-zinc-500"><span>${c.curva[0].siembra}</span><span>${c.curva[182].siembra}</span><span>${c.curva[364].siembra}</span></div></div>
    <div class="card space-y-1"><h3 class="font-semibold text-sm">Estacionalidad mensual del precio (Cali, Bogotá, Neiva)</h3>
      ${barras(e.meses.map(m => m.indice), MESES, { base: 1 })}
      <p class="text-[11px] text-zinc-500">Verde: mes con precio sobre el promedio del año (poca oferta). Rojo: por debajo (mucha oferta). ${esc(e.nota)}</p></div>
    <div class="card space-y-2"><h3 class="font-semibold text-sm">📅 Siembra escalonada para producir todo el año</h3>
      <p class="text-xs text-zinc-300">Con ${c.escalonada.length} invernadero(s) y un ciclo de ${c.dias_a_cosecha + c.dias_cosecha} días, sembrar cada ${c.paso_dias} días da un flujo continuo:</p>
      <ul class="text-sm space-y-1">${c.escalonada.map(x => `<li>Invernadero ${x.invernadero}: sembrar hacia <b>${x.siembra}</b></li>`).join('')}</ul>
      <p class="text-[11px] text-zinc-500">Para cubrir 365 días con ciclos de ~${c.dias_a_cosecha + c.dias_cosecha} días necesitas ~${Math.ceil(365 / c.paso_dias) > 0 ? Math.max(1, Math.round((c.dias_a_cosecha + c.dias_cosecha) / 60)) : 1}+ invernaderos con siembras cada ~60 días.</p></div>
    <div class="card space-y-1"><h3 class="font-semibold text-sm">Precio mensual histórico ($/kg)</h3>${linea(e.serie_mensual.map((p, i) => ({ x: i, y: p.precio })), { alto: 150, color: '#60a5fa' })}
      <div class="flex justify-between text-[10px] text-zinc-500"><span>${e.serie_mensual[0].mes}</span><span>${e.serie_mensual[e.serie_mensual.length - 1].mes}</span></div></div>`;
    $('btnCiclo').onclick = () => { try { localStorage.setItem('tomateDC', $('sDC').value); localStorage.setItem('tomateDD', $('sDD').value); } catch (e) { } RENDER.siembra(); };
};

/* ---------- ASISTENTE (drawer) ---------- */
let modo = 'preguntar', historial = [], foto = null;
const CHIPS = {
    preguntar: [['🌱 ¿Cuándo sembrar?', 'Según los precios históricos y mis invernaderos, ¿cuándo me conviene sembrar?'],
    ['💰 ¿Cuándo vender?', 'Con mi costo real, ¿conviene vender hoy o esperar? Mira la tendencia.'],
    ['🧪 ¿Comprar insumos?', '¿Qué insumos conviene comprar ahora y cuáles esperar según sus precios registrados?'],
    ['🚚 ¿A dónde vender?', '¿A dónde me conviene llevar la próxima carga? Usa mi costo real.'],
    ['⚠️ ¿Qué riesgos veo?', 'Resume los riesgos y alertas más importantes de mi finca y de los precios hoy.'],
    ['📍 ¿Garzón o sacar?', 'Con mis costos actuales, ¿me conviene más vender todo en Garzón o sacarlo a una ciudad? Dame veredicto, diferencia por viaje y el precio mínimo en Garzón que igualaría.']],
    registrar: [['💸 Un costo', 'Pagué 300.000 de jornales hoy'], ['🧺 Una cosecha', 'Hoy cosechamos 850 kg, 20 kg de descarte'],
    ['🛒 Una venta', 'Vendí 600 kg en Garzón a 2.300 el kilo'], ['🧪 Precio insumo', 'Compré 50 kg de nitrato de calcio en 145.000 en Agroinsumos'],
    ['📍 Precio Garzón', 'Hoy el tomate en Garzón está a 2.400 el kilo']]
};
function cerrarChat() { $('drawer').classList.add('translate-x-full'); }
function abrirChat(m) { $('drawer').classList.remove('translate-x-full'); if (m) fijarModo(m); $('chatInput').focus(); fetch('/api/uso').then(r => r.json()).then(u => pintarUso(u, null, 'x')).catch(() => { }); }
function fijarModo(m) {
    modo = m;
    $('modoPreguntar').className = 'flex-1 rounded py-1.5 ' + (m === 'preguntar' ? 'bg-emerald-700 text-white' : 'bg-zinc-800 text-zinc-300');
    $('modoRegistrar').className = 'flex-1 rounded py-1.5 ' + (m === 'registrar' ? 'bg-emerald-700 text-white' : 'bg-zinc-800 text-zinc-300');
    $('btnFoto').classList.toggle('hidden', m !== 'registrar');
    $('chatInput').placeholder = m === 'preguntar' ? 'Pregunta lo que quieras sobre precios, costos, siembra…' : 'Escribe el registro (o adjunta foto de factura/cuaderno)…';
    $('chips').innerHTML = CHIPS[m].map(([t, q], i) => `<button class="chip" data-i="${i}">${t}</button>`).join('');
    $('chips').querySelectorAll('button').forEach(b => b.onclick = () => {
        const q = CHIPS[m][b.dataset.i][1];
        if (m === 'preguntar') { $('chatInput').value = q; enviar(); } else { $('chatInput').value = q; $('chatInput').focus(); }
    });
}
function msg(rol, html) {
    const d = document.createElement('div');
    d.className = rol === 'user' ? 'ml-8 bg-emerald-900/50 rounded-lg p-2 whitespace-pre-wrap' : 'mr-4 bg-zinc-800 rounded-lg p-2 whitespace-pre-wrap';
    d.innerHTML = html; $('chatMsgs').appendChild(d); $('chatMsgs').scrollTop = 1e9; return d;
}
async function enviar() {
    const t = $('chatInput').value.trim();
    if (!t && !foto) return;
    $('chatInput').value = ''; $('btnEnviar').disabled = true;
    msg('user', esc(t) + (foto ? '<div class="text-[11px] text-emerald-300">📷 foto adjunta</div>' : ''));
    const w = msg('bot', 'Pensando…');
    try {
        if (modo === 'preguntar') {
            const j = await api('/api/chat', { pregunta: t, historial, costos: costosApp() });
            w.textContent = j.texto; historial.push({ role: 'user', content: t }, { role: 'assistant', content: j.texto }); historial = historial.slice(-8);
            pintarUso(j.uso, j.usd, 'x');
        } else {
            const j = await api('/api/capturar', { texto: t, imagen: foto ? foto.b64 : null, media_type: foto ? foto.tipo : null });
            foto = null; $('fotoPrev').classList.add('hidden');
            pintarUso(j.uso, j.usd, 'x'); tarjetas(w, j);
        }
    } catch (e) { w.textContent = '⚠️ ' + e.message; }
    finally { $('btnEnviar').disabled = false; }
}
const CAMPOS_EDIT = { costo: ['monto'], cosecha: ['kg', 'kg_descarte'], venta: ['kg', 'precio_kg'], precio_insumo: ['cantidad', 'precio'], precio_garzon: ['precio_kg'] };
function tarjetas(w, j) {
    if (!j.registros.length) { w.textContent = 'No entendí ningún registro. ' + (j.no_entendido || 'Intenta con más detalle: qué, cuánto, cuándo.'); return; }
    w.innerHTML = `<div class="text-xs text-zinc-300 mb-2">Esto entendí. Revisa y confirma antes de guardar:</div><div class="space-y-2" id="tj"></div>
        <div class="flex gap-2 mt-2"><button class="btn" id="btnConf">✅ Guardar seleccionados</button><button class="btn2" id="btnDesc">Descartar</button></div>`;
    const tj = w.querySelector('#tj');
    j.registros.forEach((r, i) => {
        const falta = ['costo', 'cosecha', 'venta'].includes(r.tipo) && !r.lote_id && !r.invernadero_id;
        const d = document.createElement('div'); d.className = 'border border-zinc-700 rounded-lg p-2 space-y-1'; d.dataset.i = i;
        d.innerHTML = `<label class="flex gap-2 items-start"><input type="checkbox" class="sel mt-1" checked><span><b>${esc(r.resumen)}</b><br><span class="text-[11px] text-zinc-400">${r.fecha}${r.confianza === 'baja' ? ' · ⚠️ poca certeza' : ''}</span></span></label>
            ${r.pregunta ? `<div class="text-[11px] text-amber-300">❓ ${esc(r.pregunta)}</div>` : ''}
            ${falta ? `<select class="inp w-full lote">${loteOpts(primerActivo())}</select>` : ''}
            <div class="flex gap-2 flex-wrap">${(CAMPOS_EDIT[r.tipo] || []).map(k => `<label class="text-[10px] text-zinc-400">${k}<input type="number" step="any" class="inp w-24 ml-1 ed" data-k="${k}" value="${r[k] ?? ''}"></label>`).join('')}</div>`;
        tj.appendChild(d);
    });
    w.querySelector('#btnDesc').onclick = () => w.textContent = 'Descartado. No se guardó nada.';
    w.querySelector('#btnConf').onclick = async () => {
        const regs = [];
        tj.querySelectorAll('[data-i]').forEach(d => {
            if (!d.querySelector('.sel').checked) return;
            const r = { ...j.registros[+d.dataset.i] }; delete r.resumen;
            const l = d.querySelector('.lote'); if (l) r.lote_id = +l.value;
            d.querySelectorAll('.ed').forEach(e => { if (e.value !== '') r[e.dataset.k] = +e.value; });
            regs.push(r);
        });
        if (!regs.length) return toast('No hay nada seleccionado', false);
        try {
            const res = await api('/api/confirmar', { registros: regs });
            w.innerHTML = `✅ Guardados: ${res.guardados}` + (res.errores.length ? `<div class="text-rose-300 text-xs mt-1">${res.errores.map(esc).join('<br>')}</div>` : '');
            await cargarDatos(); const t = localStorage.getItem('tomateTab'); if (RENDER[t]) RENDER[t]();
            if (typeof recargar === 'function') recargar();
        } catch (e) { toast(e.message, false); }
    };
}
function reducirFoto(file) {
    return new Promise((ok, mal) => {
        const img = new Image(), url = URL.createObjectURL(file);
        img.onload = () => {
            const k = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement('canvas');
            c.width = img.width * k; c.height = img.height * k; c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
            URL.revokeObjectURL(url); ok({ b64: c.toDataURL('image/jpeg', .85).split(',')[1], tipo: 'image/jpeg' });
        };
        img.onerror = () => mal(new Error('No pude leer la imagen')); img.src = url;
    });
}
$('fab').onclick = () => abrirChat();
$('btnCerrarChat').onclick = cerrarChat;
$('modoPreguntar').onclick = () => fijarModo('preguntar');
$('modoRegistrar').onclick = () => fijarModo('registrar');
$('btnEnviar').onclick = enviar;
$('chatInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); } });
$('btnFoto').onclick = () => $('fileFoto').click();
$('fileFoto').onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try { foto = await reducirFoto(f); $('fotoPrev').textContent = '📷 ' + f.name + ' lista para enviar'; $('fotoPrev').classList.remove('hidden'); }
    catch (er) { toast(er.message, false); }
};
fijarModo('preguntar');
msg('bot', '¡Hola! Soy tu asistente. Pregúntame por precios, costos, siembra o insumos, o cámbiate a <b>Registrar</b> para anotar costos, cosechas y ventas escribiendo o con una foto. Siempre te muestro lo que entendí antes de guardar.');

/* ---------- arranque ---------- */
(function () {
    let t = 'hoy'; try { t = localStorage.getItem('tomateTab') || 'hoy'; } catch (e) { }
    cargarDatos().catch(() => { }).finally(() => mostrar(t));
    api('/api/alertas').then(pintarBadge).catch(() => { });
})();
window.addEventListener('load', () => aplicarCostoReal().catch(() => { }));

{ const _rec = recargar; recargar = async function () { await _rec.apply(this, arguments); cargarSemaforo(); }; }
