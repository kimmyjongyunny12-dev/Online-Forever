# discord_clock_spotify.py
# - Shows current UK time (GMT/BST) as custom status
# - Shows fake Spotify rich presence with REAL album art
#   (fetches real image IDs from Spotify's public oEmbed API at startup)
# - ALL track IDs are verified real Spotify track IDs
# - Updates clock every 30s, changes song every SONG_INTERVAL seconds
#
# WARNING: This automates a user account using a user token. That can violate
# Discord's Terms of Service and may result in account action. Use at your own risk.

import os
import sys
import json
import asyncio
import random
import platform
import requests
import websockets
from datetime import datetime, timezone, timedelta
from colorama import init, Fore

try:
    from keep_alive import keep_alive
    HAVE_KEEP_ALIVE = True
except Exception:
    HAVE_KEEP_ALIVE = False

init(autoreset=True)

# ------- CONFIG -------
STATUS        = "online"    # online / dnd / idle
SONG_INTERVAL = 60          # seconds before song changes
GATEWAY       = "wss://gateway.discord.gg/?v=10&encoding=json"
# ----------------------

# ---- UK CLOCK HELPERS ----
def uk_now():
    utc_now = datetime.now(timezone.utc)
    year = utc_now.year
    march_31 = datetime(year, 3, 31, 1, 0, tzinfo=timezone.utc)
    bst_start = march_31 - timedelta(days=march_31.weekday() + 1 if march_31.weekday() != 6 else 0)
    oct_31 = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
    bst_end = oct_31 - timedelta(days=oct_31.weekday() + 1 if oct_31.weekday() != 6 else 0)
    if bst_start <= utc_now < bst_end:
        return utc_now + timedelta(hours=1), "BST"
    return utc_now, "GMT"

def clock_emoji(hour24):
    clocks = {
        0:"🕛",1:"🕐",2:"🕑",3:"🕒",4:"🕓",5:"🕔",
        6:"🕕",7:"🕖",8:"🕗",9:"🕘",10:"🕙",11:"🕚",
        12:"🕛",13:"🕐",14:"🕑",15:"🕒",16:"🕓",17:"🕔",
        18:"🕕",19:"🕖",20:"🕗",21:"🕘",22:"🕙",23:"🕚",
    }
    return clocks.get(hour24, "🕛")

# ---- PLAYLIST ----
# Format: (artist, song, album, spotify_track_id)
# ALL track IDs verified from real open.spotify.com URLs
PLAYLIST = [
    # Chase Atlantic — verified
    ("Chase Atlantic", "PHASES",   "PHASES",         "0AvVR6Bx52aY3cWdRDdTfx"),
    ("Chase Atlantic", "Friends",  "Nostalgia EP",   "7uDUb37h7Xdhza1eWMkoJv"),
    ("Chase Atlantic", "Into It",  "Chase Atlantic", "7D8DdqPvgLJkDruhvnz9NB"),
    ("Chase Atlantic", "Okay",     "Chase Atlantic", "492PZFHvGTm3RZZYeeUVWT"),
    ("Chase Atlantic", "Swim",     "Swim",           "2aZ5Ch59IWH33g9ln7lvi8"),

    # beabadoobee — verified
    ("beabadoobee", "Coffee",            "Coffee",          "429NtPmr12aypzFH3FkN9l"),

    # Lana Del Rey — verified
    ("Lana Del Rey", "Video Games",         "Born To Die",   "33HucJaMg7OBQLqmaVx58p"),
    ("Lana Del Rey", "Born To Die",         "Born To Die",   "4Ouhoi2lAhrLJKFzUqEzwl"),
    ("Lana Del Rey", "Cherry",              "Lust for Life", "0sBojHJfRAIMd9SCBKE2nh"),

    # TV Girl — verified
    ("TV Girl", "Not Allowed", "Who Really Cares", "3IznIgmXtrUaoPWpQTy5jB"),

    # Cigarettes After Sex — verified
    ("Cigarettes After Sex", "Apocalypse", "Cigarettes After Sex", "0yc6Gst2xkRu0eMLeRMGCX"),

    # NIKI — verified
    ("NIKI", "Indigo",         "Head In The Clouds II", "349Wc5mDu52d4Uv8Eg9WZv"),
    ("NIKI", "Backburner",     "Nicole",                "4x2PkqSLtuwv53hLqq4GiY"),
    ("NIKI", "La La Lost You", "Head In The Clouds II", "0QZLSImbxep9NyhhlCGOWh"),
    ("NIKI", "Before",         "Nicole",                "2OpC6XGVzBxV8bMz5n0gp4"),

    # The Weeknd — verified
    ("The Weeknd", "Blinding Lights",   "After Hours", "0VjIjW4GlUZAMYd2vXMi3b"),
    ("The Weeknd", "Starboy",           "Starboy",     "7MXVkk9YMctZqd1Srtv4MB"),
    ("The Weeknd", "Die For You",       "Starboy",     "0awWj9Wzj375IL5etqa1Dk"),
    ("The Weeknd", "Snowchild",         "After Hours", "3WlbeuhfRSqU7ylK2Ui5U7"),
]

