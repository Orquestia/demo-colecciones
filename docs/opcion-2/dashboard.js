/* Dashboard de KPIs de la plataforma central (Opción 2).
   Todas las gráficas son de una sola serie: un solo color (tinta), sin leyenda; el título dice qué se mide.
   Cada barra tiene su tooltip al pasar el cursor o con el teclado, y cada gráfica su vista en tabla. */
window.Dashboard = (function () {
  const cop = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  const num = n => (n ?? 0).toLocaleString("es-CO");
  const corto = n => n >= 1e6 ? `$ ${(n / 1e6).toLocaleString("es-CO", { maximumFractionDigits: 1 })} M` : n >= 1e3 ? `$ ${Math.round(n / 1e3)} mil` : cop.format(n);
  const fecha = s => s ? new Date(s).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  const el = (tag, cls, texto) => { const e = document.createElement(tag); if (cls) e.className = cls; if (texto != null) e.textContent = texto; return e; };
  let raiz, tip, proveedores = [];

  function tooltip(objetivo, valor, etiqueta) {
    const mostrar = ev => {
      tip.replaceChildren(el("b", null, valor), el("span", null, etiqueta));
      tip.hidden = false;
      const r = objetivo.getBoundingClientRect();
      const x = ev && ev.clientX ? ev.clientX : r.left + r.width / 2;
      tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, x - tip.offsetWidth / 2)) + "px";
      tip.style.top = (r.top - tip.offsetHeight - 8 + window.scrollY) + "px";
    };
    objetivo.tabIndex = 0;
    objetivo.addEventListener("pointermove", mostrar);
    objetivo.addEventListener("focus", () => mostrar());
    ["pointerleave", "blur"].forEach(e => objetivo.addEventListener(e, () => tip.hidden = true));
  }

  function tarjeta(titulo, sub, cuerpo, filas, columnas) {
    const t = el("section", "dash-card");
    const cab = el("div", "dash-cab");
    const tt = el("div"); tt.append(el("h3", null, titulo), el("p", "sub", sub));
    const boton = el("button", "dash-tabla-btn", "Ver tabla");
    cab.append(tt, boton);
    const tabla = el("table", "dash-tabla"); tabla.hidden = true;
    const h = el("tr"); columnas.forEach(c => h.append(el("th", null, c))); tabla.append(h);
    filas.forEach(f => { const tr = el("tr"); f.forEach(v => tr.append(el("td", null, v))); tabla.append(tr); });
    boton.onclick = () => { const ver = tabla.hidden; tabla.hidden = !ver; cuerpo.hidden = ver; boton.textContent = ver ? "Ver gráfica" : "Ver tabla"; };
    t.append(cab, cuerpo, tabla);
    return t;
  }

  // Barras horizontales: 14 px de grueso, extremo redondeado, valor en la punta.
  function barras(datos, formato = num, etiquetaTip = "productos") {
    const max = Math.max(1, ...datos.map(d => d[1]));
    const c = el("div", "hbarras");
    datos.forEach(([nombre, v]) => {
      const fila = el("div", "hb-fila");
      const pista = el("div", "hb-pista");
      const barra = el("div", "hb-barra"); barra.style.width = Math.max(0.6, 100 * v / max) + "%";
      const valor = el("span", "hb-valor", formato(v));
      pista.append(barra, valor);
      fila.append(el("span", "hb-nombre", nombre), pista);
      tooltip(fila, formato(v), `${nombre} · ${etiquetaTip}`);
      c.append(fila);
    });
    return c;
  }

  // Columnas para la distribución de precios: base común, extremo superior redondeado, valor sobre la columna.
  function columnas(datos) {
    const max = Math.max(1, ...datos.map(d => d[1]));
    const c = el("div", "vcols");
    datos.forEach(([nombre, v]) => {
      const col = el("div", "vc-col");
      const area = el("div", "vc-area");
      const barra = el("div", "vc-barra"); barra.style.height = Math.max(1, 100 * v / max) + "%";
      area.append(el("span", "vc-valor", num(v)), barra);
      col.append(area, el("span", "vc-nombre", nombre));
      tooltip(col, num(v), `productos · ${nombre}`);
      c.append(col);
    });
    return c;
  }

  function kpi(valor, etiqueta, detalle) {
    const k = el("div", "kpi");
    k.append(el("b", null, valor), el("span", null, etiqueta));
    if (detalle) k.append(el("small", "kpi-det", detalle));
    return k;
  }

  async function cargar() {
    const prov = raiz.querySelector("#d-prov").value, dias = raiz.querySelector("#d-dias").value;
    raiz.querySelector(".dash-cuerpo").style.opacity = .45;   // al recargar se conserva el marco, atenuado
    const d = await (await fetch(`/api/op2/dashboard?dias=${dias}${prov ? "&proveedor=" + encodeURIComponent(prov) : ""}`)).json();
    pintar(d);
  }

  function pintar(d) {
    const cuerpo = raiz.querySelector(".dash-cuerpo");
    cuerpo.replaceChildren();
    cuerpo.style.opacity = 1;
    const periodo = `últimos ${d.filtro.dias} días`;

    const heroe = el("div", "dash-heroe");
    heroe.append(el("span", "dash-heroe-n", num(d.publicados)), el("span", "dash-heroe-t", "productos publicados en la vitrina"),
      el("span", "sub", `${num(d.activos)} activos · ${num(d.estados.retenido || 0)} retenidos por reglas · ${num(d.estados.retirado || 0)} ya no aparecen en su fuente`));
    cuerpo.append(heroe);

    const kpis = el("div", "kpis dash-kpis");
    kpis.append(
      kpi(`${d.pct_publicado.toLocaleString("es-CO")} %`, "del catálogo activo publicado", "cumple precio, foto y categoría"),
      kpi(num(d.nuevos), "productos nuevos", periodo),
      kpi(num(d.cambios_precio), "cambios de precio", periodo),
      kpi(num(d.retirados_periodo), "retirados por la fuente", periodo),
      kpi(d.precio_mediano ? corto(d.precio_mediano) : "—", "precio mediano publicado", d.precio_min ? `de ${corto(d.precio_min)} a ${corto(d.precio_max)}` : ""),
      kpi(num(d.clasificados_ia), "completados por el agente IA", "categoría o marca"),
    );
    cuerpo.append(kpis);

    const g = el("div", "dash-grid");
    g.append(
      tarjeta("Publicados por categoría", "Lista común de categorías · productos en la vitrina", barras(d.por_categoria), d.por_categoria.map(([a, b]) => [a, num(b)]), ["Categoría", "Productos"]),
      tarjeta("Marcas con más productos", `Top 10 de ${num(d.marcas_total)} marcas publicadas`, barras(d.marcas), d.marcas.map(([a, b]) => [a, num(b)]), ["Marca", "Productos"]),
      tarjeta("Distribución de precios", "Productos publicados por rango de precio (COP)", columnas(d.rangos_precio), d.rangos_precio.map(([a, b]) => [a, num(b)]), ["Rango", "Productos"]),
      tarjeta("De dónde sale la categoría", "Productos activos según quién definió su categoría", barras(d.origen_categoria), d.origen_categoria.map(([a, b]) => [a, num(b)]), ["Origen", "Productos"]),
    );
    cuerpo.append(g);

    const tp = el("section", "dash-card dash-ancha");
    const cabp = el("div", "dash-cab"); const tt = el("div");
    tt.append(el("h3", null, "Estado por proveedor"), el("p", "sub", "Lo que aporta cada fuente y cómo fue su última lectura"));
    cabp.append(tt); tp.append(cabp);
    const tabla = el("table", "dash-tabla");
    const h = el("tr"); ["Proveedor", "Tipo", "Publicados", "Retenidos", "Ya no aparecen", "Última lectura", "Duración", "Estado"].forEach(c => h.append(el("th", null, c))); tabla.append(h);
    d.proveedores.forEach(p => {
      const tr = el("tr");
      [p.nombre, p.tipo, num(p.publicados), num(p.retenidos), num(p.retirados), fecha(p.ultima_lectura), p.segundos != null ? `${num(p.segundos)} s` : "—",
       !p.activo ? "Pausado" : p.alerta ? `⚠ ${p.alerta}` : p.ultima_lectura ? "✓ OK" : "Sin leer"].forEach((v, i) => {
        const td = el("td", i >= 2 && i <= 4 ? "num" : null, v); tr.append(td);
      });
      tabla.append(tr);
    });
    const envolver = t => { const w = el("div", "dash-scroll"); w.append(t); return w; };
    tp.append(envolver(tabla));
    cuerpo.append(tp);

    const tc = el("section", "dash-card dash-ancha");
    const cabc = el("div", "dash-cab"); const tc2 = el("div");
    tc2.append(el("h3", null, "Últimas actualizaciones"), el("p", "sub", "Cada actualización lee todas las fuentes a la vez, por eso esta tabla no cambia con el filtro de proveedor"));
    cabc.append(tc2); tc.append(cabc);
    if (!d.corridas.length) tc.append(el("p", "sub", "Aún no hay actualizaciones desde la plataforma."));
    else {
      const t2 = el("table", "dash-tabla");
      const h2 = el("tr"); ["Terminó", "Duración", "Publicados al cierre", "Clasificados por IA", "Fuentes con alerta"].forEach(c => h2.append(el("th", null, c))); t2.append(h2);
      d.corridas.forEach(r => {
        const tr = el("tr");
        [fecha(r.fin), `${Math.floor(r.segundos / 60)} min ${r.segundos % 60} s`, num(r.publicados), num(r.ia), r.alertas ? `⚠ ${r.alertas}` : "✓ 0"].forEach((v, i) => tr.append(el("td", i >= 2 && i <= 3 ? "num" : null, v)));
        t2.append(tr);
      });
      tc.append(envolver(t2));
    }
    cuerpo.append(tc);
  }

  function iniciar(contenedor, listaProveedores) {
    raiz = contenedor;
    proveedores = listaProveedores;
    tip = document.querySelector(".dash-tip") || document.body.appendChild(el("div", "dash-tip"));
    tip.hidden = true;
    const sel = raiz.querySelector("#d-prov");
    if (sel.options.length === 1) proveedores.forEach(p => sel.add(new Option(p.nombre, p.clave)));
    ["#d-prov", "#d-dias"].forEach(s => raiz.querySelector(s).onchange = cargar);
    return cargar();
  }

  return { iniciar, cargar };
})();
