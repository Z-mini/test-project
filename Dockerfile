FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python3", "app.py"]
