<div align="center">
  <img src="docs/assets/starka_banner.png" alt="STARKA AI Banner" width="100%" />

  <h1>STARKA AI</h1>
  <p><strong>Telegram AI Chatbot · 9Router-powered · Python</strong></p>
  <p>Chatbot AI berbasis Telegram dengan integrasi model AI melalui 9Router.</p>
</div>

---

## Tentang Proyek

**STARKA AI** adalah aplikasi chatbot berbasis Telegram yang dikembangkan menggunakan Python. Aplikasi ini memungkinkan pengguna mengirimkan pesan melalui Telegram dan menerima respons yang dihasilkan oleh model AI.

STARKA AI menggunakan 9Router sebagai gateway untuk menghubungkan aplikasi dengan model AI melalui API yang kompatibel dengan OpenAI.

## Fitur Utama

- **Telegram Integration** — menerima pesan dan mengirimkan respons melalui Telegram.
- **AI Model Integration** — menghubungkan chatbot dengan model AI melalui 9Router.
- **Automatic Model Routing** — memilih model berdasarkan konfigurasi dan jenis pesan jika fitur routing tersedia pada implementasi.
- **Conversation History** — mempertahankan konteks percakapan selama sesi sesuai mekanisme memori yang diterapkan.
- **Command Handling** — menyediakan perintah bot seperti `/start`, `/model`, `/mode`, dan `/reset` sesuai implementasi.

## Alur Sistem

```text
Pengguna
   |
   v
Telegram
   |
   v
Telegram Bot API
   |
   v
STARKA AI
(bot.py / Python)
   |
   v
Pemrosesan Pesan
   |
   v
Pemilihan Model AI
   |
   v
9Router API
localhost:20128/v1
   |
   v
Provider / Model AI
   |
   v
Respons AI
   |
   v
Telegram Bot API
   |
   v
Pengguna menerima respons
```

9Router berfungsi sebagai gateway lokal untuk meneruskan permintaan dari STARKA AI ke model AI yang telah dikonfigurasi. Proses pemilihan model mengikuti aturan routing yang diterapkan dalam aplikasi.

## Teknologi

| Teknologi             | Fungsi                                        |
| --------------------- | --------------------------------------------- |
| Python                | Bahasa pemrograman utama                      |
| python-telegram-bot   | Integrasi dengan Telegram Bot API             |
| OpenAI-compatible API | Antarmuka komunikasi dengan model AI          |
| 9Router               | Gateway untuk mengakses provider dan model AI |
| python-dotenv         | Membaca konfigurasi dari file environment     |
| Git dan GitHub        | Pengelolaan kode sumber dan kolaborasi        |

## Requirement

Sebelum menjalankan aplikasi, siapkan:

- Python 3.11+ atau versi yang sesuai dengan dependensi.
- Git.
- Akun Telegram.
- Token bot Telegram dari [@BotFather](https://t.me/BotFather).
- 9Router yang sudah terpasang dan berjalan.
- Provider AI dan model yang sudah dikonfigurasi di 9Router.
- Koneksi internet untuk komunikasi dengan Telegram dan provider AI.

Node.js dan npm diperlukan jika metode instalasi 9Router yang digunakan membutuhkannya.

## Instalasi

### 1. Clone Repository

```bash
git clone https://github.com/anindyapbsr/starka-ai.git
cd starka-ai
```

### 2. Buat Virtual Environment

Untuk Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Instal Dependensi

Jika repository menyediakan `requirements.txt`, jalankan:

```bash
pip install -r requirements.txt
```

### 4. Jalankan 9Router

Pasang dan jalankan 9Router sesuai dokumentasi instalasinya. Konfigurasikan provider dan model AI yang ingin digunakan.

Endpoint API lokal yang digunakan oleh aplikasi:

```text
http://localhost:20128/v1
```

Dashboard, jika tersedia pada instalasi:

```text
http://localhost:20128/dashboard
```

Pastikan alamat endpoint sesuai dengan konfigurasi di `bot.py`.

## Konfigurasi

Buat file `.env` di direktori utama repository. Isi variabel sesuai dengan nama konfigurasi yang dibaca oleh aplikasi.

Contoh format:

```env
TELEGRAM_BOT_TOKEN=isi_token_bot_telegram
OPENAI_API_KEY=isi_api_key_9router
OPENAI_BASE_URL=http://localhost:20128/v1
```

**Penting:** nama variabel pada contoh di atas harus disesuaikan dengan implementasi aktual. Jangan mengunggah `.env`, token Telegram, atau API key asli ke GitHub.

Untuk dokumentasi konfigurasi, gunakan `.env.example` yang hanya berisi nama variabel dan contoh nilai tanpa kredensial asli.

## Menjalankan Aplikasi

1. Aktifkan virtual environment.
2. Pastikan 9Router berjalan.
3. Periksa konfigurasi `.env`.
4. Jalankan chatbot:

```bash
python bot.py
```

5. Buka Telegram dan kirim pesan ke bot yang telah dikonfigurasi.

Pastikan komputer yang menjalankan chatbot tetap aktif dan terhubung ke internet selama bot digunakan. Karena 9Router berjalan secara lokal, gateway tersebut juga harus tetap aktif.

## Struktur Repository

```text
starka-ai/
├── bot.py
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
└── .venv/
```

`.venv/` merupakan lingkungan Python lokal dan tidak perlu diunggah ke GitHub. Struktur ini dapat diperluas jika aplikasi nantinya memiliki modul, dokumentasi tambahan, atau pengujian otomatis.

## Keamanan

- Jangan mengunggah file `.env` ke repository.
- Jangan menuliskan token Telegram atau API key langsung di kode.
- Jangan membagikan kredensial melalui Issues, Pull Requests, atau README.
- Jika kredensial terpublikasi, cabut dan ganti kredensial tersebut.
- Batasi akses ke endpoint lokal dan jangan mengeksposnya ke jaringan publik tanpa pengamanan yang memadai.

## Kolaborasi dan Pengembangan

Pengelolaan kode dilakukan melalui GitHub. Issues digunakan untuk mencatat pekerjaan dan masalah, sedangkan GitHub Projects digunakan untuk memantau progres pengembangan.

Untuk menjaga kualitas kode, anggota tim dapat bekerja pada branch masing-masing dan mengajukan Pull Request sebelum perubahan digabungkan ke branch utama.

## Lisensi

Lisensi proyek belum ditentukan.

---

<div align="center">
  <strong>STARKA AI</strong>
  <p>Telegram AI Chatbot powered by 9Router</p>
</div>
