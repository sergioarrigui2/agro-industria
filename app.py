import os
from datetime import date, datetime

from flask import Flask, jsonify, request, send_file

import agente
import local
import sipsa
from finca_api import bp as finca_bp

app = Flask(__name__)
app.register_blueprint(finca_bp)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _q(sql, params=()):
    conn = sipsa.conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _filtros(args):
    """Construye el WHERE común a partir de los parámetros de la petición."""
    desde = args.get("desde") or "0000-00-00"
    hasta = args.get("hasta") or "9999-99-99"
    variedad = args.get("variedad") or "Tomate chonto"
    presentacion = args.get("presentacion") or ""
    mercados = [m for m in (args.get("mercados") or "").split("|") if m]
    incluir_atipicos = args.get("atipicos") == "1"
    incluir_minorista = args.get("minorista") == "1"

    where = ["fecha BETWEEN ? AND ?", "producto = ?"]
    params = [desde, hasta, variedad]
    if presentacion:
        where.append("presentacion = ?")
        params.append(presentacion)
    if mercados:
        where.append(f"mercado IN ({','.join('?' * len(mercados))})")
        params += mercados
    if not incluir_atipicos:
        where.append("atipico = 0")
    if not incluir_minorista:
        where.append("minorista = 0")
    return " AND ".join(where), params


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"))


@app.route("/api/meta")
def meta():
    rango = _q("SELECT MIN(fecha) AS desde, MAX(fecha) AS hasta, COUNT(*) AS registros, "
               "COUNT(DISTINCT fecha) AS dias FROM precios")
    r = rango[0] if rango else {}
    if not r.get("hasta"):
        return jsonify({"vacio": True})
    rezago = (date.today() - date.fromisoformat(r["hasta"])).days
    return jsonify({
        **r,
        "rezago_dias": rezago,
        "mercados": _q(
            "SELECT mercado, ciudad, minorista, COUNT(DISTINCT fecha) AS dias, MAX(fecha) AS ultimo, "
            "MIN(fecha) AS primero FROM precios GROUP BY mercado ORDER BY ciudad, mercado"
        ),
        "variedades": _q("SELECT producto, COUNT(*) AS n FROM precios WHERE atipico = 0 "
                         "AND producto IN ('Tomate chonto', 'Tomate larga vida') GROUP BY producto ORDER BY n DESC"),
        "presentaciones": _q("SELECT presentacion, COUNT(*) AS n FROM precios WHERE atipico = 0 "
                             "GROUP BY presentacion ORDER BY n DESC"),
        "atipicos": _q("SELECT COUNT(*) AS n FROM precios WHERE atipico = 1")[0]["n"],
    })


@app.route("/api/comparar")
def comparar():
    """Precio $/kg por día y mercado (promedio de las presentaciones y rondas reportadas ese día)."""
    where, params = _filtros(request.args)
    filas = _q(
        f"""SELECT fecha, mercado, ciudad,
                   ROUND(AVG(precio_kg), 2) AS precio_kg,
                   ROUND(MIN(kg_min), 2) AS kg_min,
                   ROUND(MAX(kg_max), 2) AS kg_max,
                   COUNT(*) AS n_presentaciones
            FROM precios WHERE {where}
            GROUP BY fecha, mercado ORDER BY fecha, mercado""",
        params,
    )
    return jsonify(filas)


@app.route("/api/detalle")
def detalle():
    """Filas originales (por presentación y ronda) para auditar cualquier cifra."""
    where, params = _filtros(request.args)
    return jsonify(_q(
        f"""SELECT fecha, mercado, producto, presentacion, peso_kg, r1_min, r1_max, r2_min, r2_max,
                   kg_min, kg_max, precio_kg, atipico
            FROM precios WHERE {where} ORDER BY fecha DESC, mercado LIMIT 2000""",
        params,
    ))


@app.route("/api/actualizar_dane", methods=["POST"])
def actualizar_dane():
    try:
        r = sipsa.actualizar(dias_atras=10)
        if r["zips_nuevos"]:
            msg = (f"Se descargaron {len(r['zips_nuevos'])} boletín(es) nuevo(s) y se guardaron "
                   f"{r['registros']} registros. Último dato: {r['ultima_fecha']}.")
        else:
            msg = f"No hay boletines nuevos en el DANE. Último dato: {r['ultima_fecha']}."
        return jsonify({"status": "ok", "mensaje": msg, **r})
    except Exception as e:
        return jsonify({"status": "error", "mensaje": f"{type(e).__name__}: {e}"}), 500


def _costos():
    d = request.get_json(silent=True) or {}
    c = d.get("costos") or {}
    try:
        return {"finca": float(c.get("finca", 1800)), "merma": float(c.get("merma", 1)),
                "flete": float(c.get("flete", 680)), "kg": float(c.get("kg", 1500)),
                "fletes": {k: float(v) for k, v in (c.get("fletes") or {}).items() if v not in ("", None)}}
    except (TypeError, ValueError):
        return {}


@app.route("/api/local", methods=["GET", "POST", "DELETE"])
def api_local():
    if request.method == "GET":
        return jsonify(local.listar(request.args.get("desde") or "0000-00-00",
                                    request.args.get("hasta") or "9999-99-99"))
    d = request.get_json(silent=True) or {}
    try:
        fecha = date.fromisoformat(str(d.get("fecha"))).isoformat()
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
    if request.method == "DELETE":
        local.borrar(fecha)
        return jsonify({"ok": True})
    try:
        precio = float(d.get("precio_kg"))
    except (TypeError, ValueError):
        return jsonify({"error": "Precio inválido"}), 400
    if not 300 <= precio <= 20000:
        return jsonify({"error": "El precio debe estar entre 300 y 20.000 $/kg"}), 400
    local.guardar(fecha, precio)
    return jsonify({"ok": True})


@app.route("/api/uso")
def api_uso():
    return jsonify(agente.uso_mes())


@app.route("/api/resumen", methods=["POST"])
def api_resumen():
    return jsonify(agente.resumen(_costos()))


@app.route("/api/briefing", methods=["POST"])
def api_briefing():
    try:
        t, usd = agente.briefing(_costos())
        return jsonify({"texto": t, "usd": usd, "uso": agente.uso_mes()})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/preguntar", methods=["POST"])
def api_preguntar():
    p = ((request.get_json(silent=True) or {}).get("pregunta") or "").strip()[:500]
    if not p:
        return jsonify({"error": "Escribe una pregunta"}), 400
    try:
        t, usd = agente.preguntar(p, _costos())
        return jsonify({"texto": t, "usd": usd, "uso": agente.uso_mes()})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


if __name__ == "__main__":
    print("Servidor activo. Abre en tu navegador: http://127.0.0.1:5000")
    app.run(port=5000, debug=False)
