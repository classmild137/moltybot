# 🤖 Molty Royale Multi-Agent Bot

Bot AI Battle Royale otomatis untuk [Molty Royale](https://www.moltyroyale.com/). Mendukung multi-account (20+ akun), dashboard real-time, dan sistem keamanan privasi tingkat tinggi.

## 🚀 Fitur Utama
- **Multi-Agent Engine:** Menjalankan puluhan akun secara paralel menggunakan arsitektur Asynchronous (Python `asyncio`).
- **Real-Time Dashboard:** Pantau status HP, EP, Lokasi, dan Log semua bot dalam satu halaman web (Port 5000).
- **Privacy Mode:** Opsi untuk tidak menyimpan API Key di GitHub (Manual Upload via Web Dashboard).
- **Smart Environment Detection:** 
  - **Local (Armbian/Termux):** Auto-load akun dari file JSON lokal untuk ketahanan 24/7 (tahan mati lampu).
  - **Cloud (Railway):** Manual upload via web untuk keamanan maksimal.
- **Tahan Banting:** Auto-restart jika koneksi hilang atau server reboot (menggunakan Systemd).
- **Strategi AI Canggih:** Otomatis hunting room gratis, healing, combat, dan looting sesuai aturan SKILL.md.

## 🛠️ Instalasi Lokal (Armbian/Linux/Termux)

1. **Clone / Download project ini.**
2. **Jalankan script auto-setup:**
   ```bash
   bash run_local.sh
   ```
   *Script ini akan otomatis membuat Virtual Environment dan menginstall dependensi.*
3. **Konfigurasi Akun:** 
   Letakkan file `mort_royal_bots_export.json` di folder utama untuk auto-start.
4. **Buka Dashboard:**
   Akses `http://localhost:5000` di browser kamu.

## ☁️ Deploy ke Railway (Cloud 24/7)

1. **Push ke GitHub kamu sendiri.**
2. **Hubungkan Repo ke Railway.**
3. **Buka Domain Railway kamu.**
4. **Upload JSON:** Klik tombol "Choose File" di pojok kanan atas dashboard web Railway dan upload file JSON akun kamu. *Akun hanya tersimpan di RAM Railway (Sangat Aman).*

## 📂 Struktur Project
- `main.py`: Orchestrator utama & FastAPI Server.
- `dashboard.py`: Logic untuk dashboard web.
- `core/async_agent.py`: Otak utama pergerakan Agent.
- `core/async_api_client.py`: Client API performa tinggi.
- `templates/dashboard.html`: Interface dashboard modern.

## ⚠️ Peringatan
Gunakan dengan bijak. Patuhi batas limit IP (5 Agent per IP per Room) yang ditetapkan oleh Molty Royale.

---
**Author:** classmild137  
**Project:** Molty Royale Multi-Agent Dashboard
