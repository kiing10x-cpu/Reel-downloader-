from config import *


START_TIME = time.time()

INSTAGRAM_URL_RE = re.compile(
    r"(https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_\-]+/?\S*)"
)


def _is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def _message_mentions_this_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True when a message explicitly tags this bot. Useful in groups where
    privacy mode is disabled and we must never answer unrelated chatter."""
    try:
        username = (context.bot.username or "").lower()
    except Exception:
        username = ""
    text = (update.effective_message.text or "").lower() if update.effective_message else ""
    return bool(username and f"@{username}" in text)


def _safe_filename(value: str, fallback: str = "Instagram_Audio") -> str:
    value = re.sub(r'[\\/:*?"<>|]+', " ", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value[:80] or fallback)

# ----------------------------------------------------------------------------
# Unicode "style" helpers (#1 — Style Text)
# ----------------------------------------------------------------------------

SMALL_CAPS_MAP = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
}


def to_small_caps(text: str) -> str:
    """Bot-wide house style: Initial Capital + Unicode small caps.

    Every normal user/admin UI string that passes through this helper now
    follows the same typography, e.g. ``Stats & Activity`` ->
    ``Sᴛᴀᴛꜱ & Aᴄᴛɪᴠɪᴛʏ``. This keeps old generated messages from drifting
    between plain lowercase and all-small-caps styles.
    """
    out = []
    word_start = True
    for ch in str(text):
        if ch.isalpha() and ch.isascii():
            if word_start:
                out.append(ch.upper())
                word_start = False
            else:
                out.append(SMALL_CAPS_MAP.get(ch.lower(), ch))
        else:
            out.append(ch)
            # Start a new styled word after whitespace/punctuation, but not
            # after an already-styled Unicode small-cap glyph.
            word_start = not (ch.isalnum() or ch in "'’")
    return "".join(out)


def to_title_small_caps(text: str) -> str:
    """Alias for the single bot-wide Initial-Capital small-caps house style."""
    return to_small_caps(text)


# ----------------------------------------------------------------------------
# v2 build prompt — centralized small-caps strings (Section 10)
# ----------------------------------------------------------------------------
STR = {
    "processing": to_small_caps("processing your reel...") + "\n📥 " + to_small_caps("fetching") + " • 🔄 "
                  + to_small_caps("optimizing") + " • ✅ " + to_small_caps("almost done"),
    "done": "✅ " + to_small_caps("your reel is ready!") + "\n🎬 " + to_small_caps("saved and sent below"),
    "usage_title": to_small_caps("usage overview"),
    "how_to_use": (
        "<blockquote>"
        "𝐇𝐎𝐖 𝐓𝐎 𝐔𝐒𝐄\n\n"
        "➤ Cᴏᴘʏ ᴀɴʏ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟ ʟɪɴᴋ\n\n"
        "➤ Pᴀsᴛᴇ ᴛʜᴇ ʟɪɴᴋ ʜᴇʀᴇ ɪɴ ᴄʜᴀᴛ\n\n"
        "➤ Wᴀɪᴛ ᴀ ғᴇᴡ sᴇᴄᴏɴᴅs\n\n"
        "➤ Gᴇᴛ ʏᴏᴜʀ Rᴇᴇʟ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ɪɴsᴛᴀɴᴛʟʏ\n\n"
        "➤ 𝐍𝐎𝐓𝐄 : Oɴʟʏ Pᴜʙʟɪᴄ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟ ʟɪɴᴋs ᴀʀᴇ sᴜᴘᴘᴏʀᴛᴇᴅ"
        "</blockquote>"
    ),
    "support_prompt": to_small_caps("describe your issue (text/photo/video)"),
    "ticket_created": lambda tid: "✅ " + to_small_caps(f"ticket #{tid} created. we'll reply soon"),
    "ticket_closed": lambda tid: "🔒 " + to_small_caps(f"ticket #{tid} closed. need help again? tap") + " 🎧 " + to_small_caps("support"),
}

# Wrapped in to_small_caps() right here (not just at render time) so the
# `if rkb_action == "download":` string-matching in handle_text() still lines up
# with what the reply-keyboard button actually sends back — to_small_caps()
# is idempotent (re-applying it to already-styled text is a safe no-op), so
# this can't get out of sync with styled_kb_button()'s own wrapping below.
RKB_DOWNLOAD = to_title_small_caps("Download Reel")
RKB_USAGE = to_title_small_caps("My Usage")
RKB_GIFT = to_title_small_caps("Send A Gift")
RKB_LANGUAGE = to_title_small_caps("Language")
RKB_DEVELOPER = to_title_small_caps("Developer")
RKB_HOWTO = to_title_small_caps("How To Use")
RKB_SUPPORT = to_title_small_caps("Support")
RKB_ADMINPANEL = to_title_small_caps("Admin Panel")


def main_reply_keyboard(is_admin_user: bool = False, lang: str = None) -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard, localized to the user's selected language.

    The callback/routing identifiers remain the same; only the visible labels
    change. This keeps existing bot functionality intact while making the
    whole persistent keyboard follow the selected language."""
    labels = _get_rkb_labels(lang)
    rows = [
        [styled_kb_button(labels["download"], style="success")],
        [styled_kb_button(labels["usage"], style="primary"), styled_kb_button(labels["gift"], style="primary")],
        [styled_kb_button(labels["language"], style="primary"), styled_kb_button(labels["developer"], style="primary")],
        [styled_kb_button(labels["howto"], style="danger"), styled_kb_button(labels["support"], style="danger")],
    ]
    if is_admin_user:
        rows.append([styled_kb_button(labels["admin"], style="primary")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)



def _map_alpha_digit(text: str, upper_base: int, lower_base: int, digit_base=None) -> str:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(upper_base + (ord(ch) - ord("A"))))
        elif "a" <= ch <= "z":
            out.append(chr(lower_base + (ord(ch) - ord("a"))))
        elif digit_base and "0" <= ch <= "9":
            out.append(chr(digit_base + (ord(ch) - ord("0"))))
        else:
            out.append(ch)
    return "".join(out)


def to_bold_sans(text: str) -> str:
    return _map_alpha_digit(text, 0x1D5D4, 0x1D5EE, 0x1D7EC)


def to_bold_italic_sans(text: str) -> str:
    return _map_alpha_digit(text, 0x1D63C, 0x1D656, 0x1D7EC)


# -----------------------------------------------------------------------------
# User-facing error messages
# -----------------------------------------------------------------------------
# Keep technical exceptions (yt-dlp / ffmpeg / Telegram / network details)
# in the server/admin logs only. Users should always receive short, clean
# messages in the same typography as the rest of the bot UI.
USER_ERR_WRONG_FORMAT = (
    "❌ I" + to_small_caps("nvalid ") + "L" + to_small_caps("ink") + "\n\n"
    + "T" + to_small_caps("he link you sent is not a valid ")
    + "I" + to_small_caps("nstagram ") + "R" + to_small_caps("eel link.") + "\n\n"
    + "P" + to_small_caps("lease send a valid reel link to continue.") + "\n"
    + "F" + to_small_caps("or help, contact ") + "S" + to_small_caps("upport.")
)

USER_ERR_NOT_AVAILABLE = (
    "<blockquote>❌ " + to_title_small_caps("Not Available") + "\n\n"
    + to_title_small_caps("This Reel Can't Be Downloaded Right Now.") + "\n"
    + to_title_small_caps("Please Try Again Later Or Contact Support.")
    + "</blockquote>"
)


USER_ERR_AUDIO_NOT_AVAILABLE = (
    "<blockquote>❌ " + to_title_small_caps("Audio Not Available") + "\n\n"
    + to_title_small_caps("This Reel Doesn't Have An Audio Track To Extract.") + "\n"
    + to_title_small_caps("Please Try Again Later Or Contact Support.")
    + "</blockquote>"
)


USER_ERR_GENERIC = (
    "❌ " + to_bold_sans("Something went wrong") + "\n\n"
    + to_small_caps("Please try again later or contact support.")
)


