from storage import *


async def log_event(context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = None):
    """#14 — send a short line to the admin-configured logger channel, if any."""
    settings = BOT_DATA.get("settings", {})
    if not settings.get("logger_enabled") or not settings.get("logger_channel_id"):
        return
    try:
        await context.bot.send_message(chat_id=settings["logger_channel_id"], text=text, parse_mode=parse_mode)
    except Exception:
        log.exception("Failed to send to logger channel")


async def dm_all_admins(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode: str = None):
    """Send a message to every admin's private chat (owner + BOT_DATA['admins']).
    One admin having blocked the bot / never opened a DM must never stop the
    others from getting it, so each send is isolated."""
    targets = set(BOT_DATA.get("admins", []))
    if OWNER_ID:
        targets.add(OWNER_ID)
    for admin_id in targets:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            log.warning("Could not DM admin %s (bot blocked / never started a DM)", admin_id)


def clickable_user(user_obj) -> str:
    """HTML mention link to a user's Telegram profile — same pattern used by
    the Support flow, reused everywhere a user's name is shown to an admin
    (Live Activity, admin DMs, Support tickets, join alerts, etc.). Falls
    back to a plain @username link when a username exists (works even if
    the user has since blocked the bot), tg://user?id otherwise."""
    name = html.escape(user_obj.full_name or str(user_obj.id))
    if getattr(user_obj, "username", None):
        return f'<a href="https://t.me/{user_obj.username}">{name}</a>'
    return f'<a href="tg://user?id={user_obj.id}">{name}</a>'


_LANGUAGE_NAME_MAP = {
    "en": "English", "hi": "Hindi", "ur": "Urdu", "bn": "Bengali", "ta": "Tamil",
    "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "pa": "Punjabi", "ar": "Arabic", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "ru": "Russian", "id": "Indonesian", "tr": "Turkish", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "it": "Italian", "vi": "Vietnamese", "fa": "Persian",
}


def build_join_details(update: Update, is_new: bool) -> str:
    """Full detail card for a /start — new user OR bot started inside a
    group — so admins get the complete picture in one glance. HTML: Name
    is a clickable link straight to the user's profile."""
    user = update.effective_user
    chat = update.effective_chat
    lbl = to_title_small_caps
    username_display = f"@{user.username}" if user.username else "Not Set"
    saved_lang = BOT_DATA.get("users", {}).get(str(user.id), {}).get("lang")
    lang_code = (saved_lang or user.language_code or "").lower()
    lang_display = _LANGUAGE_NAME_MAP.get(lang_code, user.language_code or "Unknown")

    lines = [
        "🆕 " + lbl("New User Started Bot" if is_new else "Bot Started In Group"),
        "",
        _CARD_SEP,
        "",
        "👤 " + lbl("User Information"),
        "",
        f"{lbl('Name')} : {clickable_user(user)}",
        f"{lbl('Username')} : {html.escape(username_display)}",
        f"{lbl('User Id')} : {user.id}",
    ]

    if chat.type in ("group", "supergroup"):
        lines += [
            "",
            "👨‍👩‍👧 " + lbl("Group Details"),
            "",
            f"{lbl('Group')} : {html.escape(chat.title or '')}",
            f"{lbl('Group Id')} : {chat.id}",
        ]
    else:
        lines += [
            "",
            "🌐 " + lbl("Account Details"),
            "",
            f"{lbl('Language')} : {lbl(lang_display)}",
            f"{lbl('Chat Type')} : {lbl(chat.type.capitalize())}",
            f"{lbl('Telegram Premium')} : {lbl('Yes') if getattr(user, 'is_premium', False) else lbl('No')}",
        ]

    lines += [
        "",
        "🕒 " + lbl("Started At"),
        "",
        now_ist_str("%d %B %Y • %H:%M:%S") + " IST",
        "",
        _CARD_SEP,
    ]
    return "\n".join(lines)


