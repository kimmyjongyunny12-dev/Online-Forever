# discord_clock_spotify.py
# - Shows current UK time (GMT/BST) as custom status
# - Shows fake Spotify "Listening to..." rich presence with your playlist
# - Updates clock every minute, changes song every SONG_INTERVAL seconds
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
STATUS         = "online"       # online / dnd / idle
SONG_INTERVAL  = 60             # seconds before song changes (min 30 to avoid spam)
GATEWAY        = "wss://gateway.discord.gg/?v=10&encoding=json"
# ----------------------

# UK timezone (auto handles GMT/BST)
def uk_now():
    """Return current datetime in UK local time (accounts for BST/GMT)."""
    utc_now = datetime.now(timezone.utc)
    # BST: last Sunday of March 01:00 UTC → last Sunday of October 01:00 UTC
    year = utc_now.year
    # Find last Sunday of March
    march_31 = datetime(year, 3, 31, 1, 0, tzinfo=timezone.utc)
    bst_start = march_31 - timedelta(days=march_31.weekday() + 1 if march_31.weekday() != 6 else 0)
    # Find last Sunday of October
    oct_31 = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
    bst_end = oct_31 - timedelta(days=oct_31.weekday() + 1 if oct_31.weekday() != 6 else 0)

    if bst_start <= utc_now < bst_end:
        return utc_now + timedelta(hours=1), "BST"
    else:
        return utc_now, "GMT"

def clock_emoji(hour24):
    """Return the matching clock emoji for a given hour."""
    clocks = {
        0:  "🕛", 1:  "🕐", 2:  "🕑", 3:  "🕒", 4:  "🕓", 5:  "🕔",
        6:  "🕕", 7:  "🕖", 8:  "🕗", 9:  "🕘", 10: "🕙", 11: "🕚",
        12: "🕛", 13: "🕐", 14: "🕑", 15: "🕒", 16: "🕓", 17: "🕔",
        18: "🕕", 19: "🕖", 20: "🕗", 21: "🕘", 22: "🕙", 23: "🕚",
    }
    return clocks.get(hour24, "🕛")

# ---- YOUR PLAYLIST ----
PLAYLIST = [
    # Chase Atlantic
    ("Chase Atlantic", "Phases"),
    ("Chase Atlantic", "Friends"),
    ("Chase Atlantic", "Into It"),
    ("Chase Atlantic", "Okay"),
    ("Chase Atlantic", "Consume"),
    ("Chase Atlantic", "Swim"),
    # beabadoobee
    ("beabadoobee", "Coffee"),
    ("beabadoobee", "Care"),
    ("beabadoobee", "Last Day on Earth"),
    ("beabadoobee", "Sorry"),
    ("beabadoobee", "Together"),
    # Sugar Cane
    ("Sugar Cane", "Deja Vu"),
    ("Sugar Cane", "Head in the Clouds"),
    ("Sugar Cane", "Bittersweet"),
    # Dec Avenue
    ("Dec Avenue", "Kung 'Di Rin Lang Ikaw"),
    ("Dec Avenue", "Sana"),
    ("Dec Avenue", "Sa Susunod Na Habang Buhay"),
    ("Dec Avenue", "Caught in the Middle"),
    # Lana Del Rey
    ("Lana Del Rey", "Summertime Sadness"),
    ("Lana Del Rey", "Video Games"),
    ("Lana Del Rey", "Young and Beautiful"),
    ("Lana Del Rey", "Born to Die"),
    ("Lana Del Rey", "Ride"),
    ("Lana Del Rey", "Cherry"),
    # TV Girl
    ("TV Girl", "Not Allowed"),
    ("TV Girl", "Blue Hair"),
    ("TV Girl", "Taking What's Not Yours"),
    ("TV Girl", "Louise"),
    ("TV Girl", "Pantomime"),
    # Cigarettes After Sex
    ("Cigarettes After Sex", "Apocalypse"),
    ("Cigarettes After Sex", "Nothing's Gonna Hurt You Baby"),
    ("Cigarettes After Sex", "Sunsetz"),
    ("Cigarettes After Sex", "Affection"),
    ("Cigarettes After Sex", "K."),
    # NIKI
    ("NIKI", "Indigo"),
    ("NIKI", "Backburner"),
    ("NIKI", "La La Lost You"),
    ("NIKI", "Oceans & Engines"),
    ("NIKI", "Before"),
    # Planetshakers
    ("Planetshakers", "Endless Praise"),
    ("Planetshakers", "Champion"),
    ("Planetshakers", "Even Greater"),
    ("Planetshakers", "Overflow"),
    # The Weeknd
    ("The Weeknd", "Blinding Lights"),
    ("The Weeknd", "Starboy"),
    ("The Weeknd", "Save Your Tears"),
    ("The Weeknd", "Can't Feel My Face"),
    ("The Weeknd", "Die For You"),
    ("The Weeknd", "Snowchild"),
]

