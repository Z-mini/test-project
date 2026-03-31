FROM ubuntu:2.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository universe && \
    apt-get update && \
    apt-get install -y \
    python3-pip \
    libreoffice \
    libreoffice-nogui \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-cjk \
    poppler-utils && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python3", "app.py"]
