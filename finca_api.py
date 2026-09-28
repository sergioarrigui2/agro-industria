from flask import Blueprint, jsonify, request

import agente
import analisis
import asistente
import finca

bp = Blueprint("finca_api", __name__, url_prefix="/api")


def _json():
    return request.get_json(silent=True) or {}


def _costos():
    c = _json().get("costos") or {}
    try:
        return {"finca": float(c.get("finca", 1800)), "merma": float(c.get("merma", 1)),
                "flete": float(c.get("flete", 680)), "kg": float(c.get("kg", 1500)),
                "usar_real": c.get("usar_real", True),
                "fletes": {k: float(v) for k, v in (c.get("fletes") or {}).items() if v not in ("", None)}}
    except (TypeError, ValueError):
        return {}


def _ok(fn):
    try:
        return jsonify({"ok": True, "id": fn()})
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/finca/datos")
def datos():
    return jsonify(finca.datos_completos())


@bp.route("/finca/<tabla>", methods=["GET", "POST", "DELETE"])
def crud(tabla):
    a = request.args
    if request.method == "GET":
        if tabla == "invernaderos":
            return jsonify(finca.invernaderos())
        if tabla == "lotes":
            return jsonify(finca.lotes(a.get("invernadero_id", type=int)))
        if tabla == "costos":
            return jsonify(finca.costos(a.get("lote_id", type=int), a.get("invernadero_id", type=int), a.get("desde"), a.get("hasta")))
        if tabla == "cosechas":
            return jsonify(finca.cosechas(a.get("lote_id", type=int)))
        if tabla == "ventas":
            return jsonify(finca.ventas(a.get("lote_id", type=int)))
        if tabla == "insumos":
            return jsonify(finca.insumos())
        return jsonify({"error": "no existe"}), 404
    if request.method == "DELETE":
        try:
            finca.borrar(tabla, int(a.get("id")))
            return jsonify({"ok": True})
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e)}), 400
    d = _json()
    fn = {"invernaderos": finca.guardar_invernadero, "lotes": finca.guardar_lote, "costos": finca.guardar_costo,
          "cosechas": finca.guardar_cosecha, "ventas": finca.guardar_venta, "insumos": finca.guardar_insumo,
          "insumo_precios": finca.guardar_precio_insumo}.get(tabla)
    if not fn:
        return jsonify({"error": "no existe"}), 404
    return _ok(lambda: fn(d))


@bp.route("/balance")
def balance():
    return jsonify(finca.balance(request.args.get("desde"), request.args.get("hasta")))


@bp.route("/balance/categorias")
def categorias():
    a = request.args
    return jsonify(finca.por_categoria(a.get("desde"), a.get("hasta"), a.get("lote_id", type=int), a.get("invernadero_id", type=int)))


@bp.route("/costo_real")
def costo_real():
    return jsonify(finca.costo_real_kg())


@bp.route("/semaforo", methods=["POST"])
def semaforo():
    d = _json()
    return jsonify(analisis.semaforo(_costos(), d.get("kg")))


@bp.route("/estacionalidad")
def estacionalidad():
    return jsonify(analisis.estacionalidad(request.args.get("variedad") or "Tomate chonto", request.args.get("ciudad")))


@bp.route("/calendario")
def calendario():
    a = request.args
    return jsonify(analisis.calendario_siembra(a.get("variedad") or "Tomate chonto", a.get("dias_a_cosecha"), a.get("dias_cosecha")))


@bp.route("/alertas", methods=["GET", "POST"])
def alertas():
    if request.method == "POST":
        d = _json()
        analisis.descartar(str(d.get("clave")), int(d.get("dias", 7)))
        return jsonify({"ok": True})
    return jsonify(analisis.alertas(_costos() if request.method == "POST" else {}))


@bp.route("/hoy", methods=["POST"])
def hoy():
    c = _costos()
    return jsonify({"alertas": analisis.alertas(c), "kpis": analisis.kpis(c), "semaforo": analisis.semaforo(c),
                    "uso": agente.uso_mes()})


@bp.route("/briefing2", methods=["POST"])
def briefing2():
    try:
        t, usd = asistente.briefing(_costos())
        return jsonify({"texto": t, "usd": usd, "uso": agente.uso_mes()})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@bp.route("/chat", methods=["POST"])
def chat():
    d = _json()
    p = (d.get("pregunta") or "").strip()[:600]
    if not p:
        return jsonify({"error": "Escribe una pregunta"}), 400
    try:
        t, usd = asistente.chat(p, d.get("historial"), _costos())
        return jsonify({"texto": t, "usd": usd, "uso": agente.uso_mes()})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@bp.route("/capturar", methods=["POST"])
def capturar():
    d = _json()
    try:
        r = asistente.capturar((d.get("texto") or "")[:1500], d.get("imagen"), d.get("media_type") or "image/jpeg")
        r["uso"] = agente.uso_mes()
        return jsonify(r)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@bp.route("/confirmar", methods=["POST"])
def confirmar():
    guardados, errores = 0, []
    for i, x in enumerate(_json().get("registros") or []):
        try:
            asistente.guardar_registro(x)
            guardados += 1
        except (ValueError, KeyError, TypeError) as e:
            errores.append(f"Registro {i + 1}: {e}")
    return jsonify({"guardados": guardados, "errores": errores})
