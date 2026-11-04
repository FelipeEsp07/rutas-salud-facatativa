/*
 * Frontend real del microservicio: todo lo que se ve aquí viene de llamadas
 * HTTP de verdad a la API (no hay datos quemados en este archivo).
 *
 * El inicio de sesión llama al POST /token real del backend (OAuth 2.0,
 * flujo client_credentials: usuario = client_id, contraseña = client_secret).
 * El formulario trae precargadas las credenciales de demostración, pero es
 * un login de verdad: si se cambian por unas inválidas, el backend lo rechaza.
 *
 * Nota de seguridad para la sustentación: en un despliegue real, el
 * client_secret nunca debería tipearse en un formulario público así; lo
 * normal es que un backend propio del EBS guarde el secreto y llame a
 * /rutas en nombre del coordinador ya autenticado por otro medio (p. ej.
 * usuario y contraseña personales contra un directorio institucional).
 */
const API_BASE = window.location.origin;

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 1) => Number(n).toLocaleString("es-CO", { minimumFractionDigits: d, maximumFractionDigits: d });

let token = null;
let scopesActuales = new Set();
let map, geoLayer, routeLayer, markersLayer, hospitalMarker;
let veredasPorId = new Map();     // vista coordinación (con vulnerabilidad)
let veredasPublicas = new Map();  // vista pública (sin vulnerabilidad)
let poligonos = {};               // codigo_dane -> coordenadas GeoJSON
let vista = "coord";
let ultimaRuta = null;