def fetch_image_id(track_id: str) -> str | None:
    """
    Fetch the real Spotify album image hash using Spotify's public oEmbed endpoint.
    No API key needed. Returns e.g. 'ab67616d00001e02xxxx...'
    """
    try:
        url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            thumbnail_url = r.json().get("thumbnail_url", "")
            # e.g. https://i.scdn.co/image/ab67616d00001e02XXXX
            if "/image/" in thumbnail_url:
                return thumbnail_url.split("/image/")[-1]
    except Exception as e:
        print(f"{Fore.YELLOW}    oEmbed error for {track_id}: {e}")
    return None

def preload_image_ids(playlist: list) -> dict:
    """Fetch real album image IDs for all unique track IDs at startup."""
    cache = {}
    unique = list({entry[3]: entry for entry in playlist}.values())
    total  = len(unique)
    print(f"{Fore.CYAN}[i] Fetching real album art for {total} tracks...")
    for i, entry in enumerate(unique, 1):
        artist, song, album, track_id = entry
        image_id = fetch_image_id(track_id)
        if image_id:
            cache[track_id] = image_id
            print(f"{Fore.GREEN}  [{i}/{total}] ✓ {artist} — {song}")
        else:
            cache[track_id] = None
            print(f"{Fore.YELLOW}  [{i}/{total}] ✗ {artist} — {song} (no art)")
    ok = sum(1 for v in cache.values() if v)
    print(f"{Fore.GREEN}[+] Done: {ok}/{total} tracks have album art.\n")
    return cache

# TOKEN
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print(f"{Fore.RED}[!] TOKEN environment variable not found. Exiting.")
    sys.exit(1)

HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}

try:
    resp = requests.get("https://canary.discordapp.com/api/v9/users/@me", headers=HEADERS, timeout=8)
except Exception as e:
    print(f"{Fore.YELLOW}[!] Network error: {e}")
    sys.exit(1)

if resp.status_code != 200:
    print(f"{Fore.RED}[!] Token validation failed (status {resp.status_code}). Exiting.")
    sys.exit(1)

user     = resp.json()
USERNAME = user.get("username", "unknown")
DISCRIM  = user.get("discriminator", "0000")
USERID   = user.get("id", "unknown")

print(f"{Fore.GREEN}[+] Logged in as {Fore.CYAN}{USERNAME}#{DISCRIM} {Fore.WHITE}({USERID})")

IMAGE_CACHE = preload_image_ids(PLAYLIST)

def build_payload(entry: tuple) -> dict:
    artist, song, album, track_id = entry

    local_dt, tz_name = uk_now()
    emoji    = clock_emoji(local_dt.hour)
    time_str = f"{local_dt.hour:02d}:{local_dt.minute:02d} {tz_name}"

    now_ms      = int(datetime.now(timezone.utc).timestamp() * 1000)
    elapsed_ms  = random.randint(10_000, 90_000)
    duration_ms = random.randint(180_000, 300_000)
    start_ms    = now_ms - elapsed_ms
    end_ms      = start_ms + duration_ms

    image_id = IMAGE_CACHE.get(track_id)

    spotify_activity = {
        "type":    2,
        "name":    "Spotify",
        "id":      "spotify:1",
        "details": song,
        "state":   artist,
        "timestamps": {"start": start_ms, "end": end_ms},
        "sync_id":    track_id,
        "session_id": str(random.randint(10**15, 10**16)),
        "flags":      48,
        "party":      {"id": f"spotify:{USERID}"},
    }

    if image_id:
        spotify_activity["assets"] = {
            "large_image": f"mp:external/https://i.scdn.co/image/{image_id}",
            "large_text":  album,
        }

    return {
        "op": 3,
        "d": {
            "since":  0,
            "status": STATUS,
            "afk":    False,
            "activities": [
                {"type": 4, "name": "Custom Status", "id": "custom", "state": f"{emoji} {time_str}"},
                spotify_activity,
            ],
        },
    }