async def notify_admins_new_start(context: ContextTypes.DEFAULT_TYPE, update: Update, is_new: bool):
    """New user starts the bot, or the bot is (re-)started inside a group —
    full details go to every admin's DM, and to the logger group if set."""
    if not BOT_DATA["settings"].get("detailed_join_alerts", True):
        return
    is_group = update.effective_chat.type in ("group", "supergroup")
    if not (is_new or is_group):
        return
    text = build_join_details(update, is_new)
    await dm_all_admins(context, text, parse_mode="HTML")
    await log_event(context, text, parse_mode="HTML")


async def log_user_activity(context: ContextTypes.DEFAULT_TYPE, update: Update, url: str):
    """Anti-misuse monitoring: record what a user pastes into the bot and
    surface it live to the owner's DM (+ logger group), with a one-tap Ban
    button — this is a check/monitoring tool only, not automatic action."""
    user = update.effective_user
    chat = update.effective_chat
    entry = {
        "time": datetime.utcnow().isoformat(),
        "user_id": user.id,
        "name": user.full_name,
        "username": user.username,
        "chat_type": chat.type,
        "url": url,
    }
    buf = BOT_DATA.setdefault("activity_log", [])
    buf.append(entry)
    if len(buf) > 300:
        del buf[: len(buf) - 300]
    save_data()

    # The admin-DM ping for this happens once the reel is actually
    # delivered, via build_reel_delivered_card / send_reel_delivered_card
    # (same "📡 Feed To Admin DM" toggle), so only one message goes out per
    # request instead of two differently-formatted ones.


def track_sent_message(chat_id: int, message_id: int):
    """Small per-chat ring buffer backing 'Delete All Bot Messages'."""
    key = str(chat_id)
    buf = BOT_DATA.setdefault("sent_messages", {}).setdefault(key, [])
    buf.append(message_id)
    if len(buf) > 200:
        del buf[: len(buf) - 200]


def bump_usage(uid: str):
    """Daily/monthly download counters, resetting on date/month change."""
    u = BOT_DATA["users"].get(uid)
    if not u:
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.utcnow().strftime("%Y-%m")
    if u.get("downloads_today_date") != today:
        u["downloads_today"] = 0
        u["downloads_today_date"] = today
    if u.get("downloads_month_key") != month:
        u["downloads_month"] = 0
        u["downloads_month_key"] = month
    u["downloads_today"] += 1
    u["downloads_month"] += 1


IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist(dt: datetime) -> datetime:
    """All timestamps are stored in UTC internally (unchanged, so old data
    and any external tooling stays correct) — this only converts for
    on-screen display, since admins kept asking why times looked wrong."""
    return dt + IST_OFFSET


def now_ist_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return to_ist(datetime.utcnow()).strftime(fmt)


def iso_to_ist_str(iso_str: str, fmt: str = "%d %b %Y, %H:%M") -> str:
    """Safely convert a stored UTC ISO timestamp to an IST display string.
    Falls back to the raw stored value if it can't be parsed, rather than
    ever raising."""
    if not iso_str:
        return "?"
    try:
        return to_ist(datetime.fromisoformat(iso_str)).strftime(fmt)
    except Exception:
        return str(iso_str)


