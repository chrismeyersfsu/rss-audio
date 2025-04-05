FROM python:3.9-slim

WORKDIR /app

ENV PORT=9393

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
