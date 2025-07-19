#!/bin/bash

set -e

REPO_URL="https://github.com/exiledfolks/folks_scanner.git"
PROJECT_DIR="$HOME/folks_project"
VENV_DIR="$PROJECT_DIR/folks_venv"
DJANGO_MODULE="config"  # change if needed!
RANDOM_PORT=$(( RANDOM % 10000 + 30000 ))
DJANGO_SUPERUSER="admin"
DJANGO_SUPERPASS=$(openssl rand -hex 12)

echo "🔧 Installing system packages..."
sudo apt update || true
sudo apt install -y python3.12 python3.12-full python3.12-venv redis-server git curl || true
sudo systemctl enable --now redis-server

if [ -d "$PROJECT_DIR" ]; then
    echo "⚠️ $PROJECT_DIR exists, removing..."
    rm -rf "$PROJECT_DIR"
fi

echo "🚀 Cloning project..."
git clone $REPO_URL "$PROJECT_DIR"
cd "$PROJECT_DIR"

echo "🐍 Creating virtualenv..."
python3.12 -m venv "$VENV_DIR"
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
SECRET_KEY=$(openssl rand -hex 32)
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
python manage.py shell -c "
from django.contrib.auth import get_user_model; \
u = get_user_model().objects.get(username='$DJANGO_SUPERUSER'); \
u.set_password('$DJANGO_SUPERPASS'); u.save()"

echo "📦 Collecting static..."
python manage.py collectstatic --noinput

mkdir -p logs

echo "🚀 Starting services..."
nohup "$VENV_DIR/bin/gunicorn" "$DJANGO_MODULE.wsgi:application" --bind 0.0.0.0:$RANDOM_PORT --log-level debug > logs_web.out 2>&1 &
nohup "$VENV_DIR/bin/celery" -A "$DJANGO_MODULE" worker --loglevel=info > logs_celery.out 2>&1 &
nohup "$VENV_DIR/bin/celery" -A "$DJANGO_MODULE" beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler > logs_beat.out 2>&1 &

# Save project path + port globally (with sudo)
sudo bash -c "echo '$PROJECT_DIR' > /usr/local/folks_project_path"
sudo bash -c "echo '$RANDOM_PORT' > /usr/local/folks_project_port"

# Create global helper: folks-logs
sudo bash -c "cat > /usr/local/bin/folks-logs" <<'EOF'
#!/bin/bash
dir=$(cat /usr/local/folks_project_path)
case "$1" in
  web) tail -f "$dir/logs_web.out" ;;
  celery) tail -f "$dir/logs_celery.out" ;;
  beat) tail -f "$dir/logs_beat.out" ;;
  *) echo "Usage: folks-logs [web|celery|beat]" ;;
esac
EOF
sudo chmod +x /usr/local/bin/folks-logs

# Create global helper: folks-restart
sudo bash -c "cat > /usr/local/bin/folks-restart" <<'EOF'
#!/bin/bash
dir=$(cat /usr/local/folks_project_path)
venv="$dir/folks_venv"
port=$(cat /usr/local/folks_project_port)
cd "$dir" || exit
source "$venv/bin/activate"
pkill -f gunicorn || true
pkill -f celery || true
nohup "$venv/bin/gunicorn" config.wsgi:application --bind 0.0.0.0:$port --log-level debug > logs_web.out 2>&1 &
nohup "$venv/bin/celery" -A config worker --loglevel=info > logs_celery.out 2>&1 &
nohup "$venv/bin/celery" -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler > logs_beat.out 2>&1 &
echo "✅ Services restarted"
EOF
sudo chmod +x /usr/local/bin/folks-restart

# Create global helper: folks-stop
sudo bash -c "cat > /usr/local/bin/folks-stop" <<'EOF'
#!/bin/bash
pkill -f gunicorn || true
pkill -f celery || true
echo "✅ All services stopped"
EOF
sudo chmod +x /usr/local/bin/folks-stop

echo ""
echo "✅ Installation complete!"
echo "🌐 Admin panel: http://<server_ip>:$RANDOM_PORT/admin/"
echo "👤 Admin username: $DJANGO_SUPERUSER"
echo "🔑 Admin password: $DJANGO_SUPERPASS"
echo ""
echo "💬 Use:"
echo "  folks-logs [web|celery|beat]  → view logs"
echo "  folks-restart                 → restart all services"
echo "  folks-stop                    → stop all services"
