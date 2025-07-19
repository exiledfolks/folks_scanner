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


# Create systemd service for Gunicorn (with high timeout and file logging)
sudo bash -c "cat > /etc/systemd/system/folks-gunicorn.service" <<EOF
[Unit]
Description=Folks Gunicorn Service
After=network.target

[Service]
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=DJANGO_SETTINGS_MODULE=$DJANGO_MODULE.settings
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/gunicorn $DJANGO_MODULE.wsgi:application --bind 0.0.0.0:$RANDOM_PORT --log-level debug --timeout 600
StandardOutput=append:$PROJECT_DIR/logs_web.out
StandardError=append:$PROJECT_DIR/logs_web.out
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create systemd service for Celery Worker (file logging)
sudo bash -c "cat > /etc/systemd/system/folks-celery.service" <<EOF
[Unit]
Description=Folks Celery Worker Service
After=network.target

[Service]
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=DJANGO_SETTINGS_MODULE=$DJANGO_MODULE.settings
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/celery -A $DJANGO_MODULE worker --loglevel=info
StandardOutput=append:$PROJECT_DIR/logs_celery.out
StandardError=append:$PROJECT_DIR/logs_celery.out
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create systemd service for Celery Beat (file logging)
sudo bash -c "cat > /etc/systemd/system/folks-celery-beat.service" <<EOF
[Unit]
Description=Folks Celery Beat Service
After=network.target

[Service]
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=DJANGO_SETTINGS_MODULE=$DJANGO_MODULE.settings
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/celery -A $DJANGO_MODULE beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
StandardOutput=append:$PROJECT_DIR/logs_beat.out
StandardError=append:$PROJECT_DIR/logs_beat.out
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable folks-gunicorn folks-celery folks-celery-beat
sudo systemctl restart folks-gunicorn folks-celery folks-celery-beat

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

 # Create global helper: folks-manage
sudo bash -c "cat > /usr/local/bin/folks-manage" <<'EOF'
#!/bin/bash
dir=$(cat /usr/local/folks_project_path)
venv="$dir/folks_venv"
cd "$dir" || exit
source "$venv/bin/activate"
python manage.py "$@"
EOF
sudo chmod +x /usr/local/bin/folks-manage

# Create global helper: folks-celery
sudo bash -c "cat > /usr/local/bin/folks-celery" <<'EOF'
#!/bin/bash
dir=$(cat /usr/local/folks_project_path)
venv="$dir/folks_venv"
cd "$dir" || exit
source "$venv/bin/activate"
celery "$@"
EOF
sudo chmod +x /usr/local/bin/folks-celery

# Create global helper: folks-celery-task
sudo bash -c "cat > /usr/local/bin/folks-celery-task" <<'EOF'
#!/bin/bash
dir=$(cat /usr/local/folks_project_path)
venv="$dir/folks_venv"
cd "$dir" || exit
source "$venv/bin/activate"
echo "Fetching available Celery tasks..."
celery -A config inspect registered | grep -oE "'[^']+'" | tr -d "'" | sort | uniq > /tmp/folks_tasks_list.txt
if [ ! -s /tmp/folks_tasks_list.txt ]; then
  echo "No tasks found or worker not running."
  exit 1
fi
echo "Available tasks:"
nl -w2 -s'. ' /tmp/folks_tasks_list.txt
read -p "Select task number to run: " tasknum
task=$(sed -n "${tasknum}p" /tmp/folks_tasks_list.txt)
if [ -z "$task" ]; then
  echo "Invalid selection."
  exit 1
fi
read -p "Enter arguments as a Python list (e.g. ['arg1', 2]) or leave blank: " args
if [ -z "$args" ]; then
  celery -A config call "$task"
else
  celery -A config call "$task" --args "$args"
fi
EOF
sudo chmod +x /usr/local/bin/folks-celery-task

echo ""
echo "✅ Installation complete!"
SERVER_IP=$(hostname -I | awk '{print $1}')
echo "🌐 Admin panel: http://$SERVER_IP:$RANDOM_PORT/admin/"
echo "👤 Admin username: $DJANGO_SUPERUSER"
echo "🔑 Admin password: $DJANGO_SUPERPASS"
echo ""
echo "💬 Use:"
echo "  folks-logs [web|celery|beat]    → view logs"
echo "  folks-restart                   → restart all services"
echo "  folks-stop                      → stop all services"
echo "  folks-manage <command> [args]   → run Django manage.py commands (e.g. migrate, createsuperuser, run_full_scan_sync)"
echo "  folks-celery <args>             → run Celery commands (e.g. -A config worker, -A config beat)"
echo "  folks-celery-task               → list and trigger Celery tasks interactively"
echo ""
echo "🔄 Services are now managed by systemd and will start on boot."
echo "  sudo systemctl status folks-gunicorn        → Gunicorn status"
echo "  sudo systemctl status folks-celery          → Celery worker status"
echo "  sudo systemctl status folks-celery-beat     → Celery beat status"
echo "  sudo systemctl restart folks-gunicorn       → Restart Gunicorn"
echo "  sudo systemctl restart folks-celery         → Restart Celery worker"
echo "  sudo systemctl restart folks-celery-beat    → Restart Celery beat"
