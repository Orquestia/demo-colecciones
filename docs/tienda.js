/* Vitrina compartida por las dos opciones. Cada página define window.TIENDA = {api, opcion, aviso, pie, etiquetaNuevo}. */
(function () {
  const T = window.TIENDA;
  const app = document.getElementById("app");
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const cop = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  const LISTA = ["Camisetas y polos", "Camisas", "Buzos y sudaderas", "Chaquetas", "Pantalones y jeans", "Pantalonetas y shorts",
    "Vestidos y faldas", "Vestidos de baño", "Conjuntos y deportivo", "Zapatos y tenis", "Bolsos", "Gorras", "Accesorios", "Perfumes", "Otros"];

  app.innerHTML = `
  <div class="aviso">${T.aviso}</div>
  <div class="top"><div class="top-in">
    <a class="marca" href="./">Vitrina<small>${esc(T.opcion)}</small></a>
    <nav class="nav" id="nav"></nav>
    <div class="top-acc">${T.acciones || ""}<a href="/demo-colecciones/">Inicio</a></div>
  </div></div>
  <section class="hero"><p>Now available</p><h1>New Arrivals</h1><span id="hero-n"></span></section>
  <div class="catalogo">
    <aside class="filtros" id="filtros">
      <h3>Filtros</h3>
      <details class="grupo" open><summary>Disponibilidad</summary>
        <div class="opciones"><label><input type="checkbox" id="f-stock"> En existencia</label>
        <label><input type="checkbox" id="f-nuevo"> Solo lo nuevo</label></div></details>
      <details class="grupo" open><summary>Categoría</summary><div class="opciones" id="f-cat"></div></details>
      <details class="grupo"><summary>Género</summary><div class="opciones" id="f-genero"></div></details>
      <details class="grupo" open><summary>Marca</summary><div class="opciones" id="f-marca"></div></details>
      <details class="grupo"><summary>Talla</summary><div class="tallas" id="f-talla"></div></details>
      <details class="grupo" open><summary>Precio</summary><div class="precio-rango">
        <input type="range" id="f-precio" min="0" step="10000"><span id="f-precio-txt"></span></div></details>
      <button class="limpiar" id="limpiar">Quitar filtros</button>
    </aside>
    <section>
      <div class="barra-cat">
        <input class="buscar" id="q" type="search" placeholder="Buscar">
        <button class="btn-filtros" id="btn-filtros">Filtros</button>
        <span class="total" id="count"></span>
        <select id="orden" aria-label="Ordenar">
          <option value="nuevo">Ordenar: Lo más nuevo</option>
          <option value="precio-asc">Precio, menor a mayor</option>
          <option value="precio-desc">Precio, mayor a menor</option>
          <option value="az">Alfabéticamente, A-Z</option>
        </select>
      </div>
      <div class="grid" id="grid"></div>
      <button class="ver-mas" id="more">Ver más</button>
    </section>
  </div>
  <footer class="pie" id="pie">${T.pie}</footer>`;

  const $ = id => document.getElementById(id);
  const f = { cat: new Set(), marca: new Set(), genero: new Set(), talla: new Set(), stock: false, nuevo: false, precio: Infinity };
  let productos = [], lista = [], visibles = 24, precioMax = 0;
  const contar = arr => arr.reduce((m, v) => (m.set(v, (m.get(v) || 0) + 1), m), new Map());
  const cuando = p => p[T.campoFecha] || p.primera_vez || "";

  function opciones(id, pares, grupo) {
    $(id).innerHTML = pares.map(([v, n]) => `<label><input type="checkbox" value="${esc(v)}" data-g="${grupo}"> ${esc(v)} (${n})</label>`).join("") || `<span class="sub">—</span>`;
  }

  function construir() {
    productos.forEach(p => { p.categoria = p.categoria || "Otros"; });
    const cats = contar(productos.map(p => p.categoria));
    const orden = LISTA.filter(c => cats.has(c));
    opciones("f-cat", orden.map(c => [c, cats.get(c)]), "cat");
    opciones("f-genero", [...contar(productos.map(p => p.genero).filter(Boolean))], "genero");
    opciones("f-marca", [...contar(productos.map(p => p.marca).filter(Boolean)).entries()].sort((a, b) => b[1] - a[1]).slice(0, 30).sort((a, b) => a[0].localeCompare(b[0])), "marca");
    const tallas = [...contar(productos.flatMap(p => p.tallas || [])).entries()].sort((a, b) => b[1] - a[1]).slice(0, 18).map(t => t[0]);
    $("f-talla").innerHTML = tallas.map(t => `<button type="button" aria-pressed="false" data-t="${esc(t)}" title="${esc(t)}">${esc(t)}</button>`).join("") || `<span class="sub">—</span>`;
    precioMax = Math.max(0, ...productos.map(p => p.precio || 0));
    $("f-precio").max = precioMax; $("f-precio").value = precioMax;
    $("f-precio-txt").textContent = `Hasta ${cop.format(precioMax)}`;
    const top = orden.filter(c => c !== "Otros").sort((a, b) => cats.get(b) - cats.get(a)).slice(0, 6);
    $("nav").innerHTML = `<button data-nav="" aria-current="true">Todo</button>` + top.map(c => `<button data-nav="${esc(c)}">${esc(c)}</button>`).join("");
  }

  function filtrar(reiniciar = true) {
    const q = $("q").value.trim().toLowerCase(), or = $("orden").value;
    lista = productos.filter(p =>
      (!f.cat.size || f.cat.has(p.categoria)) && (!f.marca.size || f.marca.has(p.marca)) && (!f.genero.size || f.genero.has(p.genero)) &&
      (!f.talla.size || (p.tallas || []).some(t => f.talla.has(t))) && (!f.stock || p.disponible !== false) &&
      (!f.nuevo || T.esNuevo(p)) && (f.precio >= precioMax || (p.precio || 0) <= f.precio) &&
      (!q || [p.nombre, p.marca, p.categoria].join(" ").toLowerCase().includes(q)));
    const precio = p => p.precio ?? (or === "precio-asc" ? Infinity : -Infinity);
    lista.sort(or === "precio-asc" ? (a, b) => precio(a) - precio(b)
      : or === "precio-desc" ? (a, b) => precio(b) - precio(a)
      : or === "az" ? (a, b) => a.nombre.localeCompare(b.nombre)
      : (a, b) => cuando(b).localeCompare(cuando(a)));
    if (reiniciar) visibles = 24;
    pintar();
  }

  function tarjeta(p) {
    const etq = [];
    if (T.esNuevo(p)) etq.push(`<span class="etq">Nuevo</span>`);
    if (p.disponible === false) etq.push(`<span class="etq agotado">Agotado</span>`);
    return `<div class="prod">
      <div class="foto">${p.imagenes && p.imagenes[0] ? `<img loading="lazy" src="${esc(p.imagenes[0])}" alt="${esc(p.nombre)}" referrerpolicy="no-referrer">` : ""}${etq.join("")}</div>
      <div class="nom">${esc(p.nombre)}</div>
      <div class="marc">${esc([p.marca, p.categoria !== "Otros" ? p.categoria : ""].filter(Boolean).join(" · "))}</div>
      <div class="pre">${p.precio ? cop.format(p.precio) : "Precio a consultar"}</div></div>`;
  }

  function pintar() {
    $("grid").innerHTML = lista.slice(0, visibles).map(tarjeta).join("") || `<div class="vacio">No hay productos con esos filtros</div>`;
    $("count").textContent = `${lista.length.toLocaleString("es-CO")} artículos`;
    $("more").hidden = visibles >= lista.length;
  }

  document.addEventListener("change", e => {
    const g = e.target.dataset && e.target.dataset.g;
    if (g) { e.target.checked ? f[g].add(e.target.value) : f[g].delete(e.target.value); filtrar(); }
  });
  $("f-stock").onchange = e => { f.stock = e.target.checked; filtrar(); };
  $("f-nuevo").onchange = e => { f.nuevo = e.target.checked; filtrar(); };
  $("f-precio").oninput = e => { f.precio = +e.target.value; $("f-precio-txt").textContent = `Hasta ${cop.format(f.precio)}`; filtrar(); };
  $("f-talla").onclick = e => {
    const b = e.target.closest("[data-t]"); if (!b) return;
    const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", on);
    on ? f.talla.add(b.dataset.t) : f.talla.delete(b.dataset.t); filtrar();
  };
  $("nav").onclick = e => {
    const b = e.target.closest("[data-nav]"); if (!b) return;
    f.cat.clear(); if (b.dataset.nav) f.cat.add(b.dataset.nav);
    document.querySelectorAll('[data-g="cat"]').forEach(i => i.checked = f.cat.has(i.value));
    $("nav").querySelectorAll("button").forEach(x => x.setAttribute("aria-current", x === b));
    filtrar();
  };
  $("limpiar").onclick = () => {
    ["cat", "marca", "genero", "talla"].forEach(k => f[k].clear()); f.stock = f.nuevo = false; f.precio = Infinity;
    document.querySelectorAll(".filtros input[type=checkbox]").forEach(i => i.checked = false);
    document.querySelectorAll("#f-talla button").forEach(b => b.setAttribute("aria-pressed", "false"));
    $("f-precio").value = precioMax; $("f-precio-txt").textContent = `Hasta ${cop.format(precioMax)}`;
    filtrar();
  };
  $("btn-filtros").onclick = () => $("filtros").classList.toggle("abierto");
  $("more").onclick = () => { visibles += 24; pintar(); };
  $("q").addEventListener("input", () => filtrar());
  $("orden").addEventListener("input", () => filtrar());

  fetch(T.api).then(r => r.json()).then(d => {
    productos = d.productos;
    T.alCargar && T.alCargar(d, productos);
    $("hero-n").textContent = `${productos.length.toLocaleString("es-CO")} piezas · ${T.heroDetalle(d)}`;
    construir();
    filtrar();
  });
})();
