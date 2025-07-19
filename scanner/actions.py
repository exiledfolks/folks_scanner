import asyncio
import base64
import datetime
import json
import os
import random
import re
import signal
import socket
import subprocess
import time
import requests

from telethon import TelegramClient
from django.conf import settings
from .models import Node, Channel, Mirror

# === CONFIGURATION ===
api_id = getattr(settings, 'TELEGRAM_API_ID', None)
api_hash = getattr(settings, 'TELEGRAM_API_HASH', None)
timeout = 10

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
    elif proto in ['vless', 'vmess'] and 'remark=' in link:
        return re.sub(r'(remark=)[^&]+', rf'\1{new_remark}', link)
    else:
        return f'{link}#{new_remark}'

def parse_query_params(link):
    try:
        query = link.split('?', 1)[1].split('#')[0]
        params = dict(x.split('=') for x in query.split('&') if '=' in x)
        return params
    except Exception:
        return {}

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
    host, port = extract_host_port(link, proto)
    params = parse_query_params(link)
    if proto == 'ss':
        user_id, method = extract_user_id(link, proto)
    else:
        user_id = extract_user_id(link, proto)
        method = None

    stream_settings = {"network": params.get('type', 'tcp')}
    if params.get('security') == 'tls':
        stream_settings["security"] = "tls"
        if 'sni' in params:
            stream_settings["tlsSettings"] = {"serverName": params['sni']}
    if stream_settings['network'] == 'ws':
        stream_settings['wsSettings'] = {"path": params.get('path', '/'), "headers": {"Host": params.get('host', host)}}
    if stream_settings['network'] == 'grpc':
        stream_settings['grpcSettings'] = {"serviceName": params.get('serviceName', ''), "multiMode": False}

    if proto in ['vless', 'vmess']:
        outbound = {
            "protocol": proto,
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{"id": user_id, "encryption": "none" if proto == 'vless' else "auto"}]
                }]
            },
            "streamSettings": stream_settings
        }
    elif proto == 'trojan':
        outbound = {
            "protocol": "trojan",
            "settings": {"servers": [{"address": host, "port": port, "password": user_id}]}
        }
    elif proto == 'ss':
        outbound = {
            "protocol": "shadowsocks",
            "settings": {"servers": [{"address": host, "port": port, "password": user_id, "method": method}]}
        }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": socks_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound]
    }

def test_config_with_xray(link, proto, socks_port, timeout=20):
    xray_path = './xray'
    config_file = f'test_{socks_port}.json'
    success = False
    speed_kbps = 0

    try:
        with open(config_file, 'w') as f:
            json.dump(build_xray_config(link, proto, socks_port), f)

        proc = subprocess.Popen([xray_path, 'run', '-c', config_file], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, preexec_fn=os.setsid)

        if not wait_for_port(socks_port, timeout=10):
            print("⚠️ Xray failed to open port")
            return False, 0

        start = time.time()
        result = subprocess.run(['curl', '--socks5-hostname', f'127.0.0.1:{socks_port}', '-o', '/dev/null',
                                 '-m', str(timeout), 'http://speedtest.tele2.net/1MB.zip'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        end = time.time()
        duration = end - start
        if result.returncode == 0:
            speed_kbps = round((1024 / duration), 2)
            print(f"✅ Speed: {speed_kbps} KB/s")
            success = True
        else:
            print(f"❌ Speed test failed: {result.stderr.decode().strip()}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        if os.path.exists(config_file):
            os.remove(config_file)

    return success, speed_kbps

def fetch_mirror_links(mirror_urls):
    mirror_links = {proto: set() for proto in patterns.keys()}
    for url in mirror_urls:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                text = resp.text
                for proto, pattern in patterns.items():
                    matches = pattern.findall(text)
                    for link in matches:
                        mirror_links[proto].add(link.strip())
                print(f"✅ Fetched from {url}")
            else:
                print(f"❌ Failed to fetch {url} (status {resp.status_code})")
        except Exception as e:
            print(f"❌ Error fetching {url}: {e}")
    return mirror_links

async def run_full_scan():
    use_telegram = api_id and api_hash
    collected_links = {proto: set() for proto in patterns.keys()}
    seen_keys = set()

    if use_telegram:
        client = TelegramClient('session_name', api_id, api_hash)
        await client.start()
        print(f'✅ Connected to Telegram')

        channel_usernames = list(Channel.objects.values_list('name', flat=True))
        today = datetime.date.today()
        for channel_username in channel_usernames:
            try:
                channel = await client.get_entity(channel_username)
                print(f'🔍 Reading channel: {channel_username}')
            except Exception as e:
                print(f'❌ Cannot get channel {channel_username}: {e}')
                continue

            async for message in client.iter_messages(channel, limit=500):
                if message.date.date() != today:
                    continue
                if message.text:
                    for proto, pattern in patterns.items():
                        matches = pattern.findall(message.text)
                        for link in matches:
                            collected_links[proto].add(link.strip())

        await client.disconnect()

    mirror_urls = list(Mirror.objects.values_list('url', flat=True))
    mirror_links = fetch_mirror_links(mirror_urls)
    for proto in patterns.keys():
        collected_links[proto].update(mirror_links[proto])

    # --- Deduplicate + filter + save ---
    final_nodes = []
    for proto in collected_links:
        for link in collected_links[proto]:
            modified = modify_remark(link, proto)
            host, port = extract_host_port(modified, proto)
            user = extract_user_id(modified, proto)
            key = f"{proto}-{host}-{port}-{user}"
            if host and port and key not in seen_keys:
                delay = tcp_ping(host, port, timeout)
                if 0 < delay < 1050:
                    print(f'✅ {proto.upper()} {host}:{port} → {delay}ms')
                    seen_keys.add(key)
                    socks_port = random.randint(10000, 20000)
                    ok, speed = test_config_with_xray(modified, proto, socks_port, timeout=20)
                    if ok:
                        final_nodes.append(Node(
                            protocol=proto,
                            link=modified,
                            host=host,
                            port=port,
                            speed_kbps=speed,
                            checked_at=datetime.datetime.now()
                        ))
                else:
                    print(f'❌ {proto.upper()} {host}:{port} → TCP fail ({delay}ms)')

    if final_nodes:
        Node.objects.bulk_create(final_nodes)
        print(f'\n✅ Saved {len(final_nodes)} working configs to Node table')
    else:
        print('\n⚠ No working configs found.')
