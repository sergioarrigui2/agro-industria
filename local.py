import os
import sqlite3

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local.db")
MERCADO = "Garzón (mi precio)"


def _conn():
    c = sqlite3.connect(RUTA)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS venta_local (fecha TEXT PRIMARY KEY, precio_kg REAL NOT NULL)")
    return c


def listar(desde="0000-00-00", hasta="9999-99-99"):
    c = _conn()
    try:
        return [dict(r) for r in c.execute(
            "SELECT fecha, precio_kg FROM venta_local WHERE fecha BETWEEN ? AND ? ORDER BY fecha", (desde, hasta))]
    finally:
        c.close()


def guardar(fecha, precio_kg):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO venta_local (fecha, precio_kg) VALUES (?, ?)", (fecha, precio_kg))
        c.commit()
    finally:
        c.close()


def borrar(fecha):
    c = _conn()
    try:
        c.execute("DELETE FROM venta_local WHERE fecha = ?", (fecha,))
        c.commit()
    finally:
        c.close()
