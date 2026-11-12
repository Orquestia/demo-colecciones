"""Demo Orquestia: captura de colecciones desde páginas web y carpetas de Drive.

Conectores reutilizables (Opción 1 · MCP y Opción 2 · núcleo central):
- shopify:     feed público /products.json (Designer Room)
- tiendanube:  secciones del menú y datos estructurados JSON-LD (Privilex)
- arlessa:     tarjetas HTML filtradas por categoría (Clothing Girl)
- drive:       carpetas públicas; categoría y talla salen de la ruta
- jsonld:      cualquier página que publique sus productos como datos estructurados

Cada producto sale con su categoría de origen (`categoria_fuente`) y la categoría de la lista común
(`categoria`, ver categorias.py). `correr()` lee las fuentes, compara contra la corrida anterior y
guarda data/catalogo.json, que es lo que publica la vitrina de la Opción 1.

Uso:  python3 scraper.py                 # todas las fuentes, una tras otra
      python3 scraper.py --paralelo      # todas a la vez
      python3 scraper.py --solo privilex
Solo usa la librería estándar de Python.
"""
import argparse
import fcntl
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from categorias import categoria_comun, genero

BASE = Path(__file__).parent
DATA = BASE / "data"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
PAUSA = 1.0  # segundos entre peticiones, para no cargar los sitios

FUENTES = {
    "designerroom": {"nombre": "Designer Room", "tipo": "shopify", "url": "https://catalogo.designerroom.co"},
    "privilex": {"nombre": "Privilex", "tipo": "tiendanube", "url": "https://privilex.com.co"},
    "arlessa": {"nombre": "Clothing Girl (Arlessa)", "tipo": "arlessa", "url": "https://clothing.arlessa.com"},
    "drive_1": {"nombre": "Drive 1", "tipo": "drive", "url": "https://drive.google.com/drive/folders/13RtDqdiZPn0EX-XAwKYfgzvwHDzAI9QG"},
    "drive_2": {"nombre": "Drive 2", "tipo": "drive", "url": "https://drive.google.com/drive/folders/1LfuROP26Tckjy9c9FlHnEl6cUWaKY0li"},
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, intentos=5, timeout=40):
    for i in range(intentos):
        ultimo = i == intentos - 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and not ultimo:
                espera = int(e.headers.get("Retry-After") or 0) or 20 * (i + 1)
                log(f"    {e.code} en {url} - reintento en {espera}s")
                time.sleep(espera)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if ultimo:
                raise RuntimeError(f"Sin respuesta de {url}: {e}")
            espera = 5 * (i + 1)
            log(f"    {e} en {url} - reintento en {espera}s")
            time.sleep(espera)
    raise RuntimeError(f"Sin respuesta tras {intentos} intentos: {url}")


def limpiar(texto):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def producto(fuente, id_fuente, categoria_fuente="", **campos):
    p = {
        "id": f"{fuente}:{id_fuente}",
        "fuente": fuente,
        "nombre": "",
        "marca": "",
        "categoria_fuente": categoria_fuente,
        "referencia": "",
        "precio": None,
        "moneda": "COP",
        "disponible": None,
        "tallas": [],
        "imagenes": [],
        "url": "",
        "publicado_en_fuente": None,
    }
    p.update(campos)
    # Categoría común: primero la que publica la fuente; si no alcanza, la que dice el nombre.
    por_fuente = categoria_comun(categoria_fuente) if categoria_fuente else None
    p["categoria"] = por_fuente or categoria_comun(p["nombre"])
    p["cat_origen"] = "fuente" if por_fuente else ("nombre" if p["categoria"] else None)
    p["genero"] = genero(categoria_fuente, p["nombre"])
    # La huella cambia si cambia algo visible para el cliente (precio, fotos, nombre, disponibilidad)
    visible = [p["nombre"], p["precio"], p["disponible"], p["imagenes"][:1], p["tallas"]]
    p["huella"] = hashlib.sha1(json.dumps(visible, ensure_ascii=False).encode()).hexdigest()[:12]
    return p


