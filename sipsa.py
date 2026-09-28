"""Extracción, almacenamiento y verificación de precios de tomate del boletín SIPSA (DANE).

Uso:
    python sipsa.py reconstruir     # reprocesa TODOS los ZIP de pdf_cache y recrea tomate.db
    python sipsa.py actualizar      # descarga boletines nuevos y los agrega
    python sipsa.py verificar       # informe de calidad de datos
"""

import io
import os
import re
import sqlite3
import statistics
import sys
import unicodedata
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

import pypdf
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "pdf_cache")
DB_FILE = os.path.join(BASE_DIR, "tomate.db")
URL_BASE = "https://www.dane.gov.co/files/operaciones/SIPSA/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGO = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

PRECIO = r"\d{1,3}(?:\.\d{3})*"
PRESENTACIONES = (
    r"Canastilla|Caja|Bulto|Bolsa|Kilogramo|Unidad|Arroba|Atado|Cu[ñn]ete|Saco|"
    r"Malla|Bandeja|Paca|Racimo|Libra|Tonelada|Docena|Costal|Guacal|Lata|Bid[oó]n"
)
RE_FILA = re.compile(
    rf"^(?P<prod>Tomate\b.*?)\s+(?P<pres>(?:{PRESENTACIONES})\b.*?)\s+"
    rf"(?P<n>\d+(?:[.,]\d+)?)\s+(?P<u>Kilogramo|Gramo|Libra|Tonelada)s?\s+"
    rf"(?P<a>{PRECIO})\s+(?P<b>{PRECIO})\s+(?P<c>{PRECIO})\s+(?P<d>{PRECIO})\s*$",
    re.IGNORECASE,
)
RE_FECHA = re.compile(r"(\d{1,2})\s+de\s+([A-Za-zñÑ]+)\s+de\s+(\d{4})", re.IGNORECASE)
RE_SUFIJO_FECHA = re.compile(r"[\s_-]*\d{1,2}[-_/]\d{1,2}[-_/]\d{2,4}(?:[-_]\d+)?\s*$")
UNIDAD_KG = {"kilogramo": 1.0, "gramo": 0.001, "libra": 0.5, "tonelada": 1000.0}

# Rango razonable de $/kg de tomate mayorista en Colombia; fuera de él el dato se marca atípico
KG_MIN_VALIDO, KG_MAX_VALIDO = 500, 20000


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def limpiar_mercado(nombre: str) -> str:
    nombre = unicodedata.normalize("NFC", nombre).replace("_", " ")
    nombre = re.sub(r"\.pdf$", "", nombre, flags=re.IGNORECASE)
    prev = None
    while prev != nombre:
        prev = nombre
        nombre = RE_SUFIJO_FECHA.sub("", nombre)
    nombre = re.sub(r"\s+", " ", nombre).strip(" -,")
    if nombre.lower().startswith("medellín, plaza minorista"):
        nombre = "Medellín, Plaza Minorista José María Villa"
    return nombre


def ciudad_de(mercado: str) -> str:
    m = re.split(r",|\(", mercado, maxsplit=1)[0].strip()
    return m or mercado


def es_minorista(mercado: str) -> int:
    return int("minorista" in mercado.lower())


def nombre_zip(f: date) -> str:
    return f"bol-SIPSADiario-regionales-{f.day:02d}{MESES[f.month - 1]}{f.year}.zip"


def fecha_de_zip(nombre: str) -> date | None:
    m = re.search(r"regionales-(\d{2})([a-z]{3})(\d{4})\.zip$", nombre)
    if not m or m.group(2) not in MESES:
        return None
    return date(int(m.group(3)), MESES.index(m.group(2)) + 1, int(m.group(1)))


def fecha_de_pdf_nombre(nombre: str) -> date | None:
    m = re.search(r"(\d{1,2})[-_](\d{1,2})[-_](\d{4})", nombre)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _num(s: str) -> int:
    return int(s.replace(".", ""))


