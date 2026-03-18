# Gunakan Python Image
FROM python:3.10-slim

# Install Tor dan dependensi sistem
RUN apt-get update && apt-get install -y tor socket procps && rm -rf /var/lib/apt/lists/*

# Setup working directory
WORKDIR /app

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh project
COPY . .

# Buat script untuk menjalankan 11 port Tor secara otomatis
RUN echo '#!/bin/bash\n\
for i in {9050..9060}; do\n\
  echo "SocksPort 0.0.0.0:$i" >> /etc/tor/torrc\n\
done\n\
tor -f /etc/tor/torrc &\n\
sleep 15\n\
python main.py' > entrypoint.sh && chmod +x entrypoint.sh

# Jalankan via entrypoint
CMD ["./entrypoint.sh"]
