#!/usr/bin/env bash
# Windows Git Bash installer for folks_scanner
# Assumes Python 3.12, Git, and Redis are installed and in PATH.
# Run in Git Bash (not cmd.exe or PowerShell)

set -e

REPO_URL="https://github.com/exiledfolks/folks_scanner.git"
PROJECT_DIR="$HOME/folks_project"
VENV_DIR="$PROJECT_DIR/folks_venv"
DJANGO_MODULE="config"
RANDOM_PORT=$(( RANDOM % 10000 + 30000 ))
DJANGO_SUPERUSER="admin"
DJANGO_SUPERPASS=$(head -c 12 /dev/urandom | xxd -p)

if [ -d "$PROJECT_DIR" ]; then
    echo "⚠️ $PROJECT_DIR exists, removing..."
    rm -rf "$PROJECT_DIR"
fi

echo "🚀 Cloning project..."
git clone "$REPO_URL" "$PROJECT_DIR"
cd "$PROJECT_DIR"

echo "🐍 Creating virtualenv..."
python -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "⬆️ Installing Python deps..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🔑 Enter Telegram API ID (or 'no'):"
read TELEGRAM_API_ID
if [ "$TELEGRAM_API_ID" != "no" ]; then
    echo "🔑 Enter Telegram API HASH:"
    read TELEGRAM_API_HASH
else
    TELEGRAM_API_ID=""
    TELEGRAM_API_HASH=""
fi

echo "⚙️ Creating .env..."
cat > .env <<EOF
DEBUG=False
SECRET_KEY=$DJANGO_SUPERPASS
ALLOWED_HOSTS=localhost
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
XRAY_PATH=./xray
CELERY_BROKER_URL=redis://localhost:6379/0
EOF

touch db.sqlite3
chmod 664 db.sqlite3

echo "📦 Running migrations..."
python manage.py migrate

echo "👤 Creating superuser..."
python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER --email admin@example.com
python manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='$DJANGO_SUPERUSER'); u.set_password('$DJANGO_SUPERPASS'); u.save()"

echo "📦 Collecting static..."
python manage.py collectstatic --noinput

mkdir -p logs

echo "🚀 Starting services..."
nohup python manage.py runserver 0.0.0.0:$RANDOM_PORT > logs_web.out 2>&1 &
nohup celery -A $DJANGO_MODULE worker --loglevel=info > logs_celery.out 2>&1 &
nohup celery -A $DJANGO_MODULE beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler > logs_beat.out 2>&1 &

SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "✅ Installation complete!"
echo "🌐 Admin panel: http://$SERVER_IP:$RANDOM_PORT/admin/"
echo "👤 Admin username: $DJANGO_SUPERUSER"
echo "🔑 Admin password: $DJANGO_SUPERPASS"
echo ""
echo "💬 Use:"
echo "  tail -f logs_web.out         → view web logs"
echo "  tail -f logs_celery.out      → view celery logs"
echo "  tail -f logs_beat.out        → view beat logs"
echo "  source $VENV_DIR/bin/activate && python manage.py <command>   → run Django commands"
echo "  source $VENV_DIR/bin/activate && celery <args>                → run Celery commands"
echo ""
echo "Note: For production, use Waitress or Daphne for WSGI on Windows."
