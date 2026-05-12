function renderTimeline() {
    var data = window.hasil;
    if (!data) {
        try {
            var el = document.getElementById("hasilData");
            data = el ? JSON.parse(el.textContent) : {};
        } catch (e) { data = {}; }
    }
    var steps = Array.isArray(data.detailed_journey) ? data.detailed_journey : [];
    var segments = Array.isArray(data.path_segments) ? data.path_segments : [];

    var colorByKoridor = {};
    segments.forEach(function (s) {
        if (s && s.koridor != null) colorByKoridor[String(s.koridor)] = s.color || "#2563eb";
    });

    function el(tag, cls, html) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (html != null) n.innerHTML = html;
        return n;
    }

    function corridorChip(koridor) {
        var color = colorByKoridor[String(koridor)] || "#2563eb";
        return '<span class="corridor-chip" style="background:' + color + ';">' +
                 (koridor == null ? "" : koridor) +
               '</span>';
    }

    var travelSteps = steps.filter(function (s) { return s && s.type === "travel"; });
    var firstTravel = travelSteps[0];
    var lastTravel = travelSteps[travelSteps.length - 1];
    var isWalkingOnly = !!data.is_walking_only;

    var tl = document.getElementById("timeline");
    if (!tl) return;

    // Walking-only fallback banner — explains why transit was skipped.
    if (isWalkingOnly) {
        var banner = el("div", "step walk-fallback");
        banner.style.borderLeftColor = "#6b7280";
        var reasonHtml = data.fallback_reason
            ? '<div class="sub" style="color:var(--muted);">' + data.fallback_reason + '</div>'
            : '';
        banner.innerHTML =
            '<div class="ttl"><span class="pin">Jalan kaki saja</span> ' +
            'Lebih praktis ditempuh berjalan kaki</div>' + reasonHtml;
        tl.appendChild(banner);
    }

    // Start step — for walking-only, anchor on the first walk step instead of travel.
    if (firstTravel) {
        var startNode = el("div", "step start");
        startNode.innerHTML =
            '<div class="ttl"><span class="pin">Mulai &middot; ' + (data.jam_berangkat || "") + '</span> ' +
            (firstTravel.from || data.halte_asal || "") + '</div>' +
            '<div class="sub">Naik ' + corridorChip(firstTravel.koridor) + ' menuju ' +
            (firstTravel.to || "") + '</div>';
        tl.appendChild(startNode);
    } else if (isWalkingOnly && steps[0]) {
        var startNode = el("div", "step start");
        startNode.innerHTML =
            '<div class="ttl"><span class="pin">Mulai &middot; ' + (data.jam_berangkat || "") + '</span> ' +
            (steps[0].from_halte || data.halte_asal || "") + '</div>' +
            '<div class="sub">Berjalan kaki menuju ' + (steps[0].to_halte || data.halte_tujuan || "") + '</div>';
        tl.appendChild(startNode);
    }

    // Body steps
    steps.forEach(function (step) {
        if (!step || !step.type) return;

        if (step.type === "travel") {
            var color = colorByKoridor[String(step.koridor)] || "#2563eb";
            var node = el("div", "step");
            node.style.borderLeftColor = color;

            var via = Array.isArray(step.via) ? step.via : [];
            var stops = [step.from].concat(via).concat([step.to]).filter(Boolean);

            var stopsHtml = "";
            stops.forEach(function (s, i) {
                if (i > 0) stopsHtml += '<span class="arrow">&rarr;</span>';
                stopsHtml += '<span class="stop">' + s + '</span>';
            });

            node.innerHTML =
                '<div class="ttl">' + corridorChip(step.koridor) +
                  ' <span style="color:var(--muted); font-weight:500;">' +
                    stops.length + ' halte</span></div>' +
                (stopsHtml ? '<div class="stop-row">' + stopsHtml + '</div>' : "");
            tl.appendChild(node);
            return;
        }

        if (step.type === "transfer") {
            var t = el("div", "step transit");
            var fromK = step.from_koridor != null ? step.from_koridor : "";
            var toK = step.to_koridor != null ? step.to_koridor : "";
            t.innerHTML =
                '<div class="ttl"><span class="pin">Transit</span> ' +
                (step.halte || "") + '</div>' +
                '<div class="sub">Pindah dari ' + corridorChip(fromK) +
                ' ke ' + corridorChip(toK) + '</div>';
            tl.appendChild(t);
            return;
        }

        if (step.type === "walk") {
            var w = el("div", "step walk");
            var dist = step.distance_km != null ? Number(step.distance_km).toFixed(2) : "?";
            var dur = step.duration_min != null ? Math.round(step.duration_min) : "?";
            w.innerHTML =
                '<div class="ttl"><span class="pin">Jalan kaki</span> ' +
                (step.from_halte || "") + ' &rarr; ' + (step.to_halte || "") + '</div>' +
                '<div class="sub">' + dist + ' km &middot; sekitar ' + dur + ' menit</div>';
            tl.appendChild(w);
            return;
        }
    });

    // End step
    if (lastTravel) {
        var endNode = el("div", "step end");
        endNode.innerHTML =
            '<div class="ttl"><span class="pin">Tiba &middot; ' + (data.jam_tiba || "") + '</span> ' +
            (lastTravel.to || data.halte_tujuan || "") + '</div>' +
            '<div class="sub">Halte tujuan</div>';
        tl.appendChild(endNode);
    } else if (isWalkingOnly && steps[steps.length - 1]) {
        var endNode = el("div", "step end");
        endNode.innerHTML =
            '<div class="ttl"><span class="pin">Tiba &middot; ' + (data.jam_tiba || "") + '</span> ' +
            (steps[steps.length - 1].to_halte || data.halte_tujuan || "") + '</div>' +
            '<div class="sub">Halte tujuan</div>';
        tl.appendChild(endNode);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderTimeline);
} else {
    renderTimeline();
}
