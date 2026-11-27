/* Formulaire de mandat : liste déroulante de villes (multi-choix) et curseurs doubles. */
(function () {
  "use strict";

  const fmt = (n) => new Intl.NumberFormat("fr-CH").format(n).replace(/ | /g, "'");

  // --- curseurs doubles ------------------------------------------------------------------
  function initSlider(root) {
    const unit = root.dataset.unit || "";
    const minR = root.querySelector('[data-role="min"]');
    const maxR = root.querySelector('[data-role="max"]');
    const minH = root.querySelector('[data-hidden="min"]');
    const maxH = root.querySelector('[data-hidden="max"]');
    const out = root.querySelector("[data-out]");
    const fill = root.querySelector("[data-fill]");
    const low = parseFloat(minR.min);
    const high = parseFloat(minR.max);

    function render(sync) {
      let a = parseFloat(minR.value);
      let b = parseFloat(maxR.value);
      if (a > b) {
        // les poignées ne se croisent jamais : celle qu'on tire pousse l'autre
        if (document.activeElement === minR) { b = a; maxR.value = b; } else { a = b; minR.value = a; }
      }
      const atLow = a <= low;
      const atHigh = b >= high;
      if (sync) {
        // à la borne = « pas de limite » : le critère n'est pas envoyé
        minH.value = atLow ? "" : String(a);
        maxH.value = atHigh ? "" : String(b);
      }
      const span = high - low || 1;
      fill.style.left = ((a - low) / span) * 100 + "%";
      fill.style.right = (1 - (b - low) / span) * 100 + "%";
      let text;
      if (atLow && atHigh) text = "Indifférent";
      else if (atLow) text = "jusqu'à " + fmt(b) + unit;
      else if (atHigh) text = "dès " + fmt(a) + unit;
      else text = fmt(a) + " – " + fmt(b) + unit;
      out.textContent = text;
    }

    // valeurs initiales : une borne vide dans le formulaire = curseur à l'extrémité
    if (minH.value === "") minR.value = low;
    if (maxH.value === "") maxR.value = high;
    [minR, maxR].forEach((r) => r.addEventListener("input", () => render(true)));
    render(false);
  }

  // --- liste déroulante de villes --------------------------------------------------------
  function initMulti(root) {
    const label = root.querySelector("[data-multi-label]");
    const boxes = () => Array.from(root.querySelectorAll('input[type="checkbox"]'));
    const filter = root.querySelector(".multi-filter");

    function update() {
      const checked = boxes().filter((b) => b.checked).map((b) => b.value);
      if (checked.length === 0) label.textContent = label.dataset.empty;
      else if (checked.length <= 2) label.textContent = checked.join(", ");
      else label.textContent = checked.length + " villes sélectionnées";
    }

    root.addEventListener("change", update);
    if (filter) {
      filter.addEventListener("input", () => {
        const q = filter.value.trim().toLowerCase();
        root.querySelectorAll(".multi-item").forEach((item) => {
          item.hidden = q !== "" && !item.textContent.toLowerCase().includes(q);
        });
      });
    }
    // fermeture au clic extérieur ou avec Échap
    document.addEventListener("click", (e) => { if (!root.contains(e.target)) root.open = false; });
    root.addEventListener("keydown", (e) => { if (e.key === "Escape") { root.open = false; root.querySelector("summary").focus(); } });
    update();
  }

  document.querySelectorAll("[data-slider]").forEach(initSlider);
  document.querySelectorAll("[data-multi]").forEach(initMulti);
})();
