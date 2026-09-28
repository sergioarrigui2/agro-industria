import json
import os
from datetime import date, timedelta

import local
import sipsa

MODELO = "claude-haiku-4-5-20251001"
MAX_VUELTAS = 3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAVORITOS = ("Cali", "Bogotá", "Neiva")

SISTEMA = (
    "Eres el asesor comercial de un comerciante de tomate que vende desde Garzón (Huila) a Cali, "
    "comparando con Bogotá y Neiva. Usa SOLO las herramientas para obtener cifras; nunca inventes "
    "números. Responde en español, breve (máximo 120 palabras), con la recomendación primero. "
    "'Garzón (mi precio)' es el precio real registrado por el comerciante en su venta local (sin flete); Neiva es solo referencia de Garzón, que los precios son mayoristas de mercado y que "
    "Cali se reparte entre Cavasa y Santa Elena en días alternos."
)


PRECIO_IN, PRECIO_OUT = 1.0, 5.0  # USD por millón de tokens (Haiku 4.5)
RUTA_USO = os.path.join(BASE_DIR, "uso_ia.json")


def _costo(u):
    return (u.input_tokens * PRECIO_IN + u.output_tokens * PRECIO_OUT) / 1e6


def _registrar(usd, tin, tout):
    try:
        uso = json.load(open(RUTA_USO, encoding="utf-8"))
    except Exception:
        uso = {}
    mes = date.today().strftime("%Y-%m")
    m = uso.setdefault(mes, {"llamadas": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0})
    m["llamadas"] += 1
    m["tokens_in"] += tin
    m["tokens_out"] += tout
    m["usd"] = round(m["usd"] + usd, 6)
    json.dump(uso, open(RUTA_USO, "w", encoding="utf-8"))


def uso_mes():
    _cargar_env()
    trm = float(os.environ.get("TRM", 4000))
    try:
        m = json.load(open(RUTA_USO, encoding="utf-8")).get(date.today().strftime("%Y-%m"))
    except Exception:
        m = None
    m = m or {"llamadas": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}
    return {**m, "cop": round(m["usd"] * trm), "trm": trm}


def _cargar_env():
    ruta = os.path.join(BASE_DIR, ".env")
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cliente():
    _cargar_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Falta ANTHROPIC_API_KEY (ponla en el archivo .env)")
    import anthropic
    return anthropic.Anthropic()


def _serie(variedad, desde, hasta, ciudades=FAVORITOS):
    conn = sipsa.conectar()
    try:
        marks = ",".join("?" * len(ciudades))
        filas = [dict(r) for r in conn.execute(
            f"""SELECT fecha, mercado, ciudad, AVG(precio_kg) AS p FROM precios
                WHERE producto=? AND fecha BETWEEN ? AND ? AND atipico=0 AND minorista=0
                AND ciudad IN ({marks}) GROUP BY fecha, mercado ORDER BY fecha""",
            [variedad, desde, hasta, *ciudades]).fetchall()]
    finally:
        conn.close()
    filas += [{"fecha": r["fecha"], "mercado": local.MERCADO, "ciudad": "Garzón", "p": r["precio_kg"]}
              for r in local.listar(desde, hasta)]
    return sorted(filas, key=lambda x: x["fecha"])


def _margen(p, ciudad, costos):
    fl = costos.get("fletes", {}).get(ciudad, 0 if ciudad == "Garzón" else costos.get("flete", 680))
    return p * (1 - costos.get("merma", 1) / 100) - costos.get("finca", 1800) - float(fl)