def _texto_pdf(datos: bytes) -> str:
    r = pypdf.PdfReader(io.BytesIO(datos))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def parsear_pdf(nombre_pdf: str, datos: bytes) -> tuple[list[dict], list[str]]:
    """Devuelve (registros, avisos) de un PDF individual. Nunca lanza excepción."""
    avisos: list[str] = []
    try:
        texto = _texto_pdf(datos)
    except Exception as e:
        return [], [f"PDF ilegible: {type(e).__name__}: {e}"]
    lineas = [l.strip() for l in texto.split("\n")]
    if not any("tomate" in l.lower() for l in lineas):
        return [], []

    # Mercado: nombre oficial dentro del PDF (línea posterior a "PRECIOS DE VENTA MAYORISTA")
    mercado_pdf = None
    for i, l in enumerate(lineas[:6]):
        if l.upper().startswith("PRECIOS DE VENTA") and i + 1 < len(lineas):
            mercado_pdf = limpiar_mercado(lineas[i + 1])
            break
    mercado_arch = limpiar_mercado(os.path.basename(nombre_pdf))
    mercado = mercado_pdf or mercado_arch
    if mercado_pdf and _sin_acentos(mercado_pdf).lower() != _sin_acentos(mercado_arch).lower():
        avisos.append(f"nombre distinto PDF='{mercado_pdf}' archivo='{mercado_arch}' (se usa PDF)")

    # Fecha: la impresa en el encabezado del PDF manda; el nombre del archivo es respaldo
    fecha = None
    for l in lineas[:15]:
        m = RE_FECHA.search(l)
        if m and m.group(2).lower() in MESES_LARGO:
            try:
                fecha = date(int(m.group(3)), MESES_LARGO[m.group(2).lower()], int(m.group(1)))
            except ValueError:
                pass
            break
    f_arch = fecha_de_pdf_nombre(nombre_pdf)
    if fecha is None:
        fecha = f_arch
        if fecha is None:
            return [], ["sin fecha en encabezado ni en nombre de archivo"]
    elif f_arch and f_arch != fecha:
        avisos.append(f"fecha PDF {fecha} != fecha archivo {f_arch} (se usa PDF)")

    # Unir líneas partidas (p.ej. "Tomate riogrande" / "bumangués Caja de cartón 25 ...")
    logicas: list[str] = []
    i = 0
    while i < len(lineas):
        l = lineas[i]
        if re.match(r"tomate\b", l, re.IGNORECASE) and not re.search(rf"{PRECIO}\s*$", l):
            if i + 1 < len(lineas) and re.search(rf"{PRECIO}\s*$", lineas[i + 1]):
                l = f"{l} {lineas[i + 1]}"
                i += 1
        logicas.append(l)
        i += 1

    registros = []
    for l in logicas:
        low = _sin_acentos(l).lower()
        if not low.startswith("tomate") or "arbol" in low or low.strip() == "tomates":
            continue
        m = RE_FILA.match(l)
        if not m:
            avisos.append(f"línea de tomate no reconocida: '{l}'")
            continue
        n = float(m["n"].replace(",", "."))
        peso = n * UNIDAD_KG[m["u"].lower()]
        if peso <= 0:
            avisos.append(f"peso inválido: '{l}'")
            continue
        r1 = (_num(m["a"]), _num(m["b"]))
        r2 = (_num(m["c"]), _num(m["d"]))
        rondas = [r for r in (r1, r2) if r[0] > 0 and r[1] > 0]
        if not rondas:
            avisos.append(f"sin precios: '{l}'")
            continue
        kg_min = min(r[0] for r in rondas) / peso
        kg_max = max(r[1] for r in rondas) / peso
        kg_prom = statistics.mean((r[0] + r[1]) / 2 for r in rondas) / peso
        atipico = int(
            any(r[0] > r[1] for r in rondas)
            or not (KG_MIN_VALIDO <= kg_prom <= KG_MAX_VALIDO)
        )
        producto = re.sub(r"\s+", " ", m["prod"]).strip().capitalize()
        pres = re.sub(r"\s+", " ", m["pres"]).strip().capitalize()
        registros.append({
            "fecha": fecha.isoformat(),
            "mercado": mercado,
            "ciudad": ciudad_de(mercado),
            "minorista": es_minorista(mercado),
            "producto": producto,
            "presentacion": pres,
            "peso_kg": round(peso, 3),
            "r1_min": r1[0], "r1_max": r1[1], "r2_min": r2[0], "r2_max": r2[1],
            "kg_min": round(kg_min, 2), "kg_max": round(kg_max, 2), "precio_kg": round(kg_prom, 2),
            "atipico": atipico,
        })
    return registros, avisos


