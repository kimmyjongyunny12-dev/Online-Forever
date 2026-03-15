# discord_clock_spotify.py
# - Shows current UK time (GMT/BST) as custom status
# - Shows fake Spotify rich presence with REAL album art
#   (fetches real image IDs from Spotify's public oEmbed API at startup)
# - Updates clock every 30s, changes song every SONG_INTERVAL seconds
# - Identifies as Android mobile
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
# Album image IDs are fetched automatically at startup from Spotify's public API
PLAYLIST = [
    # Chase Atlantic
    ("Chase Atlantic", "Phases",   "Phases",         "6UelLqGlWMcVH1E5c4Hfpl"),
    ("Chase Atlantic", "Friends",  "Phases",         "0P3pVPMGrHC6OfDoQe0lzK"),
    ("Chase Atlantic", "Into It",  "Chase Atlantic", "4cluDES4hQEUhmXj6TXkSo"),
    ("Chase Atlantic", "Okay",     "Chase Atlantic", "6wH79oNkTFMFEVxHzBiHiU"),
    ("Chase Atlantic", "Consume",  "Consume",        "1wjzFQodRDXsFNECwxwbaf"),
    ("Chase Atlantic", "Swim",     "Swim",           "5OaVzlhfqlGEDPJo9KGRhE"),

    # beabadoobee
    ("beabadoobee", "Coffee",            "Patched Up",      "6OVHRp5xGz0YtYgPiMTHR4"),
    ("beabadoobee", "Last Day on Earth", "Fake It Flowers", "4YPitSVmPXl5yvzRONUAZ9"),
    ("beabadoobee", "Sorry",             "Fake It Flowers", "0G3LiNdPN3g2EMPJfwHDFl"),
    ("beabadoobee", "Together",          "Fake It Flowers", "1G391cbiT3v3Cywg8T7DsU"),

    # Dec Avenue
    ("Dec Avenue", "Kung 'Di Rin Lang Ikaw", "Palagi",               "4ERzMsHGqCZ9GgZITfVHLF"),
    ("Dec Avenue", "Caught in the Middle",   "Caught in the Middle", "3HkMPJAoExMJBEGpJEzOIX"),

    # Lana Del Rey
    ("Lana Del Rey", "Summertime Sadness",  "Born to Die",         "6C6GCnFJ-lJifJhVQ4YPJZ"),
    ("Lana Del Rey", "Video Games",         "Born to Die",         "2TUHOiVrCcBhUTcnNKMbVR"),
    ("Lana Del Rey", "Young and Beautiful", "The Great Gatsby OST","5JiChLZLTqaB9FhqhIiUfY"),
    ("Lana Del Rey", "Born to Die",         "Born to Die",         "1lJ3LzFz1bpScqfXbGSDJT"),
    ("Lana Del Rey", "Cherry",              "Lust for Life",       "7K3BhKMBfqoTcz4L3Ovs1E"),

    # TV Girl
    ("TV Girl", "Not Allowed",             "French Exit", "6tBPGdGxQaJDLkZRXGieMU"),
    ("TV Girl", "Blue Hair",               "French Exit", "1xBSvjhRfbxURsQxSWxnQw"),
    ("TV Girl", "Taking What's Not Yours", "French Exit", "7xhP0gLIkKwGKSEkFyaKXE"),
    ("TV Girl", "Louise",                  "French Exit", "4pYdoMnVCzgnDUxQIFdLRX"),
    ("TV Girl", "Pantomime",               "French Exit", "2OJpFnDGKLaZf9IEyRlkQX"),

    # Cigarettes After Sex
    ("Cigarettes After Sex", "Apocalypse",                    "Cigarettes After Sex", "1NkHBMGJwnOdDg0JbMQGhY"),
    ("Cigarettes After Sex", "Nothing's Gonna Hurt You Baby", "Cigarettes After Sex", "2V6TKMc8dKNzSO6wnMBxkq"),
    ("Cigarettes After Sex", "Sunsetz",                       "Cigarettes After Sex", "6DVFV7TkOcixUiWgpBFyPv"),
    ("Cigarettes After Sex", "Affection",                     "Cigarettes After Sex", "3EFbToN9dJcbFymJFNaLkH"),
    ("Cigarettes After Sex", "K.",                            "Cigarettes After Sex", "0O9KMBpH2JFb5LlIFt0lGH"),

    # NIKI
    ("NIKI", "Indigo",         "Moonchild",                "1yNHpNGOBMDFQ8D9FVWijc"),
    ("NIKI", "Backburner",     "Moonchild",                "3bRgQrKKhBqQxBRpxQSgpH"),
    ("NIKI", "La La Lost You", "Wanna Take This Downtown?","3wIBiaNYNQLzZZ0sX2IQNZ"),
    ("NIKI", "Before",         "Moonchild",                "5aUxMDMwwJMrXJxZiMtfnL"),

    # Planetshakers
    ("Planetshakers", "Endless Praise", "Endless Praise", "5eOFBsHoFKHUwqaTMOVRkR"),
    ("Planetshakers", "Champion",       "Champion",       "3FMGMYXnzSOCxDgxHqXhSO"),
    ("Planetshakers", "Overflow",       "Overflow",       "1jRzBIindDzCBCOMN1sKRT"),

    # The Weeknd
    ("The Weeknd", "Blinding Lights",   "After Hours",              "0VjIjW4GlUZAMYd2vXMi3b"),
    ("The Weeknd", "Starboy",           "Starboy",                  "7MXVkk9YMctZqd1Srtv4MB"),
    ("The Weeknd", "Save Your Tears",   "After Hours",              "5QO79kh1waicV47BqGRL3g"),
    ("The Weeknd", "Can't Feel My Face","Beauty Behind the Madness","7f0vVL3xi4i78Rv5Ptn2s1"),
    ("The Weeknd", "Die For You",       "Starboy",                  "2LMkwUfqC6S6s6qDVlEe6H"),
    ("The Weeknd", "Snowchild",         "After Hours",              "6nNhjDEgbOR4kAPDAMXoJZ"),
]

