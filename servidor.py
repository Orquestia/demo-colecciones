"""Servidor de la demo con las dos opciones de la propuesta.

    python3 servidor.py        →  http://localhost:8765

  /                          portada con los dos caminos
  /opcion-1/                 Opción 1 · vitrina alimentada por el MCP (se actualiza sola cada 3 días)
  /opcion-2/                 Opción 2 · vitrina publicada por la plataforma central
  /opcion-2/plataforma.html  Opción 2 · plataforma central (núcleo simulado; en producción Odoo 18)
"""
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import nucleo
import scraper

BASE = Path(__file__).parent
PROGRAMACION = scraper.DATA / "programacion.json"
CADA_DIAS = 3
OP1 = {"activo": False}


# ---------- Opción 1 ----------

def op1_catalogo():
    archivo = scraper.DATA / "catalogo.json"
    datos = json.loads(archivo.read_text()) if archivo.exists() else {"productos": []}
    productos = [scraper.completar(p) for p in datos["productos"] if p.get("estado") != "retirado"]
    return {"ultima_corrida": datos.get("ultima_corrida"), "programacion": programacion(),
            "productos": [{k: p.get(k) for k in ("id", "nombre", "marca", "categoria", "genero", "precio", "tallas", "imagenes",
                                                 "disponible", "primera_vez", "publicado_en_fuente", "fuente")} for p in productos],
            "fuentes": {k: v["nombre"] for k, v in scraper.FUENTES.items()}, "actualizando": OP1}


def op1_actualizar(origen="manual"):
    if OP1.get("activo"):
        return False
    OP1.clear()
    OP1.update({"activo": True, "origen": origen, "inicio": datetime.now(timezone.utc).isoformat(timespec="seconds"), "avance": {}})

    def trabajo():
        try:
            OP1["resultado"] = scraper.correr(paralelo=True, progreso=lambda c, e, n: OP1["avance"].__setitem__(c, {"etapa": e, "n": n}))["resumen"]
        except Exception as e:
            OP1["error"] = str(e)
        finally:
            OP1["activo"] = False
            guardar_programacion()

    threading.Thread(target=trabajo, daemon=True).start()
    return True


def programacion():
    if PROGRAMACION.exists():
        return json.loads(PROGRAMACION.read_text())
    return guardar_programacion()


def guardar_programacion():
    p = {"cada_dias": CADA_DIAS,
         "proxima": (datetime.now(timezone.utc) + timedelta(days=CADA_DIAS)).isoformat(timespec="seconds")}
    PROGRAMACION.write_text(json.dumps(p))
    return p


def programador():
    """En la demo, un hilo; en producción, una tarea programada en la nube cada 3 días."""
    while True:
        try:
            if datetime.fromisoformat(programacion()["proxima"]) <= datetime.now(timezone.utc):
                op1_actualizar("programada")
        except Exception as e:
            print("programador:", e, file=sys.stderr)
        time.sleep(60)


# ---------- Servidor ----------

class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE / "vitrina"), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cuerpo(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        rutas = {
            "/api/op1/catalogo": op1_catalogo,
            "/api/op2/tablero": nucleo.tablero,
            "/api/op2/publicado": lambda: {"productos": nucleo.productos("publicado")},
            "/api/op2/productos": lambda: {"productos": nucleo.productos(q.get("estado"), q.get("proveedor"))},
            "/api/op2/registro": lambda: {"eventos": nucleo.registro()},
            "/api/op2/dashboard": lambda: nucleo.dashboard(q.get("proveedor") or None, q.get("dias", 7)),
        }
        if u.path in rutas:
            return self._json(rutas[u.path]())
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path).path
        try:
            if u == "/api/op1/actualizar":
                return self._json({"iniciada": op1_actualizar()})
            if u == "/api/op2/actualizar":
                return self._json({"iniciada": nucleo.actualizar()})
            b = self._cuerpo()
            if u == "/api/op2/proveedores/probar":
                return self._json(nucleo.probar_proveedor(b["url"]))
            if u == "/api/op2/proveedores":
                return self._json({"clave": nucleo.agregar_proveedor(b["nombre"], b["url"], b["tipo"])})
            if u == "/api/op2/proveedores/activo":
                nucleo.activar_proveedor(b["clave"], b["activo"])
                return self._json({"ok": True})
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"error": "ruta no encontrada"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    except OSError:
        sys.exit(f"El puerto {puerto} ya está en uso: la demo probablemente ya está corriendo en http://localhost:{puerto}\n"
                 f"Para usar otro puerto: python3 servidor.py 8766")
    nucleo.iniciar()
    threading.Thread(target=programador, daemon=True).start()
    print(f"Demo:  http://localhost:{puerto}")
    servidor.serve_forever()
