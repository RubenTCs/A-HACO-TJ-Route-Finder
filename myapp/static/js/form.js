document.addEventListener("DOMContentLoaded", function () {
    const halteAwalInput = document.getElementById("halteAwal");
    const halteTujuanInput = document.getElementById("halteTujuan");
    const halteList = document.getElementById("halteList");

    if (!halteAwalInput || !halteTujuanInput || !halteList) {
        return;
    }

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

            // Exclude the halte value selected in the opposite input.
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
        timeout = setTimeout(() => fetchHalte(query, event.target), 300);
    }

    halteAwalInput.addEventListener("input", handleInput);
    halteTujuanInput.addEventListener("input", handleInput);
});
