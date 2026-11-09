# telegram-history-export

Export the **full message history** of any Telegram channel/group you can read to JSON — **even when the chat has "Export chat history" disabled** (content protection / restricted saving).

No app registration on [my.telegram.org](https://my.telegram.org), no phone number, no login code: the tool **reuses the login session of your locally installed Telegram Desktop** (`tdata`) and reads history directly from Telegram's servers via [Telethon](https://github.com/LonamiWebs/Telethon), using the official Telegram Desktop API identity.

> 中文说明见下文。

## How it works

1. `tg_session.py` reads the authorization keys Telegram Desktop already stores locally (`tdata/key_datas` + per-account files) and converts them into Telethon session files (`tg_acc0.session`, `tg_acc1.session`, ...). Your tdata is copied read-only and never modified. Telegram Desktop is closed briefly while copying (file locks).
2. `tg_export.py` uses that session to page through the entire history with `messages.GetHistory` and writes JSON. The server-side "content protection" flag only restricts the official clients' export/forward UI — it does not restrict reading history through the API.
3. `tg_tl_patch.py` registers the newer `channel#7ad15240` TL constructor (with `flags2`, `pinned_msg_id`, ...) that Telethon ≤1.45 cannot parse yet, so history export doesn't crash on current servers.
4. `opentele_fixes.py` contains runtime fixes for [opentele](https://github.com/thedemons/opentele) 1.15.1 (2022) so it can read tdata written by current Telegram Desktop versions (new map key types, api setter recursion bug).

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.8+ (tested on 3.12, Windows) and Telegram Desktop installed and logged in.

## Usage

```bash
# 1. create Telethon sessions from your local Telegram Desktop login
python tg_session.py                          # auto-detects tdata
python tg_session.py --proxy socks5://127.0.0.1:10808   # if Telegram is blocked

# 2. export a chat (title / @username / t.me link / numeric id all work)
python tg_export.py @channel_name
python tg_export.py "Channel Title" --session tg_acc1   # pick another account
python tg_export.py @channel_name --download-media      # also save photos/files
```

Output goes to `exports/<chat>/`:

- `result.json` — final JSON: chat info + `messages` array (id, date, text, links incl. hidden URLs behind anchor text, views, forwards, replies count, reactions, reply-to, grouped albums, forward origin, media file name/type/size, inline buttons, service actions)
- `messages.jsonl` — checkpoint, appended while fetching; **re-running the command resumes** where it stopped (also useful for incremental updates)
- `media/` — only with `--download-media`

## Notes & limitations

- **Keep `*.session` and `tdata_copy/` private** — they are full login tokens for your account.
- If your tdata has a **local passcode** set, remove it first (opentele cannot decrypt it).
- Entity `offset`/`length` follow Telegram's UTF-16 convention (same as the official export); the included `text` slice may be off by a character next to emoji.
- Flood-wait is handled automatically (up to 5 min sleeps); a large channel exports at roughly 3–5k messages/minute as text-only.
- Tested against Telegram servers as of 2026-11. If Telegram adds new TL constructors, you may need to extend `tg_tl_patch.py`.

## Disclaimer

This tool is for archiving chats you already have legitimate access to. Circumventing a channel's content-protection may violate its owner's wishes and Telegram's Terms of Service. Exported content may be copyrighted — for personal use only, do not redistribute. Use at your own risk; the authors take no responsibility.

---

# telegram-history-export（中文）

导出任何你有权阅读的 Telegram 频道/群组的**全部历史消息**为 JSON —— **即使该频道禁用了"导出聊天记录"**（内容保护）。

无需在 my.telegram.org 注册应用、无需手机号和验证码：直接**复用本机 Telegram Desktop 的登录态**（`tdata`），以官方桌面客户端的 API 身份通过 Telethon 从服务器读取历史。

## 原理

1. `tg_session.py` 读取 Telegram Desktop 本地保存的授权密钥，转换成 Telethon 会话文件（`tg_acc0.session` 等）。tdata 只读复制，不会被修改；复制时会短暂关闭 Telegram Desktop（文件锁）。
2. `tg_export.py` 用该会话通过 `messages.GetHistory` 拉取全部历史。服务端的"内容保护"标记只限制官方客户端的导出/转发界面，不影响 API 读取。
3. `tg_tl_patch.py` 注册了新版 `channel#7ad15240` TL 构造器，避免在当前服务器上解析崩溃。
4. `opentele_fixes.py` 在运行时修复 opentele 1.15.1 与新版 tdata 的两个兼容问题。

## 安装与使用

```bash
pip install -r requirements.txt

python tg_session.py                                     # 自动定位 tdata
python tg_session.py --proxy socks5://127.0.0.1:10808    # 需要代理时

python tg_export.py @频道用户名
python tg_export.py "频道标题" --session tg_acc1          # 多账号时指定
python tg_export.py @频道用户名 --download-media          # 连媒体文件一起下载
```

结果在 `exports/<聊天名>/`：`result.json`（最终结果）、`messages.jsonl`（断点续传存档，重跑即增量更新）、`media/`（可选）。

## 注意

- **`*.session` 和 `tdata_copy/` 等同于账号登录凭证，切勿泄露。**
- 若 tdata 设置了本地密码（local passcode），请先在 Telegram Desktop 里取消。
- 本工具仅供归档你自己有权访问的聊天。绕过内容保护可能违背频道主意愿和 Telegram 服务条款；导出内容可能受版权保护，请仅个人使用。使用风险自负。