def _procesar_zip(ruta: str) -> dict:
    """Procesa un ZIP completo (ejecutable en subproceso)."""
    nombre = os.path.basename(ruta)
    out = {"zip": nombre, "registros": [], "avisos": [], "n_pdfs": 0, "estado": "ok"}
    try:
        with zipfile.ZipFile(ruta) as z:
            for n in z.namelist():
                if not n.lower().endswith(".pdf"):
                    continue
                out["n_pdfs"] += 1
                regs, avisos = parsear_pdf(n, z.read(n))
                out["registros"].extend(regs)
                out["avisos"].extend((n, a) for a in avisos)
    except Exception as e:
        out["estado"] = f"zip inválido: {type(e).__name__}: {e}"
    return out


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def crear_esquema(conn: sqlite3.Connection, reset: bool = False):
    if reset:
        conn.executescript("DROP TABLE IF EXISTS precios; DROP TABLE IF EXISTS zips; DROP TABLE IF EXISTS avisos;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            mercado TEXT NOT NULL,
            ciudad TEXT NOT NULL,
            minorista INTEGER NOT NULL DEFAULT 0,
            producto TEXT NOT NULL,
            presentacion TEXT NOT NULL,
            peso_kg REAL NOT NULL,
            r1_min INTEGER, r1_max INTEGER, r2_min INTEGER, r2_max INTEGER,
            kg_min REAL, kg_max REAL, precio_kg REAL NOT NULL,
            atipico INTEGER NOT NULL DEFAULT 0,
            zip_origen TEXT,
            UNIQUE(fecha, mercado, producto, presentacion, peso_kg) ON CONFLICT REPLACE
        );
        CREATE INDEX IF NOT EXISTS ix_precios_fecha ON precios(fecha);
        CREATE INDEX IF NOT EXISTS ix_precios_mercado ON precios(mercado, producto);
        CREATE TABLE IF NOT EXISTS zips (
            nombre TEXT PRIMARY KEY, fecha_zip TEXT, n_pdfs INTEGER, n_registros INTEGER,
            estado TEXT, procesado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS avisos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zip TEXT, pdf TEXT, aviso TEXT
        );
    """)


COLS = ("fecha mercado ciudad minorista producto presentacion peso_kg r1_min r1_max r2_min r2_max "
        "kg_min kg_max precio_kg atipico").split()


def guardar_resultado(conn: sqlite3.Connection, res: dict):
    f = fecha_de_zip(res["zip"])
    conn.execute("DELETE FROM avisos WHERE zip = ?", (res["zip"],))
    conn.executemany(
        f"INSERT INTO precios ({','.join(COLS)}, zip_origen) VALUES ({','.join('?' * (len(COLS) + 1))})",
        [tuple(r[c] for c in COLS) + (res["zip"],) for r in res["registros"]],
    )
    conn.executemany(
        "INSERT INTO avisos (zip, pdf, aviso) VALUES (?, ?, ?)",
        [(res["zip"], p, a) for p, a in res["avisos"]],
    )
    conn.execute(
        "INSERT OR REPLACE INTO zips VALUES (?, ?, ?, ?, ?, ?)",
        (res["zip"], f.isoformat() if f else None, res["n_pdfs"], len(res["registros"]),
         res["estado"], datetime.now().isoformat(timespec="seconds")),
    )


def marcar_atipicos_estadisticos(conn: sqlite3.Connection):
    """Marca como atípico un precio/kg aislado: fuera de 40%-250% de la mediana de su mercado+producto+presentación
    Y a la vez fuera de 40%-250% de la mediana de ese día en todos los mercados (una caída real de precios
    que ocurre en muchos mercados a la vez NO se marca)."""
    conn.execute("UPDATE precios SET atipico = 0 WHERE precio_kg BETWEEN ? AND ?", (KG_MIN_VALIDO, KG_MAX_VALIDO))
    filas = conn.execute(
        "SELECT id, fecha, mercado, producto, presentacion, precio_kg FROM precios WHERE atipico = 0"
    ).fetchall()
    grupos: dict[tuple, list] = {}
    por_dia: dict[tuple, list] = {}
    for r in filas:
        grupos.setdefault((r["mercado"], r["producto"], r["presentacion"]), []).append(r)
        por_dia.setdefault((r["fecha"], r["producto"]), []).append(r["precio_kg"])
    ids = []
    for g in grupos.values():
        if len(g) < 5:
            continue
        med = statistics.median(x["precio_kg"] for x in g)
        for x in g:
            if 0.4 * med <= x["precio_kg"] <= 2.5 * med:
                continue
            dia = por_dia[(x["fecha"], x["producto"])]
            if len(dia) >= 3:
                med_dia = statistics.median(dia)
                if 0.4 * med_dia <= x["precio_kg"] <= 2.5 * med_dia:
                    continue
            ids.append(x["id"])
    conn.executemany("UPDATE precios SET atipico = 1 WHERE id = ?", [(i,) for i in ids])
    return len(ids)


def reconstruir():
    zips = sorted(
        os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if f.lower().endswith(".zip")
    )
    print(f"Reprocesando {len(zips)} ZIP de {CACHE_DIR} ...")
    conn = conectar()
    crear_esquema(conn, reset=True)
    with ProcessPoolExecutor() as ex:
        for i, res in enumerate(ex.map(_procesar_zip, zips, chunksize=2), 1):
            guardar_resultado(conn, res)
            if i % 25 == 0:
                conn.commit()
                print(f"  {i}/{len(zips)}", end="\r")
    n_at = marcar_atipicos_estadisticos(conn)
    conn.commit()
    print(f"\nListo. Atípicos estadísticos marcados: {n_at}")
    conn.close()
    verificar()


def _descargar(f: date, forzar: bool) -> str | None:
    """Descarga el ZIP del día. Devuelve la ruta si quedó (nuevo o distinto) o None."""
    nombre = nombre_zip(f)
    ruta = os.path.join(CACHE_DIR, nombre)
    if os.path.exists(ruta) and not forzar:
        return None
    try:
        r = requests.get(URL_BASE + nombre, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        print(f"  {f}: error de red ({type(e).__name__})")
        return None
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return None
    if os.path.exists(ruta):
        with open(ruta, "rb") as fh:
            if fh.read() == r.content:
                return None
    with open(ruta, "wb") as fh:
        fh.write(r.content)
    return ruta


def actualizar(dias_atras: int = 10) -> dict:
    """Descarga boletines faltantes de los últimos días (y revalida los 3 más recientes) y los procesa."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    hoy = date.today()
    nuevos = []
    recientes = 0
    for i in range(dias_atras + 1):
        f = hoy - timedelta(days=i)
        if f.weekday() >= 5:
            continue
        recientes += 1
        ruta = _descargar(f, forzar=recientes <= 3)
        if ruta:
            nuevos.append(ruta)
    conn = conectar()
    crear_esquema(conn)
    n_reg = 0
    for ruta in nuevos:
        res = _procesar_zip(ruta)
        guardar_resultado(conn, res)
        n_reg += len(res["registros"])
    if nuevos:
        marcar_atipicos_estadisticos(conn)
    conn.commit()
    ultima = conn.execute("SELECT MAX(fecha) FROM precios").fetchone()[0]
    conn.close()
    return {"zips_nuevos": [os.path.basename(r) for r in nuevos], "registros": n_reg, "ultima_fecha": ultima}


