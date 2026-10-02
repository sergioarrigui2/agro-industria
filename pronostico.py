"""Pronóstico del precio de mañana (ciudades DANE y Garzón), registro de predicciones y aprendizaje."""
import bisect
import json
import math
import os
import sqlite3
import statistics as st
from datetime import date, timedelta
from functools import lru_cache

import local
import sipsa

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prediccion.db")
CIUDADES = ("Bogotá", "Cali", "Neiva")
HORIZONTES = (1, 2, 3, 5, 7)
NOMBRES = {"ultimo": "Último precio", "ma3": "Promedio 3 días", "ma7": "Promedio 7 días",
           "ema": "Promedio ponderado", "dia_semana": "Con efecto del día de la semana",
           "relacion": "Relación con Neiva"}


def _con():
    c = sqlite3.connect(RUTA)
    c.row_factory = sqlite3.Row
    return c


def iniciar():
    c = _con()
    c.execute("""CREATE TABLE IF NOT EXISTS predicciones(
        id INTEGER PRIMARY KEY, creada TEXT, objetivo TEXT, ciudad TEXT, variedad TEXT, horizonte INTEGER,
        ultimo_dato TEXT, modelo TEXT, pred REAL, bajo REAL, alto REAL, modelos TEXT, real REAL, error_pct REAL,
        en_rango INTEGER, juicio TEXT, nota TEXT, UNIQUE(objetivo, ciudad, variedad))""")
    c.commit()
    c.close()


iniciar()


def _q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * p
    a, b = int(math.floor(i)), int(math.ceil(i))
    return xs[a] + (xs[b] - xs[a]) * (i - a)


def _mean(xs):
    return sum(xs) / len(xs)


# ---------- series y modelos ----------
def _serie(ciudad, variedad):
    conn = sipsa.conectar()
    try:
        rows = conn.execute("""SELECT fecha, AVG(precio_kg) FROM precios WHERE producto=? AND ciudad=? AND atipico=0
                               AND minorista=0 GROUP BY fecha ORDER BY fecha""", (variedad, ciudad)).fetchall()
    finally:
        conn.close()
    f = [r[0] for r in rows]
    v = [float(r[1]) for r in rows]
    o = [date.fromisoformat(x).toordinal() for x in f]
    wd = [date.fromordinal(x).weekday() for x in o]
    rat = [None] * len(v)
    for i in range(7, len(v)):
        rat[i] = v[i] / _mean(v[i - 7:i])
    return {"f": f, "v": v, "o": o, "wd": wd, "rat": rat}


def _modelos(s, k, wd_objetivo):
    v = s["v"]
    h = v[:k + 1]
    ema = h[max(0, k - 9)]
    for x in h[max(0, k - 9) + 1:]:
        ema = 0.5 * x + 0.5 * ema
    ma7 = _mean(h[-7:])
    facs = [s["rat"][i] for i in range(max(7, k - 250), k + 1) if s["wd"][i] == wd_objetivo and s["rat"][i]]
    f = st.median(facs) if len(facs) >= 4 else 1.0
    return {"ultimo": h[-1], "ma3": _mean(h[-3:]), "ma7": ma7, "ema": ema, "dia_semana": ma7 * f}


@lru_cache(maxsize=64)
def _bt(ciudad, variedad, h, hasta, n=300):
    s = _serie(ciudad, variedad)
    pares = {}
    for j in range(max(10, len(s["v"]) - n), len(s["v"])):
        k = bisect.bisect_right(s["o"], s["o"][j] - h) - 1
        if k < 9:
            continue
        real = s["v"][j]
        for m, p in _modelos(s, k, s["wd"][j]).items():
            pares.setdefault(m, []).append((p, real))
    return pares


def _metricas(pares):
    if not pares:
        return None
    err = [abs(p - r) / r for p, r in pares]
    return {"n": len(pares), "mape": _mean(err) * 100, "mae": _mean([abs(p - r) for p, r in pares]),
            "dentro10": sum(e <= 0.10 for e in err) / len(err) * 100,
            "sesgo": st.median([(p - r) / r for p, r in pares]) * 100}


# ---------- registro y aprendizaje ----------
def _log_pares(ciudad, variedad):
    c = _con()
    try:
        rows = c.execute("SELECT modelos, real FROM predicciones WHERE ciudad=? AND variedad=? AND real IS NOT NULL",
                         (ciudad, variedad)).fetchall()
    finally:
        c.close()
    out = {}
    for r in rows:
        for m, p in json.loads(r["modelos"] or "{}").items():
            out.setdefault(m, []).append((p, r["real"]))
    return out


