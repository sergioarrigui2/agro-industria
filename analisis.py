"""Análisis sin IA: semáforo de carga, estacionalidad, calendario de siembra y alertas por reglas."""
from datetime import date, timedelta

import agente
import finca
import local
import sipsa

CIUDADES = ("Cali", "Bogotá", "Neiva")
CICLO = {"dias_a_cosecha": 85, "dias_cosecha": 120}  # trasplante→1ª cosecha y duración de la cosecha (editable)


def cop(n):
    return f"{n:,.0f}".replace(",", ".")


def _ultima_fecha():
    conn = sipsa.conectar()
    try:
        return conn.execute("SELECT MAX(fecha) FROM precios").fetchone()[0]
    finally:
        conn.close()


def costos_efectivos(costos):
    """Si hay costo real en la finca y el usuario no lo forzó, reemplaza el 'pago a finca'."""
    costos = {"finca": 1800, "merma": 1, "flete": 680, "kg": 1500, **(costos or {})}
    real = finca.costo_real_kg()
    costos["_real"] = real
    if real.get("disponible") and costos.get("usar_real", True):
        costos["finca"] = real["costo_kg"]
        costos["_origen_costo"] = "real"
    else:
        costos["_origen_costo"] = "manual"
    return costos


# ---------- Semáforo antes de cargar ----------
def semaforo(costos, kg=None, variedad="Tomate chonto", dias=7, mercados=None):
    costos = costos_efectivos(costos)
    kg = float(kg or costos.get("kg") or 1500)
    hasta = _ultima_fecha()
    h = date.fromisoformat(hasta)
    filas = agente._serie(variedad, (h - timedelta(days=dias)).isoformat(), hasta)
    por = {}
    for f in filas:
        if mercados and f["mercado"] not in mercados:
            continue
        por.setdefault(f["mercado"], []).append(f)
    finca_kg = costos["finca"]
    out = []
    for m, fs in por.items():
        ciudad = fs[0]["ciudad"]
        ult = fs[-1]
        prom = sum(x["p"] for x in fs) / len(fs)
        mg = agente._margen(prom, ciudad, costos)
        pct = mg / finca_kg * 100 if finca_kg else 0
        color = "rojo" if mg <= 0 else ("amarillo" if pct < 15 else "verde")
        out.append({"mercado": m, "ciudad": ciudad, "precio_prom_kg": round(prom), "ultimo_precio_kg": round(ult["p"]),
                    "ultima_fecha": ult["fecha"], "dias_con_dato": len(fs), "margen_kg": round(mg),
                    "margen_pct_costo": round(pct, 1), "utilidad_carga": round(mg * kg), "color": color,
                    "es_referencia": m.startswith("Neiva")})
    out.sort(key=lambda x: -x["margen_kg"])
    mejor = next((x for x in out if not x["es_referencia"]), None)
    return {"kg": kg, "costo_kg": round(finca_kg), "origen_costo": costos["_origen_costo"], "costo_real": costos["_real"],
            "hasta": hasta, "ventana_dias": dias, "mercados": out,
            "mejor": mejor["mercado"] if mejor else None,
            "veredicto": (None if not mejor else
                          "No cargues: ningún destino deja margen con tu costo actual." if mejor["margen_kg"] <= 0 else
                          f"Mejor destino: {mejor['mercado']} con utilidad estimada de ${cop(mejor['utilidad_carga'])} por {cop(kg)} kg.")}


# ---------- Estacionalidad ----------
def _mensual(variedad="Tomate chonto", ciudades=CIUDADES):
    conn = sipsa.conectar()
    try:
        marks = ",".join("?" * len(ciudades))
        return [dict(r) for r in conn.execute(
            f"""SELECT fecha, ciudad, AVG(precio_kg) p FROM precios WHERE producto=? AND atipico=0 AND minorista=0
                AND ciudad IN ({marks}) GROUP BY fecha, ciudad""", [variedad, *ciudades]).fetchall()]
    finally:
        conn.close()


