"use strict";

// Mover, redimensionar y alinear cuadros en la vista previa (con los contornos activados).
(function () {
  const panel = document.getElementById("mover");
  if (!panel) return;

  const PASO = 0.5;
  const PASO_FINO = 0.1;
  const MINIMO = 1;
  const HISTORIAL_MAXIMO = 100;
  const CAMPOS = ["x", "y", "ancho", "alto"];

  const cajas = [...document.querySelectorAll(".cuadro")];
  const estado = document.getElementById("mover-estado");
  const titulo = document.getElementById("mover-seleccion");
  const entradas = Object.fromEntries(CAMPOS.map((c) => [c, panel.querySelector(`[data-campo=${c}]`)]));
  const botones = {
    deshacer: document.getElementById("deshacer"),
    estampa: document.getElementById("guardar-estampa"),
    modelo: document.getElementById("guardar-modelo"),
    descartar: document.getElementById("descartar"),
    restablecer: document.getElementById("restablecer-seleccion"),
  };
  const token = panel.querySelector("input[name=csrfmiddlewaretoken]").value;

  let seleccion = [];
  let historial = [];
  let ultimaTecla = 0;
  const guardado = new Map(cajas.map((c) => [c, leer(c)])); // Última posición guardada.

  const redondear = (v) => Math.round(v * 100) / 100;
  const activo = () => document.body.classList.contains("con-contorno");

  function leer(caja) {
    return Object.fromEntries(CAMPOS.map((c) => [c, parseFloat(caja.dataset[c])]));
  }

  function escribir(caja, g) {
    CAMPOS.forEach((c) => (caja.dataset[c] = redondear(g[c])));
    caja.style.left = redondear(g.x) + "mm";
    caja.style.top = redondear(g.y) + "mm";
    caja.style.width = redondear(g.ancho) + "mm";
    caja.style.height = redondear(g.alto) + "mm";
  }

  function modelo(caja) {
    return {
      x: parseFloat(caja.dataset.modeloX), y: parseFloat(caja.dataset.modeloY),
      ancho: parseFloat(caja.dataset.modeloAncho), alto: parseFloat(caja.dataset.modeloAlto),
    };
  }

  const tarjeta = (caja) => caja.closest(".tarjeta");
  const mmPorPixel = (caja) => parseFloat(tarjeta(caja).dataset.ancho) / tarjeta(caja).getBoundingClientRect().width;
  const igual = (a, b) => CAMPOS.every((c) => Math.abs(a[c] - b[c]) < 0.005);
  const modificadas = () => cajas.filter((c) => !igual(leer(c), guardado.get(c)));

  // ----- Historial (Ctrl+Z) -----

  function anotar() {
    historial.push(new Map(cajas.map((c) => [c, leer(c)])));
    if (historial.length > HISTORIAL_MAXIMO) historial.shift();
  }

  function deshacer() {
    const anterior = historial.pop();
    if (!anterior) return;
    anterior.forEach((g, caja) => escribir(caja, g));
    actualizar();
  }

  // ----- Selección y capa de tiradores -----

  function capa(caja) {
    const t = tarjeta(caja);
    let marco = t.querySelector(".marco-seleccion");
    if (!marco) {
      marco = document.createElement("div");
      marco.className = "marco-seleccion";
      ["nw", "ne", "sw", "se"].forEach((esquina) => {
        const tirador = document.createElement("span");
        tirador.className = "tirador " + esquina;
        tirador.dataset.esquina = esquina;
        marco.append(tirador);
      });
      t.append(marco);
    }
    return marco;
  }

  function dibujarMarcos() {
    document.querySelectorAll(".marco-seleccion").forEach((m) => (m.hidden = true));
    cajas.forEach((c) => c.classList.toggle("elegido", seleccion.includes(c)));
    if (seleccion.length !== 1) return;
    const caja = seleccion[0];
    const marco = capa(caja);
    const g = leer(caja);
    Object.assign(marco.style, { left: g.x + "mm", top: g.y + "mm", width: g.ancho + "mm", height: g.alto + "mm" });
    marco.hidden = false;
  }

  function actualizar() {
    dibujarMarcos();
    const una = seleccion.length === 1;
    if (!seleccion.length) titulo.textContent = "Ningún cuadro elegido";
    else if (una) titulo.textContent = seleccion[0].dataset.rol;
    else titulo.textContent = `${seleccion.length} cuadros elegidos`;
    CAMPOS.forEach((c) => {
      entradas[c].disabled = !una;
      entradas[c].value = una ? redondear(leer(seleccion[0])[c]) : "";
    });
    panel.querySelectorAll("[data-alinear]").forEach((b) => {
      b.disabled = seleccion.length < parseInt(b.dataset.minimo || "1", 10);
    });
    const cambios = modificadas();
    botones.deshacer.disabled = !historial.length;
    botones.estampa.disabled = botones.modelo.disabled = botones.descartar.disabled = !cambios.length;
    botones.restablecer.disabled = !seleccion.some((c) => !igual(leer(c), modelo(c)));
    estado.textContent = cambios.length ? `${cambios.length} cuadro(s) con cambios sin guardar` : "";
    if (typeof revisarDesbordes === "function") revisarDesbordes();
  }

  function elegir(caja, sumar) {
    if (sumar && seleccion.length && tarjeta(seleccion[0]) !== tarjeta(caja)) sumar = false; // Una página a la vez.
    if (sumar) {
      seleccion = seleccion.includes(caja) ? seleccion.filter((c) => c !== caja) : [...seleccion, caja];
    } else if (!seleccion.includes(caja)) {
      seleccion = [caja];
    }
    actualizar();
  }

  // ----- Arrastrar y redimensionar -----

  function mostrarPosicion(evento, texto) {
    let globo = document.getElementById("globo-posicion");
    if (!globo) {
      globo = document.createElement("div");
      globo.id = "globo-posicion";
      document.body.append(globo);
    }
    globo.textContent = texto;
    globo.style.left = evento.clientX + 14 + "px";
    globo.style.top = evento.clientY + 14 + "px";
    globo.hidden = false;
  }

  function arrastrar(evento, cajasAMover, esquina) {
    evento.preventDefault();
    const escala = mmPorPixel(cajasAMover[0]);
    const inicio = { x: evento.clientX, y: evento.clientY };
    const originales = new Map(cajasAMover.map((c) => [c, leer(c)]));
    let movido = false;

    function mover(e) {
      const dx = (e.clientX - inicio.x) * escala;
      const dy = (e.clientY - inicio.y) * escala;
      if (!movido && Math.hypot(dx, dy) < 0.05) return;
      if (!movido) anotar();
      movido = true;
      originales.forEach((g, caja) => {
        const nuevo = { ...g };
        if (!esquina) {
          nuevo.x = g.x + dx;
          nuevo.y = g.y + dy;
        } else {
          if (esquina.includes("w")) { nuevo.x = Math.min(g.x + dx, g.x + g.ancho - MINIMO); nuevo.ancho = g.ancho - (nuevo.x - g.x); }
          if (esquina.includes("e")) nuevo.ancho = Math.max(MINIMO, g.ancho + dx);
          if (esquina.includes("n")) { nuevo.y = Math.min(g.y + dy, g.y + g.alto - MINIMO); nuevo.alto = g.alto - (nuevo.y - g.y); }
          if (esquina.includes("s")) nuevo.alto = Math.max(MINIMO, g.alto + dy);
        }
        escribir(caja, nuevo);
      });
      const g = leer(cajasAMover[0]);
      mostrarPosicion(e, esquina
        ? `${redondear(g.ancho)} × ${redondear(g.alto)} mm`
        : `x ${redondear(g.x)} · y ${redondear(g.y)} mm`);
      dibujarMarcos();
      CAMPOS.forEach((c) => { if (seleccion.length === 1) entradas[c].value = redondear(leer(seleccion[0])[c]); });
    }

    function soltar() {
      document.removeEventListener("pointermove", mover);
      document.removeEventListener("pointerup", soltar);
      const globo = document.getElementById("globo-posicion");
      if (globo) globo.hidden = true;
      if (movido) actualizar();
    }

    document.addEventListener("pointermove", mover);
    document.addEventListener("pointerup", soltar);
  }

  cajas.forEach((caja) => {
    caja.addEventListener("pointerdown", (e) => {
      if (!activo() || e.button !== 0) return;
      elegir(caja, e.ctrlKey || e.metaKey);
      if (seleccion.includes(caja)) arrastrar(e, seleccion, null);
    });
  });

  document.addEventListener("pointerdown", (e) => {
    const tirador = e.target.closest(".tirador");
    if (tirador && activo() && seleccion.length === 1) {
      arrastrar(e, seleccion, tirador.dataset.esquina);
    } else if (activo() && e.target.closest(".tarjeta") && !e.target.closest(".cuadro")) {
      seleccion = [];
      actualizar();
    }
  });

  // ----- Teclado -----

  document.addEventListener("keydown", (e) => {
    if (!activo()) return;
    if (e.target.closest("input, textarea, select")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      deshacer();
      return;
    }
    const direcciones = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!direcciones[e.key] || !seleccion.length) return;
    e.preventDefault();
    // Varias pulsaciones seguidas se deshacen juntas.
    if (Date.now() - ultimaTecla > 800) anotar();
    ultimaTecla = Date.now();
    const paso = e.shiftKey ? PASO_FINO : PASO;
    const [dx, dy] = direcciones[e.key];
    seleccion.forEach((caja) => {
      const g = leer(caja);
      escribir(caja, { ...g, x: g.x + dx * paso, y: g.y + dy * paso });
    });
    actualizar();
  });

  // ----- Campos en mm -----

  CAMPOS.forEach((campo) => {
    entradas[campo].addEventListener("change", () => {
      const valor = parseFloat(entradas[campo].value.replace(",", "."));
      if (seleccion.length !== 1 || Number.isNaN(valor)) return actualizar();
      if ((campo === "ancho" || campo === "alto") && valor < MINIMO) return actualizar();
      anotar();
      escribir(seleccion[0], { ...leer(seleccion[0]), [campo]: valor });
      actualizar();
    });
  });

  // ----- Alinear -----

  function alinear(como) {
    const g = seleccion.map((c) => ({ caja: c, ...leer(c) }));
    const t = tarjeta(seleccion[0]);
    const anchoTarjeta = parseFloat(t.dataset.ancho);
    const altoTarjeta = parseFloat(t.dataset.alto);
    const izquierda = Math.min(...g.map((c) => c.x));
    const derecha = Math.max(...g.map((c) => c.x + c.ancho));
    const arriba = Math.min(...g.map((c) => c.y));
    const abajo = Math.max(...g.map((c) => c.y + c.alto));
    anotar();
    if (como === "distribuir") {
      const orden = [...g].sort((a, b) => a.y - b.y);
      const total = orden.reduce((s, c) => s + c.alto, 0);
      const espacio = (abajo - arriba - total) / (orden.length - 1);
      let y = arriba;
      orden.forEach((c) => { c.y = y; y += c.alto + espacio; });
    } else {
      g.forEach((c) => {
        if (como === "centro-tarjeta-h") c.x = (anchoTarjeta - c.ancho) / 2;
        if (como === "centro-tarjeta-v") c.y = (altoTarjeta - c.alto) / 2;
        if (como === "izquierda") c.x = izquierda;
        if (como === "derecha") c.x = derecha - c.ancho;
        if (como === "centro") c.x = (izquierda + derecha) / 2 - c.ancho / 2;
        if (como === "arriba") c.y = arriba;
        if (como === "abajo") c.y = abajo - c.alto;
      });
    }
    g.forEach((c) => escribir(c.caja, c));
    actualizar();
  }

  panel.querySelectorAll("[data-alinear]").forEach((b) => b.addEventListener("click", () => alinear(b.dataset.alinear)));

  // ----- Guardar -----

  async function enviar(accion, lista) {
    const cuerpo = {
      accion,
      cuadros: lista.map((c) => ({
        id: c.dataset.cuadro, x_mm: leer(c).x, y_mm: leer(c).y, ancho_mm: leer(c).ancho, alto_mm: leer(c).alto,
      })),
    };
    const respuesta = await fetch(panel.dataset.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(cuerpo),
      credentials: "same-origin",
    });
    if (!respuesta.ok) {
      const datos = await respuesta.json().catch(() => ({}));
      throw new Error(datos.error || `Error ${respuesta.status}`);
    }
  }

  async function guardar(accion) {
    const lista = modificadas();
    if (!lista.length) return;
    if (accion === "modelo" && !confirm(
      "Esto cambia la posición para todas las estampas futuras de este modelo. ¿Continuar?")) return;
    try {
      await enviar(accion, lista);
    } catch (error) {
      estado.textContent = "No se pudo guardar: " + error.message;
      return;
    }
    lista.forEach((c) => {
      guardado.set(c, leer(c));
      if (accion === "modelo") {
        const g = leer(c);
        Object.assign(c.dataset, { modeloX: g.x, modeloY: g.y, modeloAncho: g.ancho, modeloAlto: g.alto });
      }
    });
    actualizar();
    estado.textContent = accion === "modelo" ? "Guardado en el modelo." : "Guardado en esta estampa.";
  }

  botones.estampa.addEventListener("click", () => guardar("estampa"));
  botones.modelo.addEventListener("click", () => guardar("modelo"));
  botones.deshacer.addEventListener("click", deshacer);
  botones.descartar.addEventListener("click", () => {
    anotar();
    cajas.forEach((c) => escribir(c, guardado.get(c)));
    actualizar();
  });
  botones.restablecer.addEventListener("click", async () => {
    const lista = seleccion.filter((c) => !igual(leer(c), modelo(c)));
    try {
      await enviar("restablecer", lista);
    } catch (error) {
      estado.textContent = "No se pudo restablecer: " + error.message;
      return;
    }
    anotar();
    lista.forEach((c) => { escribir(c, modelo(c)); guardado.set(c, modelo(c)); });
    actualizar();
    estado.textContent = "Volvió a la posición del modelo.";
  });

  window.addEventListener("beforeunload", (e) => {
    if (modificadas().length) { e.preventDefault(); e.returnValue = ""; }
  });

  // El panel solo aparece con los contornos activados.
  const mostrarPanel = () => {
    panel.hidden = !activo();
    if (!activo()) { seleccion = []; actualizar(); }
  };
  new MutationObserver(mostrarPanel).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  mostrarPanel();
  actualizar();
})();
