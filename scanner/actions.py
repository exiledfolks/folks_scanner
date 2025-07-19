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
from django.conf import settings
from django.utils import timezone

from .models import Channel, Mirror, Node

# === CONFIGURATION ===
api_id = getattr(settings, 'TELEGRAM_API_ID', None)
api_hash = getattr(settings, 'TELEGRAM_API_HASH', None)
timeout = 10

try:
    from telethon.sync import TelegramClient  # sync import!
except ImportError:
    TelegramClient = None

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

def run_full_scan_sync(channel_ids=None, mirror_ids=None):
    use_telegram = api_id and api_hash and TelegramClient is not None
    collected_links = {proto: set() for proto in patterns.keys()}
    seen_keys = set()

    # Determine trigger source and filter accordingly
    # If called with mirror_ids: only check mirrors, skip channels
    # If called with channel_ids: only check channels, skip mirrors
    # If neither: check both

    do_channels = channel_ids is not None or (channel_ids is None and mirror_ids is None)
    do_mirrors = mirror_ids is not None or (channel_ids is None and mirror_ids is None)

    # Channels
    if do_channels:
        channel_qs = Channel.objects.filter(active=True)
        if channel_ids is not None:
            channel_qs = channel_qs.filter(id__in=channel_ids)
        # Telegram part
        if use_telegram:
            channel_usernames = list(channel_qs.values_list('username', flat=True))
            if channel_usernames:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async def fetch_telegram(channel_usernames):
                        import getpass
                        session_file = 'session_name.session'
                        client = TelegramClient('session_name', api_id, api_hash, loop=loop)
                        if not os.path.exists(session_file):
                            print('No Telegram session found. You need to login.')
                            phone = input('Enter your phone number (with country code, e.g. +989123456789): ')
                            await client.start(phone=phone)
                        else:
                            await client.start()
                        print(f'✅ Connected to Telegram')

                        today = datetime.date.today()
                        yesterday = today - datetime.timedelta(days=1)
                        for channel_username in channel_usernames:
                            try:
                                channel = await client.get_entity(channel_username)
                                print(f'🔍 Reading channel: {channel_username}')
                            except Exception as e:
                                print(f'❌ Cannot get channel {channel_username}: {e}')
                                continue

                            async for message in client.iter_messages(channel, limit=500):
                                msg_date = message.date.date()
                                if msg_date != today and msg_date != yesterday:
                                    continue
                                if message.text:
                                    for proto, pattern in patterns.items():
                                        matches = pattern.findall(message.text)
                                        for link in matches:
                                            collected_links[proto].add(link.strip())

                        await client.disconnect()

                    loop.run_until_complete(fetch_telegram(channel_usernames))

                except Exception as e:
                    print(f'⚠️ Telegram fetch failed, skipping: {e}')
            else:
                print('ℹ️ No active channels found, skipping Telegram connection.')

    # Mirrors
    if do_mirrors:
        mirror_qs = Mirror.objects.filter(active=True)
        if mirror_ids is not None:
            mirror_qs = mirror_qs.filter(id__in=mirror_ids)
        mirror_urls = list(mirror_qs.values_list('url', flat=True))
        mirror_links = fetch_mirror_links(mirror_urls)
        for proto in patterns.keys():
            collected_links[proto].update(mirror_links[proto])

    # === Process + Save (same as before) ===
    final_nodes = []
    update_nodes = []
    node_keys = {}
    def extract_remark(link):
        if '#' in link:
            return link.split('#', 1)[1]
        return ''

    for proto in collected_links:
        for link in collected_links[proto]:
            modified = modify_remark(link, proto)
            host, port = extract_host_port(modified, proto)
            user = extract_user_id(modified, proto)
            remark = extract_remark(modified)
            key = f"{proto}-{host}-{port}-{user}"
            if host and port and key not in seen_keys:
                delay = tcp_ping(host, port, timeout)
                if 0 < delay < 1050:
                    print(f'✅ {proto.upper()} {host}:{port} → {delay}ms')
                    seen_keys.add(key)
                    socks_port = random.randint(10000, 20000)
                    ok, speed = test_config_with_xray(modified, proto, socks_port, timeout=20)
                    if ok:
                        node_keys[key] = {
                            'protocol': proto,
                            'raw_link': modified,
                            'host': host,
                            'port': port,
                            'remark': remark,
                            'last_speed_kbps': speed,
                            'last_checked': timezone.now(),
                            'is_working': ok,
                        }
                else:
                    print(f'❌ {proto.upper()} {host}:{port} → TCP fail ({delay}ms)')

    # Re-test all existing nodes for the selected channels/mirrors (or all if none selected)
    from django.db.models import Q

    # Build a filter for existing nodes based on the scan scope
    node_filter = Q()
    if do_channels:
        # If scanning channels, filter by hosts/ports found in those channels
        # (or all if no new found, fallback to all active nodes)
        pass  # No additional filter, as we want to re-test all
    if do_mirrors:
        # If scanning mirrors, filter by hosts/ports found in those mirrors
        pass  # No additional filter, as we want to re-test all
    # If both, just re-test all
    existing_nodes = Node.objects.all()
    nodes_to_keep = set()
    nodes_to_delete = []
    for n in existing_nodes:
        # Re-test node
        delay = tcp_ping(n.host, n.port, timeout)
        if 0 < delay < 1050:
            print(f'✅ RETEST {n.protocol.upper()} {n.host}:{n.port} → {delay}ms')
            n.last_checked = timezone.now()
            n.is_working = True
            update_nodes.append(n)
            nodes_to_keep.add(f"{n.protocol}-{n.host}-{n.port}-{extract_user_id(n.raw_link, n.protocol)}")
        else:
            print(f'❌ RETEST {n.protocol.upper()} {n.host}:{n.port} → TCP fail ({delay}ms)')
            nodes_to_delete.append(n.pk)
    if nodes_to_delete:
        Node.objects.filter(pk__in=nodes_to_delete).delete()
        print(f'\n🗑️ Deleted {len(nodes_to_delete)} non-working configs from Node table')
    # Add new nodes that are not already kept
    for k, v in node_keys.items():
        if k not in nodes_to_keep:
            final_nodes.append(Node(**v))

    if update_nodes:
        Node.objects.bulk_update(update_nodes, ['raw_link', 'last_speed_kbps', 'last_checked', 'is_working'])
        print(f'\n✅ Updated {len(update_nodes)} existing configs in Node table')
    if final_nodes:
        Node.objects.bulk_create(final_nodes)
        print(f'\n✅ Saved {len(final_nodes)} new working configs to Node table')
    if not final_nodes and not update_nodes:
        print('\n⚠ No working configs found.')

    # Cleanup: remove all test_*.json files created during config testing
    import glob
    for f in glob.glob("test_*.json"):
        try:
            os.remove(f)
        except Exception as e:
            print(f"Warning: could not remove {f}: {e}")
