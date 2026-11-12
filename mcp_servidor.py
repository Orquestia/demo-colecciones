"""Opción 1 · Servidor MCP del catálogo de colecciones.

Expone a Claude las herramientas para mantener al día el catálogo web: leer las fuentes, ver qué llegó
nuevo, buscar por categoría o marca y consultar el estado de cada fuente. Lo que se lee se publica
directo en la vitrina de la Opción 1 (no hay aprobación manual).

Protocolo MCP sobre stdio (JSON-RPC, un mensaje por línea), sin dependencias externas.
Configuración para Claude Code: ver .mcp.json en esta carpeta.
"""
import json
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import scraper
from categorias import LISTA

VERSION_PROTOCOLO = "2025-06-18"
URL_VITRINA = "http://localhost:8765/opcion-1/"
ESTADO = {"activo": False}


def _catalogo():
    archivo = scraper.DATA / "catalogo.json"
    if not archivo.exists():
        return {"productos": [], "ultima_corrida": None}
    datos = json.loads(archivo.read_text())
    datos["productos"] = [scraper.completar(p) for p in datos["productos"] if p.get("estado") != "retirado"]
    return datos


def _corto(p):
    return {"nombre": p["nombre"], "marca": p.get("marca") or None, "categoria": p.get("categoria") or "Otros",
            "precio_cop": p.get("precio"), "fuente": scraper.FUENTES.get(p["fuente"], {}).get("nombre", p["fuente"]),
            "url": p.get("url"), "visto_por_primera_vez": (p.get("primera_vez") or "")[:10]}


def actualizar_catalogo(fuentes=None):
    if ESTADO["activo"]:
        return "Ya hay una actualización en curso. Consulta el avance con estado_actualizacion."
    fuentes = [f for f in (fuentes or []) if f in scraper.FUENTES] or None
    ESTADO.clear()
    ESTADO.update({"activo": True, "inicio": datetime.now(timezone.utc).isoformat(timespec="seconds"), "avance": {}})

    def trabajo():
        try:
            corrida = scraper.correr(fuentes, paralelo=True,
                                     progreso=lambda clave, etapa, n: ESTADO["avance"].__setitem__(clave, f"{etapa} ({n})"))
            ESTADO["resultado"] = corrida
        except Exception as e:
            ESTADO["error"] = str(e)
        finally:
            ESTADO["activo"] = False

    threading.Thread(target=trabajo, daemon=True).start()
    nombres = ", ".join(scraper.FUENTES[f]["nombre"] for f in (fuentes or scraper.FUENTES))
    return (f"Actualización iniciada en paralelo para: {nombres}. Puede tardar de 1 a 5 minutos "
            f"(Designer Room limita la velocidad). Consulta el avance con estado_actualizacion.")


def estado_actualizacion():
    if ESTADO.get("activo"):
        return {"en_curso": True, "desde": ESTADO["inicio"], "avance_por_fuente": ESTADO["avance"]}
    if "resultado" in ESTADO:
        r = ESTADO["resultado"]
        return {"en_curso": False, "terminada": r["fecha"], "resumen": r["resumen"], "fuentes": r["fuentes"],
                "vitrina": URL_VITRINA}
    if "error" in ESTADO:
        return {"en_curso": False, "error": ESTADO["error"]}
    return {"en_curso": False, "detalle": "No se ha lanzado ninguna actualización en esta sesión.", **estado_fuentes()}


def estado_fuentes():
    datos = _catalogo()
    c = datos.get("ultima_corrida") or {}
    conteo = Counter(p["fuente"] for p in datos["productos"])
    return {"ultima_actualizacion": c.get("fecha"),
            "fuentes": [{"fuente": f["nombre"], "productos_en_catalogo": conteo.get(k, 0),
                         "ultima_lectura": (c.get("fuentes") or {}).get(k)} for k, f in scraper.FUENTES.items()],
            "programacion": "Actualización automática cada 3 días", "vitrina": URL_VITRINA}


