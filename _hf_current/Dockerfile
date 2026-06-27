FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire application
COPY . .

# HF Spaces port
EXPOSE 7860

# Run app (Flask + Telegram bot dual-mode)
CMD ["python", "app.py"]
