# discord_mobile_emoji_loading.py
# Ready-to-run script:
# - identifies as mobile (Android)
# - every UPDATE_INTERVAL seconds:
#     * generates a list of 50 random emojis (logged to console)
#     * picks one emoji from that list to display in the custom status
#     * appends a 10-step loading bar to the status (e.g. "🔮 [███░░░░░░]")
# - maintains gateway heartbeat, waits for READY before sending presence
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
from colorama import init, Fore

# Optional: if you host on Replit/Glitch and want to keep process alive, provide keep_alive.py
try:
    from keep_alive import keep_alive
    HAVE_KEEP_ALIVE = True
except Exception:
    HAVE_KEEP_ALIVE = False

init(autoreset=True)

# ------- CONFIG -------
STATUS = "online"             # online / dnd / idle
UPDATE_INTERVAL = 60          # seconds between status updates
GATEWAY = "wss://gateway.discord.gg/?v=9&encoding=json"
MAX_SEND_BYTES = 1024 * 1024 - 2048  # keep well under 1 MiB
LOADING_STEPS = 10           # loading bar size (█ x steps)
# ----------------------

# A very large emoji pool (mix of common, weird, decorative)
# FIX: removed all duplicate entries (🛸, 🛠️, 🧪, 🧫, 🧬, 🦠, 🔭, 🧯, 🩺 were each listed twice)
EMOJI_POOL = [
"😀","😃","😄","😁","😆","😅","😂","🤣","🙂","🙃","😉","😊","😇","🥰","😍","🤩","😘","😗","😚","😙",
"😋","😛","😜","🤪","😝","🤑","🤗","🤭","🤫","🤔","🤐","🤨","😐","😑","😶","😏","😒","🙄","😬","🤥",
"😌","😔","😪","🤤","😴","😷","🤒","🤕","🤢","🤮","🥴","😵","🤯","🤠","🥳","😎","🤓","🧐",
"😕","😟","🙁","☹️","😮","😯","😲","😳","🥺","😦","😧","😨","😰","😥","😢","😭","😱","😖","😣",
"😞","😓","😩","😫","🥱","😤","😡","😠","🤬","😈","👿","💀","☠️","👻","👽","👾","🤖","🎃",
"🛸","🪐","🌙","⭐","✨","🔥","⚡","☄️","🌪️","🌈","🌊","❄️","🌋","🧊",
"🧠","🫀","🫁","🦷","🦴","👁️","👀","🧬","🦠","🧫","🧪",
"🗿","🪨","🧱","⚙️","🔩","🔧","🪛","🛠️","⛓️","🧲","🧰",
"🕳️","🪞","🧿","🔮","📡","🛰️","🔭","📟","💾","💿",
"🧭","🪤","🪓","🪃","🪁","🪀","🕹️","🎮","🎲","♟️",
"🍎","🍊","🍌","🍉","🍇","🍓","🍒","🍍","🥝","🥑",
"🍕","🍔","🍟","🌭","🍿","🥓","🍗","🍖","🍤","🍣",
"🚗","🚕","🚙","🚌","🚎","🏎️","🚓","🚑","🚒","🚜",
"🚀","✈️","🛶","⛵","🚤","🛥️","🚢","🚁",
"🏠","🏢","🏫","🏥","🏦","🏛️","🗼","🗽","🏰",
"🎧","🎤","🎹","🥁","🎸","🎻","🎺","🎷","📯","🎼",
"💡","🔦","🕯️","🪔","💎","📦","📚","📖","📜","✉️",
"🧩","🧸","🪆","🪅","🎈","🎁","🎗️","🏆","🥇","🥈",
"⚽","🏀","🏈","⚾","🎾","🏐","🏉","🥏","🎳","🏓",
"🔒","🗝️","🔑","🧯","🩺","💊","🩹",
"📺","📻","📷","📸","📹","🎥","🔍","🔎",
"🛎️","🧴","🧷","🧹","🧺","🪣","🧻","🪑","🛋️","🛏️",
"⚖️","🔬",
# add more if you like...
]

# TOKEN must be set in environment variables
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print(f"{Fore.RED}[!] TOKEN environment variable not found. Exiting.")
    sys.exit(1)

HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}

# quick validate
try:
    resp = requests.get("https://canary.discordapp.com/api/v9/users/@me", headers=HEADERS, timeout=8)
except Exception as e:
    print(f"{Fore.YELLOW}[!] Network error while validating token: {e}")
    sys.exit(1)

if resp.status_code != 200:
    print(f"{Fore.RED}[!] Token validation failed (status {resp.status_code}). Exiting.")
    sys.exit(1)

user = resp.json()
USERNAME = user.get("username", "unknown")
DISCRIM = user.get("discriminator", "0000")
USERID = user.get("id", "unknown")

# helper: generate a list of n random emojis (without replacement if possible)
def make_emoji_list(n=50):
    pool = EMOJI_POOL.copy()
    chosen = []
    if len(pool) >= n:
        chosen = random.sample(pool, n)
    else:
        # not enough unique emojis: sample with replacement
        for _ in range(n):
            chosen.append(random.choice(pool))
    return chosen

