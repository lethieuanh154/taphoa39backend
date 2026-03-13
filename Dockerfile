FROM python:3.11-slim

# Tạo biến môi trường
ENV e=local

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["python", "-m", "app"]