def resumen(costos=None, variedad="Tomate chonto", dias=30):
    """Todo calculado en código; es lo único que ve el modelo."""
    costos = costos or {}
    conn = sipsa.conectar()
    hasta = conn.execute("SELECT MAX(fecha) FROM precios").fetchone()[0]
    conn.close()
    h = date.fromisoformat(hasta)
    filas = _serie(variedad, (h - timedelta(days=dias)).isoformat(), hasta)
    c7 = (h - timedelta(days=7)).isoformat()
    c14 = (h - timedelta(days=14)).isoformat()
    por = {}
    for f in filas:
        por.setdefault(f["mercado"], []).append(f)
    mercados = []
    for m, fs in por.items():
        ciudad = fs[0]["ciudad"]
        ult = fs[-1]
        prom = sum(x["p"] for x in fs) / len(fs)
        r7 = [x["p"] for x in fs if x["fecha"] > c7]
        p7 = [x["p"] for x in fs if c14 < x["fecha"] <= c7]
        mercados.append({
            "mercado": m,
            "ultimo_precio_kg": round(ult["p"]), "ultima_fecha": ult["fecha"],
            "prom_30d": round(prom),
            "tendencia_7d_pct": round((sum(r7) / len(r7) / (sum(p7) / len(p7)) - 1) * 100, 1) if r7 and p7 else None,
            "dias_con_dato": len(fs),
            "flete": costos.get("fletes", {}).get(ciudad, 0 if ciudad == "Garzón" else costos.get("flete", 680)),
            "margen_ultimo_kg": round(_margen(ult["p"], ciudad, costos)),
            "margen_prom_30d_kg": round(_margen(prom, ciudad, costos)),
        })
    mercados.sort(key=lambda x: -x["margen_ultimo_kg"])
    return {
        "hoy": date.today().isoformat(), "ultimo_dato_db": hasta,
        "rezago_dias": (date.today() - h).days, "variedad": variedad,
        "costos": {"finca": costos.get("finca", 1800), "merma_pct": costos.get("merma", 1)},
        "mercados_por_margen_ultimo": mercados,
    }


def comparar(desde, hasta, costos=None, variedad="Tomate chonto"):
    costos = costos or {}
    por = {}
    for f in _serie(variedad, desde, hasta):
        por.setdefault(f["mercado"], []).append(f)
    out = []
    for m, fs in por.items():
        ps = [x["p"] for x in fs]
        ciudad = fs[0]["ciudad"]
        out.append({"mercado": m, "dias": len(fs), "prom": round(sum(ps) / len(ps)),
                    "min": round(min(ps)), "max": round(max(ps)),
                    "margen_prom_kg": round(_margen(sum(ps) / len(ps), ciudad, costos))})
    return sorted(out, key=lambda x: -x["margen_prom_kg"])


def garzon_vs_ciudades(costos=None, dias=14, variedad="Tomate chonto"):
    """Vender en Garzón vs sacar a cada ciudad: diferencia de utilidad y precio de equilibrio en Garzón."""
    costos = costos or {}
    conn = sipsa.conectar()
    hasta = conn.execute("SELECT MAX(fecha) FROM precios").fetchone()[0]
    conn.close()
    h = date.fromisoformat(hasta)
    desde = (h - timedelta(days=dias)).isoformat()
    filas = _serie(variedad, desde, hasta)
    loc = [f for f in filas if f["ciudad"] == "Garzón"]
    if not loc:
        return {"error": f"No hay precios de Garzón registrados en los últimos {dias} días; pídele al usuario que los registre."}
    pg = sum(f["p"] for f in loc) / len(loc)
    mg = _margen(pg, "Garzón", costos)
    kg = costos.get("kg", 1500)
    merma = costos.get("merma", 1) / 100
    out = []
    por = {}
    for f in filas:
        if f["ciudad"] != "Garzón":
            por.setdefault(f["mercado"], []).append(f)
    for m, fs in por.items():
        ciudad = fs[0]["ciudad"]
        pc = sum(x["p"] for x in fs) / len(fs)
        mc = _margen(pc, ciudad, costos)
        flete = costos.get("fletes", {}).get(ciudad, costos.get("flete", 680))
        out.append({"mercado": m, "dias_con_dato": len(fs), "precio_prom_kg": round(pc),
                    "margen_kg_ciudad": round(mc), "diferencia_vs_garzon_kg": round(mc - mg),
                    "diferencia_vs_garzon_por_viaje": round((mc - mg) * kg),
                    "precio_garzon_de_equilibrio_kg": round((pc * (1 - merma) - float(flete)) / (1 - merma))})
    return {"ventana_dias": dias, "hasta": hasta, "kg_por_viaje": kg,
            "garzon": {"dias_registrados": len(loc), "precio_prom_kg": round(pg), "margen_kg": round(mg)},
            "ciudades": sorted(out, key=lambda x: -x["diferencia_vs_garzon_kg"]),
            "nota": "No incluye costos fijos del viaje, comisiones ni plazos de pago; el usuario debe considerarlos."}


