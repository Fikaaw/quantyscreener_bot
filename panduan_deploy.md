PANDUAN DEPLOY — @quantyscreener_bot
Altcoin Potential Screener ke GitHub Actions
---
FILE YANG KAMU PUNYA
```
flowstate_bot/
├── main.py                          ← Script utama
├── requirements.txt                 ← Library yang dibutuhkan
└── .github/
    └── workflows/
        └── screener.yml             ← Otomasi tiap 4 jam
```
---
STEP 1 — Buat GitHub Account (kalau belum punya)
Buka https://github.com
Klik "Sign up"
Daftar dengan email
Verifikasi email
---
STEP 2 — Buat Repository Baru
Setelah login, klik tombol "+" di kanan atas
Pilih "New repository"
Isi:
Repository name: `quantyscreener_bot` (bebas)
Visibility: pilih Private (supaya kode tidak publik)
Centang "Add a README file"
Klik "Create repository"
---
STEP 3 — Upload File
Cara termudah (via browser, tidak perlu install Git):
Upload main.py:
Di halaman repo, klik "Add file" → "Upload files"
Drag & drop file `main.py`
Scroll ke bawah, klik "Commit changes"
Upload requirements.txt:
Klik "Add file" → "Upload files" lagi
Drag & drop file `requirements.txt`
Klik "Commit changes"
Upload screener.yml (ini yang paling penting):
Klik "Add file" → "Create new file"
Di kolom nama file, ketik:
```
   .github/workflows/screener.yml
   ```
(ketik persis begitu, termasuk titik di depan)
Copy-paste isi file `screener.yml` ke kotak teks di bawah
Klik "Commit changes"
---
STEP 4 — Tambahkan Secrets (PENTING)
Ini tempat kamu simpan token Telegram dengan aman.
GitHub Actions akan baca otomatis — token tidak pernah muncul di kode.
Di halaman repo, klik "Settings" (tab paling kanan)
Di sidebar kiri, cari "Secrets and variables" → klik "Actions"
Klik "New repository secret"
Secret pertama — Token Bot:
Name: `TELEGRAM_TOKEN`
Secret: (isi dengan token baru dari @BotFather setelah revoke)
Klik "Add secret"
Secret kedua — Chat ID kamu:
Name: `TELEGRAM_CHAT_ID`
Secret: `8724989560`
Klik "Add secret"
Setelah selesai, kamu akan lihat 2 secrets di sana. Token tidak bisa dilihat lagi setelah disimpan — aman.
---
STEP 5 — Test Manual (sebelum tunggu jadwal)
Klik tab "Actions" di halaman repo
Di sidebar kiri, klik "Altcoin Screener Bot"
Klik tombol "Run workflow" (kanan atas)
Klik "Run workflow" (hijau)
Tunggu ~5-10 menit
Kalau berhasil → ada centang hijau
Cek Telegram kamu — harusnya sudah ada pesan masuk!
---
STEP 6 — Verifikasi Jadwal Otomatis
Setelah step 5 berhasil, screener akan jalan otomatis:
07.00 WIB
11.00 WIB
15.00 WIB
19.00 WIB
23.00 WIB
03.00 WIB
Tiap run = 1 chart + 1 pesan teks ke Telegram kamu.
---
TROUBLESHOOTING
Actions tidak muncul di tab Actions:
→ Pastikan file `.github/workflows/screener.yml` sudah terupload dengan benar
Run gagal (merah):
→ Klik run yang gagal → klik "screener" → baca error log
→ Paling sering: secret belum diisi atau nama secret salah
Telegram tidak menerima pesan:
→ Pastikan kamu sudah `/start` bot `@quantyscreener_bot` di Telegram
→ Cek Chat ID sudah benar (8724989560)
Koin tidak ditemukan:
→ Cek apakah koin tersedia di Binance Futures (bukan spot)
→ Hapus koin dari list SYMBOLS di main.py
---
UBAH JADWAL (opsional)
Edit file `screener.yml`, bagian cron:
```yaml
# Tiap 4 jam (default)
- cron: '0 0,4,8,12,16,20 * * *'

# Tiap 8 jam
- cron: '0 0,8,16 * * *'

# Sekali sehari jam 08.00 WIB (01.00 UTC)
- cron: '0 1 * * *'
```
---
TAMBAH / HAPUS KOIN
Edit bagian `SYMBOLS` di `main.py`:
```python
SYMBOLS = [
    'SOLUSDT',
    'BTCUSDT',
    # tambah di sini
    # hapus yang tidak perlu
]
```
Koin harus ada di Binance Futures (bukan spot).
Cek di: https://www.binance.com/en/futures
---
BIAYA
GitHub Actions gratis untuk repo private:
2000 menit/bulan untuk akun free
Tiap run ~5-10 menit
6 run/hari × 30 hari = 180 run × 10 menit = 1800 menit/bulan
Masih dalam limit gratis ✓
---
Selesai! Bot kamu akan jalan otomatis tiap 4 jam
dan kirim update langsung ke Telegram.