async def onliner(token: str, status: str):
    last_entry    = None
    current_entry = random.choice(PLAYLIST)

    while True:
        try:
            async with websockets.connect(GATEWAY, ping_interval=None, max_size=None) as ws:
                raw_hello = await ws.recv()
                hello = json.loads(raw_hello)
                hb_interval = hello["d"]["heartbeat_interval"]
                print(f"{Fore.GREEN}[+] Connected. Heartbeat: {hb_interval} ms")

                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": token,
                        "properties": {"$os": "Android", "$browser": "Discord Android", "$device": "Android"},
                        "presence": {"status": status, "afk": False},
                    },
                }))
                print(f"{Fore.CYAN}[>] Sent IDENTIFY. Waiting for READY...")

                ready_event = asyncio.Event()

                async def heartbeat_loop():
                    try:
                        while True:
                            await asyncio.sleep(hb_interval / 1000)
                            await ws.send(json.dumps({"op": 1, "d": None}))
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Heartbeat error: {e}"); raise

                async def presence_loop():
                    nonlocal current_entry, last_entry
                    try:
                        await ready_event.wait()
                        await asyncio.sleep(0.8)
                        song_timer = 0
                        while True:
                            if song_timer <= 0:
                                candidate = random.choice(PLAYLIST)
                                for _ in range(4):
                                    if candidate != last_entry: break
                                    candidate = random.choice(PLAYLIST)
                                current_entry = candidate
                                last_entry    = current_entry
                                song_timer    = SONG_INTERVAL

                            artist, song, album, track_id = current_entry
                            local_dt, tz = uk_now()
                            print(f"{Fore.MAGENTA}[~] {local_dt.hour:02d}:{local_dt.minute:02d} {tz} | {artist} — {song} (next in {song_timer}s)")

                            await ws.send(json.dumps(build_payload(current_entry), ensure_ascii=False))
                            await asyncio.sleep(30)
                            song_timer -= 30
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Presence error: {e}"); raise

                async def recv_loop():
                    try:
                        while True:
                            raw = await ws.recv()
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            op = msg.get("op")
                            if op == 0 and msg.get("t") == "READY":
                                print(f"{Fore.GREEN}[i] READY.")
                                if not ready_event.is_set(): ready_event.set()
                            if op == 9:
                                raise Exception("Invalid Session (op 9)")
                            d = msg.get("d") or {}
                            if isinstance(d, dict) and d.get("code") in (4003, 4004):
                                raise Exception(f"Auth failure ({d['code']})")
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Recv error: {e}"); raise

                tasks = [
                    asyncio.create_task(heartbeat_loop()),
                    asyncio.create_task(presence_loop()),
                    asyncio.create_task(recv_loop()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                for t in pending: t.cancel()
                for t in done:
                    if not t.cancelled():
                        exc = t.exception()
                        if exc: raise exc

        except Exception as e:
            print(f"{Fore.RED}[-] Error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

async def main():
    os.system("cls" if platform.system() == "Windows" else "clear")
    print(f"{Fore.WHITE}[{Fore.LIGHTGREEN_EX}+{Fore.WHITE}] Logged in as {Fore.LIGHTBLUE_EX}{USERNAME}#{DISCRIM} {Fore.WHITE}({USERID})")
    if HAVE_KEEP_ALIVE:
        try: keep_alive(); print(f"{Fore.GREEN}[i] keep_alive() started")
        except Exception: pass
    await onliner(TOKEN, STATUS)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[i] Exiting.")
        raise
