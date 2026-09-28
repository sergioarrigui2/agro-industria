"""Agente de la finca: chat con herramientas, briefing diario y captura de registros (texto/foto) con confirmación."""
import base64
import json
import os
from datetime import date

import agente
import analisis
import finca
import local

SISTEMA = (
    "Eres el asistente de un productor de tomate en invernadero de Garzón (Huila) que vende en Garzón, Cali, Bogotá y Neiva. "
    "REGLAS: (1) Todas las cifras salen de las herramientas; nunca inventes números ni afirmes algo que las herramientas no muestren. "
    "(2) Responde en español, claro y breve (máx. 130 palabras), con la recomendación primero y luego 2-3 razones con cifras. "
    "(3) NO recomiendes productos agroquímicos, ingredientes activos ni dosis: eso es del agrónomo. Sí puedes comparar precios de "
    "insumos que el usuario ya registró y decir cuándo conviene comprar. "
    "(4) Si falta un dato (p. ej. no hay precio de Garzón, no hay costos o lotes), dilo y di qué registrar. "
    "(5) 'Garzón (mi precio)' es lo que el propio productor registró; Neiva es solo referencia. Los precios SIPSA son mayoristas. "
    "(6) Estacionalidad y calendario son patrones históricos, no garantías; menciona la confianza si es baja. "
    "(7) Cuando el costo sea 'real', úsalo; si es 'manual', avisa que es una estimación."
)

HERRAMIENTAS = agente.HERRAMIENTAS + [
    {"name": "semaforo_carga", "description": "Antes de cargar: margen por kg y utilidad estimada de la carga en cada mercado con el costo real de producción.",
     "input_schema": {"type": "object", "properties": {"kg": {"type": "number"}}}},
    {"name": "balance_finca", "description": "Balance financiero por lote, invernadero y finca: ingresos, costos, utilidad, costo/kg, ROI y meses de recuperación.",
     "input_schema": {"type": "object", "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"}}}},
    {"name": "costos_por_categoria", "description": "Costos totales por categoría (mano de obra, nutrición, sanidad, etc.) en un periodo.",
     "input_schema": {"type": "object", "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"}}}},
    {"name": "precios_insumos", "description": "Historial y comparación de precios de insumos registrados (precio por unidad, por kg de nutriente, proveedor más barato, variación vs promedio).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "calendario_siembra", "description": "Mejores fechas de siembra según precios históricos SIPSA durante la ventana de cosecha, y siembra escalonada entre invernaderos.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "estacionalidad", "description": "Índice mensual de precios históricos (>1 alto, <1 bajo) y confianza.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "alertas_activas", "description": "Alertas y riesgos vigentes calculados por reglas.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _compacto(o, limite=6000):
    s = json.dumps(o, ensure_ascii=False, default=str)
    return s if len(s) <= limite else s[:limite] + "…(recortado)"


def _ejecutar(nombre, args, costos):
    c = costos or {}
    if nombre == "semaforo_carga":
        r = analisis.semaforo(c, args.get("kg"))
        return {k: r[k] for k in ("kg", "costo_kg", "origen_costo", "hasta", "mercados", "veredicto")}
    if nombre == "balance_finca":
        b = finca.balance(args.get("desde"), args.get("hasta"))
        keep = ("nombre", "invernadero", "estado", "dias", "kg_cosechados", "kg_vendidos", "ingreso", "costo_total", "utilidad", "costo_kg", "precio_prom_kg", "por_vender_kg")
        return {"finca": b["finca"], "invernaderos": b["invernaderos"], "lotes": [{k: l[k] for k in keep} for l in b["lotes"][:12]]}
    if nombre == "costos_por_categoria":
        return {"por_categoria": finca.por_categoria(args.get("desde"), args.get("hasta"))}
    if nombre == "precios_insumos":
        return [{k: i.get(k) for k in ("nombre", "categoria", "unidad", "ultimo_precio_unidad", "ultima_fecha", "prom_unidad",
                                       "var_vs_prom_pct", "proveedor_barato", "precio_por_kg_activo")} for i in finca.insumos()]
    if nombre == "calendario_siembra":
        r = analisis.calendario_siembra()
        return r if r.get("error") else {k: r[k] for k in ("mejores", "peor", "escalonada", "confianza", "anios_datos", "nota")}
    if nombre == "estacionalidad":
        r = analisis.estacionalidad()
        return r if r.get("error") else {k: r[k] for k in ("meses", "confianza", "anios_datos", "nota")}
    if nombre == "alertas_activas":
        return analisis.alertas(c)[:10]
    return agente._ejecutar(nombre, args, c)


def chat(pregunta, historial=None, costos=None):
    cli = agente._cliente()
    costos = analisis.costos_efectivos(costos)
    msgs = [{"role": m["role"], "content": m["content"]} for m in (historial or [])[-6:]
            if m.get("role") in ("user", "assistant") and m.get("content")]
    msgs.append({"role": "user", "content": pregunta})
    usd = 0.0
    for _ in range(agente.MAX_VUELTAS + 1):
        r = cli.messages.create(model=agente.MODELO, max_tokens=600, system=SISTEMA, tools=HERRAMIENTAS, messages=msgs)
        c = agente._costo(r.usage)
        usd += c
        agente._registrar(c, r.usage.input_tokens, r.usage.output_tokens)
        if r.stop_reason != "tool_use":
            return "".join(b.text for b in r.content if b.type == "text"), usd
        msgs.append({"role": "assistant", "content": r.content})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": _compacto(_ejecutar(b.name, b.input, costos))}
            for b in r.content if b.type == "tool_use"]})
    return "No pude completar la consulta; intenta una pregunta más concreta.", usd