def estacionalidad(variedad="Tomate chonto", ciudad=None):
    filas = [f for f in _mensual(variedad) if not ciudad or f["ciudad"] == ciudad]
    if not filas:
        return {"error": "Sin datos"}
    por_ciudad_anio = {}
    for f in filas:
        por_ciudad_anio.setdefault((f["ciudad"], f["fecha"][:4]), []).append(f["p"])
    media_ca = {k: sum(v) / len(v) for k, v in por_ciudad_anio.items()}
    idx_mes = {m: [] for m in range(1, 13)}
    idx_sem = {}
    for f in filas:
        base = media_ca[(f["ciudad"], f["fecha"][:4])]
        d = date.fromisoformat(f["fecha"])
        r = f["p"] / base
        idx_mes[d.month].append(r)
        idx_sem.setdefault(min(d.isocalendar()[1], 52), []).append(r)
    anios = sorted({k[1] for k in media_ca})
    completos = [a for a in anios if sum(1 for f in filas if f["fecha"][:4] == a) > 200]
    meses = [{"mes": m, "indice": round(sum(v) / len(v), 3) if v else None, "n": len(v)} for m, v in idx_mes.items()]
    semanas = {s: sum(v) / len(v) for s, v in idx_sem.items() if len(v) >= 3}
    precios_mes = {}
    for f in filas:
        precios_mes.setdefault(f["fecha"][:7], []).append(f["p"])
    return {"variedad": variedad, "ciudad": ciudad or "Cali+Bogotá+Neiva", "anios_datos": anios,
            "anios_completos": completos, "desde": min(f["fecha"] for f in filas), "hasta": max(f["fecha"] for f in filas),
            "meses": meses, "indice_semana": {s: round(v, 3) for s, v in semanas.items()},
            "serie_mensual": [{"mes": k, "precio": round(sum(v) / len(v))} for k, v in sorted(precios_mes.items())],
            "confianza": ("alta" if len(completos) >= 3 else "media" if len(completos) == 2 else "baja"),
            "nota": "Índice = precio del mes / precio promedio del año. >1 = precio alto (poca oferta); <1 = precio bajo (mucha oferta)."}


def _indice_dia(idx_sem, d):
    s = min(d.isocalendar()[1], 52)
    if s in idx_sem:
        return idx_sem[s]
    for k in range(1, 4):
        for c in (s - k, s + k):
            if c in idx_sem:
                return idx_sem[c]
    return 1.0


def calendario_siembra(variedad="Tomate chonto", dias_a_cosecha=None, dias_cosecha=None, invernaderos=None):
    dc = int(dias_a_cosecha or CICLO["dias_a_cosecha"])
    dd = int(dias_cosecha or CICLO["dias_cosecha"])
    est = estacionalidad(variedad)
    if est.get("error"):
        return est
    sem = {int(k): v for k, v in est["indice_semana"].items()}
    hoy = date.today()
    dias = []
    for i in range(365):
        d = hoy + timedelta(days=i)
        ini, fin = d + timedelta(days=dc), d + timedelta(days=dc + dd)
        ind = [_indice_dia(sem, ini + timedelta(days=k)) for k in range(0, dd, 7)]
        dias.append({"siembra": d.isoformat(), "cosecha_desde": ini.isoformat(), "cosecha_hasta": fin.isoformat(),
                     "indice": round(sum(ind) / len(ind), 3)})
    orden = sorted(dias, key=lambda x: -x["indice"])
    mejores, usados = [], []
    for x in orden:
        d = date.fromisoformat(x["siembra"])
        if all(abs((d - u).days) > 30 for u in usados):
            mejores.append(x)
            usados.append(d)
        if len(mejores) == 3:
            break
    peor = orden[-1]
    n = int(invernaderos or len(finca.invernaderos()) or 1)
    ciclo_total = dc + dd
    paso = round(ciclo_total / n)
    escalonada = [{"invernadero": k + 1, "siembra": (date.fromisoformat(mejores[0]["siembra"]) + timedelta(days=paso * k)).isoformat()}
                  for k in range(n)]
    return {"dias_a_cosecha": dc, "dias_cosecha": dd, "confianza": est["confianza"], "anios_datos": est["anios_datos"],
            "curva": [{"siembra": x["siembra"], "indice": x["indice"]} for x in dias],
            "mejores": mejores, "peor": peor, "escalonada": escalonada, "paso_dias": paso,
            "nota": ("Compara el precio típico durante la ventana de cosecha de cada fecha de siembra. Es un patrón histórico de "
                     "SIPSA (Cali, Bogotá, Neiva), no una garantía: no incluye clima, plagas ni ciclos de la oferta nacional. "
                     "Para producir todo el año, escalona las siembras entre invernaderos.")}


