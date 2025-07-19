#!/bin/bash

set -e

REPO_URL="https://github.com/exiledfolks/folks_scanner.git"
PROJECT_DIR="folks_project"
VENV_DIR="folks_venv"
RANDOM_PORT=$(( RANDOM % 10000 + 30000 ))
DJANGO_SUPERUSER="admin"
DJANGO_SUPERPASS=$(openssl rand -hex 12)

echo "🧹 Cleaning APT sources..."
sudo rm -f /etc/apt/sources.list.d/android-studio.list
sudo rm -f /etc/apt/sources.list.d/google-chrome.list

echo "🔄 Updating system..."
sudo apt update || true
sudo apt install -y python3.12 python3.12-full python3.12-venv redis-server git curl || true

# Stop redis if not running
sudo systemctl enable --now redis-server

# Check and remove old project folder
if [ -d "$PROJECT_DIR" ]; then
    echo "⚠️ Directory $PROJECT_DIR exists. Removing..."
    rm -rf $PROJECT_DIR
fi

echo "🚀 Cloning project..."
git clone $REPO_URL $PROJECT_DIR
cd $PROJECT_DIR

echo "🐍 Creating virtualenv..."
python3.12 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

echo "⬆️ Upgrading pip + installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🔑 Enter Telegram API ID (or type 'no' to skip):"
read TELEGRAM_API_ID

if [ "$TELEGRAM_API_ID" != "no" ]; then
    echo "🔑 Enter Telegram API HASH:"
    read TELEGRAM_API_HASH
else
    TELEGRAM_API_ID=""
    TELEGRAM_API_HASH=""
fi

echo "⚙️ Creating .env file..."
cat > .env <<EOF
DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)
ALLOWED_HOSTS=localhost
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
XRAY_PATH=./xray
CELERY_BROKER_URL=redis://localhost:6379/0
EOF

echo "🔑 Fixing permissions..."
touch db.sqlite3
chmod 664 db.sqlite3
chown $USER:$USER db.sqlite3
chmod -R u+rwX,go+rX .

echo "📦 Running migrations..."
python manage.py migrate

echo "👤 Creating superuser..."
python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER --email admin@example.com
python manage.py shell -c "
from django.contrib.auth import get_user_model; \
u = get_user_model().objects.get(username='$DJANGO_SUPERUSER'); \
u.set_password('$DJANGO_SUPERPASS'); u.save()"

echo "📦 Collecting static..."
python manage.py collectstatic --noinput

echo "🚀 Starting Gunicorn on port $RANDOM_PORT..."
nohup $VENV_DIR/bin/gunicorn config.wsgi:application --bind 0.0.0.0:$RANDOM_PORT > logs_web.out 2>&1 &

echo "🚀 Starting Celery worker..."
nohup $VENV_DIR/bin/celery -A config worker --loglevel=info > logs_celery.out 2>&1 &

echo "🚀 Starting Celery Beat..."
nohup $VENV_DIR/bin/celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler > logs_beat.out 2>&1 &

echo ""
echo "✅ Deployment complete!"
echo "🌐 Admin panel: http://<server_ip>:$RANDOM_PORT/admin/"
echo "👤 Admin username: $DJANGO_SUPERUSER"
echo "🔑 Admin password: $DJANGO_SUPERPASS"
echo ""
echo "📄 Logs:"
echo "  logs_web.out"
echo "  logs_celery.out"
echo "  logs_beat.out"
