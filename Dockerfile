# Use official Python runtime as base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings

# Set work directory
WORKDIR /app

# Install system dependencies (including Redis, git, curl, openssl)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        redis-server \
        git \
        curl \
        openssl \
        && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Create necessary directories
RUN mkdir -p logs

# Create database and set permissions
RUN touch db.sqlite3 && chmod 664 db.sqlite3

# Run migrations
RUN python manage.py migrate

# Create superuser (password will be 'admin' for simplicity in Docker)
RUN echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@example.com', 'admin')" | python manage.py shell

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port 8080
EXPOSE 8080

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
echo "Starting Redis server..."\n\
redis-server --daemonize yes\n\
echo "Starting Celery worker in background..."\n\
celery -A config worker --loglevel=info &\n\
echo "Starting Celery beat in background..."\n\
celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler &\n\
echo "Starting Gunicorn server on port 8080..."\n\
exec gunicorn --bind 0.0.0.0:8080 --timeout 600 --log-level debug config.wsgi:application\n\
' > /app/start.sh && chmod +x /app/start.sh

# Run the startup script
CMD ["/app/start.sh"]
