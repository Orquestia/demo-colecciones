"""Opción 2 · Núcleo central SIMULADO (en producción: Odoo 18 en Google Cloud).

Imita los modelos que tendría Odoo para esta demo (proveedores, productos con categoría y marca,
registro de publicación) sobre SQLite. El agente:
  1. lee en paralelo a todos los proveedores activos (los mismos conectores de scraper.py),
  2. completa marca y categoría: primero con lo que publica la fuente, luego por reglas y,
     para lo que queda, con un modelo de lenguaje (Claude, vía `claude -p`),
  3. publica solo lo que cumple las reglas: con precio, con foto y con categoría.
"""
import json
import re
import shutil
import sqlite3
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scraper
from categorias import LISTA, categoria_comun, normalizar

DB = scraper.DATA / "nucleo.db"
LOTE_IA = 40
CANDADO = threading.Lock()
PROGRESO = {"activo": False}


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conexion():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def iniciar():
    scraper.DATA.mkdir(exist_ok=True)
    with conexion() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS proveedores (clave TEXT PRIMARY KEY, nombre TEXT, tipo TEXT, url TEXT,
            activo INTEGER DEFAULT 1, creado TEXT, ultima_lectura TEXT, ultimo_estado TEXT);
        CREATE TABLE IF NOT EXISTS productos (id TEXT PRIMARY KEY, proveedor TEXT, nombre TEXT, marca TEXT,
            categoria TEXT, genero TEXT, precio REAL, imagenes TEXT, tallas TEXT, url TEXT, disponible INTEGER,
            estado TEXT, motivo TEXT, cat_origen TEXT, marca_origen TEXT, ia_revisado INTEGER DEFAULT 0,
            huella TEXT, primera_vez TEXT, ultima_vez TEXT, publicado_en TEXT, publicado_en_fuente TEXT);
        CREATE TABLE IF NOT EXISTS registro (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, producto TEXT,
            accion TEXT, detalle TEXT);
        CREATE TABLE IF NOT EXISTS corridas (id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT, fin TEXT, resumen TEXT);
        """)
        if not c.execute("SELECT 1 FROM proveedores").fetchone():
            for clave, f in scraper.FUENTES.items():
                c.execute("INSERT INTO proveedores (clave, nombre, tipo, url, creado) VALUES (?,?,?,?,?)",
                          (clave, f["nombre"], f["tipo"], f["url"], ahora()))
        # Carga inicial desde la última captura, para que la plataforma no arranque vacía.
        if not c.execute("SELECT 1 FROM productos").fetchone() and (scraper.DATA / "catalogo.json").exists():
            previos = json.loads((scraper.DATA / "catalogo.json").read_text())["productos"]
            vivos = [scraper.completar(p) for p in previos if p.get("estado") != "retirado"]
            _guardar(c, vivos, set(), "Carga inicial desde la última captura")
            _completar_marcas(c)
            _aplicar_reglas(c)


def _guardar(c, productos, fuentes_ok, origen):
    """Inserta o actualiza productos; lo que desaparece de una fuente leída bien queda retirado."""
    vistos = set()
    t = ahora()
    for p in productos:
        vistos.add(p["id"])
        fila = c.execute("SELECT huella, precio FROM productos WHERE id=?", (p["id"],)).fetchone()
        valores = (p["fuente"], p["nombre"], p.get("marca") or None, p.get("categoria"), p.get("genero"), p.get("precio"),
                   json.dumps(p.get("imagenes") or []), json.dumps(p.get("tallas") or []), p.get("url"),
                   None if p.get("disponible") is None else int(bool(p["disponible"])), p.get("cat_origen"),
                   "fuente" if p.get("marca") else None, p["huella"], t, p.get("publicado_en_fuente"))
        if fila is None:
            c.execute("""INSERT INTO productos (proveedor, nombre, marca, categoria, genero, precio, imagenes, tallas, url,
                         disponible, cat_origen, marca_origen, huella, ultima_vez, publicado_en_fuente, id, primera_vez, estado)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'nuevo')""", valores + (p["id"], t))
            c.execute("INSERT INTO registro (fecha, producto, accion, detalle) VALUES (?,?,?,?)", (t, p["id"], "cargado", origen))
        elif fila["huella"] != p["huella"]:
            # Cambió en la fuente: se actualiza, pero se conserva lo que el agente ya completó (marca/categoría por IA)
            c.execute("""UPDATE productos SET proveedor=?, nombre=?, marca=COALESCE(?, marca), categoria=COALESCE(?, categoria),
                         genero=?, precio=?, imagenes=?, tallas=?, url=?, disponible=?, cat_origen=COALESCE(?, cat_origen),
                         marca_origen=COALESCE(?, marca_origen), huella=?, ultima_vez=?, publicado_en_fuente=? WHERE id=?""",
                      valores + (p["id"],))
            if fila["precio"] != p.get("precio"):
                c.execute("INSERT INTO registro (fecha, producto, accion, detalle) VALUES (?,?,?,?)",
                          (t, p["id"], "precio", f"{fila['precio']} → {p.get('precio')}"))
        else:
            c.execute("UPDATE productos SET ultima_vez=? WHERE id=?", (t, p["id"]))
    for clave in fuentes_ok:
        for fila in c.execute("SELECT id FROM productos WHERE proveedor=? AND estado!='retirado'", (clave,)).fetchall():
            if fila["id"] not in vistos:
                c.execute("UPDATE productos SET estado='retirado', motivo='Ya no aparece en la fuente' WHERE id=?", (fila["id"],))
                c.execute("INSERT INTO registro (fecha, producto, accion, detalle) VALUES (?,?,?,?)",
                          (t, fila["id"], "retirado", "Ya no aparece en la fuente"))


def _completar_marcas(c):
    """Marca por reglas: busca en el nombre las marcas que ya publican otras fuentes."""
    marcas = sorted({r["marca"] for r in c.execute("SELECT DISTINCT marca FROM productos WHERE marca_origen='fuente'")
                     if r["marca"] and len(r["marca"]) > 2}, key=len, reverse=True)
    patrones = [(m, re.compile(rf"\b{re.escape(m)}\b", re.I)) for m in marcas]
    for r in c.execute("SELECT id, nombre FROM productos WHERE marca IS NULL AND estado!='retirado'").fetchall():
        m = next((m for m, pat in patrones if pat.search(r["nombre"])), None)
        if m:
            c.execute("UPDATE productos SET marca=?, marca_origen='regla' WHERE id=?", (m, r["id"]))


def _ia_clasificar(nombres):
    """Agente LLM: clasifica nombres en la lista común e identifica la marca. Devuelve {índice: (cat, marca)}."""
    prompt = ("Clasifica cada producto de moda en UNA categoría de esta lista exacta: " + json.dumps(LISTA, ensure_ascii=False) +
              ". Identifica también la marca (nombre propio, en formato título) o null. Responde SOLO un arreglo JSON "
              "con objetos {\"i\":índice,\"categoria\":...,\"marca\":...}, sin texto adicional.\n" +
              "\n".join(f"{i}. {n}" for i, n in enumerate(nombres)))
    r = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "json"], input=prompt,
                       capture_output=True, text=True, timeout=240)
    texto = json.loads(r.stdout).get("result", "")
    datos = json.loads(re.search(r"\[.*\]", texto, re.S).group(0))
    return {d["i"]: (d.get("categoria") if d.get("categoria") in LISTA else None, d.get("marca")) for d in datos}


def _ia_completar(c, progreso):
    """Lo que las reglas no resolvieron pasa por el agente LLM, una sola vez por producto."""
    if not shutil.which("claude"):
        progreso["ia"] = {"estado": "omitido", "detalle": "Claude no está disponible en este equipo"}
        return
    filas = c.execute("""SELECT id, nombre FROM productos WHERE ia_revisado=0 AND estado!='retirado'
                         AND proveedor NOT LIKE 'drive%' AND (categoria IS NULL OR marca IS NULL)""").fetchall()
    progreso["ia"] = {"estado": "trabajando", "total": len(filas), "hechos": 0}
    for i in range(0, len(filas), LOTE_IA):
        lote = filas[i:i + LOTE_IA]
        try:
            res = _ia_clasificar([f["nombre"] for f in lote])
        except Exception as e:
            progreso["ia"] = {"estado": "error", "detalle": str(e)[:200], "total": len(filas), "hechos": i}
            return
        t = ahora()
        for j, f in enumerate(lote):
            cat, marca = res.get(j, (None, None))
            c.execute("""UPDATE productos SET ia_revisado=1,
                         categoria=COALESCE(categoria, ?), cat_origen=CASE WHEN categoria IS NULL AND ? IS NOT NULL THEN 'ia' ELSE cat_origen END,
                         marca=COALESCE(marca, ?), marca_origen=CASE WHEN marca IS NULL AND ? IS NOT NULL THEN 'ia' ELSE marca_origen END
                         WHERE id=?""", (cat, cat, marca, marca, f["id"]))
            if cat or marca:
                c.execute("INSERT INTO registro (fecha, producto, accion, detalle) VALUES (?,?,?,?)",
                          (t, f["id"], "agente", f"Categoría: {cat or '—'} · Marca: {marca or '—'}"))
        c.commit()
        progreso["ia"]["hechos"] = i + len(lote)
    progreso["ia"]["estado"] = "listo"


def _aplicar_reglas(c):
    """Aprobación automática: se publica solo lo que tiene precio, foto y categoría."""
    t = ahora()
    for r in c.execute("SELECT id, precio, imagenes, categoria, estado FROM productos WHERE estado!='retirado'").fetchall():
        faltan = [m for m, ok in [("Sin precio", r["precio"]), ("Sin foto", json.loads(r["imagenes"])),
                                  ("Sin categoría", r["categoria"])] if not ok]
        nuevo, motivo = ("retenido", " · ".join(faltan)) if faltan else ("publicado", None)
        if nuevo != r["estado"]:
            c.execute("UPDATE productos SET estado=?, motivo=?, publicado_en=CASE WHEN ?='publicado' THEN ? ELSE publicado_en END WHERE id=?",
                      (nuevo, motivo, nuevo, t, r["id"]))
            c.execute("INSERT INTO registro (fecha, producto, accion, detalle) VALUES (?,?,?,?)",
                      (t, r["id"], nuevo, motivo or "Cumple las reglas: precio, foto y categoría"))


def actualizar():
    """Botón «Actualizar»: corre el agente completo en segundo plano. Devuelve False si ya hay uno en curso."""
    if not CANDADO.acquire(blocking=False):
        return False
    with conexion() as c:
        provs = [dict(r) for r in c.execute("SELECT * FROM proveedores WHERE activo=1")]
    PROGRESO.clear()
    PROGRESO.update({"activo": True, "inicio": ahora(), "fuentes": {p["clave"]: {"nombre": p["nombre"], "etapa": "en cola", "n": 0, "estado": "esperando"} for p in provs}})

    def trabajo():
        try:
            def leer(p):
                f = PROGRESO["fuentes"][p["clave"]]
                f["estado"] = "leyendo"

                def cb(etapa, n):
                    f["etapa"], f["n"] = etapa, n
                with conexion() as c:
                    previos = [{"fuente": p["clave"], "estado": "x"}] * c.execute(
                        "SELECT COUNT(*) FROM productos WHERE proveedor=? AND estado!='retirado'", (p["clave"],)).fetchone()[0]
                productos, salud, ok = scraper.leer_fuente(p["clave"], p, previos, cb)
                f.update({"estado": "ok" if ok else "alerta", "n": salud["productos"], "alerta": salud["alerta"], "segundos": salud["segundos"]})
                return p["clave"], (productos if ok else []), ok

            with ThreadPoolExecutor(max_workers=max(1, len(provs))) as ex:
                resultados = list(ex.map(leer, provs))
            with conexion() as c:
                for clave, productos, ok in resultados:
                    if ok:
                        _guardar(c, productos, {clave}, "Agente: lectura de la fuente")
                    c.execute("UPDATE proveedores SET ultima_lectura=?, ultimo_estado=? WHERE clave=?",
                              (ahora(), json.dumps(PROGRESO["fuentes"][clave], ensure_ascii=False), clave))
                c.commit()
                _completar_marcas(c)
                c.commit()
                _ia_completar(c, PROGRESO)
                _aplicar_reglas(c)
                resumen = resumen_estados(c)
                c.execute("INSERT INTO corridas (inicio, fin, resumen) VALUES (?,?,?)",
                          (PROGRESO["inicio"], ahora(), json.dumps({"estados": resumen, "fuentes": PROGRESO["fuentes"], "ia": PROGRESO.get("ia")}, ensure_ascii=False)))
            PROGRESO["resumen"] = resumen
        except Exception as e:
            PROGRESO["error"] = str(e)
        finally:
            PROGRESO["activo"] = False
            PROGRESO["fin"] = ahora()
            CANDADO.release()

    threading.Thread(target=trabajo, daemon=True).start()
    return True


def resumen_estados(c):
    return {r["estado"]: r["n"] for r in c.execute("SELECT estado, COUNT(*) n FROM productos GROUP BY estado")}


def _fila(r):
    d = dict(r)
    d["imagenes"], d["tallas"] = json.loads(d["imagenes"] or "[]"), json.loads(d["tallas"] or "[]")
    d["disponible"] = None if d["disponible"] is None else bool(d["disponible"])
    return d


def productos(estado=None, proveedor=None):
    with conexion() as c:
        q, a = "SELECT * FROM productos WHERE 1=1", []
        if estado:
            q += " AND estado=?"; a.append(estado)
        if proveedor:
            q += " AND proveedor=?"; a.append(proveedor)
        return [_fila(r) for r in c.execute(q + " ORDER BY COALESCE(publicado_en_fuente, primera_vez) DESC", a)]


def tablero():
    with conexion() as c:
        provs = []
        for r in c.execute("SELECT * FROM proveedores ORDER BY creado"):
            d = dict(r)
            d["ultimo_estado"] = json.loads(d["ultimo_estado"]) if d["ultimo_estado"] else None
            d["conteo"] = {x["estado"]: x["n"] for x in c.execute(
                "SELECT estado, COUNT(*) n FROM productos WHERE proveedor=? GROUP BY estado", (d["clave"],))}
            provs.append(d)
        ultima = c.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT 1").fetchone()
        return {"estados": resumen_estados(c), "proveedores": provs,
                "origen_categoria": {r["o"] or "sin": r["n"] for r in c.execute(
                    "SELECT cat_origen o, COUNT(*) n FROM productos WHERE estado!='retirado' GROUP BY cat_origen")},
                "ultima_corrida": dict(ultima) | {"resumen": json.loads(ultima["resumen"])} if ultima else None,
                "progreso": PROGRESO}


def registro(limite=200):
    with conexion() as c:
        return [dict(r) | {"nombre": r["nombre"]} for r in c.execute(
            """SELECT r.*, p.nombre, p.proveedor FROM registro r LEFT JOIN productos p ON p.id=r.producto
               WHERE r.accion != 'cargado' ORDER BY r.id DESC LIMIT ?""", (limite,))]


def probar_proveedor(url):
    try:
        tipo, explicacion = scraper.detectar_tipo(url)
    except Exception as e:
        return {"tipo": None, "explicacion": f"No se pudo leer la página ({e}). Puede estar bloqueando lectores automáticos.", "muestra": []}
    try:
        muestra = scraper.lectura_de_prueba(tipo, url) if tipo else []
    except Exception as e:
        aviso = "la tienda pidió esperar; intenta de nuevo en un minuto" if "429" in str(e) else f"no se pudo leer la muestra ({e})"
        return {"tipo": tipo, "explicacion": f"{explicacion}, pero {aviso}.", "muestra": []}
    return {"tipo": tipo, "explicacion": explicacion,
            "muestra": [{k: p.get(k) for k in ("nombre", "marca", "categoria", "precio", "imagenes")} for p in muestra]}


def agregar_proveedor(nombre, url, tipo):
    clave = re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")[:30] or "proveedor"
    with conexion() as c:
        if c.execute("SELECT 1 FROM proveedores WHERE clave=? OR url=?", (clave, url.rstrip("/"))).fetchone():
            raise ValueError("Ese proveedor ya está registrado")
        c.execute("INSERT INTO proveedores (clave, nombre, tipo, url, creado) VALUES (?,?,?,?,?)",
                  (clave, nombre.strip(), tipo, url.strip().rstrip("/"), ahora()))
    return clave


def activar_proveedor(clave, activo):
    with conexion() as c:
        c.execute("UPDATE proveedores SET activo=? WHERE clave=?", (int(bool(activo)), clave))


RANGOS_PRECIO = [(0, 250_000, "Hasta 250 mil"), (250_000, 500_000, "250–500 mil"), (500_000, 1_000_000, "500 mil–1 M"),
                 (1_000_000, 2_000_000, "1–2 M"), (2_000_000, 5_000_000, "2–5 M"), (5_000_000, float("inf"), "Más de 5 M")]


def dashboard(proveedor=None, dias=7):
    """Indicadores del catálogo. `proveedor` y `dias` acotan todo el tablero (los dos filtros de la pantalla)."""
    desde = (datetime.now(timezone.utc) - timedelta(days=int(dias))).isoformat(timespec="seconds")
    filtro, args = ("WHERE proveedor=?", [proveedor]) if proveedor else ("WHERE 1=1", [])
    with conexion() as c:
        estados = {r["estado"]: r["n"] for r in c.execute(f"SELECT estado, COUNT(*) n FROM productos {filtro} GROUP BY estado", args)}
        pub = [dict(r) for r in c.execute(f"SELECT categoria, marca, precio FROM productos {filtro} AND estado='publicado'", args)]
        precios = sorted(p["precio"] for p in pub if p["precio"])
        conteo = lambda clave: sorted(Counter(p[clave] or "Sin dato" for p in pub).items(), key=lambda x: -x[1])
        # Una marca escrita distinto en cada fuente ("Off-White" / "Off White", "Hermes" / "Hermès") cuenta una sola vez,
        # con la forma más usada.
        grupos = {}
        for p in pub:
            if p["marca"]:
                grupos.setdefault(normalizar(p["marca"]).replace(" ", ""), Counter())[p["marca"]] += 1
        marcas = sorted(((g.most_common(1)[0][0], sum(g.values())) for g in grupos.values()), key=lambda x: -x[1])

        def eventos(accion, extra=""):
            q = f"""SELECT COUNT(*) FROM registro r JOIN productos p ON p.id=r.producto
                    WHERE r.accion=? AND r.fecha>=? {extra} {'AND p.proveedor=?' if proveedor else ''}"""
            return c.execute(q, [accion, desde] + ([proveedor] if proveedor else [])).fetchone()[0]

        activos = sum(v for k, v in estados.items() if k != "retirado")
        provs = []
        for r in c.execute("SELECT * FROM proveedores ORDER BY creado"):
            if proveedor and r["clave"] != proveedor:
                continue
            cnt = {x["estado"]: x["n"] for x in c.execute("SELECT estado, COUNT(*) n FROM productos WHERE proveedor=? GROUP BY estado", (r["clave"],))}
            ult = json.loads(r["ultimo_estado"]) if r["ultimo_estado"] else {}
            provs.append({"nombre": r["nombre"], "tipo": r["tipo"], "activo": bool(r["activo"]), "publicados": cnt.get("publicado", 0),
                          "retenidos": cnt.get("retenido", 0), "retirados": cnt.get("retirado", 0),
                          "ultima_lectura": r["ultima_lectura"], "segundos": ult.get("segundos"), "alerta": ult.get("alerta")})
        corridas = []
        for r in c.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT 5"):
            res = json.loads(r["resumen"])
            corridas.append({"inicio": r["inicio"], "fin": r["fin"],
                             "segundos": (datetime.fromisoformat(r["fin"]) - datetime.fromisoformat(r["inicio"])).seconds,
                             "publicados": res["estados"].get("publicado", 0), "ia": (res.get("ia") or {}).get("hechos", 0),
                             "alertas": sum(1 for f in res["fuentes"].values() if f.get("estado") != "ok")})
        return {
            "filtro": {"proveedor": proveedor, "dias": int(dias), "desde": desde},
            "publicados": estados.get("publicado", 0),
            "activos": activos,
            "pct_publicado": round(100 * estados.get("publicado", 0) / activos, 1) if activos else 0,
            "estados": estados,
            "nuevos": eventos("cargado", "AND r.detalle LIKE 'Agente%'"),
            "cambios_precio": eventos("precio"),
            "retirados_periodo": eventos("retirado"),
            "precio_mediano": precios[len(precios) // 2] if precios else None,
            "precio_min": precios[0] if precios else None, "precio_max": precios[-1] if precios else None,
            "clasificados_ia": c.execute(f"SELECT COUNT(*) FROM productos {filtro} AND (cat_origen='ia' OR marca_origen='ia')", args).fetchone()[0],
            "por_categoria": conteo("categoria"),
            "marcas": marcas[:10],
            "marcas_total": len(marcas),
            "rangos_precio": [(nombre, sum(1 for x in precios if a <= x < b)) for a, b, nombre in RANGOS_PRECIO],
            "origen_categoria": [(ORIGEN_NOMBRE.get(r["o"], "Sin categoría"), r["n"]) for r in c.execute(
                f"SELECT cat_origen o, COUNT(*) n FROM productos {filtro} AND estado!='retirado' GROUP BY cat_origen ORDER BY n DESC", args)],
            "proveedores": provs,
            "corridas": corridas,
        }


ORIGEN_NOMBRE = {"fuente": "Publicada por la fuente", "nombre": "Reglas sobre el nombre", "ia": "Agente IA"}
