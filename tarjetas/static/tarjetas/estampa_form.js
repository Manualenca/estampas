"use strict";

(function () {
  const formulario = document.getElementById("form-estampa");
  const casillas = [...formulario.querySelectorAll(".sacramento input[type=checkbox]")];
  const selector = document.getElementById("id_oracion");
  const verTodas = document.getElementById("ver-todas");
  const sinAfines = document.getElementById("sin-afines");

  function elegidos() {
    return casillas.filter((c) => c.checked).map((c) => c.dataset.codigo);
  }

  function mostrarFechasPropias() {
    casillas.forEach((c) => {
      c.closest(".sacramento").querySelector(".propios").hidden = !c.checked;
    });
  }

  // Primero las oraciones del sacramento elegido; "ver todas" muestra el resto.
  function filtrarOraciones() {
    const codigos = elegidos();
    const opciones = [...selector.options].filter((o) => o.value);
    const afines = (o) => (o.dataset.sacramentos || "").split(" ").some((c) => codigos.includes(c));
    const hayAfines = codigos.length && opciones.some(afines);
    sinAfines.hidden = !codigos.length || hayAfines;
    opciones.forEach((o) => {
      o.hidden = !(verTodas.checked || !hayAfines || afines(o) || o.selected);
    });
  }

  function mostrarModo() {
    const modo = formulario.querySelector("input[name=modo_oracion]:checked")?.value || "banco";
    document.getElementById("oracion-banco").hidden = modo !== "banco";
    document.getElementById("oracion-libre").hidden = modo !== "libre";
    document.getElementById("oracion-ninguna").hidden = modo !== "ninguna";
  }

  casillas.forEach((c) => c.addEventListener("change", () => { mostrarFechasPropias(); filtrarOraciones(); }));
  verTodas.addEventListener("change", filtrarOraciones);
  formulario.querySelectorAll("input[name=modo_oracion]").forEach((r) => r.addEventListener("change", mostrarModo));

  mostrarFechasPropias();
  filtrarOraciones();
  mostrarModo();
})();
