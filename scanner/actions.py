import asyncio
import random
import time
import requests
import socket
import subprocess
import datetime
import re
import base64
import json
import os
import signal

from telethon import TelegramClient

from django.conf import settings

from .models import Mirror, Channel, Node

# === CONFIGURATION ===

API_ID = settings.TELEGRAM_API_ID
API_HASH = settings.TELEGRAM_API_HASH
XRAY_PATH = settings.XRAY_PATH

TIMEOUT = 10


# === REGEX PATTERNS ===

patterns = {
    'vless': re.compile(r'vless://[^\s]+'),
    'vmess': re.compile(r'vmess://[^\s]+'),
    'trojan': re.compile(r'trojan://[^\s]+'),
    'ss': re.compile(r'ss://[^\s]+'),
}

def modify_remark(link, proto):
    random_number = random.randint(1000, 9999)
    new_remark = f'🕊️ freedom-{random_number}'
    if '#' in link:
        base, _ = link.split('#', 1)
        return f'{base}#{new_remark}'
    else:
        return f'{link}#{new_remark}'

def extract_host_port(link, proto):
    try:
        if proto in ['vless', 'trojan']:
            part = link.split('://')[1].split('@')[-1]
            hostport = part.split('?')[0].split('#')[0]
            host, port = hostport.split(':')
            return host, int(port)
        elif proto == 'vmess':
            b64_payload = link.split('vmess://')[1].split('#')[0]
            padded = b64_payload + '=' * (-len(b64_payload) % 4)
            decoded = base64.b64decode(padded).decode()
            json_data = json.loads(decoded)
            return json_data.get('add'), int(json_data.get('port'))
        elif proto == 'ss':
            ss_part = link.split('ss://')[1].split('#')[0]
            if '@' in ss_part:
                hostport = ss_part.split('@')[-1]
            else:
                padded = ss_part + '=' * (-len(ss_part) % 4)
                decoded = base64.b64decode(padded).decode()
                _, hostport = decoded.rsplit('@', 1)
            host, port = hostport.split(':')
            return host, int(port)
    except Exception:
        return None, None

def extract_user_id(link, proto):
    try:
        if proto in ['vless', 'trojan']:
            part = link.split('://')[1]
            user = part.split('@')[0]
            return user
        elif proto == 'vmess':
            b64_payload = link.split('vmess://')[1].split('#')[0]
            padded = b64_payload + '=' * (-len(b64_payload) % 4)
            decoded = base64.b64decode(padded).decode()
            json_data = json.loads(decoded)
            return json_data.get('id')
        elif proto == 'ss':
            ss_part = link.split('ss://')[1].split('#')[0]
            if '@' in ss_part:
                userpass_b64 = ss_part.split('@')[0]
                padded = userpass_b64 + '=' * (-len(userpass_b64) % 4)
                decoded = base64.b64decode(padded).decode()
                method, password = decoded.split(':', 1)
            else:
                decoded = base64.b64decode(ss_part + '=' * (-len(ss_part) % 4)).decode()
                method, rest = decoded.split(':', 1)
                password, _ = rest.split('@', 1)
            return password, method
    except Exception:
        return None

def tcp_ping(host, port, timeout=2):
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout):
            end = time.time()
        return int((end - start) * 1000)
    except Exception:
        return -1

def wait_for_port(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.5)
    return False

def build_xray_config(link, proto, socks_port):
    # simplified here, can add full streamSettings parsing if needed
    host, port = extract_host_port(link, proto)
    user_id = extract_user_id(link, proto)
    outbound = {
        "protocol": proto,
        "settings": {
            "vnext" if proto in ["vless", "vmess"] else "servers": [{
                "address": host,
                "port": port,
                "users": [{"id": user_id}]
            }]
        },
        "streamSettings": {"network": "tcp"}
    }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": socks_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound]
    }

def test_config_with_xray(link, proto, socks_port, timeout=20):
    config_file = f'test_{socks_port}.json'
    success, speed_kbps = False, 0
    try:
        with open(config_file, 'w') as f:
            json.dump(build_xray_config(link, proto, socks_port), f)

        proc = subprocess.Popen([XRAY_PATH, 'run', '-c', config_file],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                preexec_fn=os.setsid)

        if not wait_for_port(socks_port):
            return False, 0

        start = time.time()
        result = subprocess.run(['curl', '--socks5-hostname', f'127.0.0.1:{socks_port}', '-o', '/dev/null',
                                 '-m', str(timeout), 'http://speedtest.tele2.net/1MB.zip'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        duration = time.time() - start

        if result.returncode == 0:
            speed_kbps = round((1024 / duration), 2)
            success = True

    except Exception:
        pass
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        if os.path.exists(config_file):
            os.remove(config_file)
    return success, speed_kbps

def fetch_mirror_links():
    all_links = []
    for mirror in Mirror.objects.filter(active=True):
        try:
            resp = requests.get(mirror.url, timeout=10)
            if resp.status_code == 200:
                text = resp.text
                for proto, pattern in patterns.items():
                    all_links += pattern.findall(text)
        except Exception:
            continue
    return all_links

async def fetch_telegram_links():
    client = TelegramClient('session', API_ID, API_HASH)
    await client.start()
    all_links = []
    today = datetime.date.today()
    for channel in Channel.objects.filter(active=True):
        try:
            entity = await client.get_entity(channel.username)
            async for msg in client.iter_messages(entity, limit=500):
                if msg.date.date() != today:
                    continue
                if msg.text:
                    for proto, pattern in patterns.items():
                        all_links += pattern.findall(msg.text)
        except Exception:
            continue
    await client.disconnect()
    return all_links

def run_full_scan():
    """
    Entry point to scan mirrors and channels, and update Node model.
    """
    print("🔎 Starting full scan...")
    all_links = set()

    # Step 1: get mirror links
    all_links.update(fetch_mirror_links())

    # Step 2: get telegram links (sync run of async)
    telegram_links = asyncio.run(fetch_telegram_links())
    all_links.update(telegram_links)

    seen_keys = set()
    for link in all_links:
        for proto in patterns.keys():
            if link.startswith(f"{proto}://"):
                modified = modify_remark(link, proto)
                host, port = extract_host_port(modified, proto)
                user = extract_user_id(modified, proto)
                key = f"{proto}-{host}-{port}-{user}"
                if not host or key in seen_keys:
                    continue
                seen_keys.add(key)

                # TCP ping check
                delay = tcp_ping(host, port, timeout=5)
                if delay < 0 or delay > 1050:
                    continue

                # Real Xray check
                socks_port = random.randint(10000, 20000)
                ok, speed = test_config_with_xray(modified, proto, socks_port)

                # Save or update in DB
                node, created = Node.objects.get_or_create(
                    protocol=proto, host=host, port=port, user_id=user,
                    defaults={'raw_link': modified, 'source': None}
                )
                node.raw_link = modified
                node.last_ping_ms = delay
                node.last_speed_kbps = speed
                node.is_working = ok
                node.remark = f"🕊️ freedom-{random.randint(1000,9999)}"
                node.save()
    print("✅ Scan completed!")
