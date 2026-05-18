# Website Optimasi Rute Armada Transjakarta dengan A* dan HACO

Website pencarian rute armada Transjakarta yang memungkinkan pengguna memilih preferensi perjalanan (paling cepat, paling murah, atau transit minimal) dan membandingkan hasil dari tiga metode optimasi: **MILP**, **A\***, dan **HACO** (Hybrid Ant Colony Optimization).

## Kebutuhan Sistem

| Komponen | Minimum | Direkomendasikan |
|----------|---------|------------------|
| Prosesor | Intel Core i3 | Intel Core i5 ke atas |
| RAM | 4 GB | 8 GB |
| Penyimpanan | 2 GB ruang kosong | 5 GB ruang kosong |
| Sistem Operasi | Windows 10 / 11 | Windows 11 |
| Python | 3.11 atau yang kompatibel | 3.14 |
| Browser | Chrome / Edge versi terbaru | Chrome terbaru |
| Gurobi Optimizer | 11.0+ (opsional, hanya untuk solver MILP) | - |
| Koneksi Internet | Diperlukan untuk peta | ≥ 5 Mbps |

## Instalasi dan Menjalankan Web

Ikuti langkah berikut secara berurutan.

### 1. Clone repository dari GitHub

```bash
git clone https://github.com/RubenTCs/A-HACO-TJ-Route-Finder.git
cd A-HACO-TJ-Route-Finder
```

### 2. Buat virtual environment

```bash
python -m venv venv
```

### 3. Aktifkan virtual environment

```bash
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Migrasi database

```bash
python manage.py migrate
```

### 6. Jalankan server

```bash
python manage.py runserver
```

### 7. Buka browser

Akses website di [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

Jika halaman utama muncul, instalasi berhasil.

## Cara Menggunakan

1. **Input Halte Awal** — ketik nama halte keberangkatan (minimal 2 huruf), lalu pilih dari saran autocomplete.
2. **Input Halte Tujuan** — ketik nama halte tujuan (harus berbeda dari halte awal).
3. **Pilih Tanggal Berangkat** — sesuai rencana perjalanan, digunakan untuk mencocokkan jadwal koridor aktif.
4. **Atur Jam Berangkat** — memengaruhi kategori jam (sibuk / normal / malam) dan tarif (ekonomis pukul 05.00–07.00 atau normal).
5. **Pilih Preferensi Rute**:
   - **Seimbang** — keseimbangan antara waktu, biaya, dan transit
   - **Paling murah** — total biaya terendah
   - **Paling cepat** — waktu tempuh tersingkat
   - **Paling sedikit transit** — perpindahan koridor minimal
6. **Pilih Metode Solver**:
   - **MILP** — Mixed-Integer Linear Programming (Gurobi), optimasi eksak
   - **A\*** — pencarian jalur terpendek berbasis heuristik
   - **HACO** — metaheuristik Hybrid Ant Colony Optimization
7. **Tekan tombol Cari Rute** — sistem akan memproses dan menampilkan hasil di sisi kanan halaman.

## Output

- **Panel Hasil Pencarian** — ringkasan waktu tempuh, biaya, jumlah transit, jam tiba, serta timeline rute per langkah.
- **Visualisasi Peta Interaktif** — jalur rute geografis dengan marker halte awal (hijau), tujuan (merah), dan transit (kuning). Segmen jalan kaki ditampilkan sebagai garis putus-putus abu-abu.

## Catatan

- Solver **MILP** memerlukan instalasi Gurobi Optimizer 11.0+ beserta lisensinya. Solver **A\*** dan **HACO** dapat dijalankan tanpa Gurobi.
- Koneksi internet diperlukan untuk memuat tile peta.