async def onliner(token: str, status: str):
    last_display_emoji = None
    loading_index = 0

    while True:
        try:
            async with websockets.connect(GATEWAY, ping_interval=None) as ws:
                raw_hello = await ws.recv()
                try:
                    hello = json.loads(raw_hello)
                except Exception:
                    print(f"{Fore.YELLOW}[!] Could not decode HELLO payload.")
                    raise

                hb_interval = hello["d"]["heartbeat_interval"]
                print(f"{Fore.GREEN}[+] Connected to gateway. Heartbeat interval: {hb_interval} ms")

                # Identify as Android mobile
                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": token,
                        "properties": {
                            "$os": "Android",
                            "$browser": "Discord Android",
                            "$device": "Android"
                        },
                        # presence optional; we will update after READY
                        "presence": {"status": status, "afk": False}
                    }
                }
                await ws.send(json.dumps(identify_payload))
                print(f"{Fore.CYAN}[>] Sent IDENTIFY (Android). Waiting for READY...")

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

                async def status_loop():
                    nonlocal last_display_emoji, loading_index
                    try:
                        await ready_event.wait()
                        await asyncio.sleep(0.8)  # small buffer
                        while True:
                            # generate 50-random-emoji list (console only)
                            emoji_list = make_emoji_list(50)

                            # pick a display emoji from that list, avoid repeating same emoji twice
                            display_emoji = random.choice(emoji_list)
                            if display_emoji == last_display_emoji:
                                # try to pick a different one (up to a few times)
                                for _ in range(4):
                                    candidate = random.choice(emoji_list)
                                    if candidate != last_display_emoji:
                                        display_emoji = candidate
                                        break

                            last_display_emoji = display_emoji

                            # loading bar progress (cycles 0..LOADING_STEPS)
                            loading_index = (loading_index + 1) % (LOADING_STEPS + 1)
                            filled = "█" * loading_index
                            empty = "░" * (LOADING_STEPS - loading_index)
                            bar = f"[{filled}{empty}]"

                            # Compose state: single emoji + space + loading bar
                            state_text = f"{display_emoji} {bar}"

                            # Safety: ensure final payload is small
                            cstatus = {
                                "op": 3,
                                "d": {
                                    "since": 0,
                                    "activities": [
                                        {
                                            "type": 4,            # custom status
                                            "state": state_text,  # text shown under name
                                            "name": "Custom Status",
                                            "id": "custom"
                                        }
                                    ],
                                    "status": status,
                                    "afk": False
                                }
                            }

                            payload = json.dumps(cstatus, ensure_ascii=False)
                            payload_bytes = payload.encode("utf-8")
                            if len(payload_bytes) > MAX_SEND_BYTES:
                                # FIX: actually truncate the state text, not reassign the same value
                                truncated_state = f"{display_emoji} {bar}"[:120]
                                cstatus["d"]["activities"][0]["state"] = truncated_state
                                payload = json.dumps(cstatus, ensure_ascii=False)
                                payload_bytes = payload.encode("utf-8")
                                print(f"{Fore.YELLOW}[!] Payload was oversized, truncated state.")

                            # log the generated 50 emoji list compactly
                            try:
                                compact_list = "".join(emoji_list)
                            except Exception:
                                compact_list = str(emoji_list)

                            print(f"{Fore.MAGENTA}[~] Sending status: {state_text}  (payload {len(payload_bytes)} bytes)")
                            print(f"{Fore.WHITE}[i] Emoji list (50): {compact_list}")

                            await ws.send(payload)
                            await asyncio.sleep(UPDATE_INTERVAL)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Status loop error: {e}")
                        raise

                async def recv_loop():
                    try:
                        while True:
                            raw = await ws.recv()
                            # try decode; ignore frames we can't parse
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                # could be binary or compressed frames — ignore
                                continue

                            op = msg.get("op")

                            # READY -> allow presence updates
                            if op == 0 and msg.get("t") == "READY":
                                print(f"{Fore.GREEN}[i] Received READY from gateway.")
                                if not ready_event.is_set():
                                    ready_event.set()

                            # FIX: op 9 = Invalid Session (not op 1, which is heartbeat).
                            # Also handle explicit 4003/4004 auth-failure codes in the payload.
                            if op == 9:
                                raise Exception("Gateway reported Invalid Session (op 9)")

                            d = msg.get("d") or {}
                            if isinstance(d, dict) and d.get("code") in (4003, 4004):
                                raise Exception(f"Gateway auth failure (code {d['code']})")

                            # keep looping
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"{Fore.YELLOW}[!] Recv loop error: {e}")
                        raise

                tasks = [
                    asyncio.create_task(heartbeat_loop()),
                    asyncio.create_task(status_loop()),
                    asyncio.create_task(recv_loop())
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

                # Cancel all pending tasks first
                for t in pending:
                    t.cancel()

                # FIX: guard against cancelled tasks before calling .exception(),
                # and store the exception before re-raising to avoid calling it twice.
                for t in done:
                    if not t.cancelled():
                        exc = t.exception()
                        if exc is not None:
                            raise exc

        except Exception as e:
            print(f"{Fore.RED}[-] Connection ended / error: {e}. Reconnecting in 5s...")
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
