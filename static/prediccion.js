/* Pestaña Predicción: pronóstico del día siguiente, calificación y aprendizaje */
'use strict';
let varPred = 'Tomate chonto';
const fechaLarga = f => new Date(f + 'T12:00:00').toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' });

RENDER.prediccion = async function () {
    const [g, hist] = await Promise.all([
        api('/api/prediccion', { variedad: varPred, costos: costosApp() }),
        api('/api/prediccion/historial?limite=40')]);
    const d = g.decision;
    const cls = { sacar: 'border-emerald-600 bg-emerald-950/40', dudoso: 'border-amber-600 bg-amber-950/30', garzon: 'border-sky-600 bg-sky-950/30' };
    const conf = { alta: 'text-emerald-400', media: 'text-amber-300', baja: 'text-rose-300' };
    const pend = hist.filter(r => !r.juicio && r.objetivo <= hoyISO());
    const ap = g.aprendizaje;
    $('tab-prediccion').innerHTML = `
    <div class="flex flex-wrap gap-2 items-center"><h2 class="font-semibold">🔮 Precio de mañana: <span class="text-emerald-400">${fechaLarga(g.objetivo)}</span></h2>
      <select id="selVarPred" class="inp ml-auto">${VARIEDADES.map(v => `<option ${v === varPred ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
    ${g.fin_de_semana ? '<div class="card text-xs text-amber-300">Mañana es fin de semana: el DANE no publica esos días, por eso no podrás verificar este pronóstico con un precio oficial.</div>' : ''}
    ${d.disponible ? `<div class="border rounded-xl p-4 ${cls[d.veredicto]} space-y-1">
        <div class="text-lg font-bold">${esc(d.texto)}</div>
        <div class="text-sm text-zinc-200">${esc(d.mejor.ciudad)}: neto esperado <b>${fmt(d.mejor.neto_kg)}/kg</b> (ya descontados merma y flete de ${fmt(d.mejor.flete)}) contra <b>${fmt(d.garzon_pred)}/kg</b> en Garzón. Diferencia ${d.mejor.ventaja_kg >= 0 ? '+' : ''}${fmt(d.mejor.ventaja_kg)}/kg, con una incertidumbre de ±${fmt(d.mejor.incertidumbre_kg)}.</div>
        <div class="text-sm">Probabilidad de que sacarlo rinda más que venderlo en Garzón: <b>${d.mejor.prob_mejor}%</b></div>
        <div class="text-[11px] text-zinc-400">${d.opciones.map(o => `${esc(o.ciudad)}: ${o.prob_mejor}% (${o.ventaja_kg >= 0 ? '+' : ''}${fmt(o.ventaja_kg)}/kg)`).join(' · ')}</div></div>`
        : `<div class="card text-sm">${esc(d.motivo)}</div>`}
    <div class="card overflow-x-auto space-y-2"><h3 class="font-semibold text-sm">Pronóstico por mercado ($/kg)</h3>
      <table class="tbl"><thead><tr><th>Mercado</th><th>Último dato</th><th>Pronóstico</th><th>Rango probable (80%)</th><th>Error típico</th><th>Confianza</th><th>Método</th></tr></thead><tbody>
      ${g.predicciones.map(p => `<tr><td>${esc(p.ciudad)}</td><td>${fmt(p.ultimo_precio)}<div class="text-[10px] text-zinc-500">${p.ultimo_dato}</div></td><td><b>${fmt(p.pred)}</b></td><td>${fmt(p.bajo)} – ${fmt(p.alto)}</td><td>${p.error_tipico_pct != null ? '±' + p.error_tipico_pct + '%' : '–'}</td><td class="${conf[p.confianza]}">${p.confianza}</td><td class="text-[11px]">${esc(p.modelo_nombre)}<div class="text-[10px] text-zinc-500">rango: ${esc(p.fuente_intervalo)}</div></td></tr>`).join('')}</tbody></table>
      <p class="text-[11px] text-zinc-500">Es el precio mayorista publicado por el DANE, no necesariamente el que te pagarán. Si el último dato tiene más de un día de atraso, el pronóstico es menos preciso: actualiza el DANE cada mañana.</p></div>
    <div class="card space-y-2"><h3 class="font-semibold text-sm">¿Qué tan confiable es? (prueba con los últimos 300 días de datos reales)</h3>
      <table class="tbl"><thead><tr><th>Mercado</th><th>Con 1 día de atraso</th><th>Con 3 días</th><th>Con 5 días</th></tr></thead><tbody>
      ${g.backtest.map(b => `<tr><td>${esc(b.ciudad)}</td>${b.horizontes.map(h => `<td>±${h.mape}% <span class="text-[10px] text-zinc-500">· ${h.dentro10}% acierta a ±10%</span></td>`).join('')}</tr>`).join('')}</tbody></table>
      <p class="text-[11px] text-zinc-500">Leído así: «±6%» significa que, en promedio, el pronóstico se desvió 6% del precio real. El error crece rápido con los días sin dato. Ningún método estadístico supera por mucho a «el precio de ayer»; por eso el valor real está en el rango y en la probabilidad, no en el número exacto.</p></div>
    <div class="card space-y-2"><h3 class="font-semibold text-sm">✅ Califica los pronósticos pasados <span class="text-zinc-500 font-normal">(así el sistema aprende)</span></h3>
      ${pend.length ? pend.slice(0, 12).map(filaJuicio).join('') : '<div class="text-sm text-zinc-500">No hay pronósticos pendientes de calificar. Aparecerán aquí cuando pase el día pronosticado.</div>'}</div>
    <div class="card space-y-2"><h3 class="font-semibold text-sm">🧠 Lo que ha aprendido el sistema</h3>
      <div class="overflow-x-auto"><table class="tbl"><thead><tr><th>Mercado</th><th>Pronósticos verificados</th><th>Error medio</th><th>Real dentro del rango</th><th>Sesgo</th></tr></thead><tbody>
      ${ap.ciudades.map(c => `<tr><td>${esc(c.ciudad)}</td><td>${c.n_real}</td><td>${c.n_real ? c.error_medio_pct + '%' : '–'}</td><td>${c.n_real ? c.en_rango_pct + '%' : '–'}</td><td>${c.n_real ? (c.sesgo_pct > 0 ? '+' : '') + c.sesgo_pct + '%' : '–'}</td></tr>`).join('')}</tbody></table></div>
      <p class="text-xs text-zinc-300">Tu criterio: ${ap.buenas} buenas y ${ap.malas} malas. Para ti, un pronóstico es «bueno» con error de hasta <b>${ap.tolerancia_pct}%</b>${ap.acuerdo_pct != null ? `; coincide con la calificación automática el ${ap.acuerdo_pct}% de las veces` : ''}.</p>
      <ul class="text-[11px] text-zinc-500 list-disc ml-4"><li>Cada día guardo el pronóstico de todos los métodos y, cuando llega el precio real, mido cuál acertó más. Con más datos elijo el mejor por mercado.</li>
      <li>Con 15 o más pronósticos verificados, el rango se calcula con tus propios aciertos y fallos, no con el historial.</li></ul></div>
    <div class="card overflow-x-auto"><h3 class="font-semibold text-sm mb-2">Historial</h3><table class="tbl"><thead><tr><th>Día</th><th>Mercado</th><th>Pronóstico</th><th>Rango</th><th>Real</th><th>Error</th><th>Calificación</th></tr></thead><tbody>
      ${hist.map(r => `<tr><td>${r.objetivo}</td><td>${esc(r.ciudad)}</td><td>${fmt(r.pred)}</td><td>${fmt(r.bajo)} – ${fmt(r.alto)}</td><td>${r.real ? fmt(r.real) : '–'}</td><td>${r.error_pct != null ? (r.error_pct > 0 ? '+' : '') + r.error_pct + '%' : '–'}</td><td>${r.juicio === 'buena' ? '👍' : r.juicio === 'mala' ? '👎' : r.calif_auto ? '<span class="text-zinc-500">auto: ' + r.calif_auto + '</span>' : '–'}</td></tr>`).join('') || '<tr><td colspan="7" class="text-zinc-500">Aún sin historial.</td></tr>'}</tbody></table></div>`;
    $('selVarPred').onchange = e => { varPred = e.target.value; RENDER.prediccion(); };
};

function filaJuicio(r) {
    const falta = r.real == null;
    const info = falta ? 'sin precio real todavía'
        : `real <b>${fmt(r.real)}</b> · error ${r.error_pct > 0 ? '+' : ''}${r.error_pct}%${r.calif_auto ? ' · auto: ' + r.calif_auto : ''}`;
    return `<div class="border border-zinc-700 rounded-lg p-2 text-sm"><div class="flex flex-wrap justify-between gap-2"><div><b>${esc(r.ciudad)}</b> · ${fechaLarga(r.objetivo)}
      <div class="text-xs text-zinc-400">Pronóstico ${fmt(r.pred)} (${fmt(r.bajo)} – ${fmt(r.alto)}) · ${info}</div></div>
      <div class="flex gap-1 items-center">${falta && r.ciudad === 'Garzón' ? `<input type="number" id="re${r.id}" class="inp w-24" placeholder="Real $/kg">` : ''}
      <button class="btn2" onclick="calificar(${r.id},'buena')">👍 Buena</button><button class="btn2" onclick="calificar(${r.id},'mala')">👎 Mala</button></div></div></div>`;
}

async function calificar(id, juicio) {
    const inp = document.getElementById('re' + id);
    try {
        await api('/api/prediccion/juicio', { id, juicio, real: inp && inp.value ? inp.value : null });
        toast('Gracias, el sistema lo tendrá en cuenta');
        RENDER.prediccion();
    } catch (e) { toast(e.message, false); }
}
