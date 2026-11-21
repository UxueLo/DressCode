"use strict";

// ------------------------------------------------------------------ utilidades
const $ = (s) => document.querySelector(s);

/** Crea un elemento DOM. Todo el texto entra con textContent (nada de innerHTML: los
 *  nombres de prendas vienen de una IA y no se deben interpretar como HTML). */
function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) if (h) e.append(h);
  return e;
}

async function api(ruta, opciones = {}) {
  const init = { ...opciones };
  if (init.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(init.json);
    delete init.json;
  }
  const r = await fetch(ruta, init);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

let toastTimer;
function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), error ? 6000 : 2800);
}

const hoyISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

// ------------------------------------------------------------------ pestañas
function mostrarTab(nombre) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === nombre));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `tab-${nombre}`));
  if (nombre === "armario") cargarArmario();
  if (nombre === "gustos") iniciarMazo();
  if (nombre === "hoy") { cargarHistorial(); refrescarAncla(); }
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => mostrarTab(b.dataset.tab)));

// -------------------------------------------------------------------- estado
async function cargarEstado() {
  const e = await api("/api/estado");
  const sel = $("#evento");
  if (sel.options.length === 1) e.eventos.forEach((ev) => sel.append(el("option", { value: ev.id, text: ev.nombre })));
  if (!$("#ciudad").value) $("#ciudad").value = e.ciudad;
  $("#estado").textContent = `${e.disponibles}/${e.prendas} prendas en el armario · ${e.perfil.likes} likes, ${e.perfil.dislikes} dislikes`;
  pintarPerfil(e.perfil);
  return e;
}

function pintarPerfil(p) {
  $("#perfil").textContent = p.conocido
    ? `Tu perfil de gusto está activo: ${p.likes} me gusta y ${p.dislikes} no. Cuantas más fotos, mejor afinará.`
    : `Perfil en construcción: ${p.likes + p.dislikes}/${p.min_swipes} valoraciones para activarlo.`;
}

// --------------------------------------------------------------------- HOY
async function refrescarAncla() {
  const sel = $("#ancla");
  const actual = sel.value;
  const { prendas } = await api("/api/prendas");
  sel.replaceChildren(el("option", { value: "", text: "Que elija DressCode" }));
  prendas.filter((p) => !p.en_uso).forEach((p) => sel.append(el("option", { value: p.tag_id, text: `${p.nombre} (${p.categoria})` })));
  sel.value = actual;
}

const PORCENTAJE = (x) => Math.round(x * 100);

function metrica(nombre, valor) {
  return el("div", { class: "metrica" }, el("span", { text: nombre }),
    el("div", { class: "barra-m" }, el("i", { style: `width:${PORCENTAJE(valor)}%` })),
    el("span", { text: PORCENTAJE(valor) }));
}

function tarjetaOutfit(o) {
  const acciones = {};
  const boton = (accion, texto) => {
    const b = el("button", { type: "button", text: texto, onclick: async () => {
      try {
        const r = await api(`/api/outfits/${o.id}/feedback`, { json: { accion } });
        Object.values(acciones).forEach((x) => (x.disabled = true));
        acciones[accion].classList.add("hecho");
        toast(accion === "usar" ? "Anotado: lo llevas hoy" : accion === "like" ? "Guardado: DressCode aprende de él" : "Descartado: aprendo qué evitar");
        cargarEstado();
        return r;
      } catch (e) { toast(e.message, true); }
    } });
    acciones[accion] = b;
    return b;
  };
  return el("article", { class: "tag" },
    el("div", { class: "tag-cab" },
      el("div", { class: "tag-score" }, String(PORCENTAJE(o.score)), el("small", { text: " / 100" })),
      el("span", { class: "ayuda", text: o.evento ? "con evento" : "" })),
    el("div", { class: "prendas" }, o.prendas.map((p) =>
      el("figure", { class: "prenda", style: "margin:0" }, el("img", { src: p.imagen, alt: p.nombre, loading: "lazy" }), el("figcaption", { text: p.nombre })))),
    el("div", { class: "metricas" }, metrica("Coherencia", o.coherencia), metrica("Tus gustos", o.afinidad), metrica("Novedad", o.novedad)),
    el("ul", { class: "razones" }, o.razones.map((r) => el("li", { text: r }))),
    el("div", { class: "tag-acc" }, boton("like", "♥ Me gusta"), boton("dislike", "✕ No"), boton("usar", "Me lo pongo")));
}

