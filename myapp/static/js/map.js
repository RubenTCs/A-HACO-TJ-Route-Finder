document.addEventListener("DOMContentLoaded", function () {
    if (typeof hasil === "undefined" || !hasil.detailed_journey) {
        console.error("Map data tidak tersedia");
        return;
    }

    const routeData = typeof hasil !== "undefined" && hasil ? hasil : {};
    const detailedJourney = Array.isArray(routeData.detailed_journey) ? routeData.detailed_journey : [];
    const pathCoordinates = Array.isArray(routeData.path_coordinates) ? routeData.path_coordinates : [];
    const pathSegments = Array.isArray(routeData.path_segments) ? routeData.path_segments : [];

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

    const bounds = [];

    const addMarker = (coord, icon, popupHtml) => {
        if (!isCoord(coord)) return;
        const latlon = [coord[0], coord[1]];
        L.marker(latlon, { icon })
            .addTo(map)
            .bindPopup(popupHtml);
        bounds.push(latlon);
    };

    if (pathSegments.length > 0) {
        // Draw one colored polyline per route segment.
        pathSegments.forEach((seg) => {
            const pts = (seg.coords || []).filter(isCoord).map((c) => [c[0], c[1]]);
            if (pts.length === 0) return;
            const opts = { color: seg.color || "#2563eb", weight: 6, opacity: 0.9 };
            if (seg.dashed) {
                opts.dashArray = "8 8";
                opts.weight = 4;
            }
            const popupLabel = seg.koridor === "walk" ? "Jalan kaki" : `Koridor ${seg.koridor}`;
            L.polyline(pts, opts)
            .addTo(map)
            .bindPopup(`<b>${popupLabel}</b>`);
            bounds.push(...pts);
        });
    } else {
        // Fallback: single blue polyline from flat path_coordinates.
        const pts = pathCoordinates.filter(isCoord).map((c) => [c[0], c[1]]);
        if (pts.length > 0) {
            L.polyline(pts, { color: "#2563eb", weight: 6, opacity: 0.9 })
            .addTo(map);
            bounds.push(...pts);
        }
    }

    const travelSteps = detailedJourney.filter((step) => step.type === "travel");
    const firstTravelStep = travelSteps[0];
    const lastTravelStep = travelSteps[travelSteps.length - 1];

    // Walking-only fallback: no travel steps, anchor markers on the walk endpoints.
    const isWalkingOnly = !!routeData.is_walking_only;
    const walkOnlyStep = isWalkingOnly ? detailedJourney.find((s) => s.type === "walk") : null;

    if (firstTravelStep) {
        addMarker(
            firstTravelStep.coords_from,
            startIcon,
            `<b>Halte awal</b><br>${firstTravelStep.from || "Halte awal"}`
        );
    } else if (walkOnlyStep) {
        addMarker(
            walkOnlyStep.coords_from,
            startIcon,
            `<b>Halte awal</b><br>${walkOnlyStep.from_halte || "Halte awal"}`
        );
    }

    if (lastTravelStep) {
        addMarker(
            lastTravelStep.coords_to,
            endIcon,
            `<b>Halte tujuan</b><br>${lastTravelStep.to || "Halte tujuan"}`
        );
    } else if (walkOnlyStep) {
        addMarker(
            walkOnlyStep.coords_to,
            endIcon,
            `<b>Halte tujuan</b><br>${walkOnlyStep.to_halte || "Halte tujuan"}`
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
                `<b>Transit</b><br>${step.halte || "Perpindahan koridor"}`
            );
        }

        if (step.type === "walk") {
            addMarker(
                step.coords_from,
                transferIcon,
                `<b>Jalan kaki</b><br>${step.from_halte || ""} &rarr; ${step.to_halte || ""}`
            );
        }
    });



    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [24, 24] });
    }
});