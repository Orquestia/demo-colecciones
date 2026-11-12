"""Congela la demo en un sitio estático para GitHub Pages (carpeta docs/).

Copia las páginas de vitrina/, guarda en docs/api/ lo que hoy responde cada API y agrega
modo-estatico.js, que redirige las lecturas a esos JSON y desactiva las acciones que necesitan
el servidor (Actualizar, Probar lectura, Pausar proveedor).

Uso:  python3 exportar_estatico.py [/ruta-base]     # por defecto /demo-colecciones (nombre del repositorio)
"""
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import nucleo
import servidor

BASE = Path(__file__).parent
DOCS = BASE / "docs"
RUTA = (sys.argv[1] if len(sys.argv) > 1 else "/demo-colecciones").rstrip("/")
PERIODOS = (7, 30, 90)

SHIM = """<script>
/* Versión publicada (estática) de la demo: las lecturas salen de api/*.json y las acciones se desactivan. */
(function () {
  const BASE = "__RUTA__", FECHA = "__FECHA__";
  const original = window.fetch.bind(window);
  const AVISO = "En la versión publicada esta acción está desactivada: necesita el servidor de la demo (python3 servidor.py).";
  window.fetch = function (url, op) {
    if (typeof url === "string" && url.startsWith("/api/")) {
      if (op && op.method && op.method !== "GET")
        return Promise.resolve(new Response(JSON.stringify({ error: AVISO }), { status: 400, headers: { "Content-Type": "application/json" } }));
      const u = new URL(url, location.origin);
      let ruta = u.pathname.replace(/^\\/api\\//, "");
      if (ruta === "op2/dashboard") ruta += "-" + (u.searchParams.get("proveedor") || "todos") + "-" + (u.searchParams.get("dias") || "7");
      return original(BASE + "/api/" + ruta + ".json");
    }
    return original(url, op);
  };
  // Los botones que escriben se interceptan antes que su propio manejador.
  window.addEventListener("click", e => {
    const b = e.target.closest && e.target.closest("#actualizar, #act1, #p-probar, [data-prov]");
    if (!b) return;
    e.preventDefault(); e.stopImmediatePropagation();
    aviso(AVISO);
  }, true);
  function aviso(texto) {
    let t = document.getElementById("aviso-estatico");
    if (!t) { t = document.createElement("div"); t.id = "aviso-estatico"; document.body.append(t); }
    t.textContent = texto; t.className = "visible";
    clearTimeout(t._t); t._t = setTimeout(() => t.className = "", 4000);
  }
  document.addEventListener("DOMContentLoaded", () => {
    const cinta = document.createElement("div");
    cinta.id = "cinta-estatica";
    cinta.textContent = "Versión publicada de la demo · datos congelados el " + FECHA + " · leer fuentes, actualizar y agregar proveedores requiere el servidor";
    document.body.prepend(cinta);
  });
  const css = document.createElement("style");
  css.textContent = "#cinta-estatica{background:#000;color:#fff;text-align:center;font:11px/1.4 system-ui,sans-serif;letter-spacing:.04em;padding:6px 12px}" +
    "#aviso-estatico{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:min(560px,calc(100% - 32px));background:#000;color:#fff;" +
    "font:12px/1.4 system-ui,sans-serif;padding:12px 16px;opacity:0;pointer-events:none;transition:opacity .2s;z-index:99}#aviso-estatico.visible{opacity:1}";
  document.head.append(css);
})();
</script>"""


def guardar(ruta, datos):
    destino = DOCS / "api" / f"{ruta}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos, ensure_ascii=False))


def main():
    nucleo.iniciar()
    if DOCS.exists():
        shutil.rmtree(DOCS)
    shutil.copytree(BASE / "vitrina", DOCS)

    # Datos congelados de cada API que leen las páginas
    op1 = servidor.op1_catalogo()
    op1["actualizando"] = {"activo": False}
    guardar("op1/catalogo", op1)
    tablero = nucleo.tablero()
    tablero["progreso"] = {"activo": False}
    guardar("op2/tablero", tablero)
    guardar("op2/publicado", {"productos": nucleo.productos("publicado")})
    guardar("op2/productos", {"productos": nucleo.productos()})
    guardar("op2/registro", {"eventos": nucleo.registro()})
    for prov in [None] + [p["clave"] for p in tablero["proveedores"]]:
        for dias in PERIODOS:
            guardar(f"op2/dashboard-{prov or 'todos'}-{dias}", nucleo.dashboard(prov, dias))

    # Rutas absolutas → bajo la ruta del repositorio en GitHub Pages; shim en cada página
    fecha = datetime.now().strftime("%d/%m/%Y")
    for archivo in list(DOCS.rglob("*.html")) + list(DOCS.rglob("*.js")):
        texto = re.sub(r'(href|src)="/', rf'\1="{RUTA}/', archivo.read_text())
        if archivo.suffix == ".html":
            texto = texto.replace("<head>", "<head>\n" + SHIM.replace("__RUTA__", RUTA).replace("__FECHA__", fecha), 1)
        archivo.write_text(texto)
    (DOCS / ".nojekyll").write_text("")
    peso = sum(f.stat().st_size for f in DOCS.rglob("*") if f.is_file()) / 1e6
    print(f"Sitio estático en {DOCS} · {sum(1 for _ in DOCS.rglob('*.json'))} archivos de datos · {peso:.1f} MB · ruta base {RUTA}")


if __name__ == "__main__":
    main()
