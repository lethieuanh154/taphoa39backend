FROM python:3.11-slim

# Tạo biến môi trường
ENV e=local

# BAT BUOC: gunicorn buffer stdout -> toan bo `print()` (log [KiotVietSync], [CacheRefresh],
# [AUTH], [reserve]...) khong bao gio hien ra `docker logs`. Sync KiotViet that bai se im
# lang tuyet doi neu thieu dong nay.
ENV PYTHONUNBUFFERED=1

# Chu ky tu dong keo ton kho KiotViet -> Firestore (phut). Dat 0 de TAT khi co su co.
ENV KIOTVIET_AUTO_SYNC_MINUTES=15

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

# --workers=1 là BẮT BUỘC: SocketIO khởi tạo không có message_queue (app.py), state socket
# nằm trong RAM từng worker. >1 worker → broadcast tồn kho chỉ tới client cùng worker,
# máy này nhận update máy kia không. Muốn scale thì thêm Redis message_queue trước.
CMD ["gunicorn", "app:app", "--bind=0.0.0.0:5000", "--timeout=600", "--workers=1", "--threads=32"]