HERRAMIENTAS = [
    {"name": "garzon_vs_ciudades", "description": "Compara vender todo en Garzón contra sacar el tomate a cada ciudad: diferencia de utilidad por kg y por viaje, y precio de equilibrio en Garzón.",
     "input_schema": {"type": "object", "properties": {"dias": {"type": "integer"}}}},
    {"name": "resumen", "description": "Estado actual: último precio, promedio 30d, tendencia 7d y margen por mercado (Cali, Bogotá, Neiva).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "comparar", "description": "Precio prom/mín/máx y margen promedio por mercado entre dos fechas (YYYY-MM-DD).",
     "input_schema": {"type": "object", "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"}},
                      "required": ["desde", "hasta"]}},
]


def _ejecutar(nombre, args, costos):
    if nombre == "resumen":
        return resumen(costos)
    if nombre == "garzon_vs_ciudades":
        return garzon_vs_ciudades(costos, int(args.get("dias", 14)))
    if nombre == "comparar":
        return comparar(args["desde"], args["hasta"], costos)
    return {"error": "herramienta desconocida"}


def preguntar(pregunta, costos=None):
    cli = _cliente()
    msgs = [{"role": "user", "content": pregunta}]
    usd = 0.0
    for _ in range(MAX_VUELTAS):
        r = cli.messages.create(model=MODELO, max_tokens=500, system=SISTEMA,
                                tools=HERRAMIENTAS, messages=msgs)
        c = _costo(r.usage)
        usd += c
        _registrar(c, r.usage.input_tokens, r.usage.output_tokens)
        if r.stop_reason != "tool_use":
            return "".join(b.text for b in r.content if b.type == "text"), usd
        msgs.append({"role": "assistant", "content": r.content})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id,
             "content": json.dumps(_ejecutar(b.name, b.input, costos or {}), ensure_ascii=False)}
            for b in r.content if b.type == "tool_use"]})
    return "No pude completar la consulta con las herramientas disponibles.", usd


def briefing(costos=None):
    """Una sola llamada, sin herramientas: el resumen ya viene calculado. Se guarda por día y datos."""
    res = resumen(costos)
    ruta = os.path.join(BASE_DIR, "briefing_cache.json")
    clave = f"{res['hoy']}|{res['ultimo_dato_db']}|{json.dumps(res['costos'])}|{costos.get('flete') if costos else ''}|{costos.get('fletes') if costos else ''}"
    try:
        cache = json.load(open(ruta, encoding="utf-8"))
        if cache.get("clave") == clave:
            return cache["texto"], 0.0
    except Exception:
        pass
    r = _cliente().messages.create(
        model=MODELO, max_tokens=350, system=SISTEMA,
        messages=[{"role": "user", "content":
                   "Briefing de hoy. Dime a qué mercado conviene vender, por qué (margen, tendencia) y "
                   "cualquier alerta (datos viejos, mercado sin dato reciente).\n" + json.dumps(res, ensure_ascii=False)}])
    texto = "".join(b.text for b in r.content if b.type == "text")
    usd = _costo(r.usage)
    _registrar(usd, r.usage.input_tokens, r.usage.output_tokens)
    json.dump({"clave": clave, "texto": texto}, open(ruta, "w", encoding="utf-8"), ensure_ascii=False)
    return texto, usd


if __name__ == "__main__":
    print(briefing())
