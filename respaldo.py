"""Respaldo de las bases de la finca a GitHub (solo si el repositorio es privado).

Uso:  python respaldo.py              -> exporta, hace commit y sube
      python respaldo.py restaurar    -> reconstruye las bases desde respaldo/ (solo si no existen)
"""
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(AQUI, "respaldo")
BASES = ("finca", "local", "prediccion")  # tomate.db (precios DANE) se reconstruye con: python sipsa.py historico
REPO = "sergioarrigui2/agro-industria"


def git(*a):
    return subprocess.run(["git", *a], cwd=AQUI, capture_output=True, text=True)


def es_privado():
    r = requests.get(f"https://api.github.com/repos/{REPO}", timeout=15)
    return r.status_code == 404


def exportar():
    os.makedirs(CARPETA, exist_ok=True)
    for b in BASES:
        ruta = os.path.join(AQUI, f"{b}.db")
        if not os.path.exists(ruta):
            continue
        con = sqlite3.connect(ruta)
        with open(os.path.join(CARPETA, f"{b}.sql"), "w", encoding="utf-8", newline="\n") as f:
            for linea in con.iterdump():
                f.write(linea + "\n")
        con.close()


def restaurar():
    for b in BASES:
        sql, ruta = os.path.join(CARPETA, f"{b}.sql"), os.path.join(AQUI, f"{b}.db")
        if not os.path.exists(sql):
            continue
        if os.path.exists(ruta) and os.path.getsize(ruta) > 0:
            print(f"{b}.db ya existe: no se toca (bórralo a mano si quieres restaurar encima).")
            continue
        con = sqlite3.connect(ruta)
        con.executescript(open(sql, encoding="utf-8").read())
        con.commit()
        con.close()
        print(f"{b}.db restaurada")


def respaldar():
    if not es_privado():
        print("NO SE SUBIÓ: el repositorio es público y las bases tienen tus costos y ventas.\n"
              "Hazlo privado en GitHub: Settings > General > Danger Zone > Change visibility > Private.")
        return 1
    exportar()
    git("add", "respaldo")
    if not git("status", "--porcelain", "respaldo").stdout.strip():
        print("Sin cambios desde el último respaldo.")
        return 0
    git("commit", "-m", f"Respaldo de datos {datetime.now():%Y-%m-%d %H:%M}")
    r = git("push")
    print("Respaldo subido a GitHub." if r.returncode == 0 else "Error al subir:\n" + r.stderr)
    return r.returncode


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "restaurar":
        restaurar()
    else:
        sys.exit(respaldar())