def to_monospace(text: str) -> str:
    return _map_alpha_digit(text, 0x1D670, 0x1D68A, 0x1D7F6)


def to_fullwidth(text: str) -> str:
    out = []
    for ch in text:
        if ch == " ":
            out.append("\u3000")
        elif "!" <= ch <= "~":
            out.append(chr(ord(ch) + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def to_deco(text: str) -> str:
    return f"『 {text} 』"


STYLE_OPTIONS = [
    ("Small Caps", to_small_caps),
    ("Bold", to_bold_sans),
    ("Bold Italic", to_bold_italic_sans),
    ("Monospace", to_monospace),
    ("Fullwidth", to_fullwidth),
    ("Decorative", to_deco),
]

# ----------------------------------------------------------------------------
# Native colorful buttons (Bot API 9.4+ `style` field) — graceful fallback
# ----------------------------------------------------------------------------

try:
    InlineKeyboardButton(text="probe", callback_data="probe", style="primary")
    SUPPORTS_BUTTON_STYLE = True
except TypeError:
    SUPPORTS_BUTTON_STYLE = False
    log.warning(
        "Installed python-telegram-bot does not support button `style` "
        "(needs v22.7+). Colorful buttons will fall back to default look. "
        "Run: pip install -U python-telegram-bot"
    )

try:
    KeyboardButton(text="probe", style="primary")
    SUPPORTS_KB_BUTTON_STYLE = True
except TypeError:
    SUPPORTS_KB_BUTTON_STYLE = False


def premium_button_text(text: str) -> str:
    """First alphabetic character of EVERY word uppercase, rest of that
    word in small caps — same house style as to_title_small_caps(), used
    as the single place every button (inline + reply-keyboard) gets its
    typography from. Idempotent, so pre-styled constants stay stable even
    after passing through this a second time at render."""
    return to_title_small_caps(str(text))


# House style (requested): every inline button shows its emoji/icon at the
# END of the label instead of at the front — "Support Settings 🛠" instead
# of "🛠 Support Settings". Rather than hand-editing every one of the
# hundreds of styled_button(...) call sites across the file, this is done
# once, centrally, inside styled_button() itself, so it automatically
# applies to every button everywhere (top-level Admin Panel, every
# submenu, every confirm/cancel row, etc.) with zero risk of missing one.
_EMOJI_CHAR_RE = re.compile(
    "[\U0001F000-\U0001FFFF\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)


def _move_emoji_to_end(text: str) -> str:
    """If `text` starts with one or more emoji (optionally separated by
    single spaces, e.g. '✅ 🛠 Label'), strip that leading emoji run and
    re-attach it to the end of the label instead: 'Label ✅ 🛠'. Text with
    no leading emoji, or that is emoji-only, is returned unchanged."""
    text = str(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if _EMOJI_CHAR_RE.match(ch):
            i += 1
        elif ch == " " and i + 1 < n and _EMOJI_CHAR_RE.match(text[i + 1]):
            i += 1
        else:
            break
    prefix, rest = text[:i].strip(), text[i:].strip()
    if not prefix or not rest:
        return text
    return f"{rest} {prefix}"


def styled_button(text, callback_data=None, url=None, style=None):
    """Central inline-button renderer with premium typography."""
    kwargs = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if style and SUPPORTS_BUTTON_STYLE:
        kwargs["style"] = style
    return InlineKeyboardButton(premium_button_text(_move_emoji_to_end(text)), **kwargs)


# ---- Activity Log: categorization + plain-English fix hints -----------------
# Every entry logged to BOT_DATA["error_log"] carries a "kind" so the panel
# can show *what* went wrong, *why* it likely happened, and *how* to fix it —
# instead of a raw, undated exception string nobody but a developer could
# read.
ERROR_KIND_INFO = {
    "force_join": (
        "🔒 Force-Join Check",
        "Couldn't verify a user's membership in the force-join channel.",
        "Make sure the bot is an admin in that channel, and that the "
        "channel is set correctly (use @username, or the -100... id for "
        "private channels) in Settings & Admins → Force-Join.",
    ),
    "broadcast": (
        "📢 Broadcast Delivery",
        "A message failed to send during a broadcast.",
        "Usually harmless — the recipient blocked the bot or never started "
        "a DM. Check the Broadcast Log for the full breakdown.",
    ),
    "mongo": (
        "🗄 Database",
        "Couldn't reach or sync with MongoDB.",
        "Check the connection string is correct (via Admin Panel > 🍭 "
        "Update Backup > 🗄 Mongo Plugin, or the MONGO_URI env var) and that the "
        "database allows connections from this server's IP. The bot keeps "
        "working on local storage meanwhile, so nothing is lost.",
    ),
    "download": (
        "⬇️ Download",
        "A reel/audio download failed.",
        "Usually the link was private, deleted, or Instagram briefly "
        "rate-limited the server. Ask the user to retry in a minute.",
    ),
    "conflict": (
        "⚔️ Duplicate Bot Instance",
        "Telegram rejected polling because another process is already "
        "polling with this same BOT_TOKEN.",
        "Stop the other running copy of this bot (an old deployment, a "
        "second terminal, a duplicate server) — only one instance can poll "
        "at a time. This can't be fixed from inside this process, since "
        "the conflicting instance is the other one.",
    ),
    "unhandled": (
        "🐞 Unexpected Error",
        "Something failed outside the usual error handling.",
        "Check the message below for the exact exception — if it keeps "
        "repeating for the same action, that action likely has a bug.",
    ),
}


def log_error(kind: str, detail: str) -> None:
    """Central place every part of the bot reports a problem to. Keeps the
    Activity Log screen consistent (same field names, always categorized)
    instead of every call site hand-rolling its own dict shape."""
    entries = BOT_DATA.setdefault("error_log", [])
    next_id = BOT_DATA.get("error_log_next_id", 1)
    entries.append({
        "id": next_id,
        "time": datetime.utcnow().isoformat(),
        "kind": kind if kind in ERROR_KIND_INFO else "unhandled",
        "detail": str(detail)[:400],
    })
    BOT_DATA["error_log_next_id"] = next_id + 1
    if len(entries) > 200:
        del entries[: len(entries) - 200]


def _short_btn_label(label: str, limit: int = 22) -> str:
    """Trims a long button label in admin list screens (e.g. Manage
    Buttons) so the row stays readable on a phone instead of the button
    text overflowing/getting cut off by Telegram."""
    label = str(label)
    return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"


def toggle_label(base: str, is_on: bool) -> str:
    """Consistent ON/OFF rendering for every toggle button in the admin
    panel — a green tick when ON, a red cross when OFF, instead of the bare
    'ON'/'OFF' text every toggle used to hand-roll separately."""
    return f"{base}: {'✅ ON' if is_on else '❌ OFF'}"


def styled_kb_button(text, style=None):
    """Reply-keyboard button renderer with premium typography."""
    text = premium_button_text(text)
    if style and SUPPORTS_KB_BUTTON_STYLE:
        return KeyboardButton(text, style=style)
    return KeyboardButton(text)


# ----------------------------------------------------------------------------
# Default data / menu records (#1, #2, #4, #7)
# ----------------------------------------------------------------------------


DEFAULT_MENUS = {
    "start": {
        "text": (
            "<blockquote>"
            "Hᴇʟʟᴏ, {username}!\n\n"
            "𝐖𝐄𝐋𝐂𝐎𝐌𝐄 ᴛᴏ {bot_link}\n\n"
            "Yᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟ ᴀssɪsᴛᴀɴᴛ.\n\n"
            "𝐓𝐇𝐈𝐒 𝐁𝐎𝐓 𝐂𝐀𝐍\n\n"
            "<u>➤ Dᴏᴡɴʟᴏᴀᴅ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟs</u>\n\n"
            "<u>➤ Gᴇᴛ Rᴇᴇʟ Cᴀᴘᴛɪᴏɴs</u>\n\n"
            "<u>➤ Gᴇᴛ Rᴇᴇʟ Aᴜᴅɪᴏ</u>\n\n"
            "𝐖𝐇𝐘 𝐂𝐇𝐎𝐎𝐒𝐄 𝐔𝐒?\n\n"
            "<u>➤ Nᴏ Wᴀᴛᴇʀᴍᴀᴋs</u>\n\n"
            "<u>➤ Hɪɢʜ-Qᴜᴀʟɪᴛʏ Rᴇᴇʟ Dᴏᴡɴʟᴏᴀᴅs</u>\n\n"
            "<u>➤ Fᴀsᴛ ᴀɴᴅ Sᴍᴏᴏᴛʜ Sᴇʀᴠɪᴄᴇ</u>\n\n"
            "<u>➤ Hᴀssʟᴇ-Fʀᴇᴇ ᴀɴᴅ Eᴀsʏ ᴛᴏ Uꜱᴇ</u>\n\n"
            "<u>➤ Sᴀᴠᴇs Tɪᴍᴇ ᴀɴᴅ Eғғᴏʀᴛ</u>\n\n"
            "<u>➤ Rᴇᴇʟ, Cᴀᴘᴛɪᴏɴ ᴀɴᴅ Aᴜᴅɪᴏ ɪɴ Oɴᴇ Pʟᴀᴄᴇ</u>\n\n"
            "<u>➤ Nᴏ Exᴛʀᴀ Tᴏᴏʟs ᴏʀ Cᴏᴍᴘʟɪᴄᴀᴛᴇᴅ Sᴛᴇᴘs</u>"
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "help_user": {
        "text": (
            f"{to_deco(to_small_caps('guide'))}\n\n"
            f"<u>➤ {to_small_caps('send a reel link')}</u>\n"
            f"<u>➤ {to_small_caps('get it in best quality')}</u>\n"
            f"<u>➤ {to_small_caps('tap get caption for a short quote')}</u>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "reel_result": {
        "text": STR["done"],
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [
            {"label": to_small_caps("📝 caption"), "type": "callback", "value": "get_caption", "row": 1, "style": "primary"},
            {"label": to_small_caps("🎵 audio"), "type": "callback", "value": "get_audio", "row": 1, "style": "primary"},
        ],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "disclaimer": {
        "text": (
            "<blockquote expandable>"
            "<b>Disclaimer &amp; Terms of Use</b>\n\n"
            "This bot is a general-purpose media-downloading tool provided for "
            "personal and fair-use purposes only. It does not host, store, own, "
            "or claim any rights over the content it retrieves.\n\n"
            "By using this bot, you confirm that:\n"
            "• You have the necessary rights or permissions to download the "
            "content you request, or that your use qualifies as fair use / "
            "fair dealing under applicable law.\n"
            "• You will not use this bot to download, redistribute, or "
            "republish copyrighted material without the rights holder's consent.\n"
            "• You are solely and fully responsible for how you use any content "
            "obtained through this bot.\n\n"
            "The bot operator does not monitor, endorse, or verify the "
            "ownership of any content requested by users, and accepts no "
            "liability for any misuse, copyright infringement, or violation of "
            "third-party rights arising from your use of this service. Files "
            "are delivered directly to you and are not permanently stored on "
            "the bot's servers.\n\n"
            "This service is provided \"as is\", without warranty of any kind, "
            "and may be modified, suspended, or discontinued at any time "
            "without prior notice. Continued use of this bot after any "
            "changes to these terms constitutes acceptance of the updated "
            "terms.\n\n"
            "Tap <b>Agree &amp; Continue</b> to confirm you have read and "
            "accepted these terms."
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [
            {"label": "✅ Agree & Continue", "type": "callback", "value": "agree_terms", "row": 1, "style": "success"}
        ],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "maintenance": {
        "text": (
            "ᴛʜᴇ ʙᴏᴛ ɪꜱ ᴛᴇᴍᴘᴏʀᴀʀɪʟʏ ᴏꜰꜰʟɪɴᴇ ꜰᴏʀ\n"
            "ꜱᴄʜᴇᴅᴜʟᴇᴅ ᴜᴘɢʀᴀᴅᴇꜱ ᴀɴᴅ ɪᴍᴘʀᴏᴠᴇᴍᴇɴᴛꜱ.\n\n"
            "ᴡᴇ'ʀᴇ ᴡᴏʀᴋɪɴɢ ᴛᴏ ᴍᴀᴋᴇ ᴛʜᴇ ʙᴏᴛ\n"
            "ꜰᴀꜱᴛᴇʀ, ꜱᴍᴏᴏᴛʜᴇʀ ᴀɴᴅ ʙᴇᴛᴛᴇʀ\n"
            "ꜰᴏʀ ᴇᴠᴇʀʏᴏɴᴇ.\n\n"
            "⏳ ᴡᴇ'ʟʟ ʙᴇ ʙᴀᴄᴋ ꜱʜᴏʀᴛʟʏ.\n\n"
            "ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ʏᴏᴜʀ\n"
            "ᴘᴀᴛɪᴇɴᴄᴇ & ꜱᴜᴘᴘᴏʀᴛ."
        ),
        "parse_mode": None,
        "image_file_id": None,
        "buttons": [
            {"label": "🔔 " + to_small_caps("notify me"), "type": "callback", "value": "maint_notify_me", "row": 1, "style": "danger"}
        ],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "bot_live": {
        "text": (
            "✅ 𝐁𝐎𝐓 𝐈𝐒 𝐋𝐈𝐕𝐄\n\n"
            "ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ɪꜱ ᴄᴏᴍᴘʟᴇᴛᴇ — ᴛʜᴇ ʙᴏᴛ ɪꜱ ʙᴀᴄᴋ ᴜᴘ ᴀɴᴅ ʀᴜɴɴɪɴɢ ɴᴏʀᴍᴀʟʟʏ.\n\n"
            "🚀 ᴇᴠᴇʀʏᴛʜɪɴɢ ɪꜱ ʙᴀᴄᴋ ᴏɴʟɪɴᴇ ᴀɴᴅ ʀᴇᴀᴅʏ ᴛᴏ ᴜꜱᴇ.\n\n"
            "ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴡᴀɪᴛɪɴɢ.\n\n"
            "ᴇɴᴊᴏʏ ᴛʜᴇ ɪᴍᴘʀᴏᴠᴇᴍᴇɴᴛꜱ. ✨"
        ),
        "parse_mode": None,
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "help_admin": {
        "text": (
            "<blockquote>"
            "<u>❓ " + to_small_caps("admin help") + "</u>\n\n"
            "<u>➤ " + to_small_caps("📊 stats & activity — view the bot's live numbers") + "</u>\n\n"
            "<u>➤ " + to_small_caps("👥 users & groups — list or message any user") + "</u>\n\n"
            "<u>➤ " + to_small_caps("📢 broadcast — message everyone, with forward-lock") + "</u>\n\n"
            "<u>➤ " + to_small_caps("🎨 menu & ui — edit any menu's text, image or buttons") + "</u>\n\n"
            "<u>➤ " + to_small_caps("⚙️ settings & admins — welcome, admins, maintenance, languages") + "</u>\n\n"
            "<u>➤ " + to_small_caps("📦 update backup — save every live setting + all users to 2 files, so a code update on github never wipes them") + "</u>\n\n"
            "<u>➤ " + to_small_caps("🛑 danger zone — destructive, irreversible actions") + "</u>"
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [
            {"label": "📦 " + to_small_caps("update backup — how it works"), "type": "callback", "value": "help_update_backup_info", "row": 1, "style": "primary"},
            {"label": "🔙 Admin Panel", "type": "callback", "value": "adm_home", "row": 2, "style": "primary"},
        ],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "download": {
        "text": (
            "<blockquote>"
            "𝘞𝘢𝘯𝘵 𝘵𝘰 𝘥𝘰𝘸𝘯𝘭𝘰𝘢𝘥 𝘢 𝘙𝘦𝘦𝘭?\n\n"
            "<u>➤ 𝘊𝘰𝘱𝘺 𝘵𝘩𝘦 𝘙𝘦𝘦𝘭 𝘭𝘪𝘯𝘬 𝘧𝘳𝘰𝘮 𝘐𝘯𝘴𝘵𝘢𝘨𝘳𝘢𝘮</u>\n\n"
            "<u>➤ 𝘗𝘢𝘴𝘵𝘦 𝘵𝘩𝘦 𝘭𝘪𝘯𝘬 𝘩𝘦𝘳𝘦</u>\n\n"
            "𝘛𝘩𝘢𝘵'𝘴 𝘪𝘵 — 𝘐'𝘭𝘭 𝘥𝘰 𝘵𝘩𝘦 𝘳𝘦𝘴𝘵."
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "howto": {
        "text": (
            "<blockquote>"
            "𝐇𝐎𝐖 𝐓𝐎 𝐔𝐒𝐄\n\n"
            "➤ Cᴏᴘʏ ᴀɴʏ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟ ʟɪɴᴋ\n\n"
            "➤ Pᴀsᴛᴇ ᴛʜᴇ ʟɪɴᴋ ʜᴇʀᴇ ɪɴ ᴄʜᴀᴛ\n\n"
            "➤ Wᴀɪᴛ ᴀ ғᴇᴡ sᴇᴄᴏɴᴅs\n\n"
            "➤ Gᴇᴛ ʏᴏᴜʀ Rᴇᴇʟ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ɪɴsᴛᴀɴᴛʟʏ\n\n"
            "➤ 𝐍𝐎𝐓𝐄 : Oɴʟʏ Pᴜʙʟɪᴄ Iɴsᴛᴀɢʀᴀᴍ Rᴇᴇʟ ʟɪɴᴋs ᴀʀᴇ sᴜᴘᴘᴏʀᴛᴇᴅ"
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    # v10 — these 5 are new: the intro banner (and optional image) for each
    # of Send A Gift / Language / Developer / Support / Admin Panel is now
    # admin-editable from Menu & UI too, same as every other menu. Only the
    # BANNER text/image is stored here — the live functional buttons on
    # each screen (Stars/UPI, the language list, the developer contact
    # link, the actual open-a-ticket flow, the admin dashboard's own
    # buttons) stay code-driven and are appended after this banner, since
    # those carry real logic that can't be hand-typed as plain buttons.
    "gift": {
        "text": (
            "<blockquote>"
            "<u>✨ 𝐒𝐔𝐏𝐏𝐎𝐑𝐓 𝐎𝐔𝐑 𝐁𝐎𝐓</u>\n\n"
            "<u>➤ Tʜɪꜱ ꜱᴜᴘᴘᴏʀᴛ ɪꜱ ᴄᴏᴍᴘʟᴇᴛᴇʟʏ ᴏᴘᴛɪᴏɴᴀʟ.</u>\n"
            "<u>➤ Wᴇ ɴᴇᴠᴇʀ ꜰᴏʀᴄᴇ ᴀɴʏᴏɴᴇ ᴛᴏ ꜱᴇɴᴅ ᴀ ᴘᴀʏᴍᴇɴᴛ.</u>\n\n"
            "<u>➤ Iꜰ ʏᴏᴜ ᴇɴᴊᴏʏ ᴜꜱɪɴɢ ᴛʜᴇ ʙᴏᴛ ᴀɴᴅ ᴡᴀɴᴛ ᴛᴏ ꜱᴜᴘᴘᴏʀᴛ ɪᴛ,</u> "
            "<u>ʏᴏᴜ ᴄᴀɴ ᴄᴏɴᴛʀɪʙᴜᴛᴇ ᴀɴʏ ᴀᴍᴏᴜɴᴛ ʏᴏᴜ ᴘʀᴇꜰᴇʀ.</u>\n\n"
            "<u>➤ Yᴏᴜʀ ꜱᴜᴘᴘᴏʀᴛ ʜᴇʟᴘꜱ ᴜꜱ ᴋᴇᴇᴘ ᴡᴏʀᴋɪɴɢ ᴏɴ ᴛʜᴇ ʙᴏᴛ, ɪᴍᴘʀᴏᴠɪɴɢ "
            "ᴇxɪꜱᴛɪɴɢ ꜰᴇᴀᴛᴜʀᴇꜱ, ᴀᴅᴅɪɴɢ ɴᴇᴡ ꜰᴜɴᴄᴛɪᴏɴꜱ ᴀɴᴅ ʙʀɪɴɢɪɴɢ ᴍᴏʀᴇ ᴜꜱᴇꜰᴜʟ ᴜᴘɢʀᴀᴅᴇꜱ.</u>\n\n"
            "Wᴇ ꜱɪɴᴄᴇʀᴇʟʏ ᴀᴘᴘʀᴇᴄɪᴀᴛᴇ ᴇᴠᴇʀʏ ʙɪᴛ ᴏꜰ ꜱᴜᴘᴘᴏʀᴛ. ❤️"
            "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "language": {
        "text": "🌐 <u>" + to_small_caps("choose your language:") + "</u>",
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "developer": {
        "text": "<u>➤ " + to_small_caps("tap below to message the developer:") + "</u>",
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "support": {
        "text": (
            "<blockquote>"
            + "<u>" + to_title_small_caps("Please type your message below.") + "</u>\n\n"
            + "<u>🛠️ " + to_title_small_caps("Report a problem") + "</u>\n"
            + "<u>💡 " + to_title_small_caps("Share your feedback") + "</u>\n"
            + "<u>❓ " + to_title_small_caps("Ask a question") + "</u>\n"
            + "💭 " + to_title_small_caps("Suggest a feature") + "\n\n"
            + to_title_small_caps("We'll review your message and get back to you as soon as possible.")
            + "</blockquote>"
        ),
        "parse_mode": "HTML",
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
    "admin": {
        "text": f"│ {to_title_small_caps('Admin Dashboard')} │",
        "parse_mode": None,
        "image_file_id": None,
        "buttons": [],
        "auto_delete_seconds": None,
        "updated_by": None,
        "updated_at": None,
        "translations": {},
    },
}

# ----------------------------------------------------------------------------
# language_pack.json — ships next to bot.py with ready-made translations
# (10 languages) for the language picker plus real per-menu text for start,
# language, and (a shorter) disclaimer, howto, gift, support, developer,
# download. Loaded once at import time and merged into DEFAULT_MENUS so
# fresh installs have working translations out of the box — and again at
# runtime in load_data() so already-deployed bots pick it up too, without
# ever overwriting a translation an admin has since customized by hand.
# Missing/corrupt file is never fatal — the bot just falls back to the
# untranslated (English) text, same as before this file existed.
# ----------------------------------------------------------------------------
_LANGUAGE_PACK_CACHE = None


def _load_language_pack() -> dict:
    global _LANGUAGE_PACK_CACHE
    if _LANGUAGE_PACK_CACHE is not None:
        return _LANGUAGE_PACK_CACHE
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "language_pack.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            pack = json.load(f)
        if not isinstance(pack, dict):
            raise ValueError("language_pack.json is not a JSON object")
        _LANGUAGE_PACK_CACHE = pack
    except FileNotFoundError:
        _LANGUAGE_PACK_CACHE = {}
    except Exception as e:
        log.warning("language_pack.json present but couldn't be read/parsed (%s) — continuing without it.", e)
        _LANGUAGE_PACK_CACHE = {}
    return _LANGUAGE_PACK_CACHE


def _get_rkb_labels(lang: str = None) -> dict:
    """Return localized persistent reply-keyboard labels.

    Falls back to English if the selected language is unavailable or the
    optional keyboard section is missing from an older language pack.
    """
    pack = _load_language_pack()
    all_labels = pack.get("reply_keyboard", {})
    selected = all_labels.get(lang) if lang else None
    selected = selected if isinstance(selected, dict) else all_labels.get("en", {})
    fallback = {
        "download": RKB_DOWNLOAD, "usage": RKB_USAGE, "gift": RKB_GIFT,
        "language": RKB_LANGUAGE, "developer": RKB_DEVELOPER,
        "howto": RKB_HOWTO, "support": RKB_SUPPORT, "admin": RKB_ADMINPANEL,
    }
    for key, value in fallback.items():
        if not selected.get(key):
            selected[key] = value
    return selected


def _rkb_action_for_text(text: str, lang: str = None):
    """Map a localized reply-keyboard label back to its stable action key."""
    labels = _get_rkb_labels(lang)
    for action, label in labels.items():
        if text == label or text == to_title_small_caps(label):
            return action
    # Keep old/English keyboards working after an update.
    legacy = {
        RKB_DOWNLOAD: "download", RKB_USAGE: "usage", RKB_GIFT: "gift",
        RKB_LANGUAGE: "language", RKB_DEVELOPER: "developer",
        RKB_HOWTO: "howto", RKB_SUPPORT: "support", RKB_ADMINPANEL: "admin",
    }
    return legacy.get(text)


def _apply_language_pack_to_menus(menus: dict) -> None:
    """Fills in menu[lang] translations that are missing, for every menu the
    pack covers. Never overwrites a translation that's already there (so an
    admin's own edit, or a previous run's merge, always wins)."""
    pack = _load_language_pack()
    for menu_id, per_lang in pack.get("menus", {}).items():
        menu = menus.get(menu_id)
        if not menu or not isinstance(per_lang, dict):
            continue
        translations = menu.setdefault("translations", {})
        for lang, content in per_lang.items():
            # "en" is deliberately never stored as a translation — English
            # always falls through to the base text written in bot.py
            # (see DEFAULT_MENUS), even if language_pack.json ships an
            # "en" entry of its own.
            if lang == "en":
                continue
            if lang not in translations and isinstance(content, dict) and content.get("text"):
                translations[lang] = {"text": content["text"]}


# Populate DEFAULT_MENUS itself at import time, so brand-new installs (no
# saved bot_data.json / Mongo doc yet) start with working translations.
_apply_language_pack_to_menus(DEFAULT_MENUS)

DEFAULT_DATA = {
    "users": {},
    "groups": {},
    "admins": [OWNER_ID] if OWNER_ID else [],
    # Granular admin access — str(admin_id) -> [permission_key, ...]. An
    # admin with NO entry here (i.e. added before this feature existed) is
    # treated as full-access, so nobody already trusted silently loses
    # access. Only admins added from now on get an explicit, owner-chosen
    # list. See ADMIN_PERMISSIONS / get_admin_perms() / has_admin_perm().
    "admin_permissions": {},
    "blocked": [],
    "menus": json.loads(json.dumps(DEFAULT_MENUS)),
    "settings": {
        "maintenance": False,
        "protect_broadcasts": True,
        "global_auto_delete_seconds": 0,
        "small_caps_buttons_default": True,
        "auto_replies": {},
        "rate_limit_max": 20,
        "rate_limit_window_seconds": 60,
        "inactive_reengage_days": 0,
        # Pre-populated from language_pack.json (minus "en", which is
        # always shown anyway) so the language picker has real options out
        # of the box. Admin can still add/remove languages in Settings >
        # Languages as before — this is just the starting default.
        "languages": [c for c in _load_language_pack().get("languages", {}) if c != "en"],
        "lock_all_content": False,  # master forwarding/sharing lock
        "logger_channel_id": None,  # dedicated logger channel
        "logger_enabled": False,
        "owner_display_user_id": None,  # credit/contact button
        "owner_display_label": None,
        "support_chat_id": None,  # where support messages land; None = all admins
        "premium_enabled": False,
        "upi_id": None,
        "developer_id": None,
        "developer_link": None,
        "daily_limit": 20,
        "admin_group_id": None,   # ticket cards posted here
        "owner_id": None,         # /export gate
        "force_join_channel": None,   # legacy single force-join target
        "force_join_channels": [],   # [{"chat_id": @username/-100id or None, "link": https://...}]
        "force_join_request_verified": {}, # user_id -> [channel keys] accepted via join request
        "send_as_document": False,    # send reels as document instead of video
        "document_mode_threshold_mb": 45,  # auto-switch to document above this size
        "premium_plans": [],  # admin-defined plans: {id, name, days, price_inr, price_stars, enabled}
        "detailed_join_alerts": True,  # new-user/group-start full details -> admin DMs + logger
        "user_activity_dm": True,      # every reel-link a user sends -> owner DM (misuse monitoring)
        "notify_route": "all",         # where the Reel-Delivered activity card goes: logger | activity | dm | all
        "leaderboard_enabled": False,  # admin toggle — top-donor ranking shown inside Send Gift
        "share_enabled": True,         # admin toggle — "📤 Share" button under My Usage
        "share_url": None,             # link the Share button points to; falls back to the bot link
        "share_text": "Try this Instagram Reel Downloader bot.",
        "premium_emoji_enabled": False,   # greeting uses a Premium custom emoji
        "premium_emoji_id": None,         # custom_emoji_id captured from the admin's sample message
        "premium_emoji_char": "🌟",       # fallback glyph shown to non-Premium users automatically
        "activity_channel_id": None,      # dedicated channel for the Reel Delivered card
        "activity_channel_enabled": False,
        # Owner-only Instagram failure monitor / AI Check dashboard.
        "instagram_monitor_threshold": 5,
        "instagram_monitor_window_minutes": 10,
        "instagram_monitor_cooldown_minutes": 60,
        "instagram_monitor_recovery_successes": 3,
        "instagram_monitor_owner_ids": [OWNER_ID] if OWNER_ID else [],
    },
    "broadcast_log": [],
    "activity_log": [],         # ring buffer: {time, user_id, name, username, chat_type, url}
    "restore_log": [],
    "sent_messages": {},        # chat_id (str) -> [message_id, ...] ring buffer, last 200
    "copyright_reports": [],    # DMCA-style user reports
    "blocked_links": [],        # specific links blocked by admin
    "blocked_domains": [],      # whole domains blocked by admin
    "error_log": [],            # capped ring buffer of recent errors
    "metrics": {"reels_downloaded": 0, "audio_gets": 0, "caption_gets": 0, "start_count": 0, "broadcasts_sent": 0},
    # Rolling Instagram-only monitoring state. Old events are pruned automatically.
    "instagram_monitor": {
        "failures": [], "successes": [], "outage_active": False,
        "last_alert_at": None, "last_recovery_at": None,
        "last_error_category": None, "last_error_detail": None,
        "alert_count": 0, "recovery_count": 0,
    },
    "tickets": {},               # ticket_id(str) -> {...}
    "ticket_msg_map": {},        # admin_group_message_id(str) -> ticket_id
    "support_msg_map": {},       # one-shot support admin-message-id(str) -> user_id(str)
    "support_requests": {},      # request_id(str) -> {user_id, chat_id, confirm_chat_id,
                                  #   confirm_message_id, admin_message_ids: [...], status, text, created_at}
    "support_admin_msg_map": {}, # one-shot support admin-message-id(str) -> request_id(str)
    "next_support_id": 100000,   # 6-digit request IDs, e.g. #100000, #100001, ...
    "next_ticket_id": 1,
    "panel_msg": {},              # chat_id(str) -> last panel message_id
    "gift_orders": {},            # order_id(str) -> {...} (UPI pending payments)
    "next_gift_id": 1,
    "next_plan_id": 1,            # admin-defined premium plans
    "donations": {},              # uid(str) -> {"name", "stars", "inr", "score"} — leaderboard source
    "maintenance_notified": [],   # chat_id(int) list — everyone shown the maintenance notice,
                                   # so we know exactly who to ping with BOT_LIVE_TEXT on toggle-off
    "maintenance_notice_msg": {},  # chat_id(str) -> message_id(int) of that chat's LATEST maintenance
                                    # notice — lets us delete the old one before sending a new one
                                    # (no more duplicate notices piling up), and delete it automatically
                                    # the moment maintenance is switched off.
}

# ----------------------------------------------------------------------------
# Storage layer — menus/settings merge into it
# ----------------------------------------------------------------------------


BOT_DATA = {}
_mongo_client = None
_mongo_collection = None
_mongo_last_error = None
_mongo_last_checked_at = None   # ISO timestamp of the most recent ping attempt
_rate_state = {}  # in-memory only, not persisted
_caption_cache = {}  # (chat_id, message_id) -> {"caption": str, "url": str}, in-memory only
CAPTION_CACHE_MAX = 500


def _replace_bot_data(new_data: dict) -> None:
    # Every other module got its own reference to this exact BOT_DATA
    # object via "from storage import *" — rebinding the name here would
    # only update storage.py's own namespace, leaving every other module
    # pointed at the old (now-stale) dict. Clearing and refilling the same
    # object in place keeps every module looking at live, current data.
    BOT_DATA.clear()
    BOT_DATA.update(new_data)


def _deep_merge_defaults(data: dict) -> dict:
    merged = json.loads(json.dumps(DEFAULT_DATA))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    # ensure any newly-added default menus (and newly-added fields on
    # existing menus, e.g. "translations") exist even in old data files
    for menu_id, menu in DEFAULT_MENUS.items():
        if menu_id not in merged["menus"]:
            merged["menus"][menu_id] = json.loads(json.dumps(menu))
        else:
            for field, default_val in menu.items():
                merged["menus"][menu_id].setdefault(field, json.loads(json.dumps(default_val)))
    return merged


def get_mongo_collection(force: bool = False):
    """Returns the live 'bot_data' collection, or None if MongoDB isn't
    configured/reachable. Caches the connection — pass force=True to make
    it actually re-ping right now (used by /mongodb and the Mongo Plugin
    admin screen so their status is always live, never stale)."""
    global _mongo_client, _mongo_collection, _mongo_last_error, _mongo_last_checked_at
    if not MONGO_URI:
        return None
    if _mongo_collection is not None and not force:
        return _mongo_collection
    try:
        from pymongo import MongoClient

        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client.get_default_database() or client["bot_db"]
        _mongo_client = client
        _mongo_collection = db["bot_data"]
        _mongo_last_error = None
        return _mongo_collection
    except Exception as e:  # noqa: BLE001
        _mongo_last_error = str(e)
        _mongo_collection = None
        return None
    finally:
        _mongo_last_checked_at = datetime.utcnow().isoformat()


def _save_mongo_config(uri: str, connected_at: str) -> None:
    """Persists an admin-panel-set Mongo URI to its own local file so it
    survives a bot restart even without MONGO_URI being set in the
    environment. Never touches bot_data.json / MongoDB itself."""
    try:
        with open(MONGO_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"uri": uri, "connected_at": connected_at}, f)
    except Exception as e:
        log.warning("Could not persist %s: %s", MONGO_CONFIG_FILE, e)


def _clear_mongo_config() -> None:
    try:
        if os.path.exists(MONGO_CONFIG_FILE):
            os.remove(MONGO_CONFIG_FILE)
    except Exception as e:
        log.warning("Could not remove %s: %s", MONGO_CONFIG_FILE, e)


def set_mongo_uri(new_uri: str):
    """🗄 Mongo Plugin — test-connects to a freshly pasted URI and, only on
    success, activates it live (no restart needed) and persists it. On
    success also immediately pushes the bot's current in-memory data into
    the new database, so switching storage never starts the bot on an
    empty slate. Returns (ok: bool, message: str)."""
    global MONGO_URI, MONGO_URI_SOURCE, MONGO_CONNECTED_AT
    global _mongo_client, _mongo_collection, _mongo_last_error, _mongo_last_checked_at
    new_uri = (new_uri or "").strip()
    if not new_uri:
        return False, "Empty URI."
    try:
        from pymongo import MongoClient
    except ImportError:
        return False, "pymongo isn't installed on this server. Run: pip install pymongo"
    try:
        test_client = MongoClient(new_uri, serverSelectionTimeoutMS=5000)
        test_client.admin.command("ping")
        db = test_client.get_default_database() or test_client["bot_db"]
        col = db["bot_data"]
    except Exception as e:  # noqa: BLE001
        return False, str(e)

    MONGO_URI = new_uri
    MONGO_URI_SOURCE = "admin_panel"
    MONGO_CONNECTED_AT = datetime.utcnow().isoformat()
    _mongo_client = test_client
    _mongo_collection = col
    _mongo_last_error = None
    _mongo_last_checked_at = MONGO_CONNECTED_AT
    _save_mongo_config(new_uri, MONGO_CONNECTED_AT)
    try:
        col.update_one({"_id": "bot_data"}, {"$set": BOT_DATA}, upsert=True)
    except Exception as e:  # noqa: BLE001
        return True, f"Connected, but the initial data copy failed: {e}. It will sync on the next save."
    return True, "Connected — this bot's data is now saved to MongoDB."


def disconnect_mongo():
    """Deactivates an admin-panel-set Mongo URI and reverts to the local
    bot_data.json file. Only ever called when MONGO_URI_SOURCE ==
    'admin_panel' — a URI coming from the MONGO_URI env var can't be
    disconnected from inside the bot (it's infra-managed; unset the env
    var and restart instead)."""
    global MONGO_URI, MONGO_URI_SOURCE, MONGO_CONNECTED_AT
    global _mongo_client, _mongo_collection, _mongo_last_error
    MONGO_URI = ""
    MONGO_URI_SOURCE = None
    MONGO_CONNECTED_AT = None
    _mongo_client = None
    _mongo_collection = None
    _mongo_last_error = None
    _clear_mongo_config()
    save_data()  # now falls through to the local JSON file


def get_mongo_status() -> dict:
    """Single source of truth for /mongodb and the 🗄 Mongo Plugin admin
    screen — always re-pings live so the status shown is never stale."""
    col = get_mongo_collection(force=True)
    masked_uri = None
    if MONGO_URI:
        m = re.match(r"^(mongodb(?:\+srv)?://)([^@/]+)@(.+)$", MONGO_URI)
        masked_uri = f"{m.group(1)}***:***@{m.group(3)}" if m else MONGO_URI
    doc_count = None
    if col is not None:
        try:
            doc_count = col.count_documents({})
        except Exception:
            pass
    return {
        "configured": bool(MONGO_URI),
        "connected": col is not None,
        "source": MONGO_URI_SOURCE,
        "masked_uri": masked_uri,
        "connected_at": MONGO_CONNECTED_AT,
        "last_checked_at": _mongo_last_checked_at,
        "last_error": _mongo_last_error,
        "doc_count": doc_count,
    }


def _apply_seed_files_if_present() -> bool:
    """Part of the 📦 Update Backup system (see SEED_SETTINGS_FILE /
    SEED_USERS_FILE and send_update_backup()). Only ever called from
    load_data() in the branch where NO existing data was found (fresh
    Mongo, or no local bot_data.json) — so on a host with persistent
    storage this never runs and never clobbers live data. It exists
    specifically for hosts that wipe the filesystem on every redeploy:
    export the two seed files from the admin panel, commit them into the
    repo next to bot.py with these exact names, push the update — the
    bot then reconstructs its previous settings/menus/users right here,
    automatically, on the very first startup after the deploy."""
    global BOT_DATA
    seed = {}
    if os.path.exists(SEED_SETTINGS_FILE):
        try:
            with open(SEED_SETTINGS_FILE, "r", encoding="utf-8") as f:
                seed.update(json.load(f))
            log.info("Update Backup: found %s — seeding settings/menus from it.", SEED_SETTINGS_FILE)
        except Exception as e:
            log.warning("Update Backup: could not read %s: %s", SEED_SETTINGS_FILE, e)
    if os.path.exists(SEED_USERS_FILE):
        try:
            with open(SEED_USERS_FILE, "r", encoding="utf-8") as f:
                users_payload = json.load(f)
            seed["users"] = users_payload.get("users", users_payload)
            log.info("Update Backup: found %s — seeding users from it.", SEED_USERS_FILE)
        except Exception as e:
            log.warning("Update Backup: could not read %s: %s", SEED_USERS_FILE, e)
    if seed:
        _replace_bot_data(_deep_merge_defaults(seed))
        return True
    return False


def _apply_language_pack_migration():
    """Runs once after BOT_DATA is loaded from any source (fresh, local
    JSON, MongoDB, or a restored/seeded backup). Backfills missing menu
    translations and, if the owner has never touched Settings > Languages
    (still the empty default), pre-fills it from language_pack.json so the
    picker isn't empty. Purely additive — never overwrites an existing
    admin-set value — so it's always safe to re-run on every startup."""
    changed = False
    menus = BOT_DATA.get("menus", {})
    before = json.dumps(menus, sort_keys=True)
    _apply_language_pack_to_menus(menus)
    if json.dumps(menus, sort_keys=True) != before:
        changed = True
    settings = BOT_DATA.setdefault("settings", {})
    if not settings.get("languages"):
        pack_langs = [c for c in _load_language_pack().get("languages", {}) if c != "en"]
        if pack_langs:
            settings["languages"] = pack_langs
            changed = True
    if changed:
        save_data()


def load_data():
    global BOT_DATA
    col = get_mongo_collection()

    if col is not None:
        doc = col.find_one({"_id": "bot_data"})
        if doc:
            doc.pop("_id", None)
            _replace_bot_data(_deep_merge_defaults(doc))
            log.info("Loaded data from MongoDB.")
        else:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    local = json.load(f)
                _replace_bot_data(_deep_merge_defaults(local))
                col.update_one({"_id": "bot_data"}, {"$set": BOT_DATA}, upsert=True)
                log.info("Migrated local JSON data into MongoDB.")
            else:
                _replace_bot_data(json.loads(json.dumps(DEFAULT_DATA)))
                _apply_seed_files_if_present()
                col.update_one({"_id": "bot_data"}, {"$set": BOT_DATA}, upsert=True)
        _apply_language_pack_migration()
        return

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _replace_bot_data(_deep_merge_defaults(json.load(f)))
        log.info("Loaded data from local JSON file.")
    else:
        _replace_bot_data(json.loads(json.dumps(DEFAULT_DATA)))
        _apply_seed_files_if_present()
        save_data()
    _apply_language_pack_migration()


def save_data():
    col = get_mongo_collection()
    if col is not None:
        col.update_one({"_id": "bot_data"}, {"$set": BOT_DATA}, upsert=True)
        return
    tmp_path = DATA_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(BOT_DATA, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_FILE)


def get_or_create_backup_key() -> "bytes | None":
    """Local Fernet key used to encrypt backup files. Generated once and
    reused — losing this file means old encrypted backups can never be
    decrypted again, so it's kept next to bot_data.json, never inside the
    BACKUP_DIR (which the /export source-zip explicitly excludes anyway)."""
    if not BACKUP_ENCRYPTION_AVAILABLE:
        return None
    if os.path.exists(BACKUP_KEY_FILE):
        with open(BACKUP_KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(BACKUP_KEY_FILE, "wb") as f:
        f.write(key)
    log.warning(
        "Generated a new backup encryption key at %s — this file is the "
        "ONLY way to decrypt existing .enc backups. Keep it safe and never "
        "commit it to git.", BACKUP_KEY_FILE,
    )
    return key


def encrypt_backup_bytes(raw: bytes) -> "tuple[bytes, bool]":
    """Returns (payload, was_encrypted). Falls back to plain bytes if the
    `cryptography` package isn't installed, so backups still work either way."""
    key = get_or_create_backup_key()
    if key is None:
        return raw, False
    return Fernet(key).encrypt(raw), True


def decrypt_backup_bytes(payload: bytes) -> bytes:
    """Reverses encrypt_backup_bytes. Raises InvalidToken if the key doesn't
    match, or ValueError if `cryptography` isn't installed but the payload
    is actually encrypted — callers should catch and show a clear message."""
    key = get_or_create_backup_key()
    if key is None:
        raise ValueError("cryptography package not installed — cannot decrypt.")
    return Fernet(key).decrypt(payload)


def make_backup_snapshot(reason: str = "scheduled") -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw = json.dumps(BOT_DATA, ensure_ascii=False, indent=2).encode("utf-8")
    json.loads(raw)  # integrity check before we ever touch disk/encryption
    payload, encrypted = encrypt_backup_bytes(raw)
    ext = "json.enc" if encrypted else "json"
    path = os.path.join(BACKUP_DIR, f"backup_{ts}_{reason}.{ext}")
    with open(path, "wb") as f:
        f.write(payload)
    files = sorted(
        [os.path.join(BACKUP_DIR, x) for x in os.listdir(BACKUP_DIR)], key=os.path.getmtime
    )
    while len(files) > MAX_LOCAL_BACKUPS:
        os.remove(files.pop(0))
    return path


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    return is_owner(user_id) or user_id in BOT_DATA.get("admins", [])


# ----------------------------------------------------------------------------
# Granular admin permissions — every grantable Admin Panel section. Keys
# match the panel's callback_data with the "adm_" prefix stripped (see
# _perm_key_for_screen). 📦 Update Backup, ☠️ Danger Zone, and 👤 Manage
# Admins are intentionally NOT in this list — they stay owner-only no
# matter what, since they can export all data, do irreversible damage, or
# hand out access, respectively.
# ----------------------------------------------------------------------------
ADMIN_PERMISSIONS = [
    ("stats", "📊 Statistics"),
    ("users", "👥 Users & Groups"),
    ("live", "🍃 Live User Feed"),
    ("broadcast", "📢 Broadcast"),
    ("premium", "💎 Premium"),
    ("leaderboard", "🏆 Leaderboard"),
    ("share", "🎚 Share Settings"),
    ("devsettings", "😎 Developer Settings"),
    ("support_settings", "🛠 Support Settings"),
    ("tickets", "📬 Tickets"),
    ("menu_ui", "🪄 Menu & UI"),
    ("plugins", "🧩 Feature Plugins"),
    ("notifications", "🔔 Notifications"),
    ("activity", "📜 Activity Log"),
    ("selftest", "🗽 Self-Test"),
    ("cmdtest", "📟 Test Commands"),
    ("ai_check", "🤖 AI Check"),
    ("settings", "⚙️ Settings"),
]
ADMIN_PERMISSION_KEYS = [k for k, _ in ADMIN_PERMISSIONS]
ADMIN_PERMISSION_LABELS = dict(ADMIN_PERMISSIONS)


def _perm_key_for_screen(screen_key: str) -> str:
    return screen_key[4:] if screen_key.startswith("adm_") else screen_key


def get_admin_perms(user_id: int) -> set:
    """Owner -> every permission. An admin with NO explicit entry in
    admin_permissions (i.e. added before this feature existed) also gets
    every permission, so upgrading the bot never silently locks out an
    already-trusted admin. Only admins added AFTER this feature exists get
    the exact list the owner picked for them at add-time (can be empty)."""
    if is_owner(user_id):
        return set(ADMIN_PERMISSION_KEYS)
    uid = str(user_id)
    perms_map = BOT_DATA.get("admin_permissions", {})
    if uid not in perms_map:
        return set(ADMIN_PERMISSION_KEYS)  # legacy admin, added before permissions existed
    return set(perms_map.get(uid) or [])


def has_admin_perm(user_id: int, perm_key: str) -> bool:
    return is_owner(user_id) or perm_key in get_admin_perms(user_id)


def touch_user(update: Update) -> bool:
    """Records/updates the user record. Returns True if this is a brand-new user."""
    user = update.effective_user
    if not user:
        return False
    uid = str(user.id)
    now = datetime.utcnow().isoformat()
    users = BOT_DATA["users"]
    is_new = uid not in users
    if is_new:
        users[uid] = {
            "name": user.full_name, "username": user.username,
            "joined": now, "last_active": now, "last_reengaged": None,
            "lang": None, "lang_prompted": False,
            "accepted_terms": False, "accepted_terms_at": None,
            "downloads_today": 0, "downloads_today_date": None,
            "downloads_month": 0, "downloads_month_key": None,
            "reels_count": 0, "audio_count": 0, "caption_count": 0,
            "plan": "Free", "open_ticket_id": None,
        }
    else:
        users[uid]["last_active"] = now
        users[uid]["name"] = user.full_name
    save_data()
    return is_new


def is_blocked(user_id: int) -> bool:
    return user_id in BOT_DATA.get("blocked", [])


def is_premium_active(uid: str) -> bool:
    """A user counts as premium only while plan != Free AND (no expiry
    set, or expiry is in the future)."""
    u = BOT_DATA["users"].get(uid, {})
    if u.get("plan", "Free") == "Free":
        return False
    exp = u.get("plan_expires_at")
    if not exp:
        return True
    try:
        return datetime.fromisoformat(exp) > datetime.utcnow()
    except Exception:
        return True


def grant_premium(uid: str, days: int = 30):
    """Used by both Stars payments and admin-confirmed UPI orders."""
    u = BOT_DATA["users"].setdefault(uid, {})
    u["plan"] = "Premium"
    u["plan_expires_at"] = (datetime.utcnow() + timedelta(days=days)).isoformat()
    save_data()


def check_daily_limit(uid: str) -> bool:
    """Premium users are unlimited; everyone else is capped per day."""
    if is_premium_active(uid):
        return True
    u = BOT_DATA["users"].get(uid, {})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_count = u.get("downloads_today", 0) if u.get("downloads_today_date") == today else 0
    limit = BOT_DATA["settings"].get("daily_limit", 20)
    return today_count < limit


async def cm_track_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Keeps BOT_DATA['groups'] in sync so the admin panel's group count
    reflects reality."""
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type not in ("group", "supergroup"):
        return
    gid = str(cmu.chat.id)
    new_status = cmu.new_chat_member.status
    if new_status in ("member", "administrator"):
        BOT_DATA["groups"][gid] = {
            "title": cmu.chat.title, "added_at": datetime.utcnow().isoformat(),
        }
    elif new_status in ("left", "kicked"):
        BOT_DATA["groups"].pop(gid, None)
    save_data()


def _force_join_targets():
    """Return normalized multi-force-join targets, while migrating legacy data."""
    settings = BOT_DATA["settings"]
    targets = settings.get("force_join_channels") or []
    if not targets and settings.get("force_join_channel"):
        legacy = settings["force_join_channel"]
        targets = [{"chat_id": legacy if not str(legacy).startswith("http") else None,
                    "link": legacy if str(legacy).startswith("http") else None}]
        settings["force_join_channels"] = targets
    normalized = []
    for item in targets:
        if isinstance(item, str):
            item = {"chat_id": item if not item.startswith("http") else None,
                    "link": item if item.startswith("http") else None}
        if isinstance(item, dict) and (item.get("chat_id") or item.get("link")):
            normalized.append(item)
    return normalized


def normalize_channel_id(raw: str) -> str:
    """Auto-fix the #1 real-world force-join bug: an admin pastes a numeric
    channel ID that's missing Telegram's mandatory "-100" prefix for
    channels/supergroups (very common — many ID-lookup bots/forwarded
    messages show the bare internal number, e.g. "-5080988402" instead of
    the actual Bot-API-usable "-1005080988402"). Using the bare form makes
    every get_chat_member call fail with "chat not found", which silently
    blocks every single user — exactly the "force-join doesn't work at
    all" symptom. Public @usernames and already-correct IDs pass through
    unchanged."""
    raw = str(raw).strip()
    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        return raw
    digits = raw.lstrip("-")
    if raw.startswith("-") and not digits.startswith("100"):
        return f"-100{digits}"
    return raw


async def is_force_join_ok(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Require membership in every configured force-join channel.

    Join requests are also accepted: when Telegram sends the bot a
    ChatJoinRequest update, that user is temporarily/explicitly marked as
    verified for that target, so they can start using the bot without waiting
    for a manual re-check.
    """
    targets = _force_join_targets()
    if not targets or is_admin(user_id):
        return True
    verified = BOT_DATA["settings"].get("force_join_request_verified", {}).get(str(user_id), [])
    for target in targets:
        chat_id = normalize_channel_id(target.get("chat_id")) if target.get("chat_id") else None
        key = str(chat_id or target.get("link"))
        if key in verified:
            continue
        if not chat_id:
            # Link-only targets cannot be queried by getChatMember. They can
            # still be verified through a join-request update.
            return False
        try:
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("left", "kicked", "restricted"):
                return False
        except Exception as e:
            log.warning("Force-join check failed (target=%s, user=%s): %s", target, user_id, e)
            log_error("force_join", f"target={target}, user={user_id}: {e}")
            return False
    return True


async def resolve_force_join_link(context: ContextTypes.DEFAULT_TYPE, channel) -> str | None:
    if not channel:
        return None
    ch = normalize_channel_id(channel)
    if ch.startswith("http"):
        return ch
    if ch.lstrip("-").isdigit():
        try:
            chat = await context.bot.get_chat(int(ch))
            if chat.username:
                return f"https://t.me/{chat.username}"
            if getattr(chat, "invite_link", None):
                return chat.invite_link
            return await context.bot.export_chat_invite_link(int(ch))
        except Exception as e:
            # This is the #1 real cause of "no usable join link found" on the
            # user-facing prompt: either the ID is still wrong (not a real
            # channel the bot can see), or the bot IS in the channel but
            # isn't an admin there (export_chat_invite_link needs admin
            # rights). Logged so it shows up in Activity Log instead of
            # silently failing with zero diagnosis.
            log.warning("Force-join: could not resolve invite link for %s: %s", ch, e)
            log_error("force_join", f"could not resolve a join link for channel {ch}: {e}")
            return None
    return f"https://t.me/{ch.lstrip('@')}"


async def get_force_join_links(context):
    links = []
    for target in _force_join_targets():
        link = target.get("link") or await resolve_force_join_link(context, target.get("chat_id"))
        if link:
            links.append(link)
    return links


async def handle_force_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accept a received join request as verification for force-join."""
    req = update.chat_join_request
    if not req:
        return
    uid = str(req.from_user.id)
    verified_map = BOT_DATA["settings"].setdefault("force_join_request_verified", {})
    keys = set(verified_map.get(uid, []))
    for target in _force_join_targets():
        chat_id = normalize_channel_id(target.get("chat_id")) if target.get("chat_id") else None
        if chat_id and str(chat_id) == str(req.chat.id):
            keys.add(str(chat_id))
        # Match the actual invite link if Telegram exposes it.
        inv = getattr(req, "invite_link", None)
        if inv and target.get("link") and getattr(inv, "invite_link", None) == target.get("link"):
            keys.add(str(target.get("link")))
    if keys:
        verified_map[uid] = list(keys)
        save_data()


def is_link_blocked(url: str) -> bool:
    if url in BOT_DATA.get("blocked_links", []):
        return True
    for domain in BOT_DATA.get("blocked_domains", []):
        if domain.lower() in url.lower():
            return True
    return False


def check_rate_limit(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    limit = BOT_DATA["settings"].get("rate_limit_max", 20)
    window = BOT_DATA["settings"].get("rate_limit_window_seconds", 60)
    if limit <= 0:
        return True
    now = time.time()
    bucket = _rate_state.setdefault(user_id, [])
    while bucket and now - bucket[0] > window:
        bucket.pop(0)
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True



__all__ = [_n for _n in dir() if not _n.startswith("__")]