def briefing(costos=None):
    """Una sola llamada por día/datos. El contexto ya viene calculado."""
    costos = analisis.costos_efectivos(costos)
    sf = analisis.semaforo(costos)
    al = analisis.alertas(costos)[:6]
    k = analisis.kpis(costos)
    hay_garzon = any(m["ciudad"] == "Garzón" for m in sf["mercados"])
    ctx = {"hoy": date.today().isoformat(), "garzon_disponible": hay_garzon, "costo_kg": sf["costo_kg"], "origen_costo": sf["origen_costo"],
           "veredicto": sf["veredicto"], "mercados": [{k2: m[k2] for k2 in ("mercado", "precio_prom_kg", "margen_kg", "color")} for m in sf["mercados"]],
           "alertas": [{"nivel": a["nivel"], "titulo": a["titulo"]} for a in al],
           "stock_por_vender": k["stock_por_vender"], "ultimos_30d": k["ultimos_30d"]}
    clave = json.dumps(ctx, sort_keys=True, ensure_ascii=False)
    ruta = os.path.join(agente.BASE_DIR, "briefing_cache.json")
    try:
        cache = json.load(open(ruta, encoding="utf-8"))
        if cache.get("clave") == clave:
            return cache["texto"], 0.0
    except Exception:
        pass
    r = agente._cliente().messages.create(
        model=agente.MODELO, max_tokens=350, system=SISTEMA,
        messages=[{"role": "user", "content":
                   "Escribe el briefing de hoy: 1) qué hacer hoy (vender/cargar/esperar) 2) por qué 3) los 1-2 riesgos más importantes. "
                   "Solo usa estos datos; si garzon_disponible es false, no menciones a Garzón salvo para pedir que registre su precio.\n" + clave}])
    texto = "".join(b.text for b in r.content if b.type == "text")
    usd = agente._costo(r.usage)
    agente._registrar(usd, r.usage.input_tokens, r.usage.output_tokens)
    json.dump({"clave": clave, "texto": texto}, open(ruta, "w", encoding="utf-8"), ensure_ascii=False)
    return texto, usd


# ---------- Captura por texto o foto ----------
TIPOS_REG = ["costo", "cosecha", "venta", "precio_insumo", "precio_garzon"]

HERRAMIENTA_CAPTURA = {
    "name": "proponer_registros",
    "description": "Devuelve los registros que el usuario quiere guardar, tal como los entendiste. No inventes datos que no estén en el mensaje o la imagen.",
    "input_schema": {"type": "object", "properties": {
        "registros": {"type": "array", "items": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": TIPOS_REG},
            "fecha": {"type": "string", "description": "YYYY-MM-DD; si no se indica, hoy"},
            "lote_id": {"type": "integer"}, "invernadero_id": {"type": "integer"},
            "categoria": {"type": "string"}, "subcategoria": {"type": "string"}, "descripcion": {"type": "string"},
            "monto": {"type": "number"}, "costo_tipo": {"type": "string", "enum": list(finca.TIPOS)},
            "kg": {"type": "number"}, "kg_descarte": {"type": "number"},
            "destino": {"type": "string"}, "precio_kg": {"type": "number"}, "flete": {"type": "number"}, "comision": {"type": "number"},
            "insumo": {"type": "string"}, "insumo_categoria": {"type": "string"}, "unidad": {"type": "string"},
            "contenido": {"type": "string"}, "cantidad": {"type": "number"}, "precio": {"type": "number"}, "proveedor": {"type": "string"},
            "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
            "pregunta": {"type": "string", "description": "Solo si falta un dato clave (p. ej. a qué lote pertenece)"}},
            "required": ["tipo"]}},
        "no_entendido": {"type": "string"}}, "required": ["registros"]}}