# ---------- Conectores ----------

def _shopify_producto(d, base, clave):
    variantes = d.get("variants") or []
    precios = [float(v["price"]) for v in variantes if v.get("price")]
    ref = re.search(r"Referencia:\s*([A-Z0-9_\-]+)", d.get("body_html") or "")
    etiquetas = d.get("tags") or []
    etiquetas = etiquetas.split(",") if isinstance(etiquetas, str) else etiquetas
    return producto(
        clave, d["id"],
        categoria_fuente=" ".join([d.get("product_type") or ""] + list(etiquetas)).strip(),
        nombre=d["title"],
        marca=(d.get("vendor") or "").title(),
        referencia=ref.group(1) if ref else (variantes[0].get("sku") if variantes else ""),
        precio=min(precios) if precios else None,
        disponible=any(v.get("available") for v in variantes),
        tallas=[v["title"] for v in variantes if v.get("available") and v["title"] != "Default Title"],
        imagenes=[i["src"] for i in d.get("images", [])[:4]],
        url=f"{base}/products/{d['handle']}",
        publicado_en_fuente=d.get("published_at") or d.get("created_at"),
    )


def shopify(base, clave, progreso=None):
    """Feed público /products.json, 250 productos por página. La categoría sale del tipo o las etiquetas."""
    salida, pagina = [], 1
    while True:
        datos = json.loads(get(f"{base}/products.json?limit=250&page={pagina}"))["products"]
        if not datos:
            break
        salida += [_shopify_producto(d, base, clave) for d in datos]
        progreso and progreso(f"página {pagina}", len(salida))
        pagina += 1
        time.sleep(PAUSA * 2)
    return salida


def _jsonld_productos(pagina_html):
    for bloque in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', pagina_html, re.S):
        try:
            d = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        for item in d if isinstance(d, list) else d.get("@graph", [d]):
            if isinstance(item, dict) and item.get("@type") == "Product":
                yield item


def _producto_jsonld(clave, d, categoria_fuente, url_defecto):
    ofertas = d.get("offers") or {}
    ofertas = ofertas[0] if isinstance(ofertas, list) and ofertas else ofertas
    url_p = ofertas.get("url") or d.get("url") or d.get("@id") or url_defecto
    img = d.get("image", "")
    img = img[0] if isinstance(img, list) and img else img
    img = img.get("url", "") if isinstance(img, dict) else img
    marca = d.get("brand") or {}
    marca = marca.get("name", "") if isinstance(marca, dict) else str(marca)
    return producto(
        clave, url_p.rstrip("/").rsplit("/", 1)[-1],
        categoria_fuente=categoria_fuente,
        nombre=html.unescape(d.get("name", "")),
        marca=html.unescape(marca).title(),
        referencia=d.get("sku", ""),
        precio=float(ofertas["price"]) if ofertas.get("price") else None,
        moneda=ofertas.get("priceCurrency", "COP"),
        disponible=str(ofertas.get("availability", "")).endswith("InStock") if ofertas else None,
        imagenes=[img.replace("-480-0.", "-1024-1024.")] if img else [],
        url=url_p,
    ), url_p


def tiendanube(base, clave, progreso=None):
    """Recorre las secciones del menú (p. ej. hombres/zapatos) y después /productos/ para lo que falte."""
    inicio = get(base + "/")
    secciones = sorted(set(re.findall(rf'href="{re.escape(base)}/((?:hombres?|mujer(?:es)?|ninos|unisex)/[a-z0-9-]+)/"', inicio)))
    rutas = [(s, s.replace("/", " ")) for s in secciones] + [("productos", "")]
    vistos, salida = set(), []
    for ruta, categoria_fuente in rutas:
        pagina = 1
        while True:
            url = f"{base}/{ruta}/" if pagina == 1 else f"{base}/{ruta}/page/{pagina}/"
            try:
                pagina_html = get(url)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                raise
            nuevos = 0
            for d in _jsonld_productos(pagina_html):
                p, url_p = _producto_jsonld(clave, d, re.sub(r"\d+$", "", categoria_fuente), url)
                if url_p in vistos:
                    continue
                vistos.add(url_p)
                nuevos += 1
                salida.append(p)
            if nuevos == 0:
                break
            pagina += 1
            time.sleep(PAUSA)
        progreso and progreso(ruta, len(salida))
    return salida


