/* Base-map switcher shared by the home, listing and add/edit pages.
   - Street map (OpenStreetMap)
   - Satellite + place names (Esri imagery + reference labels)  <- more detail
   - Satellite (Esri imagery)
   - Google Maps layers, only when GOOGLE_MAPS_API_KEY is configured on the server
   Usage:  addBaseLayers(map);   // after  L.map(...)  */
(function () {
  window.addBaseLayers = function (map) {
    var cfg = window.MAP_CFG || { labels: {} };
    var lb = cfg.labels || {};

    var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });
    var imagery = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19, maxNativeZoom: 17,
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
      });
    var names = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19, maxNativeZoom: 17, attribution: 'Labels &copy; Esri'
      });
    var hybrid = L.layerGroup([imagery, names]);

    var bases = {};
    var googleLayers = [];
    var first = osm;

    var googleReady = cfg.google && window.google && window.google.maps &&
                      L.gridLayer && L.gridLayer.googleMutant;
    if (googleReady) {
      try {
        var gRoad = L.gridLayer.googleMutant({ type: 'roadmap', maxZoom: 21 });
        var gHybrid = L.gridLayer.googleMutant({ type: 'hybrid', maxZoom: 21 });
        bases[lb.google || 'Google Maps'] = gRoad;
        bases[lb.google_hybrid || 'Google Satellite'] = gHybrid;
        googleLayers = [gRoad, gHybrid];
        first = gRoad;
      } catch (e) {
        console.warn('Google Maps layers unavailable:', e);
      }
    }

    bases[lb.osm || 'Street map'] = osm;
    bases[lb.hybrid || 'Satellite + names'] = hybrid;
    bases[lb.satellite || 'Satellite'] = imagery;

    first.addTo(map);
    L.control.layers(bases, null, { collapsed: true, position: 'topright' }).addTo(map);

    // Invalid / unauthorised Google key: fall back to the free street map.
    window.gm_authFailure = function () {
      googleLayers.forEach(function (l) { if (map.hasLayer(l)) map.removeLayer(l); });
      if (!map.hasLayer(osm) && !map.hasLayer(hybrid) && !map.hasLayer(imagery)) osm.addTo(map);
    };
  };
})();