// Pesos del índice de vulnerabilidad: el mismo objeto alimenta GET /veredas (vista
// previa en el mapa) y POST /rutas (la selección real), para que nunca se muestre
// un número distinto del que de verdad usa el algoritmo.
const pesosIndice = { peso_adulto_mayor: 25, peso_gestantes: 25, peso_via: 25, peso_dias_sin_visita: 25 };

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function mostrarError(msg) {
  const host = $("toasts");
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg><span>${msg}</span>`;
  host.appendChild(t);
  setTimeout(() => {
    t.classList.add("out");
    t.addEventListener("animationend", () => t.remove(), { once: true });
  }, 6000);
}

function setConexion(ok, texto) {
  $("connDot").className = "dot " + (ok ? "ok" : "err");
  $("connTxt").textContent = texto;
}

async function pedirToken(usuario, contrasena) {
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    username: usuario,
    password: contrasena,
    scope: "rutas:generar auditoria:leer",
  });
  const res = await fetch(`${API_BASE}/token`, { method: "POST", body });
  if (res.status === 401) throw new Error("Usuario o contraseña incorrectos.");
  if (!res.ok) throw new Error(`POST /token -> ${res.status}`);
  return res.json(); // { access_token, scope, expires_in, token_type }
}

async function api(path, { auth = true, method = "GET", body = null } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: body ? JSON.stringify(body) : null });
  if (!res.ok) {
    const detalle = await res.text();
    throw new Error(`${method} ${path} -> ${res.status}: ${detalle}`);
  }
  return res.json();
}

// ---------- mapa ----------
function colorVulnerabilidad(v) {
  // interpola entre --seq-lo (#E6EEE2) y --seq-hi (#1F5560)
  const lo = [0xe6, 0xee, 0xe2], hi = [0x1f, 0x55, 0x60];
  const c = lo.map((x, i) => Math.round(x + (hi[i] - x) * v));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function construirFeatureCollection(veredas, coloreado) {
  return {
    type: "FeatureCollection",
    features: veredas.map((v) => ({
      type: "Feature",
      properties: { id: v.id, nombre: v.nombre, vulnerabilidad: v.vulnerabilidad ?? null },
      geometry: { type: "MultiPolygon", coordinates: poligonos[v.codigo_dane] || [] },
    })),
  };
}

function dibujarVeredas() {
  if (geoLayer) map.removeLayer(geoLayer);
  const fuente = vista === "coord" ? [...veredasPorId.values()] : [...veredasPublicas.values()];
  const fc = construirFeatureCollection(fuente, vista === "coord");
  geoLayer = L.geoJSON(fc, {
    style: (feat) => {
      const v = feat.properties.vulnerabilidad;
      return {
        color: "#ffffff",
        weight: 1.5,
        fillColor: vista === "coord" && v != null ? colorVulnerabilidad(v) : "#E3E9DD",
        fillOpacity: 0.85,
      };
    },
    onEachFeature: (feat, layer) => {
      const v = feat.properties.vulnerabilidad;
      const txt = vista === "coord" && v != null
        ? `<strong>${feat.properties.nombre}</strong><br>Índice: ${(v * 100).toFixed(0)} / 100`
        : `<strong>${feat.properties.nombre}</strong>`;
      layer.bindTooltip(txt);
    },
  }).addTo(map);
}

function aplicarVisibilidadIndice() {
  // La vista pública no debe mostrar el índice de vulnerabilidad en ninguna forma,
  // ni siquiera agregado en un KPI (ver /etica: "no exponer un puntaje por comunidad").
  const kCov = $("kCov");
  if (vista === "pub") {
    kCov.textContent = "— oculto —";
    kCov.title = "Este dato se oculta en la vista pública para no exponer un puntaje de vulnerabilidad.";
  } else {
    kCov.title = "";
    kCov.textContent = ultimaRuta ? fmt(ultimaRuta.vulnerabilidad_cubierta_pct, 0) + " %" : "—";
  }
}

function limpiarRutaDelMapa() {
  if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
  if (markersLayer) { map.removeLayer(markersLayer); markersLayer = null; }
}

function dibujarRuta(resp, sedeLatLon) {
  limpiarRutaDelMapa();
  const puntos = [sedeLatLon, ...resp.orden_visita.map((p) => veredasPorId.get(p.vereda_id)).map((v) => [v.lat, v.lon]), sedeLatLon];
  routeLayer = L.polyline(puntos, { color: "#B4532A", weight: 3, dashArray: null }).addTo(map);

  markersLayer = L.layerGroup();
  resp.orden_visita.forEach((p) => {
    const v = veredasPorId.get(p.vereda_id);
    const icon = L.divIcon({
      className: "",
      html: `<div style="background:#B4532A;color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3)">${p.orden}</div>`,
      iconSize: [22, 22], iconAnchor: [11, 11],
    });
    L.marker([v.lat, v.lon], { icon }).bindTooltip(`${p.orden}. ${p.nombre} · ${fmt(p.distancia_tramo_km)} km de tramo`).addTo(markersLayer);
  });
  markersLayer.addTo(map);
  map.fitBounds(routeLayer.getBounds(), { padding: [30, 30] });
}

// ---------- carga inicial ----------
function queryPesos() {
  return new URLSearchParams(pesosIndice).toString();
}

async function cargarVeredasCoordinacion() {
  const lista = await api(`/veredas?${queryPesos()}`);
  veredasPorId = new Map(lista.map((v) => [v.id, v]));
}

async function cargarVeredasPublicas() {
  const lista = await api("/veredas/publico", { auth: false });
  veredasPublicas = new Map(lista.map((v) => [v.id, v]));
}

async function manejarLogin(e) {
  e.preventDefault();
  const boton = $("loginBtn");
  const label = $("loginBtnLabel");
  boton.disabled = true;
  label.innerHTML = `<span class="spin"></span>Iniciando sesión…`;
  try {
    await iniciarSesionConCredenciales($("loginUser").value.trim(), $("loginPass").value);
  } catch (err) {
    mostrarError(err.message.includes("incorrectos")
      ? err.message
      : `No se pudo iniciar sesión. ¿Está corriendo el servidor? (${err.message})`);
  } finally {
    boton.disabled = false;
    label.textContent = "Iniciar sesión";
  }
}

async function iniciarSesionConCredenciales(usuario, contrasena) {
  const datosToken = await pedirToken(usuario, contrasena);
  token = datosToken.access_token;
  scopesActuales = new Set((datosToken.scope || "").split(" ").filter(Boolean));
  $("clientInfo").textContent = `usuario: ${usuario} · scope: ${datosToken.scope || "(ninguno)"}`;
  $("loginScreen").classList.add("hidden");
  $("appRoot").classList.remove("hidden");
  setConexion(true, "Conectado a la API");
  await iniciarApp();
}

async function manejarRegistro(e) {
  e.preventDefault();
  const boton = $("registerBtn");
  const label = $("registerBtnLabel");
  const usuario = $("regUser").value.trim();
  const contrasena = $("regPass").value;
  const confirmacion = $("regPass2").value;
  const rol = $("regRol").value;

  if (contrasena !== confirmacion) {
    mostrarError("Las contraseñas no coinciden.");
    return;
  }

  boton.disabled = true;
  label.innerHTML = `<span class="spin"></span>Creando usuario…`;
  try {
    const res = await fetch(`${API_BASE}/usuarios`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usuario, password: contrasena, rol }),
    });
    if (res.status === 409) throw new Error("Ya existe una cuenta con ese usuario.");
    if (!res.ok) {
      const detalle = await res.json().catch(() => null);
      const mensaje = detalle?.detail
        ? (Array.isArray(detalle.detail) ? detalle.detail.map((d) => d.msg).join(" · ") : detalle.detail)
        : `POST /usuarios -> ${res.status}`;
      throw new Error(mensaje);
    }
    // Cuenta creada: inicia sesión con las mismas credenciales, sin pedirlas de nuevo.
    await iniciarSesionConCredenciales(usuario, contrasena);
  } catch (err) {
    mostrarError(`No se pudo crear el usuario: ${err.message}`);
  } finally {
    boton.disabled = false;
    label.textContent = "Crear usuario";
  }
}

function mostrarFormularioLogin() {
  $("registerForm").classList.add("hidden");
  $("loginForm").classList.remove("hidden");
  $("loginUser").focus();
}

function mostrarFormularioRegistro() {
  $("loginForm").classList.add("hidden");
  $("registerForm").classList.remove("hidden");
  $("regUser").focus();
}

function cerrarSesion() {
  // El token solo vive en memoria (nunca en localStorage), así que recargar
  // la página es la forma más simple y segura de volver a la pantalla de login.
  location.reload();
}

async function iniciarApp() {
  map = L.map("map", { scrollWheelZoom: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
    maxZoom: 18,
  }).addTo(map);

  try {
    const [geo] = await Promise.all([
      api("/veredas/geometria", { auth: false }),
      cargarVeredasCoordinacion(),
      cargarVeredasPublicas(),
    ]).then((r) => [r[0]]);
    poligonos = geo;
  } catch (e) {
    mostrarError(`No se pudieron cargar las veredas: ${e.message}`);
    return;
  }
  $("mapOverlay").classList.add("hidden");

  const sede = { lat: 4.8068265, lon: -74.3496229 }; // misma sede del backend (data/veredas.json)
  hospitalMarker = L.marker([sede.lat, sede.lon], {
    icon: L.divIcon({
      className: "",
      html: `<div style="background:#1B241C;width:16px;height:16px;transform:rotate(45deg);border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
      iconSize: [16, 16], iconAnchor: [8, 8],
    }),
  }).bindTooltip("Hospital San Rafael — sede de salud").addTo(map);

  dibujarVeredas();
  map.setView([sede.lat, sede.lon], 12);

  $("genBtn").disabled = false;
  await refrescarAuditoria();
  await actualizarDashboard();
}

