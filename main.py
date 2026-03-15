# discord_mobile_status.py
import os
import sys
import json
import asyncio
import platform
import random
import requests
import websockets
from colorama import init, Fore

# Optional: keep_alive if you have a webserver to keep process alive (e.g., Replit)
try:
    from keep_alive import keep_alive
    HAVE_KEEP_ALIVE = True
except Exception:
    HAVE_KEEP_ALIVE = False

init(autoreset=True)

# CONFIG
STATUS = "online"                # online / dnd / idle
UPDATE_INTERVAL = 600            # seconds between status updates (600 = 10 minutes)
GATEWAY = "wss://gateway.discord.gg/?v=9&encoding=json"

# Weird emojis (obscure / aesthetic)
EMOJIS = [
    "🛸","👁️","🕳️","⚗️","🪐","🕸️","🧬","🪦","☢️","☣️",
    "🗿","🪞","🧪","🧿","🪤","🪵","🦠","🧹","🩸","🩻",
    "⚰️","☄️","🛠️","🛎️","🧲","🧱","🧊","🧸","🦴","🧭",
    "🪃","🪁","🪀","🕹️","🕳️"
]

# Simple, one-word activities that describe what you're doing
PHRASES = [
    "ruminating",      # thinking deeply
    "cogitating",      # meditating/thinking
    "perambulating",   # walking slowly
    "speculating",     # thinking/guessing
    "contemplating",   # deep thought
    "oscillating",     # moving back and forth
    "meandering",      # wandering
    "fluctuating",     # varying
    "concocting",      # devising/creating
    "ruminative",      # thoughtful, introspective
    "pondering",       # thinking deeply
    "musing",          # reflective thought
    "interpolating",   # estimating between data points
    "juxtaposing",     # comparing side by side
    "cogitating",      # deep thinking
    "enumerating",     # counting, listing
    "reverberating",   # echoing, resonating
    "perceiving",      # noticing, sensing
    "calculating",     # mentally computing
    "oscillatory",     # swinging, back-and-forth
    "disambiguating",  # clarifying
    "synthesizing",    # combining ideas
    "deciphering",     # figuring out
    "perusing",        # reading carefully
    "delineating",     # describing precisely
    "juxtaposition",   # act of placing side by side
    "transmuting",     # transforming
    "inferring",       # deducing
    "abstracting",     # conceptualizing
    "evanescing",      # fading away
    "specifying",      # identifying precisely
    "introspecting",   # self-reflecting
    "postulating",     # hypothesizing
    "oscillate",       # swing back and forth
    "differentiating", # distinguishing
    "metamorphosing",  # transforming
    "catalyzing",      # causing change
    "ruminatory",      # reflective
]

# Get token from environment
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print(f"{Fore.WHITE}[{Fore.RED}-{Fore.WHITE}] Please set TOKEN in environment variables.")
    sys.exit(1)

headers = {"Authorization": TOKEN, "Content-Type": "application/json"}

# Validate token quickly
try:
    r = requests.get("https://canary.discordapp.com/api/v9/users/@me", headers=headers, timeout=8)
except Exception as e:
    print(f"{Fore.WHITE}[{Fore.RED}!{Fore.WHITE}] Network error while validating token: {e}")
    sys.exit(1)

if r.status_code != 200:
    print(f"{Fore.WHITE}[{Fore.RED}-{Fore.WHITE}] Token invalid or request blocked (status {r.status_code}).")
    sys.exit(1)

user = r.json()
USERNAME = user.get("username", "unknown")
DISCRIM = user.get("discriminator", "0000")
USERID = user.get("id", "unknown")

async def onliner(token: str, status: str):
    while True:
        try:
            async with websockets.connect(GATEWAY, ping_interval=None) as ws:
                # Receive HELLO
                hello = json.loads(await ws.recv())
                hb_interval = hello["d"]["heartbeat_interval"]  # milliseconds
                print(f"{Fore.GREEN}[+] Connected to gateway. Heartbeat interval: {hb_interval} ms")

                # Identify as mobile
                identify = {
                    "op": 2,
                    "d": {
                        "token": token,
                        "properties": {
                            "$os": "Android",
                            "$browser": "Discord Android",
                            "$device": "Android"
                        },
                        # presence here is optional; we'll push presence updates separately
                        "presence": {"status": status, "afk": False},
                    }
                }
                await ws.send(json.dumps(identify))
                print(f"{Fore.CYAN}[>] Sent IDENTIFY (mobile)")

                # helper loops
                async def heartbeat_loop():
                    try:
                        while True:
                            await asyncio.sleep(hb_interval / 1000)
                            await ws.send(json.dumps({"op": 1, "d": None}))
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # Let outer scope handle reconnect
                        print(f"{Fore.YELLOW}[!] Heartbeat loop error: {exc}")
                        raise

                async def status_loop():
                    try:
                        # initial small delay to let identify settle
                        await asyncio.sleep(1.5)
                        while True:
                            emoji = random.choice(EMOJIS)
                            phrase = random.choice(PHRASES)
                            cstatus = {
                                "op": 3,
                                "d": {
                                    "since": 0,
                                    "activities": [
                                        {
                                            "type": 4,                # custom status
                                            "state": phrase,         # the one-word phrase
                                            "name": "Custom Status",
                                            "id": "custom",
                                            "emoji": {
                                                "name": emoji,
                                                "id": None,
                                                "animated": False
                                            }
                                        }
                                    ],
                                    "status": status,
                                    "afk": False
                                }
                            }
                            await ws.send(json.dumps(cstatus))
                            print(f"{Fore.MAGENTA}[~] Updated status: {emoji} {phrase}")
                            await asyncio.sleep(UPDATE_INTERVAL)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        print(f"{Fore.YELLOW}[!] Status loop error: {exc}")
                        raise

                async def recv_loop():
                    # read incoming events so the server doesn't consider us idle/unresponsive
                    try:
                        while True:
                            msg = await ws.recv()
                            # We don't need to process everything; just keep the connection alive.
                            # Optionally ack or handle opcodes here.
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        print(f"{Fore.YELLOW}[!] Recv loop error: {exc}")
                        raise

                # Run loops concurrently; if any fails, cancel others and reconnect
                tasks = [
                    asyncio.create_task(heartbeat_loop()),
                    asyncio.create_task(status_loop()),
                    asyncio.create_task(recv_loop()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                # if we get here, one task raised; cancel others
                for t in pending:
                    t.cancel()
                # raise first exception so outer try handles reconnect
                for t in done:
                    if t.exception():
                        raise t.exception()

        except Exception as e:
            print(f"{Fore.RED}[-] Connection ended or error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
            continue

async def main():
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")
    print(f"{Fore.WHITE}[{Fore.LIGHTGREEN_EX}+{Fore.WHITE}] Logged in as {Fore.LIGHTBLUE_EX}{USERNAME}#{DISCRIM} {Fore.WHITE}({USERID})")
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
        print(f"\n{Fore.YELLOW}[i] Exiting by user request.")
        raise