def descargar_historico(desde: date, hasta: date, hilos: int = 6) -> int:
    """Baja en paralelo los boletines de días hábiles entre dos fechas (los que ya existen se omiten)."""
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(CACHE_DIR, exist_ok=True)
    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    dias = [d for d in dias if d.weekday() < 5]
    with ThreadPoolExecutor(hilos) as ex:
        nuevos = [r for r in ex.map(lambda d: _descargar(d, False), dias) if r]
    print(f"Descargados {len(nuevos)} boletines nuevos de {len(dias)} días hábiles")
    return len(nuevos)


def verificar():
    conn = conectar()
    q = lambda s, *a: conn.execute(s, a).fetchall()
    tot, ini, fin, dias = q("SELECT COUNT(*), MIN(fecha), MAX(fecha), COUNT(DISTINCT fecha) FROM precios")[0]
    print(f"\n== VERIFICACIÓN ==\nRegistros: {tot} | fechas: {ini} -> {fin} | días con datos: {dias}")
    print("Mercados distintos:", q("SELECT COUNT(DISTINCT mercado) FROM precios")[0][0])
    print("Atípicos:", q("SELECT COUNT(*) FROM precios WHERE atipico=1")[0][0])
    print("ZIP con problemas:", [tuple(r) for r in q("SELECT nombre, estado FROM zips WHERE estado != 'ok'")])
    print("ZIP sin registros:", q("SELECT COUNT(*) FROM zips WHERE n_registros = 0")[0][0])
    tipos = {}
    for r in q("SELECT aviso FROM avisos"):
        k = re.sub(r"'.*'", "'…'", re.sub(r"\d{4}-\d{2}-\d{2}", "F", r[0]))[:70]
        tipos[k] = tipos.get(k, 0) + 1
    print("Avisos de extracción:", tipos or "ninguno")
    print("Mercados con más registros:")
    for r in q("SELECT mercado, COUNT(*) n, COUNT(DISTINCT fecha) d FROM precios GROUP BY mercado ORDER BY d DESC LIMIT 12"):
        print(f"  {r[0]:50s} filas={r[1]:5d} días={r[2]}")
    dup = q("SELECT COUNT(*) FROM (SELECT 1 FROM precios GROUP BY fecha,mercado,producto,presentacion,peso_kg HAVING COUNT(*)>1)")[0][0]
    print("Duplicados de clave:", dup)
    conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    if cmd == "reconstruir":
        reconstruir()
    elif cmd == "actualizar":
        print(actualizar(int(sys.argv[2]) if len(sys.argv) > 2 else 10))
    elif cmd == "historico":
        descargar_historico(date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]))
        reconstruir()
    elif cmd == "verificar":
        verificar()
    else:
        print(__doc__)
