# Gunakan Python Image
FROM python:3.10-slim

# Install Tor dan dependensi sistem
RUN apt-get update && apt-get install -y tor curl procps && rm -rf /var/lib/apt/lists/*

# Setup working directory
WORKDIR /app

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh project
COPY . .

# Konfigurasi Tor: 11 port dengan ExitNodes diacak agar tidak gampang kena blokir
RUN echo 'Log notice stdout\n\
AvoidDiskWrites 1\n' > /etc/tor/torrc && \
for i in {9050..9060}; do \
  echo "SocksPort 127.0.0.1:$i" >> /etc/tor/torrc; \
done

# Script start: Jalankan Tor, tunggu sampai konek, baru jalankan Bot
RUN echo '#!/bin/bash\n\
tor -f /etc/tor/torrc &\n\
echo "Waiting for Tor to bootstrap..."\n\
for i in {1..30}; do\n\
  if curl --socks5 localhost:9050 -s https://check.torproject.org/ | grep -q "Congratulations"; then\n\
    echo "Tor is ONLINE!"\n\
    break\n\
  fi\n\
  sleep 2\n\
done\n\
python main.py' > entrypoint.sh && chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
