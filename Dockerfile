FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 user
USER user

COPY --chown=user:user . .

RUN chmod +x run.sh start.sh

EXPOSE 8501 8000

CMD ["./run.sh"]
