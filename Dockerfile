# Small official Python image
FROM python:3.12-slim

# Don't write .pyc files; print logs straight away
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/tracker.db

WORKDIR /app

# Install dependencies first, so Docker can cache this layer between code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app ./app
COPY static ./static
COPY seed.py .

# Run as a normal user (not root); /data holds the SQLite file
RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