function pintarOutfits(d) {
  const cont = $("#outfits");
  cont.replaceChildren();
  const clima = $("#clima");
  if (d.clima) { clima.hidden = false; clima.textContent = `${d.clima.city === "manual" ? "Temperatura manual" : d.clima.city} · ${d.clima.date} · ${d.clima.resumen}`; }
  $("#notas").replaceChildren(...(d.notas || []).map((n) => el("li", { text: n })));
  if (!d.outfits.length) cont.append(el("p", { class: "vacio", text: "No hay outfits posibles con estas condiciones. Revisa las notas de arriba." }));
  d.outfits.forEach((o) => cont.append(tarjetaOutfit(o)));
  if (d.perfil && !d.perfil.conocido) mostrarTabHint();
}
function mostrarTabHint() { /* las notas del servidor ya explican la afinidad neutra */ }

$("#form-generar").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = ev.submitter || $("#form-generar button.primario");
  btn.disabled = true; btn.textContent = "Generando…";
  try {
    const f = new FormData(ev.target);
    const cuerpo = Object.fromEntries([...f.entries()].map(([k, v]) => [k, v === "" ? null : v]));
    if (cuerpo.ciudad) api("/api/ajustes", { json: { ciudad: cuerpo.ciudad } }).catch(() => {});
    pintarOutfits(await api("/api/outfits/generar", { json: cuerpo }));
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Generar outfits"; }
});

async function cargarDiario() {
  try {
    const d = await api("/api/outfits/diario");
    if (d.outfits.length) pintarOutfits(d);
  } catch (_) { /* aún no hay outfit del día */ }
}

async function cargarHistorial() {
  const { outfits } = await api("/api/outfits/historial");
  const cont = $("#historial");
  cont.replaceChildren();
  if (!outfits.length) return cont.append(el("p", { class: "ayuda", text: "Aún no has guardado ni usado ningún outfit." }));
  outfits.forEach((o) => cont.append(el("div", { class: "hist-fila" },
    el("span", { text: o.fecha }),
    el("div", { class: "miniaturas" }, o.prendas.map((p) => el("img", { src: p.imagen, alt: p.nombre }))),
    el("span", { class: "estado-h", text: o.estado }))));
}

// ------------------------------------------------------------------ ARMARIO
let pollArmario = null;

async function cargarArmario() {
  const { prendas, jobs } = await api("/api/prendas");
  const grid = $("#armario");
  grid.replaceChildren();
  const enBD = new Set(prendas.map((p) => p.tag_id));
  let procesando = false;
  for (const [tag, j] of Object.entries(jobs)) {
    if (j.estado === "procesando") {
      procesando = true;
      grid.append(el("div", { class: "card procesando" }, el("div", { class: "cuerpo" }, el("div", { class: "giro" }), el("span", { text: `Analizando ${tag}…` }))));
    } else if (j.estado === "error") {
      grid.append(el("div", { class: "card error" }, el("div", { class: "cuerpo" }, el("strong", { text: `No se pudo añadir ${tag}` }), el("span", { text: j.mensaje || "" }),
        el("div", { class: "botones" }, el("button", { type: "button", text: "Cerrar", onclick: (e) => e.target.closest(".card").remove() })))));
    } else if (j.estado === "ok" && j.mensaje && enBD.has(tag)) {
      toast(j.mensaje);
    }
  }
  prendas.forEach((p) => grid.append(tarjetaPrenda(p)));
  $("#reindexar").hidden = !prendas.some((p) => !p.tiene_vector);
  if (!prendas.length && !procesando) grid.append(el("p", { class: "vacio", text: "Tu armario está vacío. Sube la foto de una prenda para empezar." }));
  clearTimeout(pollArmario);
  if (procesando && !$("#tab-armario").hidden) pollArmario = setTimeout(cargarArmario, 1500);
}