def _elegir(preds, bt, log):
    """Modelo con menor error: mezcla el historial simulado con los aciertos reales ya registrados."""
    mejor, mejor_s = None, None
    for m in preds:
        mb = _metricas(bt.get(m))
        if not mb:
            continue
        rl = log.get(m, [])
        n = len(rl)
        mr = _mean([abs(p - r) / r for p, r in rl]) * 100 if n else 0
        score = (n * mr + 8 * mb["mape"]) / (n + 8)
        if mejor_s is None or score < mejor_s:
            mejor, mejor_s = m, score
    return mejor


def _intervalo(m, p, bt, log):
    rl = log.get(m, [])
    if len(rl) >= 15:
        pares, fuente = rl, "aprendida con tus registros"
    else:
        pares, fuente = bt.get(m, []), "historial 2023-hoy"
    if len(pares) < 8:
        return p, p * 0.88, p * 1.12, "estimada (pocos datos)", None
    r = [real / pred for pred, real in pares if pred]
    return p * _q(r, .5), p * _q(r, .1), p * _q(r, .9), fuente, _metricas(pares)


def _confianza(mape, n):
    if mape is None or n < 15:
        return "baja"
    return "alta" if mape <= 6 else ("media" if mape <= 12 else "baja")


def predecir_ciudad(ciudad, variedad, objetivo):
    s = _serie(ciudad, variedad)
    if len(s["v"]) < 15:
        return None
    k = len(s["v"]) - 1
    ultimo = s["f"][k]
    h = max(1, (objetivo - date.fromisoformat(ultimo)).days)
    hb = next((x for x in HORIZONTES if x >= h), HORIZONTES[-1])
    preds = _modelos(s, k, objetivo.weekday())
    bt = _bt(ciudad, variedad, hb, ultimo)
    log = _log_pares(ciudad, variedad)
    m = _elegir(preds, bt, log)
    c, lo, hi, fuente, met = _intervalo(m, preds[m], bt, log)
    return {"ciudad": ciudad, "variedad": variedad, "objetivo": objetivo.isoformat(), "horizonte": h,
            "ultimo_dato": ultimo, "ultimo_precio": round(s["v"][k]), "modelo": m, "modelo_nombre": NOMBRES[m],
            "pred": round(c), "bajo": round(lo), "alto": round(hi), "fuente_intervalo": fuente,
            "error_tipico_pct": round(met["mape"], 1) if met else None,
            "confianza": _confianza(met["mape"] if met else None, met["n"] if met else 0),
            "modelos": {k_: round(x) for k_, x in preds.items()}, "_neiva_serie": s if ciudad == "Neiva" else None}


def _garzon_obs():
    return sorted(((r["fecha"], r["precio_kg"]) for r in local.listar()))


def _gz_modelos(hist, ratios, neiva_ref):
    p = [x[1] for x in hist]
    out = {"ultimo": p[-1], "ma3": _mean(p[-3:])}
    if len(ratios) >= 3 and neiva_ref:
        out["relacion"] = st.median(ratios[-20:]) * neiva_ref
    return out


def predecir_garzon(variedad, objetivo, neiva_central):
    obs = _garzon_obs()
    if len(obs) < 3:
        return None
    sn = _serie("Neiva", variedad)
    nv = dict(zip(sn["f"], sn["v"]))

    def razones(h):
        return [g / nv[f] for f, g in h if f in nv and nv[f]]

    def neiva_antes(fecha):
        k = bisect.bisect_left(sn["f"], fecha) - 1
        return _mean(sn["v"][max(0, k - 2):k + 1]) if k >= 2 else None

    bt = {}
    for j in range(3, len(obs)):
        pr = _gz_modelos(obs[:j], razones(obs[:j]), neiva_antes(obs[j][0]))
        for m, p in pr.items():
            bt.setdefault(m, []).append((p, obs[j][1]))
    preds = _gz_modelos(obs, razones(obs), neiva_central)
    log = _log_pares("Garzón", variedad)
    m = _elegir(preds, bt, log) or "ultimo"
    c, lo, hi, fuente, met = _intervalo(m, preds[m], bt, log)
    fuente = "tus precios de Garzón" if fuente == "historial 2023-hoy" else fuente
    return {"ciudad": "Garzón", "variedad": variedad, "objetivo": objetivo.isoformat(),
            "horizonte": max(1, (objetivo - date.fromisoformat(obs[-1][0])).days), "ultimo_dato": obs[-1][0],
            "ultimo_precio": round(obs[-1][1]), "modelo": m, "modelo_nombre": NOMBRES[m], "pred": round(c),
            "bajo": round(lo), "alto": round(hi), "fuente_intervalo": fuente,
            "error_tipico_pct": round(met["mape"], 1) if met else None,
            "confianza": "baja" if len(obs) < 25 else _confianza(met["mape"] if met else None, met["n"] if met else 0),
            "modelos": {k_: round(x) for k_, x in preds.items()}, "n_obs": len(obs)}