def fetch_image_id(track_id: str) -> str | None:
    """
    Fetch the real Spotify album image ID using Spotify's public oEmbed endpoint.
    No API key needed. Returns the image hash (e.g. ab67616d00001e02xxxx...)
    """
    try:
        url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            thumbnail_url = r.json().get("thumbnail_url", "")
            # thumbnail_url: https://i.scdn.co/image/ab67616d00001e02XXXXXXXX
            if "/image/" in thumbnail_url:
                return thumbnail_url.split("/image/")[-1]
    except Exception as e:
        print(f"{Fore.YELLOW}[!] oEmbed fetch failed for {track_id}: {e}")
    return None

def preload_image_ids(playlist: list) -> dict:
    """
    At startup, fetch real album image IDs for all unique track IDs.
    Returns a dict: {track_id: image_id}
    """
    cache = {}
    seen  = set()
    total = sum(1 for entry in playlist if entry[3] not in seen and not seen.add(entry[3]))
    done  = 0

    print(f"{Fore.CYAN}[i] Fetching real album art for {total} tracks...")

    for entry in playlist:
        track_id = entry[3]
        if track_id in cache:
            continue

        image_id = fetch_image_id(track_id)
        done += 1

        if image_id:
            cache[track_id] = image_id
            print(f"{Fore.GREEN}  [{done}/{total}] ✓ {entry[0]} — {entry[1]}")
        else:
            cache[track_id] = None
            print(f"{Fore.YELLOW}  [{done}/{total}] ✗ {entry[0]} — {entry[1]} (no image, will skip album art)")

    print(f"{Fore.GREEN}[+] Album art loaded: {sum(1 for v in cache.values() if v)}/{total} succeeded.\n")
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

# Fetch all real album image IDs at startup
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
        "timestamps": {
            "start": start_ms,
            "end":   end_ms,
        },
        "sync_id":    track_id,
        "session_id": f"{random.randint(10**15, 10**16)}",
        "flags":      48,
        "party":      {"id": f"spotify:{USERID}"},
    }

    # Only add album art assets if we got a real image ID
    if image_id:
        spotify_activity["assets"] = {
            "large_image": f"spotify:{image_id}",
            "large_text":  album,
        }

    return {
        "op": 3,
        "d": {
            "since":  0,
            "status": STATUS,
            "afk":    False,
            "activities": [
                # Custom status — clock
                {
                    "type":  4,
                    "name":  "Custom Status",
                    "id":    "custom",
                    "state": f"{emoji} {time_str}",
                },
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
                try:
                    hello = json.loads(raw_hello)
                except Exception:
                    print(f"{Fore.YELLOW}[!] Could not decode HELLO.")
                    raise

                hb_interval = hello["d"]["heartbeat_interval"]
                print(f"{Fore.GREEN}[+] Connected. Heartbeat: {hb_interval} ms")

                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": token,
                        "properties": {
                            "$os":      "Android",
                            "$browser": "Discord Android",
                            "$device":  "Android",
                        },
                        "presence": {"status": status, "afk": False},
                    },
                }
                await ws.send(json.dumps(identify_payload))
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
                        print(f"{Fore.YELLOW}[!] Heartbeat error: {e}")
                        raise

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
                                    if candidate != last_entry:
                                        break
                                    candidate = random.choice(PLAYLIST)
                                current_entry = candidate
                                last_entry    = current_entry
                                song_timer    = SONG_INTERVAL

                            artist, song, album, track_id = current_entry
                            payload  = build_payload(current_entry)
                            local_dt, tz = uk_now()

                            print(
                                f"{Fore.MAGENTA}[~] Clock: {local_dt.hour:02d}:{local_dt.minute:02d} {tz}  "
                                f"| Spotify: {artist} — {song}  [{album}]  "
                                f"(next in {song_timer}s)"
                            )

                            await ws.send(json.dumps(payload, ensure_ascii=False))
                            await asyncio.sleep(30)
                            song_timer -= 30

                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Presence loop error: {e}")
                        raise

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
                                print(f"{Fore.GREEN}[i] READY received.")
                                if not ready_event.is_set():
                                    ready_event.set()

                            if op == 9:
                                raise Exception("Invalid Session (op 9)")

                            d = msg.get("d") or {}
                            if isinstance(d, dict) and d.get("code") in (4003, 4004):
                                raise Exception(f"Auth failure (code {d['code']})")

                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Recv loop error: {e}")
                        raise

                tasks = [
                    asyncio.create_task(heartbeat_loop()),
                    asyncio.create_task(presence_loop()),
                    asyncio.create_task(recv_loop()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

                for t in pending:
                    t.cancel()
                for t in done:
                    if not t.cancelled():
                        exc = t.exception()
                        if exc is not None:
                            raise exc

        except Exception as e:
            print(f"{Fore.RED}[-] Error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

async def main():
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")

    print(f"{Fore.WHITE}[{Fore.LIGHTGREEN_EX}+{Fore.WHITE}] Logged in as "
          f"{Fore.LIGHTBLUE_EX}{USERNAME}#{DISCRIM} {Fore.WHITE}({USERID})")

    if HAVE_KEEP_ALIVE:
        try:
            keep_alive()
            print(f"{Fore.GREEN}[i] keep_alive() started")
        except Exception:
            pass

    await onliner(TOKEN, STATUS)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[i] Exiting.")
        raise