function tarjetaPrenda(p) {
  return el("div", { class: "card" + (p.en_uso ? " fuera" : "") },
    el("img", { src: p.imagen, alt: p.nombre, loading: "lazy" }),
    el("div", { class: "cuerpo" },
      el("span", { class: "nombre", text: p.sub_category }),
      el("span", {}, el("i", { class: "punto", style: `background:${p.color_hex}` }), `${p.color} · ${p.categoria}`),
      el("span", { text: `${p.temp_min}–${p.temp_max} °C · formalidad ${p.formalidad}/5` }),
      el("span", { text: p.estilos.join(", ") }),
      el("div", { class: "botones" },
        el("button", { type: "button", text: p.en_uso ? "Devolver" : "Sacar", title: "Simula pasar la etiqueta por el lector NFC",
          onclick: async () => { await api(`/api/prendas/${encodeURIComponent(p.tag_id)}/toggle`, { method: "POST" }); cargarArmario(); cargarEstado(); } }),
        el("button", { type: "button", class: "borrar", text: "Borrar",
          onclick: async () => { if (confirm(`¿Borrar «${p.nombre}»?`)) { await api(`/api/prendas/${encodeURIComponent(p.tag_id)}`, { method: "DELETE" }); cargarArmario(); cargarEstado(); } } }))));
}

// Reduce la foto en el navegador antes de subirla: las fotos de cámara pesan varios MB y la subida
// era parte de la espera (y a veces superaba el límite del servidor). El canvas también aplica la
// orientación EXIF y convierte WEBP/AVIF/HEIC (lo que el navegador sepa abrir) a JPEG.
// Si el navegador no puede abrirla, se envía el original y el servidor decide.
async function reducirFoto(archivo, lado = 1024) {
  try {
    const bmp = await createImageBitmap(archivo, { imageOrientation: "from-image" });
    const k = Math.min(1, lado / Math.max(bmp.width, bmp.height));
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.round(bmp.width * k);
    lienzo.height = Math.round(bmp.height * k);
    const ctx = lienzo.getContext("2d");
    ctx.fillStyle = "#fff";                       // PNG/WEBP con transparencia -> fondo blanco, no negro
    ctx.fillRect(0, 0, lienzo.width, lienzo.height);
    ctx.drawImage(bmp, 0, 0, lienzo.width, lienzo.height);
    bmp.close();
    const blob = await new Promise((ok) => lienzo.toBlob(ok, "image/jpeg", 0.88));
    return blob && blob.size < archivo.size ? blob : archivo;
  } catch { return archivo; }
}

$("#form-subir").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = ev.submitter;
  btn.disabled = true;
  try {
    const datos = new FormData(ev.target);
    const foto = datos.get("foto");
    if (foto && foto.size) datos.set("foto", await reducirFoto(foto), "prenda.jpg");   // sube ~200 KB en vez de 5-10 MB
    await api("/api/prendas", { method: "POST", body: datos });
    ev.target.reset();
    toast("Foto enviada: Gemini la está analizando");
    cargarArmario();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});

$("#reindexar").addEventListener("click", async () => {
  const r = await api("/api/prendas/reindexar", { method: "POST" });
  toast(`${r.encoladas} prenda(s) en cola para reindexar`);
  setTimeout(cargarArmario, 1200);
});

// ------------------------------------------------------------------- GUSTOS
let cola = [];          // fotos pendientes de valorar
const historialSwipes = [];  // para "deshacer"
let cargandoFeed = false, envio = Promise.resolve(), mensajeFeed = null;

async function iniciarMazo() {
  if (!cola.length) await rellenarFeed();
  pintarMazo();
}

async function rellenarFeed() {
  if (cargandoFeed) return;
  cargandoFeed = true;
  try {
    const d = await api("/api/feed?n=10");
    const ya = new Set(cola.map((f) => f.ref));
    cola.push(...d.fotos.filter((f) => !ya.has(f.ref)));
    mensajeFeed = d.aviso;
    pintarPerfil(d.perfil);
  } catch (e) { toast(e.message, true); }
  finally { cargandoFeed = false; }
}

