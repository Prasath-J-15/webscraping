FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installs the Chromium binary plus every OS-level library it needs to run
# headless on Debian — the same role `playwright install chromium` plays on
# a bare host, just with --with-deps covering the apt packages too.
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 9000

# core/config.py already defaults to headless=false off Windows, so no
# PLAYWRIGHT_HEADLESS override is needed here — this container just is
# "off Windows".
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