def _arlessa_tarjetas(pagina_html, base, clave, categoria_fuente=""):
    for t in re.split(r'<div style="order: \d+"', pagina_html)[1:]:
        codigo = re.search(r'href="/p/([^/"]+)/"', t)
        nombre = re.search(r"<h2[^>]*>(.*?)</h2>", t, re.S)
        if not codigo or not nombre:
            continue
        precio = re.search(r"\$\s*([\d.,]+)", t)
        imgs = re.findall(r'<img src="([^"]+)"', t)
        yield producto(
            clave, codigo.group(1),
            categoria_fuente=categoria_fuente,
            nombre=limpiar(nombre.group(1)),
            referencia=codigo.group(1),
            precio=float(re.sub(r"[.,]", "", precio.group(1))) if precio else None,
            disponible=True,
            imagenes=[imgs[-1].replace("_sm.webp", "_md.webp")] if imgs else [],
            url=f"{base}/p/{codigo.group(1)}/",
        )


def arlessa(base, clave, progreso=None):
    """Catálogo a la medida: recorre cada categoría (?categories=…) y lee las tarjetas del HTML."""
    inicio = get(base + "/")
    chips = re.findall(r'data-category-filter-chip="(cat-[^"]+)".*?data-category-filter-chip-label>([^<]+)<', inicio, re.S)
    rutas = [(f"?categories={c}&", html.unescape(n).strip()) for c, n in chips] + [("?", "")]
    vistos, salida = set(), []
    for consulta, categoria_fuente in rutas:
        pagina = 1
        while True:
            pagina_html = get(f"{base}/{consulta}page={pagina}")
            nuevos = 0
            for p in _arlessa_tarjetas(pagina_html, base, clave, categoria_fuente):
                if p["referencia"] in vistos:
                    continue
                vistos.add(p["referencia"])
                nuevos += 1
                salida.append(p)
            if nuevos == 0:
                break
            pagina += 1
            time.sleep(PAUSA)
        progreso and progreso(categoria_fuente or "resto", len(salida))
    return salida


MESES = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _fecha_drive(texto, hoy):
    """'Oct 26' (últimos 12 meses) o '7/31/25' (más antiguo) -> AAAA-MM-DD."""
    texto = texto.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})$", texto)
    if m:
        return datetime(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2))).date().isoformat()
    m = re.match(r"([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?$", texto)
    if not m:
        return None
    anio = int(m.group(3)) if m.group(3) else hoy.year
    fecha = datetime(anio, MESES[m.group(1)], int(m.group(2)))
    if not m.group(3) and fecha.date() > hoy.date():
        fecha = fecha.replace(year=anio - 1)
    return fecha.date().isoformat()


def _drive_listar(carpeta_id):
    """Vista pública 'embebida' de la carpeta: lista todo, sin el tope de 50 de la vista normal."""
    pagina_html = get(f"https://drive.google.com/embeddedfolderview?id={carpeta_id}")
    hoy = datetime.now()
    items = {}
    for bloque in pagina_html.split('<div class="flip-entry" id="entry-')[1:]:
        id_ = bloque.split('"', 1)[0]
        enlace = re.search(r'<a href="([^"]+)"', bloque)
        titulo = re.search(r'flip-entry-title">(.*?)</div>', bloque, re.S)
        fecha = re.search(r'flip-entry-last-modified"><div>(.*?)</div>', bloque, re.S)
        if not enlace or not titulo:
            continue
        tipo = "carpeta" if "/folders/" in enlace.group(1) else "imagen" if 'alt="' in bloque and "Image" in bloque else "otro"
        items[id_] = (tipo, html.unescape(titulo.group(1)).strip(), _fecha_drive(fecha.group(1), hoy) if fecha else None)
    return items


