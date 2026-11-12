# Demo: catálogo de colecciones · dos opciones

Demo de las dos propuestas para Juan Camilo Estrada Quintero. Las dos leen las mismas fuentes reales (Privilex, Designer Room, Clothing Girl y dos carpetas de Drive) y ordenan los productos con la misma lista común de categorías.

```bash
python3 servidor.py          # http://localhost:8765
```

| Dirección | Qué muestra |
|---|---|
| `/` | Portada con los dos caminos y datos en vivo |
| `/opcion-1/` | **Opción 1** · vitrina que alimenta el MCP; publica todo lo leído, ordenado por categoría |
| `/opcion-2/plataforma.html` | **Opción 2** · plataforma central: botón «Actualizar», agentes en paralelo, agente IA, reglas de publicación, proveedores y registro |
| `/opcion-2/` | **Opción 2** · vitrina con lo que la plataforma publicó |

No necesita instalar nada: solo la librería estándar de Python. El agente IA de la Opción 2 usa Claude Code (`claude -p`) si está instalado.

## Versión publicada (GitHub Pages)

`docs/` es una copia estática de la demo con los datos congelados: vitrinas, plataforma y dashboard se pueden recorrer, pero leer fuentes, «Actualizar», «Probar lectura» y pausar proveedores necesitan el servidor y aparecen desactivados. Para regenerarla después de una actualización:

```bash
python3 exportar_estatico.py      # reescribe docs/ con los datos actuales
```

## Opción 1 · Catálogo con MCP

- `mcp_servidor.py`: servidor MCP (stdio) con 7 herramientas: `actualizar_catalogo`, `estado_actualizacion`, `estado_fuentes`, `novedades`, `buscar_productos`, `categorias`, `enlace_catalogo`.
- `.mcp.json`: lo conecta a Claude Code al abrir Claude en esta carpeta. Prueba rápida:

  ```bash
  echo "¿Qué llegó esta semana de Privilex?" | claude -p --mcp-config .mcp.json --allowedTools "mcp__catalogo-colecciones__novedades"
  ```
- Actualización automática cada 3 días: en la demo la hace un hilo de `servidor.py` (`data/programacion.json`); en producción, una tarea programada en la nube.

## Opción 2 · Plataforma central

- `nucleo.py`: **núcleo simulado** sobre SQLite (`data/nucleo.db`) con los modelos que tendría Odoo 18: proveedores, productos con categoría y marca, estados y registro.
- El agente lee a todos los proveedores **en paralelo**, completa la marca y la categoría (primero con lo que publica la fuente, luego con reglas sobre el nombre y, para lo que queda, con Claude Haiku) y **publica solo lo que tiene precio, foto y categoría**. Lo demás queda retenido con su motivo.
- «Agregar proveedor»: detecta Shopify, Tiendanube, catálogos Arlessa, páginas con datos estructurados y carpetas de Drive, y hace una lectura de prueba antes de activar el proveedor.
- **Dashboard** (pestaña de la plataforma): productos publicados, % del catálogo publicado, nuevos, cambios de precio, retirados, precio mediano, completados por IA; gráficas por categoría, marcas (agrupando variantes como «Off-White» / «Off White»), rangos de precio y origen de la categoría; estado por proveedor y últimas actualizaciones. Se filtra por proveedor y período (7, 30 o 90 días); cada gráfica tiene vista en tabla. Datos en `/api/op2/dashboard`.
- Contabilidad, CRM e inventario aparecen como fase 2 (M7–M9), sin funcionalidad.

## Piezas comunes

- `scraper.py`: conectores por tipo de fuente, comparación con la corrida anterior y controles: si una fuente falla o trae menos de la mitad, se conserva lo anterior y se avisa.
- `categorias.py`: lista común de 14 categorías y las reglas que llevan a ella las categorías de cada fuente.
- `vitrina/`: portada, tienda compartida (`tienda.js`) y plataforma, con estilo monocromático de tienda multimarca.

## Límites conocidos de la demo

- Designer Room (Shopify) limita la velocidad: tras varias lecturas seguidas pide esperar 60 s. Los conectores reintentan y, si no alcanza, conservan los productos de la lectura anterior.
- Las fotos de Drive no traen nombre, marca ni precio. En la Opción 2 quedan retenidas por la regla «sin precio».
- El núcleo es simulado; en producción se reemplaza por Odoo 18 en Google Cloud.
- El enlace de la vitrina es `localhost`; para compartirlo con clientes hay que publicarla en un dominio.
