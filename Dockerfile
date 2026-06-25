FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY app.py .

# HF Spaces chạy port 7860
EXPOSE 7860

# Start với gunicorn
CMD ["gunicorn", \
     "--workers", "4", \
     "--threads", "2", \
     "--bind", "0.0.0.0:7860", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "app:app"]
