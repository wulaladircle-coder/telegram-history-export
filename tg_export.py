"""
Export the full message history of a Telegram channel/group to JSON via the
Telegram API (Telethon). Also works for chats where the desktop client's
"Export chat history" is disabled (restricted content), because reading
history through the API is not affected by that flag.

Prerequisite: run tg_session.py once to create session files (tg_acc0.session,
...) from your local Telegram Desktop login.

Usage:
    python tg_export.py "Channel Title"                # match by title
    python tg_export.py @some_username                 # username / t.me link / id
    python tg_export.py @channel_name --session tg_acc1   # pick another account
    python tg_export.py @channel_name --download-media    # also save photos/files
    python tg_export.py @channel_name --proxy socks5://127.0.0.1:10808

Output (under exports/<chat>/):
    messages.jsonl   - checkpoint, appended as messages are fetched (resumable)
    result.json      - final JSON, written when the export finishes
    media/           - only with --download-media
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.tl import types

import tg_tl_patch  # noqa: F401  register newer TL constructors (channel#7ad15240)

BASE_DIR = Path(__file__).resolve().parent

# avoid UnicodeEncodeError when printing emoji titles on a GBK console/pipe
sys.stdout.reconfigure(errors="replace")


def parse_proxy(url):
    """'socks5://127.0.0.1:10808' -> telethon proxy tuple."""
    if not url:
        return None
    scheme, _, rest = url.partition("://")
    host, _, port = rest.rpartition(":")
    ptype = {"socks5": "socks5", "socks5h": "socks5",
             "http": "http"}.get(scheme.lower())
    if not ptype or not host or not port:
        raise SystemExit(f"cannot parse proxy: {url}")
    return (ptype, host, int(port))


def json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def entity_to_dict(e, text):
    item = {
        "type": type(e).__name__.replace("MessageEntity", "").lower(),
        "offset": e.offset,
        "length": e.length,
        "text": text[e.offset:e.offset + e.length] if text else None,
    }
    if isinstance(e, types.MessageEntityTextUrl):
        item["url"] = e.url
    return item


def reactions_to_list(msg):
    r = getattr(msg, "reactions", None)
    if not r or not r.results:
        return []
    out = []
    for rc in r.results:
        reaction = rc.reaction
        if isinstance(reaction, types.ReactionEmoji):
            key = reaction.emoticon
        elif isinstance(reaction, types.ReactionCustomEmoji):
            key = f"custom:{reaction.document_id}"
        else:
            key = type(reaction).__name__
        out.append({"reaction": key, "count": rc.count})
    return out


def media_info(msg):
    m = msg.media
    if m is None:
        return None
    info = {"type": type(m).__name__.replace("MessageMedia", "").lower()}
    if msg.file:
        info.update({
            "file_name": msg.file.name,
            "mime_type": msg.file.mime_type,
            "size": msg.file.size,
        })
    if isinstance(m, types.MessageMediaWebPage) and isinstance(m.webpage, types.WebPage):
        info.update({"url": m.webpage.url, "title": m.webpage.title,
                     "description": m.webpage.description})
    return info


def message_to_dict(msg):
    text = msg.message or ""
    fwd = None
    if msg.fwd_from:
        fwd = {
            "from_id": utils.get_peer_id(msg.fwd_from.from_id) if msg.fwd_from.from_id else None,
            "from_name": msg.fwd_from.from_name,
            "date": msg.fwd_from.date,
        }
    buttons = None
    if msg.buttons:
        buttons = [[{"text": b.text, "url": getattr(b, "url", None)} for b in row]
                   for row in msg.buttons]
    return {
        "id": msg.id,
        "type": "service" if isinstance(msg, types.MessageService) else "message",
        "date": msg.date,
        "edit_date": getattr(msg, "edit_date", None),
        "from_id": msg.sender_id,
        "post_author": getattr(msg, "post_author", None),
        "text": text,
        "entities": [entity_to_dict(e, text) for e in (msg.entities or [])],
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "replies": msg.replies.replies if getattr(msg, "replies", None) else None,
        "reactions": reactions_to_list(msg),
        "reply_to_msg_id": msg.reply_to_msg_id,
        "grouped_id": getattr(msg, "grouped_id", None),
        "forwarded_from": fwd,
        "media": media_info(msg),
        "buttons": buttons,
        "action": type(msg.action).__name__ if isinstance(msg, types.MessageService) else None,
    }


async def resolve_chat(client, target):
    # username / link / numeric id first
    try:
        return await client.get_entity(int(target) if target.lstrip("-").isdigit() else target)
    except (ValueError, TypeError):
        pass
    # fall back to exact (then partial) title match among dialogs
    exact, partial = [], []
    async for d in client.iter_dialogs():
        if d.name == target:
            exact.append(d)
        elif target.lower() in (d.name or "").lower():
            partial.append(d)
    matches = exact or partial
    if not matches:
        sys.exit(f"chat not found: {target}")
    if len(matches) > 1:
        print("multiple chats matched, using the first; pass an id to pick another:")
        for d in matches:
            print(f"  id={d.id}  {d.name}")
    return matches[0].entity


def read_jsonl(jsonl_path):
    """Yield saved messages; skips a partially written last line after a crash."""
    if not jsonl_path.exists():
        return
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass



async def main():
    ap = argparse.ArgumentParser(description="Export Telegram chat history to JSON")
    ap.add_argument("chat", help="chat title / @username / t.me link / numeric id")
    ap.add_argument("--session", default="tg_acc0", help="session file name (no .session)")
    ap.add_argument("--proxy", default=None, help="e.g. socks5://127.0.0.1:10808")
    ap.add_argument("--download-media", action="store_true", help="also download photos/files")
    args = ap.parse_args()

    from opentele.api import API  # reuse the desktop-client identity from tdata

    client = TelegramClient(
        str(BASE_DIR / args.session),
        api=API.TelegramDesktop.copy(),
        proxy=parse_proxy(args.proxy),
        flood_sleep_threshold=300,  # auto-sleep on FloodWait up to 5 min
    )
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit(f"session {args.session}.session is not authorized, run tg_session.py first")

    chat = await resolve_chat(client, args.chat)
    title = utils.get_display_name(chat)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip() or str(chat.id)
    out_dir = BASE_DIR / "exports" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "messages.jsonl"
    media_dir = out_dir / "media"

    min_id = max((m["id"] for m in read_jsonl(jsonl_path)), default=0)
    total = (await client.get_messages(chat, limit=0)).total
    print(f"exporting: {title} (id={chat.id}), ~{total} messages on server, resuming from id>{min_id}")

    count = 0
    with jsonl_path.open("a", encoding="utf-8") as f:
        async for msg in client.iter_messages(chat, reverse=True, min_id=min_id, wait_time=1):
            data = message_to_dict(msg)
            if (args.download_media and msg.media
                    and not isinstance(msg.media, types.MessageMediaWebPage)):
                media_dir.mkdir(exist_ok=True)
                try:
                    path = await msg.download_media(file=str(media_dir / f"{msg.id}_"))
                    if path and data["media"] is not None:
                        data["media"]["local_path"] = os.path.relpath(path, out_dir)
                except Exception as e:  # keep exporting text even if one file fails
                    print(f"  media download failed id={msg.id}: {e}")
            f.write(json.dumps(data, ensure_ascii=False, default=json_default) + "\n")
            count += 1
            if count % 500 == 0:
                f.flush()
                print(f"  exported {count} (current id={msg.id}, {data['date']})")

    messages = {m["id"]: m for m in read_jsonl(jsonl_path)}  # dedupe by id
    result = {
        "name": title,
        "id": chat.id,
        "username": getattr(chat, "username", None),
        "type": type(chat).__name__.lower(),
        "exported_at": datetime.now().isoformat(),
        "messages": [messages[k] for k in sorted(messages)],
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: +{count} new, {len(messages)} total -> {result_path}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