// ---------- dashboard ----------
function renderBarras(contenedorId, items, colorFn) {
  const cont = $(contenedorId);
  cont.innerHTML = "";
  if (!items.length) return;
  const max = Math.max(...items.map((it) => it.valor), 1);
  items.forEach((it) => {
    const ancho = Math.max(2, Math.round((it.valor / max) * 100));
    const row = document.createElement("div");
    row.className = "bar-row" + (it.valor === 0 ? " cero" : "");
    row.innerHTML = `
      <span class="nm" title="${it.nombre}">${it.nombre}</span>
      <div class="track"><div class="fill" style="width:${ancho}%;background:${colorFn(it)}"></div></div>
      <span class="val">${it.etiqueta}</span>`;
    cont.appendChild(row);
  });
}

function actualizarDashboardVulnerabilidad() {
  const veredas = [...veredasPorId.values()];
  if (!veredas.length) return;

  const ordenadas = [...veredas].sort((a, b) => b.vulnerabilidad - a.vulnerabilidad);
  renderBarras(
    "chartVulnerabilidad",
    ordenadas.map((v) => ({ nombre: v.nombre, valor: v.vulnerabilidad * 100, etiqueta: fmt(v.vulnerabilidad * 100, 0) })),
    (it) => colorVulnerabilidad(it.valor / 100),
  );

  $("dkTotal").textContent = veredas.length;
  const promedio = veredas.reduce((s, v) => s + v.vulnerabilidad, 0) / veredas.length;
  $("dkPromedio").textContent = fmt(promedio * 100, 0) + " / 100";
  $("dkTop").textContent = ordenadas[0]?.nombre ?? "—";
}

