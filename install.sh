#!/bin/bash

set -e

REPO_URL="https://github.com/exiledfolks/folks_scanner.git"
PROJECT_DIR="folks_project"
VENV_DIR="folks_venv"
RANDOM_PORT=$(( RANDOM % 10000 + 30000 ))
DJANGO_SUPERUSER="admin"
DJANGO_SUPERPASS=$(openssl rand -hex 12)

echo "🛠️ Installing system packages..."
sudo apt update || true
sudo apt install -y python3.12 python3.12-venv python3.12-distutils python3-pip redis-server supervisor git curl

# Ensure ensurepip exists
if ! python3.12 -m ensurepip --version >/dev/null 2>&1; then
    echo "⚙ Installing ensurepip for Python 3.12..."
    curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.12
fi

# Check and remove old project folder
if [ -d "$PROJECT_DIR" ]; then
    echo "⚠ WARNING: Directory $PROJECT_DIR already exists and will be DELETED!"
    read -p "Type 'yes' to confirm deletion: " confirm
    if [ "$confirm" != "yes" ]; then
        echo "❌ Aborted by user."
        exit 1
    fi
    echo "🗑 Removing existing $PROJECT_DIR..."
    rm -rf $PROJECT_DIR
fi

echo "🚀 Cloning project..."
git clone $REPO_URL $PROJECT_DIR
cd $PROJECT_DIR || exit 1

echo "🐍 Setting up virtualenv..."
python3.12 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

echo "🛠 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🔑 Please enter Telegram API ID (or type 'no' to skip):"
read TELEGRAM_API_ID

if [ "$TELEGRAM_API_ID" != "no" ]; then
    echo "🔑 Please enter Telegram API HASH:"
    read TELEGRAM_API_HASH
else
    TELEGRAM_API_ID=""
    TELEGRAM_API_HASH=""
fi

echo "🔧 Creating .env file..."
cat > .env <<EOF
DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)
ALLOWED_HOSTS=localhost
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
XRAY_PATH=./xray
CELERY_BROKER_URL=redis://localhost:6379/0
EOF

echo "📦 Running migrations..."
python manage.py migrate

echo "👤 Creating superuser..."
python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER --email admin@example.com
python manage.py shell -c "
from django.contrib.auth import get_user_model; \
u = get_user_model().objects.get(username='$DJANGO_SUPERUSER'); \
u.set_password('$DJANGO_SUPERPASS'); u.save()"

echo "📂 Collecting static files..."
python manage.py collectstatic --noinput

echo "📂 Creating logs directory..."
mkdir -p logs

echo "⚙ Configuring Supervisor..."
SUPERVISOR_CONF="/etc/supervisor/conf.d/folks_scanner.conf"
sudo bash -c "cat > $SUPERVISOR_CONF" <<EOF
[program:folks_web]
command=$(pwd)/$VENV_DIR/bin/gunicorn config.wsgi:application --bind 0.0.0.0:$RANDOM_PORT
directory=$(pwd)
autostart=true
autorestart=true
stdout_logfile=$(pwd)/logs/web.log
stderr_logfile=$(pwd)/logs/web.err

[program:folks_celery]
command=$(pwd)/$VENV_DIR/bin/celery -A config worker --loglevel=info
directory=$(pwd)
autostart=true
autorestart=true
stdout_logfile=$(pwd)/logs/celery.log
stderr_logfile=$(pwd)/logs/celery.err

[program:folks_celery_beat]
command=$(pwd)/$VENV_DIR/bin/celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
directory=$(pwd)
autostart=true
autorestart=true
stdout_logfile=$(pwd)/logs/beat.log
stderr_logfile=$(pwd)/logs/beat.err
EOF

echo "🔄 Reloading Supervisor..."
sudo supervisorctl reread
sudo supervisorctl update

echo ""
echo "✅ Deployment complete!"
echo "🌐 Admin panel: http://<server_ip>:$RANDOM_PORT/admin/"
echo "👤 Admin username: $DJANGO_SUPERUSER"
echo "🔑 Admin password: $DJANGO_SUPERPASS"