def drive(url, clave, progreso=None):
    """Carpetas públicas de Drive con fotos. Categoría y talla salen de la ruta de carpetas.

    En producción esto va por la API de Google Drive (files.list + changes),
    que además entrega fecha de creación exacta y nombres sin depender del HTML.
    """
    raiz = re.search(r"folders/([A-Za-z0-9_-]+)", url).group(1)
    salida, pendientes = [], [(raiz, [])]
    while pendientes:
        carpeta, ruta = pendientes.pop(0)
        for id_, (tipo, nombre, fecha) in _drive_listar(carpeta).items():
            if tipo == "carpeta":
                pendientes.append((id_, ruta + [nombre]))
            elif tipo == "imagen":
                ruta_limpia = [re.sub(r"[^\w\s/.,-]", "", r).strip().title() for r in ruta]
                talla = next((r.replace("Talla", "").strip() for r in ruta_limpia if r.startswith("Talla")), "")
                carpeta_cat = next((r for r in ruta_limpia if not r.startswith("Talla")), "")
                salida.append(producto(
                    clave, id_,
                    categoria_fuente=carpeta_cat,
                    nombre=f"{carpeta_cat or 'Foto'} · {Path(nombre).stem}",
                    tallas=[talla] if talla else [],
                    imagenes=[f"https://drive.google.com/thumbnail?id={id_}&sz=w800"],
                    url=f"https://drive.google.com/file/d/{id_}/view",
                    publicado_en_fuente=fecha,
                    ruta=" / ".join(ruta_limpia),
                ))
        progreso and progreso(" / ".join(ruta) or "raíz", len(salida))
        time.sleep(PAUSA / 2)
    return salida


def jsonld(url, clave, progreso=None):
    """Página genérica que publica sus productos como datos estructurados (schema.org/Product)."""
    vistos, salida = set(), []
    for d in _jsonld_productos(get(url)):
        p, url_p = _producto_jsonld(clave, d, "", url)
        if url_p not in vistos:
            vistos.add(url_p)
            salida.append(p)
    progreso and progreso("página", len(salida))
    return salida


TIPOS = {"shopify": shopify, "tiendanube": tiendanube, "arlessa": arlessa, "drive": drive, "jsonld": jsonld}


def capturar(clave, fuente, progreso=None):
    return TIPOS[fuente["tipo"]](fuente["url"].rstrip("/"), clave, progreso)


def detectar_tipo(url):
    """Para «Agregar proveedor»: averigua cómo está hecha la página y con qué conector se lee."""
    url = url.strip().rstrip("/")
    if "drive.google.com" in url and "/folders/" in url:
        return "drive", "Carpeta de Google Drive: se leen las fotos y las subcarpetas"
    base = re.match(r"https?://[^/]+", url).group(0)
    try:
        datos = json.loads(get(f"{base}/products.json?limit=1", intentos=1, timeout=15))
        if "products" in datos:
            return "shopify", "Tienda Shopify: tiene un feed público de productos"
    except Exception:
        pass
    pagina = get(url, intentos=1, timeout=20)
    if "cdn.shopify.com" in pagina or "Shopify.theme" in pagina:
        return "shopify", "Tienda Shopify: tiene un feed público de productos"
    if "mitiendanube.com" in pagina or "tiendanube" in pagina.lower():
        return "tiendanube", "Tienda Tiendanube: publica sus productos como datos estructurados"
    if 'data-category-filter-chip' in pagina and "/p/" in pagina:
        return "arlessa", "Catálogo Arlessa: se leen las tarjetas por categoría"
    if any(True for _ in _jsonld_productos(pagina)):
        return "jsonld", "La página publica sus productos como datos estructurados (schema.org)"
    return None, "No se reconoce la estructura: esta página necesita un conector a la medida"


