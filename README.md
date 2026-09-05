# Instagram Reel Downloader Bot

Telegram bot for downloading Instagram reels, with a fully dynamic admin
panel — menus, buttons, images, premium plans, tickets, broadcasts and more
are all stored in `bot_data.json` (or MongoDB) and edited live from inside
Telegram, never hardcoded.

## Setup

```bash
pip install -r requirements.txt
export BOT_TOKEN="123456:ABC-your-bot-token"
export OWNER_ID="123456789"

# optional
export MONGO_URI="mongodb+srv://..."
export BACKUP_INTERVAL_HOURS="12"

python3 main.py
```

## Project structure

| File | Responsibility |
|---|---|
| `config.py` | Env vars, paths, logging, optional-dependency detection, QR code generation |
| `storage.py` | Text styling, keyboards, default menu/settings schema, data load/save, MongoDB, backups, admin/premium/rate-limit checks |
| `helpers.py` | Logging, notifications, uptime/system stats, menu rendering engine, onboarding gate |
| `handlers_user.py` | `/start`, `/help`, language, reel downloads, Instagram monitor, AI-check |
| `handlers_billing.py` | Usage screen, support tickets, premium plans, Stars/UPI payments, text-input routing |
| `admin_panel.py` | Full admin panel — home, activity, users/groups, broadcast, menu editor, settings, admins, access control, danger zone |
| `handlers_admin_text.py` | Admin text/media input routing |
| `export_backup.py` | Backups, database export, `/export`, `/ping`, unknown-command/error handling, Mongo plugin |
| `main.py` | Application setup and entry point |

## Notes

- `bot_data.json` holds all live bot data — do not commit it.
- `backup.key` (created automatically if `cryptography` is installed) and
  `mongo_config.json` hold secrets and are excluded from both `.gitignore`
  and the in-bot `/export` zip.
