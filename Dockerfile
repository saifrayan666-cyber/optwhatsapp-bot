FROM python:3.10-slim

WORKDIR /app

# প্রয়োজনীয় প্যাকেজ ইনস্টল
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ক্রোমিয়াম ইনস্টল
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# পাইথন ডিপেন্ডেন্সি
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# প্লে রাইট ব্রাউজার ইনস্টল
RUN playwright install chromium
RUN playwright install-deps

# কোড কপি
COPY . .

# পোর্ট
EXPOSE 8080

# রান
CMD ["python", "main.py"]
