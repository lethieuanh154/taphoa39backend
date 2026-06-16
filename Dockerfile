FROM python:3.11-slim

# Tạo biến môi trường
ENV e=local

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["gunicorn", "app:app", "--bind=0.0.0.0:5000", "--timeout=600", "--workers=1", "--threads=8"]
