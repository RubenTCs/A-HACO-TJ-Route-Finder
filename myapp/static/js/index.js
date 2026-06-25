// Ubah hasil JSON menjadi objek JavaScript
var hasil = {};
try {
    var hasilEl = document.getElementById("hasilData");
    if (hasilEl) hasil = JSON.parse(hasilEl.textContent);
} catch (e) {
    console.error("Gagal parsing hasil JSON:", e);
}
window.hasil = hasil;
var pathCoords = hasil.path_coords || [];
console.log("hasil dari Django:", hasil);