async function actualizarDashboardCobertura() {
  const permiso = scopesActuales.has("auditoria:leer");
  if (!permiso) {
    $("dkRutas").textContent = "—";
    $("chartCobertura").innerHTML = `<div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      Disponible solo para cuentas de administrador</div>`;
    return;
  }
  try {
    const registros = await api("/auditoria?limite=200");
    $("dkRutas").textContent = registros.length;

    const conteo = new Map([...veredasPorId.values()].map((v) => [v.nombre, 0]));
    registros.forEach((r) => r.orden_visita.forEach((nombre) => {
      conteo.set(nombre, (conteo.get(nombre) || 0) + 1);
    }));
    const items = [...conteo.entries()]
      .sort((a, b) => a[1] - b[1])
      .map(([nombre, veces]) => ({ nombre, valor: veces, etiqueta: veces === 0 ? "Nunca" : `${veces}×` }));
    renderBarras("chartCobertura", items, (it) => it.valor === 0 ? "var(--err)" : "var(--accent-2)");
  } catch (e) {
    mostrarError(`No se pudo calcular la cobertura: ${e.message}`);
  }
}

async function actualizarDashboard() {
  actualizarDashboardVulnerabilidad();
  await actualizarDashboardCobertura();
}

// ---------- generar ruta ----------
async function generarRuta() {
  const boton = $("genBtn");
  const label = $("genBtnLabel");
  boton.disabled = true;
  label.innerHTML = `<span class="spin"></span>Generando…`;
  try {
    const params = {
      n_visitas: Number($("nvis").value),
      alfa: Number($("alfa").value),
      aplicar_equidad: $("equidad").checked,
      factor_sinuosidad: Number($("sin").value),
      pesos_indice: pesosIndice,
    };
    const resp = await api("/rutas", { method: "POST", body: params });
    ultimaRuta = resp;

    $("kKm").textContent = fmt(resp.distancia_total_km) + " km";
    $("kOpt").textContent = fmt(resp.distancia_optima_km) + " km";
    const gapEl = $("kGap");
    gapEl.textContent = fmt(resp.brecha_vs_optimo_pct) + " %";
    gapEl.classList.remove("ok", "warn");
    gapEl.classList.add(resp.brecha_vs_optimo_pct > 15 ? "warn" : "ok");
    $("mapTitle").lastChild.textContent = ` Ruta ${resp.id_ruta} · ${resp.orden_visita.length} veredas`;
    aplicarVisibilidadIndice();
    $("itinMeta").textContent = resp.algoritmo_version;

    const itin = $("itin");
    itin.innerHTML = "";
    const li = (cls, num, nombre, km) => {
      const e = document.createElement("li");
      e.innerHTML = `<span class="n ${cls}">${num}</span><span class="nm">${nombre}</span><span class="km">${km}</span>`;
      itin.appendChild(e);
    };
    li("base", "H", "Hospital San Rafael (salida)", "0.0 km");
    resp.orden_visita.forEach((p) => li("", p.orden, p.nombre, fmt(p.distancia_tramo_km) + " km"));
    li("base", "H", "Regreso al hospital", fmt(resp.distancia_regreso_km) + " km");

    const sede = { lat: 4.8068265, lon: -74.3496229 };
    dibujarRuta(resp, [sede.lat, sede.lon]);

    await refrescarAuditoria();
    await actualizarDashboardCobertura(); // la cobertura cambia con cada ruta nueva
  } catch (e) {
    mostrarError(`No se pudo generar la ruta: ${e.message}`);
  } finally {
    boton.disabled = false;
    label.textContent = "Generar ruta · POST /rutas";
  }
}

