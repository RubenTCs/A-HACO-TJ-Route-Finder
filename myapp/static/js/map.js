document.addEventListener("DOMContentLoaded", function () {
    if (typeof hasil === "undefined" || !hasil.detailed_journey) {
        console.error("Map data tidak tersedia");
        return;
    }

    const routeData = typeof hasil !== "undefined" && hasil ? hasil : {};
    const detailedJourney = Array.isArray(routeData.detailed_journey) ? routeData.detailed_journey : [];
    const pathCoordinates = Array.isArray(routeData.path_coordinates) ? routeData.path_coordinates : [];

    const isCoord = (coord) => Array.isArray(coord) && coord.length === 2;

    const map = L.map("routeMap").setView([-6.2, 106.8], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
        referrerPolicy: "strict-origin",
    }).addTo(map);

    const startIcon = L.divIcon({
        html: '<div style="width:20px;height:20px;background:#16a34a;border:3px solid white;border-radius:50%;box-shadow:0 0 4px rgba(22,163,74,.45);"></div>',
        className: "grab-point",
        iconSize: [20, 20],
        popupAnchor: [0, -10],
    });

    const endIcon = L.divIcon({
        html: '<div style="width:20px;height:20px;background:#dc2626;border:3px solid white;border-radius:50%;box-shadow:0 0 4px rgba(220,38,38,.45);"></div>',
        className: "grab-point",
        iconSize: [20, 20],
        popupAnchor: [0, -10],
    });

    const stopIcon = L.divIcon({
        html: '<div style="width:14px;height:14px;background:#2563eb;border:2px solid white;border-radius:50%;box-shadow:0 0 3px rgba(37,99,235,.45);"></div>',
        className: "grab-point",
        iconSize: [14, 14],
        popupAnchor: [0, -7],
    });

    const transferIcon = L.divIcon({
        html: '<div style="width:14px;height:14px;background:#fbbf24;border:2px solid white;border-radius:50%;box-shadow:0 0 3px rgba(251,191,36,.45);"></div>',
        className: "grab-point",
        iconSize: [14, 14],
        popupAnchor: [0, -7],
    });

    const routeLine = L.polyline([], { color: "#2563eb", weight: 6, opacity: 0.9 }).addTo(map);
    const bounds = [];

    const addMarker = (coord, icon, popupHtml) => {
        if (!isCoord(coord)) {
            return;
        }

        const latlon = [coord[0], coord[1]];
        L.marker(latlon, { icon }).addTo(map).bindPopup(popupHtml);
        bounds.push(latlon);
    };

    const polylinePoints = pathCoordinates
        .filter(isCoord)
        .map((coord) => [coord[0], coord[1]]);

    // ADD to bounds
    if (polylinePoints.length > 0) {
        polylinePoints.forEach((point) => {
            routeLine.addLatLng(point);
        });
        bounds.push(...polylinePoints);
    }

    const travelSteps = detailedJourney.filter((step) => step.type === "travel");
    const firstTravelStep = travelSteps[0];
    const lastTravelStep = travelSteps[travelSteps.length - 1];

    if (firstTravelStep) {
        addMarker(
            firstTravelStep.coords_from,
            startIcon,
            `<b>Halte awal</b><br>${firstTravelStep.from || "Halte awal"}`
        );
    }

    if (lastTravelStep) {
        addMarker(
            lastTravelStep.coords_to,
            endIcon,
            `<b>Halte tujuan</b><br>${lastTravelStep.to || "Halte tujuan"}`
        );
    }

    detailedJourney.forEach((step) => {
        if (step.type === "travel") {
            const viaStops = Array.isArray(step.via) ? step.via : [];

            viaStops.forEach((halteName) => {
                const halteData = detailedJourney.find((h) => h.from === halteName || h.to === halteName);
                addMarker(
                    halteData ? halteData.coords_from : null,
                    stopIcon,
                    `<b>${halteName}</b><br>Koridor ${step.koridor}`
                );
            });

            return;
        }

        if (step.type === "transfer") {
            const transferCoord = isCoord(step.coords) ? step.coords : step.coords_from;
            addMarker(
                transferCoord,
                transferIcon,
                `<b>Transfer</b><br>${step.halte || "Perpindahan koridor"}`
            );
        }
    });



    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [24, 24] });
    }
});