def novedades(dias=3, limite=30):
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    datos = _catalogo()
    nuevos = [p for p in datos["productos"] if (p.get("primera_vez") or "") >= desde
              or (p.get("publicado_en_fuente") or "") >= desde[:10]]
    nuevos.sort(key=lambda p: p.get("publicado_en_fuente") or p.get("primera_vez") or "", reverse=True)
    return {"desde": desde[:10], "total": len(nuevos), "por_categoria": dict(Counter(p.get("categoria") or "Otros" for p in nuevos)),
            "productos": [_corto(p) for p in nuevos[:limite]]}


def buscar_productos(texto=None, categoria=None, marca=None, precio_max=None, limite=20):
    datos = _catalogo()
    res = []
    for p in datos["productos"]:
        if categoria and (p.get("categoria") or "").lower() != categoria.lower():
            continue
        if marca and marca.lower() not in (p.get("marca") or p["nombre"]).lower():
            continue
        if precio_max and (not p.get("precio") or p["precio"] > precio_max):
            continue
        if texto and texto.lower() not in f"{p['nombre']} {p.get('marca', '')}".lower():
            continue
        res.append(p)
    return {"total": len(res), "productos": [_corto(p) for p in res[:limite]]}


def categorias():
    datos = _catalogo()
    conteo = Counter(p.get("categoria") or "Otros" for p in datos["productos"])
    return {"lista_comun": [{"categoria": c, "productos": conteo.get(c, 0)} for c in LISTA + ["Otros"]]}


def enlace_catalogo():
    return {"enlace": URL_VITRINA, "nota": "Este es el enlace que se comparte con los clientes."}


HERRAMIENTAS = {
    "actualizar_catalogo": (actualizar_catalogo, "Lee las fuentes (3 páginas web y 2 carpetas de Drive) en paralelo y actualiza la vitrina. Corre en segundo plano.",
                            {"fuentes": {"type": "array", "items": {"type": "string", "enum": list(scraper.FUENTES)},
                                         "description": "Opcional: solo estas fuentes. Vacío = todas."}}),
    "estado_actualizacion": (estado_actualizacion, "Avance o resultado de la última actualización lanzada.", {}),
    "estado_fuentes": (estado_fuentes, "Cuántos productos hay por fuente y cuándo se leyó cada una.", {}),
    "novedades": (novedades, "Productos que llegaron en los últimos N días, con su categoría.",
                  {"dias": {"type": "integer", "default": 3}, "limite": {"type": "integer", "default": 30}}),
    "buscar_productos": (buscar_productos, "Busca en el catálogo por texto, categoría de la lista común, marca o precio máximo (COP).",
                         {"texto": {"type": "string"}, "categoria": {"type": "string", "enum": LISTA + ["Otros"]},
                          "marca": {"type": "string"}, "precio_max": {"type": "number"}, "limite": {"type": "integer", "default": 20}}),
    "categorias": (categorias, "La lista común de categorías con cuántos productos tiene cada una.", {}),
    "enlace_catalogo": (enlace_catalogo, "El enlace de la vitrina web para compartir con clientes.", {}),
}


def responder(msg):
    metodo, id_ = msg.get("method"), msg.get("id")
    if id_ is None:  # notificación: no se responde
        return None
    if metodo == "initialize":
        version = msg.get("params", {}).get("protocolVersion", VERSION_PROTOCOLO)
        res = {"protocolVersion": version, "capabilities": {"tools": {}},
               "serverInfo": {"name": "catalogo-colecciones", "version": "0.1.0"},
               "instructions": "Catálogo de colecciones de Camilo (Opción 1 de Orquestia). Responde en español."}
    elif metodo == "ping":
        res = {}
    elif metodo == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props}}
                         for n, (_, d, props) in HERRAMIENTAS.items()]}
    elif metodo == "tools/call":
        nombre = msg["params"]["name"]
        args = msg["params"].get("arguments") or {}
        try:
            salida = HERRAMIENTAS[nombre][0](**args)
            texto = salida if isinstance(salida, str) else json.dumps(salida, ensure_ascii=False, indent=1)
            res = {"content": [{"type": "text", "text": texto}], "isError": False}
        except Exception as e:
            res = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Método no soportado: {metodo}"}}
    return {"jsonrpc": "2.0", "id": id_, "result": res}


def main():
    for linea in sys.stdin:
        if not linea.strip():
            continue
        try:
            respuesta = responder(json.loads(linea))
        except Exception as e:
            respuesta = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if respuesta:
            sys.stdout.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
