"""Finca: invernaderos, lotes, costos, cosechas, ventas, insumos y balances."""
import os
import sqlite3
from datetime import date, timedelta

import local

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE_DIR, "finca.db")

CATEGORIAS = {
    "Mano de obra": ["Jornales", "Nómina fija", "Prestaciones"],
    "Nutrición": ["Fertilizantes", "Enmiendas", "Foliares"],
    "Sanidad": ["Fungicidas", "Insecticidas", "Bioinsumos", "Herbicidas"],
    "Siembra": ["Plántulas", "Semilla", "Sustrato"],
    "Estructura y riego": ["Tutorado", "Plástico", "Riego", "Mantenimiento invernadero"],
    "Energía y agua": ["Energía", "Agua", "Combustible"],
    "Cosecha y empaque": ["Canastillas", "Empaque", "Jornal cosecha"],
    "Transporte y venta": ["Flete", "Comisión", "Descargue"],
    "Administración": ["Arriendo", "Asistencia técnica", "Seguros", "Impuestos", "Otros"],
}
TIPOS = ("directo", "indirecto", "mantenimiento")


def conectar():
    conn = sqlite3.connect(RUTA)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iniciar():
    c = conectar()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS invernaderos(
        id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, cultivo TEXT DEFAULT 'Tomate',
        area_m2 REAL DEFAULT 0, plantas INTEGER DEFAULT 0, inversion REAL DEFAULT 0,
        vida_util_anios REAL DEFAULT 8, fecha_inicio TEXT, notas TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS lotes(
        id INTEGER PRIMARY KEY, invernadero_id INTEGER NOT NULL REFERENCES invernaderos(id) ON DELETE CASCADE,
        nombre TEXT NOT NULL, cultivo TEXT DEFAULT 'Tomate', variedad TEXT DEFAULT 'Tomate chonto',
        fecha_siembra TEXT, plantas INTEGER DEFAULT 0, estado TEXT DEFAULT 'activo',
        fecha_cierre TEXT, notas TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS costos(
        id INTEGER PRIMARY KEY, fecha TEXT NOT NULL,
        invernadero_id INTEGER REFERENCES invernaderos(id) ON DELETE CASCADE,
        lote_id INTEGER REFERENCES lotes(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, subcategoria TEXT DEFAULT '', descripcion TEXT DEFAULT '',
        monto REAL NOT NULL, tipo TEXT DEFAULT 'directo');
    CREATE TABLE IF NOT EXISTS cosechas(
        id INTEGER PRIMARY KEY, fecha TEXT NOT NULL,
        lote_id INTEGER NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
        kg REAL NOT NULL, kg_descarte REAL DEFAULT 0, notas TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS ventas(
        id INTEGER PRIMARY KEY, fecha TEXT NOT NULL,
        lote_id INTEGER NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
        destino TEXT NOT NULL, kg REAL NOT NULL, precio_kg REAL NOT NULL,
        flete REAL DEFAULT 0, comision REAL DEFAULT 0, notas TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS insumos(
        id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, categoria TEXT DEFAULT 'Nutrición',
        unidad TEXT DEFAULT 'kg', contenido TEXT DEFAULT '', UNIQUE(nombre));
    CREATE TABLE IF NOT EXISTS insumo_precios(
        id INTEGER PRIMARY KEY, insumo_id INTEGER NOT NULL REFERENCES insumos(id) ON DELETE CASCADE,
        fecha TEXT NOT NULL, proveedor TEXT DEFAULT '', cantidad REAL NOT NULL, precio REAL NOT NULL,
        notas TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS descartadas(clave TEXT PRIMARY KEY, hasta TEXT);
    """)
    c.commit()
    c.close()


def _rows(sql, p=()):
    c = conectar()
    try:
        return [dict(r) for r in c.execute(sql, p).fetchall()]
    finally:
        c.close()


def _exec(sql, p=()):
    c = conectar()
    try:
        cur = c.execute(sql, p)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _fecha(v):
    return date.fromisoformat(str(v)).isoformat()


def _num(v, minimo=0.0, nombre="valor"):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} inválido")
    if x < minimo:
        raise ValueError(f"{nombre} no puede ser menor que {minimo:g}")
    return x


# ---------- CRUD genérico ----------
def invernaderos():
    return _rows("SELECT * FROM invernaderos ORDER BY id")


def guardar_invernadero(d):
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre del invernadero")
    v = (nombre, (d.get("cultivo") or "Tomate").strip(), _num(d.get("area_m2", 0), 0, "área"),
         int(_num(d.get("plantas", 0), 0, "plantas")), _num(d.get("inversion", 0), 0, "inversión"),
         _num(d.get("vida_util_anios", 8) or 8, 0.5, "vida útil"),
         _fecha(d["fecha_inicio"]) if d.get("fecha_inicio") else None, d.get("notas") or "")
    if d.get("id"):
        _exec("UPDATE invernaderos SET nombre=?,cultivo=?,area_m2=?,plantas=?,inversion=?,vida_util_anios=?,"
              "fecha_inicio=?,notas=? WHERE id=?", (*v, int(d["id"])))
        return int(d["id"])
    return _exec("INSERT INTO invernaderos(nombre,cultivo,area_m2,plantas,inversion,vida_util_anios,fecha_inicio,notas)"
                 " VALUES(?,?,?,?,?,?,?,?)", v)


def lotes(invernadero_id=None):
    q = ("SELECT l.*, i.nombre AS invernadero FROM lotes l JOIN invernaderos i ON i.id=l.invernadero_id")
    if invernadero_id:
        return _rows(q + " WHERE l.invernadero_id=? ORDER BY l.fecha_siembra DESC", (invernadero_id,))
    return _rows(q + " ORDER BY l.fecha_siembra DESC")


def guardar_lote(d):
    nombre = (d.get("nombre") or "").strip()
    if not nombre or not d.get("invernadero_id"):
        raise ValueError("Falta el nombre o el invernadero del lote")
    estado = d.get("estado") or "activo"
    if estado not in ("activo", "cerrado"):
        raise ValueError("Estado inválido")
    cierre = _fecha(d["fecha_cierre"]) if d.get("fecha_cierre") else (date.today().isoformat() if estado == "cerrado" else None)
    v = (int(d["invernadero_id"]), nombre, (d.get("cultivo") or "Tomate").strip(), d.get("variedad") or "Tomate chonto",
         _fecha(d["fecha_siembra"]) if d.get("fecha_siembra") else date.today().isoformat(),
         int(_num(d.get("plantas", 0), 0, "plantas")), estado, cierre if estado == "cerrado" else None, d.get("notas") or "")
    if d.get("id"):
        _exec("UPDATE lotes SET invernadero_id=?,nombre=?,cultivo=?,variedad=?,fecha_siembra=?,plantas=?,estado=?,"
              "fecha_cierre=?,notas=? WHERE id=?", (*v, int(d["id"])))
        return int(d["id"])
    return _exec("INSERT INTO lotes(invernadero_id,nombre,cultivo,variedad,fecha_siembra,plantas,estado,fecha_cierre,notas)"
                 " VALUES(?,?,?,?,?,?,?,?,?)", v)


def costos(lote_id=None, invernadero_id=None, desde=None, hasta=None):
    w, p = ["c.fecha BETWEEN ? AND ?"], [desde or "0000-00-00", hasta or "9999-99-99"]
    if lote_id:
        w.append("c.lote_id=?")
        p.append(lote_id)
    if invernadero_id:
        w.append("(c.invernadero_id=? OR l.invernadero_id=?)")
        p += [invernadero_id, invernadero_id]
    return _rows("SELECT c.*, l.nombre AS lote, COALESCE(i.nombre, i2.nombre) AS invernadero FROM costos c "
                 "LEFT JOIN lotes l ON l.id=c.lote_id LEFT JOIN invernaderos i ON i.id=c.invernadero_id "
                 "LEFT JOIN invernaderos i2 ON i2.id=l.invernadero_id "
                 f"WHERE {' AND '.join(w)} ORDER BY c.fecha DESC, c.id DESC LIMIT 1500", p)


def guardar_costo(d):
    cat = (d.get("categoria") or "").strip()
    if not cat:
        raise ValueError("Falta la categoría")
    tipo = d.get("tipo") or "directo"
    if tipo not in TIPOS:
        raise ValueError("Tipo inválido")
    lote = int(d["lote_id"]) if d.get("lote_id") else None
    inv = int(d["invernadero_id"]) if d.get("invernadero_id") else None
    if not lote and not inv:
        raise ValueError("Indica el lote o el invernadero al que pertenece el costo")
    if lote:
        r = _rows("SELECT invernadero_id FROM lotes WHERE id=?", (lote,))
        if not r:
            raise ValueError("Lote no existe")
        inv = r[0]["invernadero_id"]
    monto = _num(d.get("monto"), 0.01, "monto")
    v = (_fecha(d.get("fecha") or date.today()), inv, lote, cat, (d.get("subcategoria") or "").strip(),
         (d.get("descripcion") or "").strip(), monto, tipo)
    if d.get("id"):
        _exec("UPDATE costos SET fecha=?,invernadero_id=?,lote_id=?,categoria=?,subcategoria=?,descripcion=?,monto=?,"
              "tipo=? WHERE id=?", (*v, int(d["id"])))
        return int(d["id"])
    return _exec("INSERT INTO costos(fecha,invernadero_id,lote_id,categoria,subcategoria,descripcion,monto,tipo)"
                 " VALUES(?,?,?,?,?,?,?,?)", v)


def cosechas(lote_id=None):
    q = "SELECT c.*, l.nombre AS lote FROM cosechas c JOIN lotes l ON l.id=c.lote_id"
    if lote_id:
        return _rows(q + " WHERE c.lote_id=? ORDER BY c.fecha DESC, c.id DESC", (lote_id,))
    return _rows(q + " ORDER BY c.fecha DESC, c.id DESC LIMIT 1500")


def guardar_cosecha(d):
    if not d.get("lote_id"):
        raise ValueError("Falta el lote")
    kg = _num(d.get("kg"), 0.1, "kg")
    desc = _num(d.get("kg_descarte", 0) or 0, 0, "descarte")
    if desc > kg:
        raise ValueError("El descarte no puede superar los kg cosechados")
    v = (_fecha(d.get("fecha") or date.today()), int(d["lote_id"]), kg, desc, d.get("notas") or "")
    if d.get("id"):
        _exec("UPDATE cosechas SET fecha=?,lote_id=?,kg=?,kg_descarte=?,notas=? WHERE id=?", (*v, int(d["id"])))
        return int(d["id"])
    return _exec("INSERT INTO cosechas(fecha,lote_id,kg,kg_descarte,notas) VALUES(?,?,?,?,?)", v)


def ventas(lote_id=None):
    q = "SELECT v.*, l.nombre AS lote FROM ventas v JOIN lotes l ON l.id=v.lote_id"
    if lote_id:
        return _rows(q + " WHERE v.lote_id=? ORDER BY v.fecha DESC, v.id DESC", (lote_id,))
    return _rows(q + " ORDER BY v.fecha DESC, v.id DESC LIMIT 1500")


def guardar_venta(d):
    if not d.get("lote_id"):
        raise ValueError("Falta el lote")
    destino = (d.get("destino") or "").strip()
    if not destino:
        raise ValueError("Falta el destino")
    precio = _num(d.get("precio_kg"), 300, "precio")
    if precio > 20000:
        raise ValueError("El precio debe estar entre 300 y 20.000 $/kg")
    v = (_fecha(d.get("fecha") or date.today()), int(d["lote_id"]), destino, _num(d.get("kg"), 0.1, "kg"), precio,
         _num(d.get("flete", 0) or 0, 0, "flete"), _num(d.get("comision", 0) or 0, 0, "comisión"), d.get("notas") or "")
    if d.get("id"):
        _exec("UPDATE ventas SET fecha=?,lote_id=?,destino=?,kg=?,precio_kg=?,flete=?,comision=?,notas=? WHERE id=?",
              (*v, int(d["id"])))
        vid = int(d["id"])
    else:
        vid = _exec("INSERT INTO ventas(fecha,lote_id,destino,kg,precio_kg,flete,comision,notas) VALUES(?,?,?,?,?,?,?,?)", v)
    if destino.lower().startswith("garz"):
        sincronizar_local(v[0])
    return vid


def sincronizar_local(fecha):
    """El precio de Garzón en el comparador es el promedio ponderado de las ventas locales del día."""
    r = _rows("SELECT SUM(kg*precio_kg)/SUM(kg) AS p FROM ventas WHERE fecha=? AND lower(destino) LIKE 'garz%'", (fecha,))
    if r and r[0]["p"]:
        local.guardar(fecha, round(r[0]["p"]))


TABLAS = {"invernaderos": "invernaderos", "lotes": "lotes", "costos": "costos", "cosechas": "cosechas",
          "ventas": "ventas", "insumos": "insumos", "insumo_precios": "insumo_precios"}


def borrar(tabla, id_):
    if tabla not in TABLAS:
        raise ValueError("Tabla inválida")
    fecha = None
    if tabla == "ventas":
        r = _rows("SELECT fecha, destino FROM ventas WHERE id=?", (id_,))
        fecha = r[0]["fecha"] if r and r[0]["destino"].lower().startswith("garz") else None
    _exec(f"DELETE FROM {TABLAS[tabla]} WHERE id=?", (id_,))
    if fecha:
        if _rows("SELECT 1 FROM ventas WHERE fecha=? AND lower(destino) LIKE 'garz%'", (fecha,)):
            sincronizar_local(fecha)
        else:
            local.borrar(fecha)


# ---------- Balances ----------
def _dias(a, b):
    return max(0, (date.fromisoformat(b) - date.fromisoformat(a)).days)


def balance(desde=None, hasta=None):
    """Balance por lote, invernadero y finca. Depreciación lineal diaria repartida por días de ocupación del lote."""
    hoy = date.today().isoformat()
    hasta = hasta or hoy
    desde = desde or "0000-00-00"
    invs = {i["id"]: i for i in invernaderos()}
    lts = lotes()
    cst = _rows("SELECT * FROM costos WHERE fecha BETWEEN ? AND ?", (desde, hasta))
    cos = _rows("SELECT lote_id, SUM(kg) kg, SUM(kg_descarte) d FROM cosechas WHERE fecha BETWEEN ? AND ? GROUP BY lote_id", (desde, hasta))
    ven = _rows("SELECT lote_id, SUM(kg) kg, SUM(kg*precio_kg) ingreso, SUM(flete) flete, SUM(comision) comision "
                "FROM ventas WHERE fecha BETWEEN ? AND ? GROUP BY lote_id", (desde, hasta))
    cos = {r["lote_id"]: r for r in cos}
    ven = {r["lote_id"]: r for r in ven}

    res_l = {}
    for l in lts:
        fin = l["fecha_cierre"] or hoy
        dias = _dias(l["fecha_siembra"], fin)
        inv = invs.get(l["invernadero_id"], {})
        dep_dia = (inv.get("inversion", 0) / (inv.get("vida_util_anios", 8) * 365)) if inv else 0
        k = cos.get(l["id"], {"kg": 0, "d": 0})
        v = ven.get(l["id"], {"kg": 0, "ingreso": 0, "flete": 0, "comision": 0})
        directo = sum(c["monto"] for c in cst if c["lote_id"] == l["id"] and c["tipo"] == "directo")
        mant = sum(c["monto"] for c in cst if c["lote_id"] == l["id"] and c["tipo"] == "mantenimiento")
        indir = sum(c["monto"] for c in cst if c["lote_id"] == l["id"] and c["tipo"] == "indirecto")
        res_l[l["id"]] = {
            "id": l["id"], "nombre": l["nombre"], "invernadero_id": l["invernadero_id"], "invernadero": l["invernadero"],
            "variedad": l["variedad"], "estado": l["estado"], "fecha_siembra": l["fecha_siembra"], "dias": dias,
            "plantas": l["plantas"], "kg_cosechados": k["kg"] or 0, "kg_descarte": k["d"] or 0,
            "kg_vendidos": v["kg"] or 0, "ingreso": v["ingreso"] or 0,
            "costo_flete_venta": (v["flete"] or 0) + (v["comision"] or 0),
            "costo_directo": directo, "costo_indirecto": indir, "costo_mantenimiento": mant,
            "depreciacion": dep_dia * dias,
        }
    # costos de invernadero sin lote se reparten entre sus lotes por kg cosechados (o por plantas-día si no hay kg)
    for iid in invs:
        sueltos = [c for c in cst if c["lote_id"] is None and c["invernadero_id"] == iid]
        ls = [r for r in res_l.values() if r["invernadero_id"] == iid]
        for c in sueltos:
            if not ls:
                continue
            tot_kg = sum(r["kg_cosechados"] for r in ls)
            tot_pd = sum(max(r["plantas"], 1) * max(r["dias"], 1) for r in ls)
            for r in ls:
                f = (r["kg_cosechados"] / tot_kg) if tot_kg else (max(r["plantas"], 1) * max(r["dias"], 1) / tot_pd)
                key = "costo_mantenimiento" if c["tipo"] == "mantenimiento" else "costo_indirecto"
                r[key] += c["monto"] * f
    for r in res_l.values():
        r["costo_total"] = (r["costo_directo"] + r["costo_indirecto"] + r["costo_mantenimiento"]
                            + r["depreciacion"] + r["costo_flete_venta"])
        r["utilidad"] = r["ingreso"] - r["costo_total"]
        kg = r["kg_cosechados"] or r["kg_vendidos"]
        r["kg_por_planta"] = round(r["kg_cosechados"] / r["plantas"], 2) if r["plantas"] else None
        r["costo_kg"] = round(r["costo_total"] / kg) if kg else None
        r["costo_kg_sin_dep"] = round((r["costo_total"] - r["depreciacion"]) / kg) if kg else None
        r["precio_prom_kg"] = round(r["ingreso"] / r["kg_vendidos"]) if r["kg_vendidos"] else None
        r["margen_pct"] = round(r["utilidad"] / r["ingreso"] * 100, 1) if r["ingreso"] else None
        r["merma_pct"] = round(r["kg_descarte"] / r["kg_cosechados"] * 100, 1) if r["kg_cosechados"] else None
        r["por_vender_kg"] = round(max(0, r["kg_cosechados"] - r["kg_descarte"] - r["kg_vendidos"]), 1)

    res_i = []
    for iid, inv in invs.items():
        ls = [r for r in res_l.values() if r["invernadero_id"] == iid]
        ing = sum(r["ingreso"] for r in ls)
        # depreciación del invernadero: desde fecha_inicio (o primer lote) al final del periodo, aunque esté vacío
        ini = inv["fecha_inicio"] or min((r["fecha_siembra"] for r in ls), default=hoy)
        dep_total = inv["inversion"] / (inv["vida_util_anios"] * 365) * _dias(max(ini, desde if desde != "0000-00-00" else ini), hasta)
        dep_lotes = sum(r["depreciacion"] for r in ls)
        vacio = max(0.0, dep_total - dep_lotes)
        costo = sum(r["costo_total"] for r in ls) + vacio
        util = ing - costo
        kgc = sum(r["kg_cosechados"] for r in ls)
        dias_op = max(1, _dias(ini, hasta))
        util_caja = ing - (costo - dep_total)  # utilidad antes de depreciación
        meses = dias_op / 30.4
        payback = round(inv["inversion"] / (util_caja / meses)) if util_caja > 0 and inv["inversion"] > 0 else None
        res_i.append({
            "id": iid, "nombre": inv["nombre"], "area_m2": inv["area_m2"], "plantas": inv["plantas"],
            "inversion": inv["inversion"], "lotes": len(ls), "kg_cosechados": kgc, "ingreso": ing,
            "costo_total": costo, "depreciacion": dep_total, "depreciacion_vacio": vacio,
            "costo_mantenimiento": sum(r["costo_mantenimiento"] for r in ls),
            "utilidad": util, "utilidad_antes_dep": util_caja,
            "kg_m2": round(kgc / inv["area_m2"], 2) if inv["area_m2"] else None,
            "utilidad_m2": round(util / inv["area_m2"]) if inv["area_m2"] else None,
            "costo_kg": round(costo / kgc) if kgc else None,
            "roi_pct": round(util_caja / inv["inversion"] * 100, 1) if inv["inversion"] else None,
            "recuperacion_meses": payback,
            "recuperado_pct": round(max(0, util_caja) / inv["inversion"] * 100, 1) if inv["inversion"] else None,
            "meses_operacion": round(meses, 1),
        })
    sumar = lambda k: sum(x[k] for x in res_i)
    total = {"ingreso": sumar("ingreso"), "costo_total": sumar("costo_total"), "utilidad": sumar("utilidad"),
             "kg_cosechados": sumar("kg_cosechados"), "inversion": sumar("inversion")}
    total["costo_kg"] = round(total["costo_total"] / total["kg_cosechados"]) if total["kg_cosechados"] else None
    return {"desde": desde, "hasta": hasta, "lotes": sorted(res_l.values(), key=lambda r: r["fecha_siembra"], reverse=True),
            "invernaderos": res_i, "finca": total}


def por_categoria(desde=None, hasta=None, lote_id=None, invernadero_id=None):
    filas = costos(lote_id, invernadero_id, desde, hasta)
    out = {}
    for f in filas:
        out[f["categoria"]] = out.get(f["categoria"], 0) + f["monto"]
    return sorted(([k, round(v)] for k, v in out.items()), key=lambda x: -x[1])


def costo_real_kg(dias=180):
    """Costo por kg que reemplaza el 'pago a finca' en Ventas.
    Usa lotes con cosecha; prioriza los cerrados y, si no hay, los activos (marcado como parcial)."""
    b = balance()
    cand = [l for l in b["lotes"] if l["kg_cosechados"] > 0 and l["costo_kg_sin_dep"]]
    for l in cand:
        l["_base"] = l["costo_total"] - l["costo_flete_venta"]
    if not cand:
        return {"disponible": False}
    cerr = [l for l in cand if l["estado"] == "cerrado"]
    usar = cerr or cand
    kg = sum(l["kg_cosechados"] for l in usar)
    total = sum(l["_base"] for l in usar)
    sin_dep = sum(l["_base"] - l["depreciacion"] for l in usar)
    return {"disponible": True, "costo_kg": round(total / kg), "costo_kg_sin_dep": round(sin_dep / kg),
            "kg_base": round(kg), "lotes": [l["nombre"] for l in usar], "parcial": not cerr,
            "nota": ("Basado en lotes aún activos: el costo por kg baja a medida que se cosecha más." if not cerr else
                     "Basado en lotes cerrados.")}


def stock_por_vender():
    b = balance()
    return [{"lote_id": l["id"], "lote": l["nombre"], "kg": l["por_vender_kg"]} for l in b["lotes"]
            if l["estado"] == "activo" and l["por_vender_kg"] > 0]


# ---------- Insumos ----------
def insumos():
    filas = _rows("SELECT * FROM insumos ORDER BY categoria, nombre")
    for f in filas:
        h = _rows("SELECT * FROM insumo_precios WHERE insumo_id=? ORDER BY fecha DESC, id DESC", (f["id"],))
        for x in h:
            x["precio_unidad"] = round(x["precio"] / x["cantidad"], 2)
        f["historial"] = h
        if h:
            f["ultimo_precio_unidad"] = h[0]["precio_unidad"]
            f["ultima_fecha"] = h[0]["fecha"]
            pu = [x["precio_unidad"] for x in h[:6]]
            f["min_unidad"] = min(pu)
            f["prom_unidad"] = round(sum(pu) / len(pu), 2)
            f["proveedor_barato"] = min(h[:6], key=lambda x: x["precio_unidad"])["proveedor"]
            f["var_vs_prom_pct"] = round((h[0]["precio_unidad"] / f["prom_unidad"] - 1) * 100, 1) if f["prom_unidad"] else 0
            ct = f.get("contenido") or ""
            try:  # contenido = '% del nutriente/ingrediente activo' -> precio por kg de nutriente
                pct = float(ct.split("%")[0].strip().replace(",", "."))
                if pct > 0 and f["unidad"] in ("kg", "L", "litro"):
                    f["precio_por_kg_activo"] = round(h[0]["precio_unidad"] / (pct / 100))
            except ValueError:
                pass
    return filas


def guardar_insumo(d):
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre del insumo")
    r = _rows("SELECT id FROM insumos WHERE lower(nombre)=lower(?)", (nombre,))
    if r:
        _exec("UPDATE insumos SET categoria=?,unidad=?,contenido=? WHERE id=?",
              (d.get("categoria") or "Nutrición", d.get("unidad") or "kg", d.get("contenido") or "", r[0]["id"]))
        return r[0]["id"]
    return _exec("INSERT INTO insumos(nombre,categoria,unidad,contenido) VALUES(?,?,?,?)",
                 (nombre, d.get("categoria") or "Nutrición", d.get("unidad") or "kg", d.get("contenido") or ""))


def guardar_precio_insumo(d):
    iid = d.get("insumo_id") or guardar_insumo(d)
    v = (int(iid), _fecha(d.get("fecha") or date.today()), (d.get("proveedor") or "").strip(),
         _num(d.get("cantidad"), 0.001, "cantidad"), _num(d.get("precio"), 1, "precio"), d.get("notas") or "")
    return _exec("INSERT INTO insumo_precios(insumo_id,fecha,proveedor,cantidad,precio,notas) VALUES(?,?,?,?,?,?)", v)


def datos_completos():
    return {"invernaderos": invernaderos(), "lotes": lotes(), "categorias": CATEGORIAS}


iniciar()
