FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set default environment
ENV e=prod
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

# Use port 8000 for prod, 5000 for others
EXPOSE 8000

# Dynamic port based on environment
CMD ["sh", "-c", "if [ \"$e\" = \"prod\" ]; then gunicorn -k eventlet -w 1 app:app --bind 0.0.0.0:8000; else gunicorn -k eventlet -w 1 app:app --bind 0.0.0.0:5000; fi"]