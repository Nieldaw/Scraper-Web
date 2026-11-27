/* Visite guidée (Driver.js). Se lance une seule fois par navigateur ; rejouable via « Visite guidée ».
 *
 * Parcours : barre latérale -> recherche -> (page Propriétés) filtres -> bouton « Nouveau mandat ».
 * Depuis une autre page que Propriétés, le tour s'arrête sur le lien « Propriétés » puis continue
 * sur cette page. L'état (terminé / en cours) est gardé en localStorage / sessionStorage.
 */
(function () {
  "use strict";
  var DONE_KEY = "immo_tour_v1_done";
  var STAGE_KEY = "immo_tour_v1_stage";

  function store(area, op, key, value) {
    try {
      var s = window[area];
      if (op === "get") return s.getItem(key);
      if (op === "set") s.setItem(key, value);
      if (op === "del") s.removeItem(key);
    } catch (e) { /* stockage indisponible (navigation privée…) : le tour se relancera */ }
    return null;
  }

  var driverFactory = window.driver && window.driver.js && window.driver.js.driver;
  if (!driverFactory) return; // Driver.js non chargé (hors ligne) : l'interface reste utilisable.

  function visible(selector) {
    var el = document.querySelector(selector);
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < window.innerWidth;
  }

  var STEPS = {
    sidebar: {
      element: '[data-tour="sidebar"]',
      popover: {
        title: "Navigation",
        description: "Passez d'une page à l'autre : tableau de bord, propriétés, mandats, historique des collectes et configuration.",
        side: "right", align: "start"
      }
    },
    search: {
      element: '[data-tour="search"]',
      popover: {
        title: "Recherche rapide",
        description: "Tapez une ville, un titre ou une adresse puis Entrée : la liste des propriétés s'ouvre déjà filtrée.",
        side: "bottom", align: "start"
      }
    },
    filters: {
      element: '[data-tour="filters"]',
      popover: {
        title: "Filtres",
        description: "Affinez par statut (nouveaux, modifiés, plus disponibles), ville, canton, prix ou pièces. La liste se met à jour toute seule.",
        side: "bottom", align: "start"
      }
    },
    mandate: {
      element: '[data-tour="new-mandate"]',
      popover: {
        title: "Nouveau mandat",
        description: "Enregistrez vos critères de recherche (villes, budget, pièces…) pour retrouver à tout moment les biens qui correspondent.",
        side: "left", align: "start"
      }
    }
  };

  function isProperties() { return window.location.pathname === "/properties"; }

  var navigating = false;

  function buildSteps(stage) {
    var list;
    if (stage === "properties") {
      list = [STEPS.filters, STEPS.mandate];
    } else if (isProperties()) {
      list = [STEPS.sidebar, STEPS.search, STEPS.filters, STEPS.mandate];
    } else {
      var toProperties = {
        element: '[data-tour="nav-properties"]',
        popover: {
          title: "Les propriétés",
          description: "C'est ici que vous consultez les biens collectés. Cliquez sur « Suivant » pour l'ouvrir et découvrir les filtres.",
          side: "right", align: "start",
          nextBtnText: "Ouvrir Propriétés",
          onNextClick: function () {
            navigating = true;
            store("sessionStorage", "set", STAGE_KEY, "properties");
            window.location.href = "/properties";
          }
        }
      };
      list = [STEPS.sidebar, STEPS.search, toProperties];
    }
    // Ignore les étapes dont la cible est absente ou hors écran (ex. barre latérale repliée sur mobile).
    return list.filter(function (step) { return visible(step.element); });
  }

  function start(stage) {
    var steps = buildSteps(stage);
    if (!steps.length) return;
    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var tour = driverFactory({
      steps: steps,
      showProgress: true,
      animate: !reduceMotion,
      allowClose: true,
      overlayOpacity: 0.7,
      stagePadding: 6,
      nextBtnText: "Suivant",
      prevBtnText: "Précédent",
      doneBtnText: "Terminer",
      progressText: "{{current}} sur {{total}}",
      // Appelé quand on termine, ferme (croix, Échap) ou clique sur le fond. C'est ce crochet qui
      // couvre toutes les sorties : `onDestroyed` n'est pas fiable à la fermeture.
      onDestroyStarted: function () {
        if (!navigating) { // si on change de page, le tour continue là-bas : ne rien mémoriser
          store("localStorage", "set", DONE_KEY, "1");
          store("sessionStorage", "del", STAGE_KEY);
        }
        tour.destroy();
      }
    });
    tour.drive();
  }

  function init() {
    var params = new URLSearchParams(window.location.search);
    var forced = params.get("tour") === "1" && isProperties();
    var stage = store("sessionStorage", "get", STAGE_KEY);
    var done = store("localStorage", "get", DONE_KEY) === "1";

    if (forced) {
      store("localStorage", "del", DONE_KEY);
      store("sessionStorage", "del", STAGE_KEY);
      start(null);
    } else if (stage === "properties" && isProperties() && !done) {
      store("sessionStorage", "del", STAGE_KEY);
      start("properties");
    } else if (!done && !stage) {
      start(null);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