def _guardar(p):
    c = _con()
    try:
        c.execute("""INSERT INTO predicciones(creada,objetivo,ciudad,variedad,horizonte,ultimo_dato,modelo,pred,bajo,alto,modelos)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(objetivo,ciudad,variedad) DO UPDATE SET creada=excluded.creada,
                       horizonte=excluded.horizonte, ultimo_dato=excluded.ultimo_dato, modelo=excluded.modelo,
                       pred=excluded.pred, bajo=excluded.bajo, alto=excluded.alto, modelos=excluded.modelos
                     WHERE predicciones.real IS NULL""",
                  (date.today().isoformat(), p["objetivo"], p["ciudad"], p["variedad"], p["horizonte"], p["ultimo_dato"],
                   p["modelo"], p["pred"], p["bajo"], p["alto"], json.dumps(p["modelos"])))
        c.commit()
    finally:
        c.close()


def resolver():
    """Completa con el precio real los pronósticos cuyo día ya pasó y hay dato."""
    c = _con()
    try:
        pend = c.execute("SELECT * FROM predicciones WHERE real IS NULL AND objetivo<=?",
                         (date.today().isoformat(),)).fetchall()
        gz = dict(_garzon_obs())
        for r in pend:
            if r["ciudad"] == "Garzón":
                real = gz.get(r["objetivo"])
            else:
                s = _serie(r["ciudad"], r["variedad"])
                real = dict(zip(s["f"], s["v"])).get(r["objetivo"])
            if real:
                c.execute("UPDATE predicciones SET real=?, error_pct=?, en_rango=? WHERE id=?",
                          (round(real), round((r["pred"] - real) / real * 100, 1),
                           int(r["bajo"] <= real <= r["alto"]), r["id"]))
        c.commit()
    finally:
        c.close()


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def decidir(preds, costos):
    merma = float(costos.get("merma", 1)) / 100
    g = next((p for p in preds if p["ciudad"] == "Garzón"), None)
    if not g:
        return {"disponible": False, "motivo": "Registra al menos 3 precios de Garzón para comparar."}
    opciones = []
    for p in preds:
        if p["ciudad"] == "Garzón":
            continue
        fl = float(costos.get("fletes", {}).get(p["ciudad"], costos.get("flete", 680)))
        neto = p["pred"] * (1 - merma) - fl
        a = (p["alto"] - p["bajo"]) / 2 * (1 - merma)
        b = (g["alto"] - g["bajo"]) / 2
        u = math.sqrt(a * a + b * b) or 1
        diff = neto - g["pred"]
        opciones.append({"ciudad": p["ciudad"], "neto_kg": round(neto), "flete": round(fl), "ventaja_kg": round(diff),
                         "incertidumbre_kg": round(u), "prob_mejor": round(_phi(diff / (u / 1.2816)) * 100)})
    opciones.sort(key=lambda x: -x["ventaja_kg"])
    mejor = opciones[0]
    if mejor["ventaja_kg"] > mejor["incertidumbre_kg"]:
        v, t = "sacar", f"Sacar a {mejor['ciudad']}: la ventaja supera la incertidumbre."
    elif mejor["ventaja_kg"] > 0:
        v, t = "dudoso", f"{mejor['ciudad']} rendiría un poco más, pero la ventaja es menor que la incertidumbre: decisión pareja."
    else:
        v, t = "garzon", "Vender en Garzón: ninguna ciudad supera lo esperado allí después de flete y merma."
    return {"disponible": True, "veredicto": v, "texto": t, "mejor": mejor, "opciones": opciones,
            "garzon_pred": g["pred"]}


def tolerancia():
    c = _con()
    try:
        b = [abs(r[0]) for r in c.execute("SELECT error_pct FROM predicciones WHERE juicio='buena' AND error_pct IS NOT NULL")]
    finally:
        c.close()
    return round(max(5, _q(b, .8)), 1) if len(b) >= 3 else 10.0