# TOKEN
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print(f"{Fore.RED}[!] TOKEN environment variable not found. Exiting.")
    sys.exit(1)

HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}

try:
    resp = requests.get("https://canary.discordapp.com/api/v9/users/@me", headers=HEADERS, timeout=8)
except Exception as e:
    print(f"{Fore.YELLOW}[!] Network error while validating token: {e}")
    sys.exit(1)

if resp.status_code != 200:
    print(f"{Fore.RED}[!] Token validation failed (status {resp.status_code}). Exiting.")
    sys.exit(1)

user      = resp.json()
USERNAME  = user.get("username", "unknown")
DISCRIM   = user.get("discriminator", "0000")
USERID    = user.get("id", "unknown")

def build_payload(artist: str, song: str) -> dict:
    """Build the op 3 presence payload with clock + fake Spotify."""
    local_dt, tz_name = uk_now()
    hour   = local_dt.hour
    minute = local_dt.minute
    emoji  = clock_emoji(hour)
    time_str = f"{hour:02d}:{minute:02d} {tz_name}"

    # Fake Spotify: track position simulated with timestamps
    # start = now - random elapsed, end = start + fake duration (3~5 min)
    now_ms       = int(datetime.now(timezone.utc).timestamp() * 1000)
    elapsed_ms   = random.randint(10_000, 60_000)           # 10s–60s in already
    duration_ms  = random.randint(180_000, 300_000)         # 3–5 min song length
    start_ms     = now_ms - elapsed_ms
    end_ms       = start_ms + duration_ms

    return {
        "op": 3,
        "d": {
            "since": 0,
            "status": STATUS,
            "afk": False,
            "activities": [
                # Custom status — clock
                {
                    "type": 4,
                    "name": "Custom Status",
                    "id":   "custom",
                    "state": f"{emoji} {time_str}",
                },
                # Fake Spotify
                {
                    "type":    2,
                    "name":    "Spotify",
                    "id":      "spotify:1",
                    "details": song,
                    "state":   artist,
                    "assets": {
                        "large_image": "spotify:ab67616d00001e02" + "4e0f04c37b7e9e1c44e1d3e7",
                        "large_text":  song,
                    },
                    "timestamps": {
                        "start": start_ms,
                        "end":   end_ms,
                    },
                    "flags": 48,
                    "party": {"id": f"spotify:{USERID}"},
                    "sync_id": f"{random.randint(10**15, 10**16)}",
                },
            ],
        },
    }

async def onliner(token: str, status: str):
    last_song  = None
    current_song = random.choice(PLAYLIST)

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
                    nonlocal current_song, last_song
                    try:
                        await ready_event.wait()
                        await asyncio.sleep(0.8)

                        song_timer = 0  # seconds since last song change

                        while True:
                            # Change song every SONG_INTERVAL seconds
                            if song_timer <= 0:
                                candidate = random.choice(PLAYLIST)
                                # avoid repeating same song
                                for _ in range(4):
                                    if candidate != last_song:
                                        break
                                    candidate = random.choice(PLAYLIST)
                                current_song = candidate
                                last_song    = current_song
                                song_timer   = SONG_INTERVAL

                            artist, song = current_song
                            payload      = build_payload(artist, song)
                            local_dt, tz = uk_now()

                            print(
                                f"{Fore.MAGENTA}[~] Clock: {local_dt.hour:02d}:{local_dt.minute:02d} {tz}  "
                                f"| Spotify: {artist} — {song}  "
                                f"(next song in {song_timer}s)"
                            )

                            await ws.send(json.dumps(payload, ensure_ascii=False))

                            await asyncio.sleep(30)  # update clock every 30s
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
