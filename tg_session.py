"""
Convert the local Telegram Desktop login (tdata) into Telethon session files.

No my.telegram.org app, no phone number, no login code: the authorization
keys that Telegram Desktop already stores locally are copied into Telethon
sessions (one per account: tg_acc0.session, tg_acc1.session, ...), using the
official Telegram Desktop API identity.

Usage:
    python tg_session.py                 # auto-detect tdata, no proxy
    python tg_session.py --proxy socks5://127.0.0.1:10808
    python tg_session.py --tdata "D:\\path\\to\\tdata"

Telegram Desktop will be closed while reading (tdata is locked otherwise);
restart it yourself afterwards. The original tdata is never modified.

Keep the generated *.session files private: they are full login tokens.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import opentele_fixes

opentele_fixes.apply()

from opentele.api import API
from opentele.td import TDesktop
from telethon import TelegramClient, functions, types
from telethon.crypto import AuthKey as TelethonAuthKey
from telethon.sessions import SQLiteSession

BASE_DIR = Path(__file__).resolve().parent
DC_IPS = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100",
          4: "149.154.167.91", 5: "91.108.56.130"}


def default_tdata():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Telegram Desktop" / "tdata"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Telegram Desktop/tdata"
    return Path.home() / ".local/share/TelegramDesktop/tdata"


def parse_proxy(url):
    """'socks5://127.0.0.1:10808' -> telethon proxy tuple."""
    if not url:
        return None
    scheme, _, rest = url.partition("://")
    host, _, port = rest.rpartition(":")
    ptype = {"socks5": "socks5", "socks5h": "socks5",
             "http": "http"}.get(scheme.lower())
    if not ptype or not host or not port:
        raise SystemExit(f"无法解析代理地址 / cannot parse proxy: {url}")
    return (ptype, host, int(port))


async def main():
    ap = argparse.ArgumentParser(description="Convert Telegram Desktop tdata to Telethon sessions")
    ap.add_argument("--tdata", default=str(default_tdata()), help="path to the tdata folder")
    ap.add_argument("--proxy", default=None,
                    help="e.g. socks5://127.0.0.1:10808 (needed where Telegram is blocked)")
    args = ap.parse_args()
    proxy = parse_proxy(args.proxy)

    # tdata files are locked while Telegram Desktop runs
    running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Telegram.exe"],
                             capture_output=True, text=True).stdout
    if "Telegram.exe" in running:
        print("closing running Telegram.exe (restart it yourself later)...")
        subprocess.run(["taskkill", "/F", "/IM", "Telegram.exe"], capture_output=True)

    tdata_copy = BASE_DIR / "tdata_copy"

    def ignore(dirpath, names):
        # skip media caches (huge, not needed for the session keys)
        return [n for n in names
                if n in ("dumps", "temp", "tdummy", "emoji", "working", "prefix")
                or n.startswith("user_data")]

    if tdata_copy.exists():
        shutil.rmtree(tdata_copy, ignore_errors=True)
    shutil.copytree(args.tdata, tdata_copy, dirs_exist_ok=True, ignore=ignore)
    print(f"tdata copied to {tdata_copy}")

    tdesk = TDesktop(str(tdata_copy))
    if not tdesk.isLoaded():
        raise SystemExit("cannot read tdata: if a local passcode is set, remove it first")

    for acc in tdesk.accounts:
        if not acc.authKey:
            print(f"account index={acc.index}: no auth key, skipped")
            continue
        name = str(BASE_DIR / f"tg_acc{acc.index}")
        for suffix in ("", "-journal"):
            try:
                os.remove(name + ".session" + suffix)
            except OSError:
                pass
        sess = SQLiteSession(name)
        sess.set_dc(acc.MainDcId, DC_IPS.get(acc.MainDcId, f"149.154.167.{40 + acc.MainDcId}"), 443)
        sess.auth_key = TelethonAuthKey(acc.authKey.key)
        sess.save()
        sess.close()

        client = TelegramClient(name, api=API.TelegramDesktop.copy(), proxy=proxy)
        await client.connect()
        try:
            users = await client(functions.users.GetUsersRequest([types.InputUserSelf()]))
            u = users[0]
            print(f"account index={acc.index}: OK  id={u.id}  "
                  f"name={u.first_name}  @{u.username}")
            sess = SQLiteSession(name)
            sess._self_id = u.id  # so is_user_authorized() works later
            sess.save()
            sess.close()
        except Exception as e:
            print(f"account index={acc.index}: {type(e).__name__}: {e}")
        await client.disconnect()

    print("done. now run: python tg_export.py <chat> --session tg_acc0")


if __name__ == "__main__":
    asyncio.run(main())

