document.addEventListener("DOMContentLoaded", function () {
    // ---- Halte autocomplete ------------------------------------------------
    const halteAwalInput = document.getElementById("halteAwal");
    const halteTujuanInput = document.getElementById("halteTujuan");
    const halteList = document.getElementById("halteList");

    if (halteAwalInput && halteTujuanInput && halteList) {
        async function fetchHalte(query, activeInput) {
            if (query.length < 2) {
                halteList.innerHTML = "";
                return;
            }
            try {
                const response = await fetch(
                    `/api/getHalteList?q=${encodeURIComponent(query)}`,
                );
                const data = await response.json();

                const otherValue =
                    activeInput === halteAwalInput
                        ? halteTujuanInput.value.trim()
                        : halteAwalInput.value.trim();

                halteList.innerHTML = "";
                data.forEach((halte) => {
                    if (halte === otherValue) return;
                    const option = document.createElement("option");
                    option.value = halte;
                    halteList.appendChild(option);
                });
            } catch (error) {
                console.error("Error fetching halte:", error);
            }
        }

        let timeout = null;
        function handleInput(event) {
            clearTimeout(timeout);
            const query = event.target.value;
            timeout = setTimeout(() => fetchHalte(query, event.target), 200);
        }
        halteAwalInput.addEventListener("input", handleInput);
        halteTujuanInput.addEventListener("input", handleInput);

    }

    // ---- Submit / solver-running indicator --------------------------------
    const routeForm = document.getElementById("routeForm");
    const submitBtn = document.getElementById("submitBtn");
    const solverSelect = document.getElementById("metodeSolverSelect");
    const solverStatus = document.getElementById("solverStatus");
    const solverStatusText = solverStatus
        ? solverStatus.querySelector(".solver-status-text")
        : null;

    const SOLVER_LABEL = {
        MILP: "MILP (Gurobi)",
        ASTAR: "A*",
        HACO: "HACO",
    };

    if (routeForm && submitBtn) {
        routeForm.addEventListener("submit", function () {
            // Browser handles HTML5 required-validation before this fires.
            const solver = solverSelect ? solverSelect.value : "";
            const label = SOLVER_LABEL[solver] || solver || "solver";

            submitBtn.disabled = true;
            submitBtn.classList.add("is-submitting");
            routeForm.classList.add("is-submitting");

            const labelEl = submitBtn.querySelector(".btn-label");
            if (labelEl) labelEl.textContent = "Mencari rute…";

            if (solverStatus && solverStatusText) {
                solverStatusText.textContent =
                    `Menjalankan solver ${label} — mohon tunggu…`;
                solverStatus.hidden = false;
            }
        });
    }
});
