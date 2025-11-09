# Layanan Proxy OpenAI

![Lisensi: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python: 3.9-3.12](https://img.shields.io/badge/python-3.9--3.12-green.svg)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688.svg)

Layanan proxy kompatibel OpenAI API berbasis FastAPI dengan arsitektur multi-penyedia, mendukung berbagai model AI seperti Z.AI (GLM-4.5/4.6 Series), K2Think, dan LongCat.

## ✨ Fitur Utama

- 🔌 **Kompatibel OpenAI API** - Integrasi langsung dengan klien OpenAI yang ada
- 🏗️ **Arsitektur Multi-Penyedia** - Antarmuka seragam untuk Z.AI, K2Think, LongCat
- 🧬 **Manajemen Database** - SQLite + Dasbor Web untuk manajemen Token
- 🚀 **Responsa Streaming** - Output streaming SSE real-time berperforma tinggi
- 🧠 **Mode Berpikir** - Mendukung proses inferensi model Thinking
- 🐳 **Deployment Kontainer** - Satu klik deployment dengan Docker/Docker Compose
- 🔄 **Pool Token** - Rotasi cerdas, pemulihan kesalahan, pemeriksaan kesehatan
- 📊 **Dasbor Administrasi** - Monitoring real-time, manajemen konfigurasi
- 🔐 **Otentikasi Keamanan** - Akses dasbor administrasi dilindungi kata sandi

Terima kasih atas umpan balik semua yang mendorong perbaikan proyek!

## 🚀 Memulai Cepat

### Persyaratan Lingkungan

- Python 3.9-3.12
- pip atau uv (disarankan)

### Jalankan Lokal

```bash
# 1. Clone proyek
git clone https://github.com/ZyphrZero/z.ai2api_python.git
cd z.ai2api_python

# 2. Instal dependensi (menggunakan uv disarankan)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# atau menggunakan pip
pip install -r requirements.txt

# 3. Konfigurasi variabel lingkungan
cp .env.example .env
# Edit file .env, atur AUTH_TOKEN dan konfigurasi lainnya

# 4. Jalankan layanan
uv run python main.py  # atau python main.py
```

**Saat pertama kali dijalankan akan secara otomatis menginisialisasi database**, akses alamat berikut:
- Dokumentasi API: http://localhost:8080/docs
- Dasbor administrasi: http://localhost:8080/admin (**membutuhkan login**)
- Manajemen Token: http://localhost:8080/admin/tokens

> ⚠️ **Penting**:
> - Jaga kerahasiaan `AUTH_TOKEN`, jangan berikan kepada orang lain
> - Kata sandi dasbor administrasi default adalah `admin123`, **segera ubah setelah penggunaan pertama**

### Deployment Docker

Tarik image dari Docker Hub:

```bash
# Tarik image terbaru
docker pull zyphrzero/z-ai2api-python:latest

# Jalankan cepat (buat direktori data)
mkdir -p data logs

# Jalankan kontainer
docker run -d \
  --name z-ai-api-server \
  -p 8080:8080 \
  -e ADMIN_PASSWORD=admin123 \
  -e AUTH_TOKEN=sk-your-api-key \
  -e ANONYMOUS_MODE=true \
  -e DB_PATH=/app/data/tokens.db \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  zyphrzero/z-ai2api-python:latest
```

Jalankan layanan:

```bash
docker compose up -d
```

#### Cara Kedua: Build Lokal

```bash
# Masuk ke direktori deployment
cd deploy

# Jalankan layanan (akan otomatis build image)
docker compose up -d

# Lihat log
docker compose logs -f api-server
```

#### Persistensi Data

Kontainer menggunakan mapping volume untuk persistensi data otomatis:

```
data/                  # Direktori penyimpanan file database
├── tokens.db          # Database SQLite (dibuat otomatis)
logs/                  # Direktori penyimpanan file log
```

Data tetap ada setelah restart atau rebuild kontainer, tidak perlu khawatir kehilangan data.

> 📖 **Dokumentasi Lengkap**: [Panduan Deployment Docker](deploy/README_DOCKER.md)

## 📖 Model yang Didukung

### Penyedia Z.AI (Seri GLM)

| Model | ID Asal | Fitur |
|------|---------|------|
| `GLM-4.5` | 0727-360B-API | Model standar, percakapan umum |
| `GLM-4.5-Thinking` | 0727-360B-API | Model berpikir, tampilkan proses inferensi |
| `GLM-4.5-Search` | 0727-360B-API | Model pencarian, koneksi internet real-time |
| `GLM-4.5-Air` | 0727-106B-API | Model ringan, respons cepat |
| `GLM-4.5V` | glm-4.5v | Model multimodal, dukungan pemahaman gambar |
| `GLM-4.6` | GLM-4-6-API-V1 | Model standar versi baru, konteks 200K |
| `GLM-4.6-Thinking` | GLM-4-6-API-V1 | Model berpikir versi baru, inferensi ditingkatkan |
| `GLM-4.6-Search` | GLM-4-6-API-V1 | Model pencarian versi baru, kemampuan koneksi ditingkatkan |
| `GLM-4.6-advanced-search` | GLM-4-6-API-V1 | Model pencarian lanjutan, penelitian mendalam |

### Penyedia K2Think

| Model | Fitur |
|------|------|
| `MBZUAI-IFM/K2-Think` | Model inferensi kualitas tinggi |

### Penyedia LongCat

| Model | Fitur |
|------|------|
| `LongCat-Flash` | Respons cepat |
| `LongCat` | Model standar |
| `LongCat-Search` | Peningkatan pencarian |

## ⚙️ Penjelasan Konfigurasi

### Variabel Lingkungan Utama

| Nama Variabel | Nilai Default | Penjelasan |
|--------|--------|------|
| `AUTH_TOKEN` | `sk-your-api-key` | Kunci akses klien (wajib) |
| `ADMIN_PASSWORD` | `admin123` | Kata sandi login dasbor administrasi (**sangat disarankan untuk diubah**) |
| `LISTEN_PORT` | `8080` | Port layanan |
| `DEBUG_LOGGING` | `false` | Log debug (dukung hot reload) |
| `ANONYMOUS_MODE` | `true` | Mode anonim Z.AI |
| `TOOL_SUPPORT` | `true` | Saklar Function Call |
| `SKIP_AUTH_TOKEN` | `false` | Lewati otentikasi (hanya untuk pengembangan) |
| `DB_PATH` | `tokens.db` | Jalur file database (Docker: `/app/data/tokens.db`) |

### Konfigurasi Token

| Nama Variabel | Penjelasan |
|--------|------|
| `LONGCAT_TOKEN` | Token otentikasi LongCat (opsional) |
| `TOKEN_FAILURE_THRESHOLD` | Ambang kegagalan Token (default 3) |
| `TOKEN_RECOVERY_TIMEOUT` | Timeout pemulihan Token (default 1800 detik) |

> 💡 Konfigurasi lengkap lihat [.env.example](.env.example) atau [deploy/.env.example](deploy/.env.example)

## 🔐 Login Dasbor Administrasi

### Login Pertama Kali

1. Setelah menjalankan layanan, akses: http://localhost:8080/admin
2. Akan otomatis dialihkan ke halaman login
3. Masukkan kata sandi administrasi (default: `admin123`)
4. Login berhasil masuk ke dasbor

### Ubah Kata Sandi

Ubah `ADMIN_PASSWORD` di file `.env`:

```bash
# Gunakan kata sandi kuat (disarankan 12+ karakter)
ADMIN_PASSWORD=Your_Secure_Password_2025!
```

Restart layanan agar berlaku.

### Fitur Keamanan

- ✅ **Manajemen Session**: Session berbasis Cookie yang aman
- ✅ **Kedaluwarsa Otomatis**: Login kedaluwarsa setelah 24 jam
- ✅ **HttpOnly Cookie**: Cegah serangan XSS
- ✅ **Perlindungan SameSite**: Cegah serangan CSRF
- ✅ **Token Acak**: Gunakan angka acak kriptografi yang aman

> 💡 Dokumentasi lengkap: [Panduan Penggunaan Fitur Login Dasbor Administrasi](manajemen_login_dasbor_admin.md)

## 🔄 Manajemen Token

### Metode Database (disarankan)

Proyek menggunakan database SQLite untuk mengelola Token secara terpadu, pertama kali dijalankan akan otomatis inisialisasi:

```bash
# Pertama kali dijalankan otomatis buat tokens.db
python main.py

# Akses dasbor web administrasi
http://localhost:8080/admin
```

### Fungsi Dasbor Administrasi

- ✅ **Perlindungan Kata Sandi** - Otentikasi login yang aman
- ✅ Tambah/Hapus/Edit Token
- ✅ Impor/ekspor massal
- ✅ Aktifkan/nonaktifkan Token
- ✅ Deteksi validitas Token
- ✅ Dukungan multi-penyedia (Z.AI/K2Think/LongCat)

### Mekanisme Pool Token

- **Load Balancing**: Rotasi beberapa Token untuk distribusi permintaan
- **Fault Tolerance Otomatis**: Otomatis beralih saat Token gagal
- **Pemulihan Otomatis**: Ulang Token gagal setelah timeout
- **Dedupe Cerdas**: Otomatis deteksi Token duplikat
- **Fallback**: Otentikasi gagal otomatis downgrade ke mode anonim

## ❓ Pertanyaan Umum

### Q: Bagaimana cara mendapatkan AUTH_TOKEN?
A: `AUTH_TOKEN` adalah kunci API kustom untuk mengakses layanan ini, perlu dikonfigurasi di file `.env` atau `docker-compose.yml`, pastikan klien dan server konsisten.

### Q: Apa itu mode anonim?
A: Mode anonim menggunakan Token sementara untuk mengakses Z.AI, hindari berbagi riwayat percakapan, lindungi privasi. Atur `ANONYMOUS_MODE=true` untuk mengaktifkan.

### Q: Bagaimana cara mengelola Token?
A: Akses dasbor web administrasi http://localhost:8080/admin/tokens (perlu login dulu) untuk tambah/hapus/edit Token, dukung impor/ekspor massal.

### Q: Lupa kata sandi dasbor administrasi bagaimana?
A: Di file `.env` atau `docker-compose.yml` ubah `ADMIN_PASSWORD` menjadi kata sandi baru, lalu restart layanan.

### Q: Docker deployment gagal inisialisasi database?
A: Pesan kesalahan `unable to open database file` biasanya masalah izin. Solusi:
```bash
cd deploy
mkdir -p ./data ./logs
chmod 755 ./data ./logs
docker compose down && docker compose up -d --build
```
Lihat [Panduan Deployment Docker](deploy/README_DOCKER.md#troubleshooting) untuk detail

### Q: Bagaimana menonaktifkan login dasbor administrasi?
A: Versi saat ini belum mendukung menonaktifkan fungsi login. Jika diperlukan, hapus secara manual `dependencies=[Depends(require_auth)]` dari rute.

## 🔑 Dapatkan Token

### Token Z.AI

1. Akses [Situs Web Z.AI](https://chat.z.ai) dan login
2. Tekan F12 buka alat pengembang
3. Masuk ke Application → Local Storage → Cookies
4. Salin nilai `token`

> ⚠️ Fungsi multimodal membutuhkan Token non-anonim

### Token LongCat

1. Akses [Situs Web LongCat](https://longcat.chat/) dan login akun Meituan
2. Tekan F12 buka alat pengembang
3. Masuk ke "Application" -> "Local Storage" -> Daftar "Cookie" cari nilai bernama `passport_token_key`
4. Salin nilai `passport_token_key`

## 🛠️ Stack Teknologi

| Komponen | Teknologi | Versi | Penjelasan |
|------|------|------|------|
| Framework Web | [FastAPI](https://fastapi.tiangolo.com/) | 0.116.1 | Framework asinkron berperformasi tinggi |
| Server ASGI | [Granian](https://github.com/emmett-framework/granian) | 2.5.2 | Server berperformasi tinggi Rust |
| Klien HTTP | [HTTPX](https://www.python-httpx.org/) | 0.28.1 | Klien HTTP asinkron |
| Validasi Data | [Pydantic](https://pydantic.dev/) | 2.11.7 | Validasi tipe aman |
| Database | SQLite (aiosqlite) | 0.20.0 | Penyimpanan Token |
| Mesin Template | Jinja2 | 3.1.4 | Template dasbor web |
| Sistem Log | [Loguru](https://loguru.readthedocs.io/) | 0.7.3 | Log struktural |

## 🏗️ Arsitektur Sistem

```
┌─────────────┐      ┌────────────────────────────────┐      ┌──────────────┐
│   OpenAI    │      │      Server FastAPI            │      │   API Z.AI   │
│   Klien     │─────▶│                                │─────▶│   (GLM-4.x)  │
└─────────────┘      │  ┌──────────────────────────┐  │      └──────────────┘
                     │  │   Router Penyedia        │  │
                     │  │  ┌────────┬────────────┐ │  │      ┌──────────────┐
                     │  │  │ Z.AI   │ K2Think    │ │  │      │  API K2Think │
                     │  │  │Penyedia│ Penyedia   │ │  │─────▶│              │
                     │  │  └────────┴────────────┘ │  │      └──────────────┘
                     │  │  ┌────────────┐          │  │
                     │  │  │ LongCat    │          │  │      ┌──────────────┐
                     │  │  │ Penyedia   │          │  │      │ API LongCat  │
                     │  │  └────────────┘          │  │─────▶│              │
                     │  └──────────────────────────┘  │      └──────────────┘
                     │                                │
                     │  ┌──────────────────────────┐  │
                     │  │   Dasbor Admin Web       │  │
                     │  │   (Token/Statistik/Monitor)│  │
                     │  └──────────────────────────┘  │
                     └────────────────────────────────┘
                               ↕
                          ┌─────────┐
                          │Database │
                          │SQLite   │
                          └─────────┘
```

## 🤝 Panduan Kontribusi

Selamat datang untuk mengirimkan Issue dan Pull Request! Pastikan kode sesuai dengan standar PEP 8.

## ⭐ Riwayat Star

[![Grafik Riwayat Star](https://api.star-history.com/svg?repos=ZyphrZero/z.ai2api_python&type=Date)](https://star-history.com/#ZyphrZero/z.ai2api_python&Date)

## 📄 Lisensi

Proyek ini menggunakan lisensi MIT - lihat file [LICENSE](LICENSE) untuk detail.

## ⚠️ Penyangkalan

- Proyek ini tidak berafiliasi dengan penyedia AI resmi seperti Z.AI, K2Think, LongCat, dll.
- Pastikan untuk mematuhi ketentuan layanan masing-masing penyedia sebelum menggunakan
- Jangan gunakan untuk tujuan komersial atau skenario yang melanggar ketentuan penggunaan
- Proyek ini hanya untuk pembelajaran dan penelitian
- Pengguna harus menanggung risiko penggunaan sendiri

---

<div align="center">
Dibuat dengan ❤️ oleh komunitas
</div>