# ---------- Alertas por reglas ----------
def _descartadas():
    hoy = date.today().isoformat()
    return {r["clave"] for r in finca._rows("SELECT clave FROM descartadas WHERE hasta >= ?", (hoy,))}


def descartar(clave, dias=7):
    finca._exec("INSERT OR REPLACE INTO descartadas(clave, hasta) VALUES(?,?)",
                (clave, (date.today() + timedelta(days=dias)).isoformat()))


def alertas(costos=None, incluir_descartadas=False):
    out = []
    hoy = date.today()

    def add(clave, nivel, titulo, detalle, tab=None):
        out.append({"clave": clave, "nivel": nivel, "titulo": titulo, "detalle": detalle, "tab": tab})

    hasta = _ultima_fecha()
    if hasta:
        rez = (hoy - date.fromisoformat(hasta)).days
        if rez > 4:
            add("dane-viejo", "amarillo", f"Datos del DANE con {rez} días de retraso",
                "Pulsa «Actualizar DANE». Si sigue igual, el boletín aún no se ha publicado.", "ventas")
    # precio propio de Garzón
    loc = local.listar("0000-00-00", "9999-99-99")
    if loc:
        ult = max(r["fecha"] for r in loc)
        d = (hoy - date.fromisoformat(ult)).days
        if d > 7:
            add("garzon-viejo", "amarillo", f"Hace {d} días no registras precio en Garzón",
                "Sin ese dato la comparación Garzón vs ciudades pierde validez.", "registros")
    # semáforo + tendencia
    try:
        sf = semaforo(costos or {})
        util = [m for m in sf["mercados"] if not m["es_referencia"]]
        if util and all(m["margen_kg"] <= 0 for m in util):
            add("margen-neg", "rojo", "Ningún destino deja margen con tu costo",
                f"Costo {cop(sf['costo_kg'])} $/kg ({sf['origen_costo']}). Espera precios mejores o revisa costos.", "ventas")
        elif sf["mejor"]:
            m = next(x for x in util if x["mercado"] == sf["mejor"])
            add("mejor-destino", "verde" if m["color"] == "verde" else "info", f"Hoy conviene: {m['mercado']}",
                f"Margen {cop(m['margen_kg'])} $/kg (~{cop(m['utilidad_carga'])} por {cop(sf['kg'])} kg).", "ventas")
        conn = sipsa.conectar()
        for c in CIUDADES:
            r = conn.execute("""SELECT AVG(CASE WHEN fecha > date(?, '-7 day') THEN precio_kg END) a,
                                AVG(CASE WHEN fecha <= date(?, '-7 day') AND fecha > date(?, '-14 day') THEN precio_kg END) b
                                FROM precios WHERE ciudad=? AND producto='Tomate chonto' AND atipico=0 AND minorista=0""",
                             (hasta, hasta, hasta, c)).fetchone()
            if r and r["a"] and r["b"]:
                v = (r["a"] / r["b"] - 1) * 100
                if v <= -12:
                    add(f"caida-{c}", "amarillo", f"Precio en {c} cae {abs(v):.0f}% en 7 días",
                        "Si tienes producto listo, considera vender en otro destino o esperar.", "ventas")
                elif v >= 12:
                    add(f"alza-{c}", "verde", f"Precio en {c} sube {v:.0f}% en 7 días",
                        "Buen momento para llevar carga si tu cosecha lo permite.", "ventas")
        conn.close()
    except Exception:
        pass
    # finca
    b = finca.balance()
    for l in b["lotes"]:
        if l["estado"] != "activo":
            continue
        ult_c = finca._rows("SELECT MAX(fecha) f FROM cosechas WHERE lote_id=?", (l["id"],))[0]["f"]
        if ult_c and (hoy - date.fromisoformat(ult_c)).days > 10:
            add(f"sin-cosecha-{l['id']}", "info", f"{l['nombre']}: sin cosecha hace {(hoy - date.fromisoformat(ult_c)).days} días",
                "¿Terminó el ciclo? Ciérralo para ver su balance final.", "finca")
        ult_g = finca._rows("SELECT MAX(fecha) f FROM costos WHERE lote_id=?", (l["id"],))[0]["f"]
        if not ult_g or (hoy - date.fromisoformat(ult_g)).days > 21:
            add(f"sin-costos-{l['id']}", "info", f"{l['nombre']}: sin costos registrados hace 3+ semanas",
                "Costos incompletos hacen que el margen se vea mejor de lo real.", "registros")
        if l["por_vender_kg"] > 0 and l["kg_cosechados"]:
            pass
        if l["kg_cosechados"] and l["ingreso"] and l["costo_kg"] and l["precio_prom_kg"] and l["precio_prom_kg"] < l["costo_kg"]:
            add(f"perdida-{l['id']}", "rojo", f"{l['nombre']}: vendes por debajo del costo",
                f"Precio promedio {cop(l['precio_prom_kg'])} vs costo {cop(l['costo_kg'])} $/kg.", "balance")
    for i in b["invernaderos"]:
        if i["inversion"] and i["costo_mantenimiento"] > 0.15 * max(i["ingreso"], 1) and i["ingreso"]:
            add(f"mant-{i['id']}", "amarillo", f"{i['nombre']}: el mantenimiento pesa {i['costo_mantenimiento'] / i['ingreso'] * 100:.0f}% de los ingresos",
                "Revisa si conviene renovar o reparar.", "balance")
    # insumos
    for ins in finca.insumos():
        v = ins.get("var_vs_prom_pct")
        if v is None or len(ins["historial"]) < 3:
            continue
        if v >= 10:
            add(f"insumo-alto-{ins['id']}", "amarillo", f"{ins['nombre']} está {v:.0f}% sobre su promedio",
                "Si puedes, difiere la compra o cotiza otro proveedor.", "insumos")
        elif v <= -10:
            add(f"insumo-bajo-{ins['id']}", "verde", f"{ins['nombre']} está {abs(v):.0f}% bajo su promedio",
                f"Buen momento para abastecerte (proveedor más barato: {ins.get('proveedor_barato') or '—'}).", "insumos")
    # siembra
    try:
        cal = calendario_siembra()
        if not cal.get("error") and cal["confianza"] != "baja":
            m = cal["mejores"][0]
            dias = (date.fromisoformat(m["siembra"]) - hoy).days
            if 0 <= dias <= 30:
                add("siembra-ventana", "info", f"Ventana de siembra favorable en {dias} días",
                    f"Sembrar hacia {m['siembra']} lleva la cosecha a semanas de mejores precios históricos.", "siembra")
    except Exception:
        pass
    orden = {"rojo": 0, "amarillo": 1, "verde": 2, "info": 3}
    out.sort(key=lambda a: orden[a["nivel"]])
    if not incluir_descartadas:
        d = _descartadas()
        out = [a for a in out if a["clave"] not in d]
    return out


def kpis(costos=None):
    b = finca.balance()
    hoy = date.today()
    desde30 = (hoy - timedelta(days=30)).isoformat()
    b30 = finca.balance(desde=desde30)
    return {"finca": b["finca"], "ultimos_30d": b30["finca"], "stock_por_vender": finca.stock_por_vender(),
            "costo_real": finca.costo_real_kg(), "lotes_activos": sum(1 for l in b["lotes"] if l["estado"] == "activo")}