def aprendizaje():
    c = _con()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM predicciones")]
    finally:
        c.close()
    tol = tolerancia()
    out = []
    for ciu in (*CIUDADES, "Garzón"):
        rs = [r for r in rows if r["ciudad"] == ciu and r["real"]]
        if not rs:
            out.append({"ciudad": ciu, "n_real": 0})
            continue
        e = [abs(r["error_pct"]) for r in rs]
        out.append({"ciudad": ciu, "n_real": len(rs), "error_medio_pct": round(_mean(e), 1),
                    "en_rango_pct": round(sum(r["en_rango"] for r in rs) / len(rs) * 100),
                    "sesgo_pct": round(st.median([r["error_pct"] for r in rs]), 1)})
    jb = sum(r["juicio"] == "buena" for r in rows)
    jm = sum(r["juicio"] == "mala" for r in rows)
    acuerdo = [r for r in rows if r["juicio"] and r["error_pct"] is not None]
    ok = sum((abs(r["error_pct"]) <= tol) == (r["juicio"] == "buena") for r in acuerdo)
    return {"ciudades": out, "tolerancia_pct": tol, "buenas": jb, "malas": jm,
            "acuerdo_pct": round(ok / len(acuerdo) * 100) if acuerdo else None, "total": len(rows)}


def backtest_resumen(variedad="Tomate chonto"):
    s0 = {c: _serie(c, variedad) for c in CIUDADES}
    out = []
    for c in CIUDADES:
        if len(s0[c]["v"]) < 40:
            continue
        ult = s0[c]["f"][-1]
        fila = {"ciudad": c, "n_dias": len(s0[c]["v"]), "horizontes": []}
        for h in (1, 3, 5):
            bt = _bt(c, variedad, h, ult)
            mm = {m: _metricas(p) for m, p in bt.items()}
            mejor = min(mm, key=lambda m: mm[m]["mape"])
            fila["horizontes"].append({"dias": h, "modelo": NOMBRES[mejor], "mape": round(mm[mejor]["mape"], 1),
                                       "dentro10": round(mm[mejor]["dentro10"]), "mape_ingenuo": round(mm["ultimo"]["mape"], 1),
                                       "n": mm[mejor]["n"]})
        out.append(fila)
    return out


def generar(variedad="Tomate chonto", costos=None):
    resolver()
    objetivo = date.today() + timedelta(days=1)
    preds = []
    for c in CIUDADES:
        p = predecir_ciudad(c, variedad, objetivo)
        if p:
            p.pop("_neiva_serie", None)
            preds.append(p)
    neiva = next((p for p in preds if p["ciudad"] == "Neiva"), None)
    g = predecir_garzon(variedad, objetivo, neiva["pred"] if neiva else None)
    if g:
        preds.append(g)
    for p in preds:
        _guardar(p)
    return {"objetivo": objetivo.isoformat(), "fin_de_semana": objetivo.weekday() >= 5, "predicciones": preds,
            "decision": decidir(preds, costos or {}), "aprendizaje": aprendizaje(), "backtest": backtest_resumen(variedad)}


def historial(limite=40):
    resolver()
    c = _con()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM predicciones ORDER BY objetivo DESC, ciudad LIMIT ?", (limite,))]
    finally:
        c.close()
    tol = tolerancia()
    for r in rows:
        r.pop("modelos", None)
        r["calif_auto"] = None if r["error_pct"] is None else ("buena" if abs(r["error_pct"]) <= tol else "mala")
    return rows


def juicio(id_, valor, nota="", real=None):
    if valor not in ("buena", "mala", None, ""):
        raise ValueError("Juicio inválido")
    c = _con()
    try:
        r = c.execute("SELECT * FROM predicciones WHERE id=?", (int(id_),)).fetchone()
        if not r:
            raise ValueError("No existe la predicción")
        if real not in (None, ""):
            real = float(real)
            if not 300 <= real <= 20000:
                raise ValueError("El precio real debe estar entre 300 y 20.000 $/kg")
            if r["ciudad"] != "Garzón":
                raise ValueError("El precio real de las ciudades lo trae el DANE")
            local.guardar(r["objetivo"], real)
        c.execute("UPDATE predicciones SET juicio=?, nota=? WHERE id=?", (valor or None, (nota or "")[:300], int(id_)))
        c.commit()
    finally:
        c.close()
    resolver()