def human_uptime() -> str:
    secs = int(time.time() - START_TIME)
    d, secs = divmod(secs, 86400)
    h, secs = divmod(secs, 3600)
    m, _ = divmod(secs, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def human_uptime_full() -> str:
    """Same as human_uptime() but with seconds, in the small-caps
    'Xᴅᴀʏs, Yʜ:Zᴍ:Ws' style used by the /ping quote block."""
    secs = int(time.time() - START_TIME)
    d, secs = divmod(secs, 86400)
    h, secs = divmod(secs, 3600)
    m, s = divmod(secs, 60)
    if d:
        return f"{d}ᴅᴀʏs, {h}ʜ:{m:02d}ᴍ:{s:02d}s"
    return f"{h}ʜ:{m:02d}ᴍ:{s:02d}s"


def get_memory_usage_mb():
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        try:
            import resource

            return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        except Exception:
            return None


def get_cpu_percent():
    """System-wide CPU usage %, or None if psutil isn't installed."""
    try:
        import psutil

        return psutil.cpu_percent(interval=0.3)
    except Exception:
        return None


def get_ram_percent():
    """System-wide RAM usage %, or None if psutil isn't installed."""
    try:
        import psutil

        return psutil.virtual_memory().percent
    except Exception:
        return None


def get_disk_percent():
    """Disk usage % of the filesystem the bot runs on, or None if psutil
    isn't installed."""
    try:
        import psutil

        return psutil.disk_usage(os.getcwd()).percent
    except Exception:
        return None


async def _delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception:
        pass


async def schedule_delete(context, chat_id, message_id, seconds):
    if seconds and seconds > 0:
        context.job_queue.run_once(
            _delete_message_job, when=timedelta(seconds=seconds),
            data={"chat_id": chat_id, "message_id": message_id},
        )


# ----------------------------------------------------------------------------
# Dynamic menu engine — render_menu is the ONE function every command/callback
# uses to show a menu (#1, #2, #3). Same-message edit-in-place navigation.
# ----------------------------------------------------------------------------


def build_keyboard_from_buttons(buttons, menu_id):
    if not buttons:
        return None
    rows = {}
    for b in buttons:
        rows.setdefault(b.get("row", 1), []).append(b)
    kb_rows = []
    for row_num in sorted(rows.keys()):
        row_widgets = []
        for b in rows[row_num]:
            style = b.get("style")
            btype = b.get("type")
            if btype == "url":
                row_widgets.append(styled_button(b["label"], url=b["value"], style=style or "primary"))
            elif btype == "menu":
                row_widgets.append(styled_button(b["label"], callback_data=f"nav:{b['value']}", style=style or "primary"))
            elif btype == "toggle":
                current = bool(BOT_DATA["settings"].get(b["value"], False))
                st = "success" if current else "danger"
                row_widgets.append(
                    styled_button(toggle_label(b["label"], current), callback_data=f"tgl:{b['value']}:{menu_id}", style=st)
                )
            elif btype == "callback":
                row_widgets.append(styled_button(b["label"], callback_data=b["value"], style=style or "primary"))
            else:
                continue
        if row_widgets:
            kb_rows.append(row_widgets)
    return InlineKeyboardMarkup(kb_rows) if kb_rows else None


_me_cache = {"me": None, "at": 0.0}


async def _cached_get_me(context: ContextTypes.DEFAULT_TYPE):
    """get_me() never changes mid-run, but render_menu() used to call it on
    every single welcome-screen render — an avoidable network round-trip on
    the hottest path in the bot, and one more place a transient network
    hiccup could make the bot's name/link silently fail to show. Cached for
    10 minutes; refreshed automatically after that or if it's never been
    fetched yet."""
    now = time.monotonic()
    if _me_cache["me"] is None or (now - _me_cache["at"]) > 600:
        _me_cache["me"] = await context.bot.get_me()
        _me_cache["at"] = now
    return _me_cache["me"]


async def render_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, menu_id: str, existing_message=None, lang: str = None):
    await _clear_ephemeral(context, chat_id)
    menu = BOT_DATA["menus"].get(menu_id)
    if not menu:
        await context.bot.send_message(chat_id, to_small_caps(f"⚠️ menu '{menu_id}' not found."))
        return

    # Resolve language: explicit arg > saved user preference > base (default) text.
    if lang is None:
        lang = BOT_DATA["users"].get(str(chat_id), {}).get("lang")
    translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the bot.py default, never a translation override

    buttons = (translation or {}).get("buttons") or menu.get("buttons", [])
    text = (translation or {}).get("text") or menu.get("text", "")
    kb = build_keyboard_from_buttons(buttons, menu_id)
    parse_mode = menu.get("parse_mode") or None
    image = menu.get("image_file_id")

    # Welcome-screen personalization — supports {username}/{bot_name} and
    # legacy {first_name}/{bot_link} placeholders for the start menu.
    if menu_id == "start":
        if "{username}" in text or "{first_name}" in text:
            stored_name = BOT_DATA["users"].get(str(chat_id), {}).get("name") or ""
            first_name = stored_name.split(" ")[0] if stored_name else "there"
            user_display = html.escape(first_name)
            # Make the user's displayed name open their Telegram profile.
            username_link = f'<a href="tg://user?id={int(chat_id)}">{user_display}</a>'
            text = text.replace("{username}", username_link)
            text = text.replace("{first_name}", user_display)
        if "{bot_name}" in text or "{bot_link}" in text:
            bot_name = "our bot"
            bot_link = "our bot"
            try:
                me = await _cached_get_me(context)
                display_name = html.escape(me.first_name or "our bot")
                bot_name = display_name
                # tg://user?id=<id> (not an https://t.me/<username> link) —
                # same trick already used above for {username}. A t.me/
                # link jumps straight into the chat; this ID-based deep
                # link opens the bot's profile card first instead.
                bot_link = f'<a href="tg://user?id={me.id}">{display_name}</a>'
            except Exception as e:
                log_error("bot_link_resolve", f"render_menu couldn't resolve bot name/link: {e}")
            text = text.replace("{bot_name}", bot_name)
            text = text.replace("{bot_link}", bot_link)

    # #10 — owner/developer credit button, injected at render time (not part
    # of the admin-editable button list) so it can't be accidentally deleted
    # by editing menu buttons.
    if menu_id in ("start", "help_user"):
        owner_id = BOT_DATA["settings"].get("owner_display_user_id")
        if owner_id:
            label = BOT_DATA["settings"].get("owner_display_label") or "👑 Developer"
            owner_id_str = str(owner_id)
            if owner_id_str.isdigit():
                # Same tg://user?id= reliability issue as the developer
                # button — resolve the real @username via getChat when we can.
                url = f"tg://user?id={owner_id_str}"
                try:
                    chat = await context.bot.get_chat(int(owner_id_str))
                    if chat.username:
                        url = f"https://t.me/{chat.username}"
                except Exception:
                    pass
            else:
                url = f"https://t.me/{owner_id_str.lstrip('@')}"
            owner_row = [styled_button(label, url=url, style="primary")]
            kb = InlineKeyboardMarkup((kb.inline_keyboard if kb else []) + [owner_row])

    # #4 — global forwarding/sharing lock applies to every menu the bot sends.
    protect = bool(BOT_DATA["settings"].get("lock_all_content", False))

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    sent_message = None
    try:
        if existing_message is not None:
            has_photo = bool(existing_message.photo)
            if image and has_photo:
                await existing_message.edit_media(
                    media=InputMediaPhoto(media=image, caption=text, parse_mode=parse_mode), reply_markup=kb
                )
                sent_message = existing_message
            elif image and not has_photo:
                await existing_message.delete()
                sent_message = await context.bot.send_photo(
                    chat_id, photo=image, caption=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
            elif not image and has_photo:
                await existing_message.delete()
                sent_message = await context.bot.send_message(
                    chat_id, text=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
            else:
                await existing_message.edit_text(text=text, parse_mode=parse_mode, reply_markup=kb)
                sent_message = existing_message
        else:
            if image:
                sent_message = await context.bot.send_photo(
                    chat_id, photo=image, caption=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
            else:
                sent_message = await context.bot.send_message(
                    chat_id, text=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
    except Exception:
        log.exception("render_menu failed for %s, sending fresh", menu_id)
        try:
            if image:
                sent_message = await context.bot.send_photo(
                    chat_id, photo=image, caption=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
            else:
                sent_message = await context.bot.send_message(
                    chat_id, text=text, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
        except Exception:
            log.exception("render_menu completely failed for %s", menu_id)
            return

    seconds = menu.get("auto_delete_seconds")
    if seconds is None:
        seconds = BOT_DATA["settings"].get("global_auto_delete_seconds", 0)
    if sent_message:
        track_sent_message(chat_id, sent_message.message_id)
        await schedule_delete(context, chat_id, sent_message.message_id, seconds)
    return sent_message


async def track_and_refresh_panel(context: ContextTypes.DEFAULT_TYPE, chat_id: int, key: str, sent_message):
    """The first panel message stays forever; every later /start or /admin
    deletes the previous panel message and leaves only the fresh one."""
    if not sent_message:
        return
    key = f"{key}:{chat_id}"
    prev = BOT_DATA["panel_msg"].get(key)
    if prev and prev != sent_message.message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prev)
        except Exception:
            pass
    BOT_DATA["panel_msg"][key] = sent_message.message_id
    save_data()


def remember_panel_message(context: ContextTypes.DEFAULT_TYPE, query, screen_key: str):
    """Remembers which panel message triggered a text-input flow, so once
    the value is saved that same message can be edited in place instead of
    leaving it stale with just a small confirmation line further down."""
    context.user_data["panel_refresh"] = {
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
        "screen": screen_key,
    }


async def refresh_panel_after_save(context: ContextTypes.DEFAULT_TYPE, screen_key: str, build_fn, parse_mode=None) -> bool:
    """Edits the original admin-panel screen (remembered via
    remember_panel_message) in place to reflect a just-saved value.
    Returns True if it succeeded, so callers can still send a plain
    confirmation as a fallback if the panel message is gone."""
    info = context.user_data.get("panel_refresh")
    if not info or info.get("screen") != screen_key:
        return False
    context.user_data.pop("panel_refresh", None)
    text, kb = build_fn()
    try:
        await context.bot.edit_message_text(
            chat_id=info["chat_id"], message_id=info["message_id"], text=text, reply_markup=kb, parse_mode=parse_mode,
        )
        return True
    except Exception:
        return False


async def cb_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, menu_id = query.data.split(":", 1)
    await render_menu(context, query.message.chat_id, menu_id, existing_message=query.message)


async def cb_toggle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle button embedded inside a dynamic menu (#4 toggle-type button)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    _, key, menu_id = query.data.split(":", 2)
    BOT_DATA["settings"][key] = not bool(BOT_DATA["settings"].get(key, False))
    save_data()
    await render_menu(context, query.message.chat_id, menu_id, existing_message=query.message)


# ----------------------------------------------------------------------------
# Style Text picker (#1) — reusable for menu body text AND button labels
# ----------------------------------------------------------------------------

# The welcome screen's live placeholders — {first_name} and {bot_link} (the
# bot's own clickable name/username in the welcome text). BUG FIX: every
# STYLE_OPTIONS function remaps plain a-z/A-Z letters (small caps, bold,
# fullwidth, ...), so styling text that contains these tokens used to
# mangle the literal word "bot_link" inside the braces into unicode
# look-alike letters. render_menu()'s exact `text.replace("{bot_link}", ...)`
# could then never find the token again, so the bot's name/link in the
# welcome message silently stopped being clickable the moment an admin
# styled the welcome text even once. Fixed by shielding these tokens with
# private-use sentinel characters (untouched by every style function) before
# styling, then restoring the real placeholder text afterwards.
_WELCOME_PLACEHOLDERS = ["{first_name}", "{bot_link}", "{username}", "{bot_name}"]


def apply_style_preserving_placeholders(func, text: str) -> str:
    protected = text
    markers = {}
    for i, token in enumerate(_WELCOME_PLACEHOLDERS):
        if token in protected:
            marker = f"\ue000{i}\ue001"
            markers[marker] = token
            protected = protected.replace(token, marker)
    styled = func(protected)
    for marker, token in markers.items():
        styled = styled.replace(marker, token)
    return styled


async def send_style_preview(context, chat_id, source_text):
    rows = []
    for i, (label, func) in enumerate(STYLE_OPTIONS):
        preview = apply_style_preserving_placeholders(func, source_text)
        display = preview if len(preview) <= 30 else preview[:27] + "..."
        rows.append([styled_button(display, callback_data=f"styleset:{i}")])
    await context.bot.send_message(chat_id, to_small_caps("🅰️ choose a style:"), reply_markup=InlineKeyboardMarkup(rows))


async def _replace_rkb_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int, key: str, text: str, reply_markup=None, parse_mode=None):
    """Delete the previous message shown for this reply-keyboard screen (if
    any) before sending the new one — for EVERY persistent bottom button
    (📊 My Usage, 🎁 Send A Gift, 👨‍💻 Developer, 📘 How To Use, 🎧 Support,
    ⬇️ Download Reel, 🌐 Language), not just one of them. Without this,
    tapping the same button over and over just stacked a fresh bot reply
    under the last one every time, click after click. Uses the same
    persisted panel_msg store as /start and /admin, so it survives a bot
    restart, not just context.user_data."""
    msg = await context.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    # All persistent reply-keyboard actions share one panel slot. This means
    # the user's own button message remains in chat, while only the latest
    # bot-side screen is replaced on every button tap.
    await track_and_refresh_panel(context, chat_id, "rkb_latest", msg)
    return msg



async def cb_styleset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    idx = int(query.data.split(":", 1)[1])
    src = context.user_data.pop("style_source_text", None)
    target = context.user_data.pop("style_target", None)
    if src is None or target is None:
        await query.edit_message_text(to_small_caps("session expired — please try again."))
        return
    label, func = STYLE_OPTIONS[idx]
    styled_text = apply_style_preserving_placeholders(func, src)

    if target.startswith("menu_text:"):
        menu_id = target.split(":", 1)[1]
        BOT_DATA["menus"][menu_id]["text"] = styled_text
        BOT_DATA["menus"][menu_id]["updated_by"] = update.effective_user.id
        BOT_DATA["menus"][menu_id]["updated_at"] = datetime.utcnow().isoformat()
        save_data()
        await query.edit_message_text(f"✅ Menu text updated ({label} style).")
    elif target.startswith("button_label:"):
        _, menu_id, idx_str = target.split(":", 2)
        BOT_DATA["menus"][menu_id]["buttons"][int(idx_str)]["label"] = styled_text
        save_data()
        await query.edit_message_text(f"✅ Button label updated ({label} style).")


# ----------------------------------------------------------------------------
# Basic user-facing commands
# ----------------------------------------------------------------------------

async def delete_incoming(update: Update):
    """#6 — best-effort cleanup of the user's own command message."""
    try:
        await update.message.delete()
    except Exception:
        pass


# The Send-Gift/Stars flow's "choose an amount" / invoice messages are
# tracked per-user and swept away the moment another menu is opened —
# no bot restart or persistent duplicate messages needed.


def _track_ephemeral(context: ContextTypes.DEFAULT_TYPE, message) -> None:
    if message is None:
        return
    ids = context.user_data.setdefault("ephemeral_msg_ids", [])
    ids.append((message.chat_id, message.message_id))


async def _clear_ephemeral(context: ContextTypes.DEFAULT_TYPE, chat_id: int = None) -> None:
    ids = context.user_data.pop("ephemeral_msg_ids", [])
    for cid, mid in ids:
        if chat_id is not None and cid != chat_id:
            continue
        try:
            await context.bot.delete_message(chat_id=cid, message_id=mid)
        except Exception:
            pass


async def require_disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """PDF #1 — gate behind LANGUAGE SELECTION FIRST, then the
    disclaimer/agree flow (no force-join check here). Kept as a standalone
    building block for require_gate() below; most call sites should use
    require_gate() instead, which also enforces force-join. Language is
    asked before the disclaimer so the disclaimer that follows can be shown
    immediately in the language the user just picked. Returns True if the
    user may proceed; otherwise shows whichever screen is still pending and
    returns False. Admins are exempt."""
    user_obj = update.effective_user
    if not user_obj:
        return True
    if is_admin(user_obj.id):
        return True
    uid = str(user_obj.id)
    user = BOT_DATA["users"].get(uid, {})
    if not user.get("lang_prompted"):
        user["lang_prompted"] = True
        save_data()
        await _send_language_picker(context, update.effective_chat.id)
        return False
    if not user.get("accepted_terms"):
        await render_menu(context, update.effective_chat.id, "disclaimer", lang=user.get("lang"))
        return False
    return True


async def show_force_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show one full-width-looking join button per required channel."""
    links = await get_force_join_links(context)
    kb_rows = []
    for i, link in enumerate(links, 1):
        label = "📢 Join Channel" if len(links) == 1 else f"📢 Join Channel {i}"
        kb_rows.append([styled_button(label, url=link, style="primary")])
    kb_rows.append([styled_button("✅ I'VE JOINED / SENT REQUEST", callback_data="check_force_join", style="success")])
    text = "🔒 " + to_small_caps("please join all required channels to use this bot.")
    if not links:
        text += "\n⚠️ " + to_small_caps("no usable join link found — contact an admin.")
    chat_id = update.effective_chat.id
    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
            return
        except Exception:
            pass
    await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb_rows))


# NOTE: the maintenance notice and the "bot is live again" message are both
# fully admin-customisable — edit them anytime via 🎨 Menu & UI → maintenance
# / bot_live, or directly from Settings → 🔒 Maintenance → ✏️ Set New Message.
# The constant below only exists as a last-resort fallback if the "bot_live"
# menu entry is ever missing from storage.
_BOT_LIVE_FALLBACK = (
    "✅ 𝐁𝐎𝐓 𝐈𝐒 𝐋𝐈𝐕𝐄\n\n"
    "ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ɪꜱ ᴄᴏᴍᴘʟᴇᴛᴇ — ᴛʜᴇ ʙᴏᴛ ɪꜱ ʙᴀᴄᴋ ᴜᴘ ᴀɴᴅ ʀᴜɴɴɪɴɢ ɴᴏʀᴍᴀʟʟʏ."
)


async def _send_typewriter(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str,
    reply_markup=None, parse_mode=None, delay: float = 0.25,
):
    """Reveals the message progressively, word by word, instead of dumping
    the full block instantly — a light animation just enough for a premium
    'someone is actually typing this' feel without dragging the user's wait
    time out. The button (if any) only appears on the final, complete
    message.

    parse_mode is applied ONLY on the final, complete frame — every
    intermediate reveal is sent as plain text. This matters when `text`
    contains HTML (e.g. a <blockquote> wrapper): parsing a half-revealed
    string as HTML would leave an unclosed tag and Telegram would reject
    the edit, so intermediate frames are deliberately unparsed and only the
    finished message renders styled.

    `delay` controls the pause between reveal steps — bump it slightly
    (e.g. for the Support confirmation) for a more deliberate, human-typed
    feel; the default stays snappy for shorter, lower-stakes messages."""
    words = text.split(" ")
    if len(words) <= 4:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(max(delay, 0.5))
        except Exception:
            pass
        return await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    steps = 5  # short and deliberate — just enough to feel alive, not slow
    chunk = max(1, -(-len(words) // steps))  # ceil division
    msg = None
    for i in range(chunk, len(words) + chunk, chunk):
        shown = " ".join(words[:i])
        is_last = i >= len(words)
        cursor = "" if is_last else " ▌"
        try:
            if msg is None:
                msg = await context.bot.send_message(chat_id=chat_id, text=shown + cursor)
            else:
                await msg.edit_text(
                    shown + cursor,
                    reply_markup=reply_markup if is_last else None,
                    parse_mode=parse_mode if is_last else None,
                )
        except Exception:
            pass
        if not is_last:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(delay)
    if msg is None:
        msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    return msg


async def send_maintenance_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Show the maintenance message — typed out live, with the 🔔 Notify Me
    button attached. Deletes that chat's previous notice first (if any) so
    at most one maintenance message ever sits in the chat at a time."""
    notice_map = BOT_DATA.setdefault("maintenance_notice_msg", {})
    chat_key = str(chat_id)
    prev_msg_id = notice_map.get(chat_key)
    if prev_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass  # already gone / too old to delete — fine, we just move on
        notice_map.pop(chat_key, None)

    try:
        menu = BOT_DATA["menus"].get("maintenance", {})
        if menu.get("image_file_id"):
            # admin has attached an image via the generic Menu & UI editor —
            # animation doesn't apply there, send normally.
            first = await render_menu(context, chat_id, "maintenance")
        else:
            text = menu.get("text") or to_small_caps("maintenance is currently active.")
            buttons = menu.get("buttons") or []
            kb = build_keyboard_from_buttons(buttons, "maintenance") if buttons else None
            first = await _send_typewriter(context, chat_id, text, reply_markup=kb)

        # Remember every chat_id shown the notice, so that when maintenance
        # is switched off we know exactly who to notify (instead of nobody
        # finding out except by tapping something again) — and remember
        # THIS message's id specifically, so it can be auto-deleted the
        # moment maintenance goes off, or replaced next time this fires.
        notified = BOT_DATA.setdefault("maintenance_notified", [])
        if chat_id not in notified:
            notified.append(chat_id)
        if first is not None:
            notice_map[chat_key] = first.message_id
        save_data()
        return first
    except Exception:
        return None


async def broadcast_bot_live(context: ContextTypes.DEFAULT_TYPE):
    """Ping everyone who saw the maintenance notice that the bot is back up,
    deleting their old notice first so the "bot is live" message replaces
    it instead of sitting underneath a stale card."""
    live_menu = BOT_DATA["menus"].get("bot_live", {})
    live_text = live_menu.get("text") or _BOT_LIVE_FALLBACK
    chat_ids = BOT_DATA.get("maintenance_notified", [])
    notice_map = BOT_DATA.setdefault("maintenance_notice_msg", {})
    for chat_id in chat_ids:
        prev_msg_id = notice_map.pop(str(chat_id), None)
        if prev_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
            except Exception:
                pass
        try:
            await context.bot.send_message(chat_id=chat_id, text=live_text, parse_mode=live_menu.get("parse_mode"))
        except Exception:
            pass
    BOT_DATA["maintenance_notified"] = []
    notice_map.clear()
    save_data()


async def require_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """The single source of truth for 'is this user allowed to do anything
    yet'. Combines the disclaimer-acceptance gate AND the force-join gate —
    until BOTH are satisfied, nothing else in the bot should run: no
    command, no inline button, no reply-keyboard button. Admins are exempt
    from both. Returns True if the user may proceed; otherwise shows
    whichever screen is still pending (disclaimer takes priority over
    force-join, since there's no point sending someone to join a channel
    before they've even agreed to use the bot) and returns False."""
    user_obj = update.effective_user
    if not user_obj:
        return True
    if is_admin(user_obj.id):
        return True
    if not await require_disclaimer(update, context):
        return False
    if not await is_force_join_ok(context, user_obj.id):
        await show_force_join_prompt(update, context)
        return False
    return True


async def cb_global_button_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registered in handler group -1, ahead of EVERY other handler — this
    is what makes 'no button works until agree + join' actually true,
    instead of each of 100+ individual callback handlers needing its own
    check (which is exactly how it stayed half-enforced before: some
    screens checked, most didn't). is_admin() inside require_gate() exempts
    admins as usual. The callbacks that ARE the gate itself — agree_terms,
    check_force_join, and setlang:* (language is now picked BEFORE the
    disclaimer, so it must work even though the user hasn't agreed to
    terms yet) — must fall through untouched, or the user would have no
    way to ever pass the gate."""
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    if data in ("maint_notify_me", "maint_notify_me_done"):
        # This IS the maintenance screen's own button — it must always work
        # while maintenance is on, or tapping it would just re-trigger the
        # maintenance notice instead of confirming the opt-in.
        return
    if BOT_DATA["settings"].get("maintenance") and not is_admin(update.effective_user.id):
        await send_maintenance_notice(context, update.effective_chat.id)
        try:
            await query.answer()
        except Exception:
            pass
        raise ApplicationHandlerStop
    if data in ("agree_terms", "check_force_join") or data.startswith("setlang:"):
        return
    if not await require_gate(update, context):
        try:
            await query.answer()
        except Exception:
            pass
        raise ApplicationHandlerStop



__all__ = [_n for _n in dir() if not _n.startswith("__")]