function pintarMazo() {
  const mazo = $("#mazo");
  mazo.replaceChildren();
  if (!cola.length) {
    mazo.append(el("div", { class: "mazo-vacio" }, el("p", { text: mensajeFeed || "Cargando fotos…" })));
    return;
  }
  // se dibujan las 2 primeras; la de arriba es la interactiva
  cola.slice(0, 2).reverse().forEach((f, i, arr) => {
    const arriba = i === arr.length - 1;
    const carta = el("div", { class: "foto", "data-ref": f.ref },
      el("img", { src: f.url, alt: "Look de inspiración", draggable: "false" }),
      el("span", { class: "sello si", text: "ME GUSTA" }), el("span", { class: "sello no", text: "NO" }));
    if (!arriba) carta.style.transform = "scale(.95) translateY(10px)";
    else activarArrastre(carta);
    mazo.append(carta);
  });
  if (cola.length < 4) rellenarFeed().then(() => { if (cola.length && !$("#mazo .foto")) pintarMazo(); });
}

function activarArrastre(carta) {
  let x0 = null, dx = 0;
  carta.addEventListener("pointerdown", (e) => { x0 = e.clientX; carta.setPointerCapture(e.pointerId); carta.style.transition = "none"; });
  carta.addEventListener("pointermove", (e) => {
    if (x0 === null) return;
    dx = e.clientX - x0;
    carta.style.transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
    carta.querySelector(".si").style.opacity = Math.max(0, Math.min(1, dx / 90));
    carta.querySelector(".no").style.opacity = Math.max(0, Math.min(1, -dx / 90));
  });
  const soltar = () => {
    if (x0 === null) return;
    const d = dx; x0 = null; dx = 0;
    if (Math.abs(d) > 100) decidir(d > 0);
    else { carta.style.transition = "transform .2s"; carta.style.transform = ""; carta.querySelectorAll(".sello").forEach((s) => (s.style.opacity = 0)); }
  };
  carta.addEventListener("pointerup", soltar);
  carta.addEventListener("pointercancel", soltar);
}

function decidir(liked) {
  const foto = cola.shift();
  if (!foto) return;
  historialSwipes.push(foto);
  const carta = $("#mazo .foto:last-child");
  if (carta) {
    carta.style.transition = "transform .25s, opacity .25s";
    carta.style.transform = `translateX(${liked ? 600 : -600}px) rotate(${liked ? 25 : -25}deg)`;
    carta.style.opacity = 0;
  }
  // los envíos van en cadena para que el servidor los guarde en orden (importa al deshacer)
  envio = envio.then(() => api("/api/swipe", { json: { ref: foto.ref, liked } }))
    .then((r) => { pintarPerfil(r.perfil); cargarEstado(); })
    .catch((e) => { toast(e.message, true); historialSwipes.pop(); cola.unshift(foto); pintarMazo(); });
  setTimeout(pintarMazo, 220);
}

$("#btn-si").addEventListener("click", () => decidir(true));
$("#btn-no").addEventListener("click", () => decidir(false));
$("#btn-undo").addEventListener("click", () => {
  envio = envio.then(async () => {
    const r = await api("/api/swipe/deshacer", { method: "POST" });
    const foto = historialSwipes.pop();
    if (r.ref && foto && foto.ref === r.ref) cola.unshift(foto);
    pintarPerfil(r.perfil); pintarMazo(); cargarEstado();
  }).catch((e) => toast(e.message, true));
});
document.addEventListener("keydown", (e) => {
  if ($("#tab-gustos").hidden || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
  if (e.key === "ArrowRight") decidir(true);
  if (e.key === "ArrowLeft") decidir(false);
});

// -------------------------------------------------------------------- inicio
(async function init() {
  $("#fecha").value = hoyISO();
  try {
    await cargarEstado();
    await refrescarAncla();
    await cargarDiario();
    await cargarHistorial();
  } catch (e) { toast(e.message, true); }
})();