def _contexto_captura():
    return {"hoy": date.today().isoformat(),
            "invernaderos": [{"id": i["id"], "nombre": i["nombre"]} for i in finca.invernaderos()],
            "lotes_activos": [{"id": l["id"], "nombre": l["nombre"], "invernadero_id": l["invernadero_id"], "invernadero": l["invernadero"]}
                              for l in finca.lotes() if l["estado"] == "activo"],
            "categorias": finca.CATEGORIAS,
            "reglas": "Costos: categoria debe ser una de las categorías. Ventas: precio_kg por kilo (si dicen por canastilla de 20 kg, divide). "
                      "Cosechas en kg. Precio de Garzón: tipo precio_garzon con precio_kg. Si hay un solo lote activo y no dicen cuál, úsalo. "
                      "Si hay varios y no se sabe, deja lote_id vacío y llena 'pregunta'."}


def capturar(texto="", imagen_b64=None, media_type="image/jpeg"):
    content = []
    if imagen_b64:
        if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise ValueError("Formato de imagen no soportado")
        if len(imagen_b64) > 7_000_000:
            raise ValueError("La imagen es muy grande (máx. ~5 MB)")
        base64.b64decode(imagen_b64, validate=True)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": imagen_b64}})
    content.append({"type": "text", "text": f"Contexto: {json.dumps(_contexto_captura(), ensure_ascii=False)}\n\nMensaje del usuario: {texto or '(solo imagen: factura, nota o cuaderno)'}"})
    r = agente._cliente().messages.create(
        model=agente.MODELO, max_tokens=1200,
        system="Conviertes mensajes, facturas y notas de un productor de tomate en registros estructurados. Solo extraes lo que se ve o se dice.",
        tools=[HERRAMIENTA_CAPTURA], tool_choice={"type": "tool", "name": "proponer_registros"},
        messages=[{"role": "user", "content": content}])
    usd = agente._costo(r.usage)
    agente._registrar(usd, r.usage.input_tokens, r.usage.output_tokens)
    datos = next((b.input for b in r.content if b.type == "tool_use"), {"registros": []})
    return {"registros": [_normalizar(x) for x in datos.get("registros", [])], "no_entendido": datos.get("no_entendido", ""), "usd": usd}


def _normalizar(x):
    x = {k: v for k, v in x.items() if v not in (None, "")}
    x.setdefault("fecha", date.today().isoformat())
    x["resumen"] = _resumen(x)
    return x


def _resumen(x):
    t = x.get("tipo")
    m = lambda v: f"${v:,.0f}".replace(",", ".")
    if t == "costo":
        return f"Costo {x.get('categoria', '?')} {m(x.get('monto', 0))} — {x.get('descripcion', '')}".strip(" —")
    if t == "cosecha":
        return f"Cosecha {x.get('kg', '?')} kg" + (f" (descarte {x['kg_descarte']} kg)" if x.get("kg_descarte") else "")
    if t == "venta":
        return f"Venta {x.get('kg', '?')} kg a {x.get('destino', '?')} a {m(x.get('precio_kg', 0))}/kg"
    if t == "precio_insumo":
        return f"Insumo {x.get('insumo', '?')}: {x.get('cantidad', '?')} {x.get('unidad', '')} por {m(x.get('precio', 0))} ({x.get('proveedor', 's/prov.')})"
    if t == "precio_garzon":
        return f"Precio Garzón {m(x.get('precio_kg', 0))}/kg"
    return t or "?"


def guardar_registro(x):
    """Guarda un registro ya confirmado por el usuario. Reusa las validaciones de finca.py."""
    t = x.get("tipo")
    if t == "costo":
        return finca.guardar_costo({**x, "tipo": x.get("costo_tipo", "directo")})
    if t == "cosecha":
        return finca.guardar_cosecha(x)
    if t == "venta":
        return finca.guardar_venta(x)
    if t == "precio_insumo":
        return finca.guardar_precio_insumo({**x, "nombre": x.get("insumo"), "categoria": x.get("insumo_categoria") or "Nutrición"})
    if t == "precio_garzon":
        p = float(x.get("precio_kg", 0))
        if not 300 <= p <= 20000:
            raise ValueError("El precio debe estar entre 300 y 20.000 $/kg")
        local.guardar(date.fromisoformat(x["fecha"]).isoformat(), p)
        return 1
    raise ValueError("Tipo de registro desconocido")