def lectura_de_prueba(tipo, url, n=8):
    """Muestra rápida (una sola página) para validar un proveedor nuevo antes de activarlo."""
    url = url.strip().rstrip("/")
    if tipo == "shopify":
        base = re.match(r"https?://[^/]+", url).group(0)
        datos = json.loads(get(f"{base}/products.json?limit={n}", intentos=1, timeout=20))["products"]
        return [_shopify_producto(d, base, "prueba") for d in datos]
    if tipo == "arlessa":
        return list(_arlessa_tarjetas(get(url + "/", intentos=2), url, "prueba"))[:n]
    if tipo == "drive":
        raiz = re.search(r"folders/([A-Za-z0-9_-]+)", url).group(1)
        items = _drive_listar(raiz)
        carpetas = [(i, nom) for i, (t, nom, _) in items.items() if t == "carpeta"]
        fotos = [(i, nom, f, "") for i, (t, nom, f) in items.items() if t == "imagen"]
        for cid, cnom in carpetas[:3]:
            if len(fotos) >= n:
                break
            fotos += [(i, nom, f, cnom) for i, (t, nom, f) in _drive_listar(cid).items() if t == "imagen"]
        return [producto("prueba", i, categoria_fuente=c, nombre=f"{c or 'Foto'} · {Path(nom).stem}",
                         imagenes=[f"https://drive.google.com/thumbnail?id={i}&sz=w800"], publicado_en_fuente=f)
                for i, nom, f, c in fotos[:n]]
    pagina = get(url + ("/productos/" if tipo == "tiendanube" and "/productos" not in url else ""), intentos=2)
    return [_producto_jsonld("prueba", d, "", url)[0] for d in _jsonld_productos(pagina)][:n]


# ---------- Comparación con la corrida anterior ----------

def comparar(anterior, actuales, fuentes_ok, ahora):
    """Marca cada producto como nuevo / cambiado / sin cambios / ya no aparece."""
    previo = {p["id"]: p for p in anterior}
    catalogo, resumen = [], {"nuevos": 0, "cambiados": 0, "sin_cambios": 0, "retirados": 0}
    for p in actuales:
        antes = previo.pop(p["id"], None)
        if antes is None:
            p["estado"], p["primera_vez"] = "nuevo", ahora
            resumen["nuevos"] += 1
        else:
            p["primera_vez"] = antes["primera_vez"]
            if antes["huella"] != p["huella"]:
                p["estado"] = "cambiado"
                p["cambios"] = {k: [antes.get(k), p.get(k)] for k in ("precio", "disponible", "nombre") if antes.get(k) != p.get(k)}
                resumen["cambiados"] += 1
            else:
                p["estado"] = "sin_cambios"
                resumen["sin_cambios"] += 1
        p["ultima_vez"] = ahora
        catalogo.append(p)
    # Lo que no apareció: solo se marca retirado si su fuente sí se pudo leer
    for p in previo.values():
        if p["fuente"] in fuentes_ok:
            if p.get("estado") != "retirado":
                p["estado"] = "retirado"
                resumen["retirados"] += 1
        catalogo.append(p)
    return catalogo, resumen


def completar(p):
    """Recalcula la categoría común de un producto guardado (p. ej. si cambió la lista) sin volver a leer la fuente."""
    # Los guardados antes de la lista común solo traían la carpeta (ruta) o la categoría de la fuente.
    cf = p["categoria_fuente"] if "categoria_fuente" in p else (p.get("ruta") or p.get("categoria") or "")
    por_fuente = categoria_comun(cf) if cf else None
    p["categoria_fuente"] = cf
    p["categoria"] = por_fuente or categoria_comun(p["nombre"])
    p["cat_origen"] = "fuente" if por_fuente else ("nombre" if p["categoria"] else None)
    p["genero"] = genero(cf, p["nombre"])
    return p


