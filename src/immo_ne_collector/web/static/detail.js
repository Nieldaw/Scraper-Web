// Fiche d'un bien : carrousel photos + carte OpenStreetMap (Leaflet) centrée sur le code postal.
(function () {
  function initGallery(root) {
    var track = root.querySelector(".gallery-track");
    if (!track) return;
    var count = root.querySelector("[data-count]");
    var imgs = track.querySelectorAll("img");
    function index() { return Math.round(track.scrollLeft / track.clientWidth); }
    function go(i) {
      i = Math.max(0, Math.min(imgs.length - 1, i));
      track.scrollTo({ left: i * track.clientWidth, behavior: "smooth" });
    }
    var prev = root.querySelector(".gal-prev"), next = root.querySelector(".gal-next");
    if (prev) prev.addEventListener("click", function (e) { e.preventDefault(); go(index() - 1); });
    if (next) next.addEventListener("click", function (e) { e.preventDefault(); go(index() + 1); });
    track.addEventListener("scroll", function () {
      if (count) count.textContent = (index() + 1) + " / " + imgs.length;
    });
    imgs.forEach(function (img) {
      img.addEventListener("error", function () { img.style.visibility = "hidden"; });
    });
  }

  function initMap(el) {
    if (!window.L) { el.textContent = "Carte indisponible (bibliothèque non chargée)."; return; }
    var query = el.dataset.query;
    var key = "immo_geo_" + query;
    function show(lat, lon) {
      var map = L.map(el).setView([lat, lon], 13);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>"
      }).addTo(map);
      L.circle([lat, lon], { radius: 600, color: "#c8f53c", fillOpacity: 0.15 }).addTo(map);
    }
    var cached = null;
    try { cached = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) {}
    if (cached) return show(cached[0], cached[1]);
    fetch("https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=ch&q=" +
          encodeURIComponent(query), { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.length) { el.textContent = "Lieu introuvable sur la carte."; return; }
        var lat = parseFloat(res[0].lat), lon = parseFloat(res[0].lon);
        try { localStorage.setItem(key, JSON.stringify([lat, lon])); } catch (e) {}
        show(lat, lon);
      })
      .catch(function () { el.textContent = "Carte indisponible (pas de connexion)."; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-gallery]").forEach(initGallery);
    var map = document.getElementById("map");
    if (map) initMap(map);
  });
})();