async function refrescarAuditoria() {
  const tbody = $("auditBody");
  if (!scopesActuales.has("auditoria:leer")) {
    // No se llama a /auditoria: un coordinador EBS no tiene ese permiso (solo
    // el rol administrador). Mostrarlo así, en vez de como un error, es más
    // honesto que disparar un 403 cada vez que inicia sesión.
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      Tu cuenta no tiene permiso para consultar la auditoría (solo administradores)</div></td></tr>`;
    return;
  }
  try {
    const registros = await api("/auditoria?limite=10");
    if (!registros.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-4"/></svg>
        Sin registros todavía</div></td></tr>`;
      return;
    }
    tbody.innerHTML = registros.map((r) => `
      <tr>
        <td><span class="id-pill">${r.id_ruta}</span></td>
        <td>${new Date(r.generado_en).toLocaleString("es-CO")}</td>
        <td>${r.generado_por}</td>
        <td>α=${r.parametros.alfa} · n=${r.parametros.n_visitas}</td>
        <td>${fmt(r.distancia_total_km)}</td>
      </tr>
    `).join("");
  } catch (e) {
    mostrarError(`No se pudo leer la auditoría: ${e.message}`);
  }
}

// ---------- controles ----------
$("alfa").addEventListener("input", (e) => { $("alfaV").textContent = Number(e.target.value).toFixed(2); });
$("nvis").addEventListener("input", (e) => { $("nvisV").textContent = e.target.value; });
$("sin").addEventListener("input", (e) => { $("sinV").textContent = Number(e.target.value).toFixed(2); });
$("genBtn").addEventListener("click", generarRuta);

// ---------- composición del índice ----------
const refrescarIndicePorPesos = debounce(async () => {
  try {
    await cargarVeredasCoordinacion();
    dibujarVeredas();
    actualizarDashboardVulnerabilidad();
  } catch (e) {
    mostrarError(`No se pudo recalcular el índice: ${e.message}`);
  }
}, 250);

const SLIDERS_PESO = [
  ["wMayor", "peso_adulto_mayor"],
  ["wGestantes", "peso_gestantes"],
  ["wVia", "peso_via"],
  ["wDias", "peso_dias_sin_visita"],
];
SLIDERS_PESO.forEach(([id, clave]) => {
  $(id).addEventListener("input", (e) => {
    $(id + "V").textContent = e.target.value;
    pesosIndice[clave] = Number(e.target.value);
    refrescarIndicePorPesos();
  });
});

document.querySelectorAll("#viewToggle button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#viewToggle button").forEach((x) => x.classList.toggle("active", x === b));
    vista = b.dataset.v;
    dibujarVeredas();
    aplicarVisibilidadIndice();
    if (ultimaRuta) {
      const sede = { lat: 4.8068265, lon: -74.3496229 };
      dibujarRuta(ultimaRuta, [sede.lat, sede.lon]);
    }
  });
});

$("loginForm").addEventListener("submit", manejarLogin);
$("registerForm").addEventListener("submit", manejarRegistro);
$("irACrearCuenta").addEventListener("click", mostrarFormularioRegistro);
$("irAIniciarSesion").addEventListener("click", mostrarFormularioLogin);
$("logoutBtn").addEventListener("click", cerrarSesion);
$("loginUser").focus();
