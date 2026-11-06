"use strict";

const PASO = 0.01;
const ESCALA_MINIMA = 0.3;

// Como Word, el texto puede ocupar el margen interno del cuadro (1,27 mm arriba y abajo):
// solo es desborde si pasa del borde del cuadro.
function desborda(caja) {
  const contenido = caja.querySelector(".contenido");
  return contenido.scrollHeight > caja.clientHeight + 1 || contenido.scrollWidth > contenido.clientWidth + 1;
}

function revisarDesbordes() {
  const lista = document.getElementById("desbordes");
  lista.innerHTML = "";
  document.querySelectorAll(".cuadro").forEach((caja) => {
    const editor = document.getElementById("cuadro-" + caja.dataset.cuadro);
    const mal = !caja.classList.contains("vacio") && desborda(caja);
    caja.classList.toggle("desborda", mal);
    if (editor) {
      editor.querySelector("[data-aviso-desborde]").hidden = !mal;
      editor.querySelector("[data-achicar]").hidden = !mal;
    }
    if (mal) {
      const item = document.createElement("li");
      const enlace = document.createElement("a");
      enlace.href = "#cuadro-" + caja.dataset.cuadro;
      enlace.textContent = caja.dataset.rol;
      item.append("El texto no entra en el cuadro ", enlace, ". Podés achicar la fuente solo para esta estampa.");
      lista.append(item);
    }
  });
  lista.hidden = !lista.children.length;
}

function achicar(cuadroId) {
  const caja = document.getElementById("caja-" + cuadroId);
  const base = parseFloat(caja.dataset.base);
  let escala = parseFloat(caja.dataset.escala);
  while (desborda(caja) && escala > ESCALA_MINIMA) {
    escala -= PASO;
    caja.style.setProperty("--escala", escala.toFixed(3));
  }
  // Redondeo hacia abajo a cuartos de punto, para quedar seguro dentro del cuadro.
  const tamano = Math.floor(base * escala * 4) / 4;
  const formulario = document.querySelector("#cuadro-" + cuadroId + " form.tamano");
  formulario.querySelector("input[name=tamano]").value = tamano;
  const enviar = document.createElement("input");
  enviar.type = "hidden";
  enviar.name = "accion";
  enviar.value = "tamano";
  formulario.append(enviar);
  formulario.submit();
}

function iniciar() {
  const boton = document.getElementById("contorno");
  const aplicar = (activo) => {
    document.body.classList.toggle("con-contorno", activo);
    boton.setAttribute("aria-pressed", String(activo));
    boton.textContent = activo ? "Ocultar contornos" : "Mostrar contornos";
    localStorage.setItem("estampas-contorno", activo ? "1" : "0");
  };
  aplicar(localStorage.getItem("estampas-contorno") === "1");
  boton.addEventListener("click", () => aplicar(!document.body.classList.contains("con-contorno")));

  const zoom = document.getElementById("zoom");
  const paginas = document.getElementById("paginas");
  zoom.value = localStorage.getItem("estampas-zoom") || zoom.value;
  const aplicarZoom = () => {
    paginas.style.zoom = zoom.value;
    localStorage.setItem("estampas-zoom", zoom.value);
  };
  zoom.addEventListener("change", aplicarZoom);
  aplicarZoom();

  document.querySelectorAll("[data-achicar]").forEach((b) => {
    b.addEventListener("click", () => achicar(b.closest(".editor").dataset.cuadro));
  });

  // Medir recién cuando las fuentes terminaron de cargar.
  document.fonts.ready.then(revisarDesbordes);
}

iniciar();