def leer_fuente(clave, fuente, anterior, progreso=None):
    """Corre un conector con sus controles: si falla o trae muy poco, se conserva lo anterior."""
    inicio = time.time()
    previos = [p for p in anterior if p["fuente"] == clave and p.get("estado") != "retirado"]
    try:
        productos = capturar(clave, fuente, progreso)
        alerta = None
        if not productos:
            alerta = "0 productos: probablemente cambió la estructura del sitio"
        elif previos and len(productos) < len(previos) * 0.5:
            alerta = f"Cayó de {len(previos)} a {len(productos)} productos: revisar conector"
        salud = {"ok": not alerta, "productos": len(productos), "segundos": round(time.time() - inicio), "alerta": alerta}
        return (previos if alerta else productos), salud, not alerta
    except Exception as e:  # una fuente caída no tumba la corrida
        return previos, {"ok": False, "productos": 0, "segundos": round(time.time() - inicio), "alerta": f"Error: {e}"}, False


def correr(claves=None, paralelo=False, progreso=None):
    """Lee las fuentes, compara y guarda data/catalogo.json. Devuelve el resumen de la corrida.

    `progreso(clave, etapa, n)` recibe avances por fuente (lo usa el MCP y la plataforma)."""
    DATA.mkdir(exist_ok=True)
    candado = open(DATA / ".actualizando", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("Ya hay una actualización en curso; espera a que termine.")
    archivo = DATA / "catalogo.json"
    anterior = [completar(p) for p in json.loads(archivo.read_text())["productos"]] if archivo.exists() else []
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    elegidas = [c for c in FUENTES if not claves or c in claves]

    def una(clave):
        log(f"→ {FUENTES[clave]['nombre']}")
        cb = (lambda etapa, n: progreso(clave, etapa, n)) if progreso else (lambda etapa, n: log(f"    {clave} · {etapa}: {n}"))
        r = leer_fuente(clave, FUENTES[clave], anterior, cb)
        progreso and progreso(clave, "fin", r[1]["productos"])
        log(f"  {clave} {r[1]}")
        return clave, r

    if paralelo:
        with ThreadPoolExecutor(max_workers=len(elegidas)) as ex:
            resultados = dict(ex.map(una, elegidas))
    else:
        resultados = dict(una(c) for c in elegidas)

    actuales, fuentes_ok, salud = [], set(), {}
    for clave in FUENTES:
        if clave not in resultados:  # fuente no corrida: se conserva lo que había tal cual
            actuales += [p for p in anterior if p["fuente"] == clave and p.get("estado") != "retirado"]
            continue
        productos, salud[clave], ok = resultados[clave]
        actuales += productos
        if ok:
            fuentes_ok.add(clave)

    catalogo, resumen = comparar(anterior, actuales, fuentes_ok, ahora)
    if not anterior:
        resumen["nota"] = "Primera corrida: todo queda como línea base. Desde la próxima solo se marca lo nuevo."
    corrida = {"fecha": ahora, "resumen": resumen, "fuentes": salud}
    archivo.write_text(json.dumps({"fuentes": FUENTES, "ultima_corrida": corrida, "productos": catalogo}, ensure_ascii=False, indent=1))
    with (DATA / "historial.jsonl").open("a") as h:
        h.write(json.dumps(corrida, ensure_ascii=False) + "\n")
    nuevos = [p for p in catalogo if p["estado"] in ("nuevo", "cambiado")]
    (DATA / f"novedades_{datetime.now().date().isoformat()}.json").write_text(json.dumps(nuevos, ensure_ascii=False, indent=1))
    return corrida


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", nargs="*", choices=list(FUENTES), help="correr solo estas fuentes")
    ap.add_argument("--paralelo", action="store_true", help="leer todas las fuentes a la vez")
    a = ap.parse_args()
    c = correr(a.solo, a.paralelo)
    print(json.dumps(c["resumen"], ensure_ascii=False))
