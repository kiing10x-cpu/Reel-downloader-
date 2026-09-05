from helpers import *


LANG_NAMES = {
    "en": "English",
    "hi": "हिन्दी",
}


async def _send_language_picker(context: ContextTypes.DEFAULT_TYPE, chat_id: int, existing_message=None):
    """Shared 'choose your language' screen — shown at the very start of
    onboarding, before the disclaimer. Edits existing_message in place when
    given (so a button tap replaces the same message), otherwise sends a
    fresh one (e.g. the very first prompt during /start)."""
    text = (
        "🌐 <b>" + to_small_caps("Language Selection") + "</b>\n\n"
        "<blockquote>"
        "<u>➤ " + to_small_caps("Welcome!") + "</u>\n\n"
        + to_small_caps("Please select your preferred language to continue.") + "\n\n"
        "<u>➤ " + to_small_caps("Select Language") + "</u>\n"
        + to_small_caps("Choose one of the languages below.") +
        "</blockquote>"
    )
    current_lang = BOT_DATA["users"].get(str(chat_id), {}).get("lang") or "en"
    kb = build_language_keyboard(current_lang)
    if existing_message is not None:
        try:
            return await existing_message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
    return await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)


def build_language_keyboard(current_lang: str = None) -> InlineKeyboardMarkup:
    """Dynamic language picker — shows every language enabled in
    Settings > Languages (which is pre-filled from language_pack.json),
    not just English/Hindi. English is always included first since it's
    the bot's built-in/default language.

    FIX (list not being enabled): this used to be hardcoded to only
    हिन्दी + English, so even though language_pack.json ships 10 languages
    and Settings > Languages was pre-populated with all of them, the
    actual picker shown to users never reflected that. Now it reads
    BOT_DATA["settings"]["languages"] (admin-editable) and looks up each
    code's display name from language_pack.json's "languages" map — with
    flag emojis — falling back to LANG_NAMES/the bare code if a name
    isn't found.

    FIX (wrong highlight): the picker used to always render English in
    green ('success') no matter what the user actually had selected. Now
    it highlights whichever language is passed in as `current_lang` (the
    user's own saved preference, or "en" if they haven't picked yet), and
    marks it with a ✅ too so it's unambiguous even without colour.

    Layout: 2 languages per row (grid), as requested.
    """
    pack_names = _load_language_pack().get("languages", {})
    enabled = list(BOT_DATA.get("settings", {}).get("languages", []) or [])
    codes = ["en"] + [c for c in enabled if c != "en"]
    cur = current_lang or "en"

    def _label(code: str) -> str:
        return pack_names.get(code) or LANG_NAMES.get(code) or code.upper()

    buttons = []
    for code in codes:
        is_selected = (code == cur)
        label = ("✅ " if is_selected else "") + _label(code)
        buttons.append(styled_button(
            label, callback_data=f"setlang:{code}",
            style="success" if is_selected else "primary",
        ))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


async def show_post_onboarding(context: ContextTypes.DEFAULT_TYPE, chat_id: int, uid: str):
    """Lands the user on the start menu once both onboarding gates
    (language selection, then disclaimer — see require_disclaimer()) are
    already satisfied. The language-prompt branch that used to live here
    was moved earlier in the flow, ahead of the disclaimer, so language
    selection always happens first. This is kept as a safety fallback: if
    some caller ever reaches here with lang_prompted still unset, it shows
    the picker instead of skipping straight to start."""
    user = BOT_DATA["users"].get(uid, {})
    if not user.get("lang_prompted"):
        user["lang_prompted"] = True
        save_data()
        return await _send_language_picker(context, chat_id)
    sent = await render_menu(context, chat_id, "start")
    if not BOT_DATA["users"].get(uid, {}).get("reply_kb_sent"):
        try:
            await context.bot.send_message(chat_id, "⠀", reply_markup=main_reply_keyboard(is_admin(int(uid)), BOT_DATA["users"].get(uid, {}).get("lang")))
        except Exception:
            pass
        BOT_DATA["users"].setdefault(uid, {})["reply_kb_sent"] = True
        save_data()
    return sent


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_obj = update.effective_user
    if is_blocked(user_obj.id) and not is_admin(user_obj.id):
        return  # blocked users get silence, not an error
    is_new = touch_user(update)

    # Group-specific /start: don't show the private onboarding/gate flow in
    # a group. Show a clean card with the group name as a link and who
    # started the bot, matching the bot's house typography.
    if not _is_private_chat(update):
        chat = update.effective_chat
        title = html.escape(chat.title or "This Group")
        if getattr(chat, "username", None):
            group_link = f"https://t.me/{chat.username}"
        elif str(chat.id).startswith("-100") and update.message:
            group_link = f"https://t.me/c/{str(chat.id)[4:]}/{update.message.message_id}"
        else:
            group_link = None
        group_name = f'<a href="{group_link}">{title}</a>' if group_link else title
        starter = update.effective_user
        starter_name = html.escape(starter.full_name or "User")
        starter_link = f'<a href="tg://user?id={starter.id}">{starter_name}</a>'
        body = (
            "<blockquote>🚀 " + to_title_small_caps("Bot Started In") + "\n\n"
            + "👥 " + group_name + "\n"
            + "👤 " + to_title_small_caps("Started By") + " : " + starter_link + "\n\n"
            + to_title_small_caps("Send An Instagram Reel Link To Download It.")
            + "</blockquote>"
        )
        await update.message.reply_text(body, parse_mode="HTML", disable_web_page_preview=True)
        await notify_admins_new_start(context, update, is_new)
        await delete_incoming(update)
        return

    # Notify admins here, before any gate check (rate-limit, maintenance,
    # disclaimer/force-join) gets a chance to return early — touch_user()
    # already flipped is_new to False for any later /start from this user,
    # so this is the only point where a genuinely new user can be reported.
    await notify_admins_new_start(context, update, is_new)
    if not check_rate_limit(user_obj.id):
        await update.message.reply_text("⏳ " + to_small_caps("slow down, too many requests too fast."))
        await delete_incoming(update)
        return
    if BOT_DATA["settings"].get("maintenance") and not is_admin(user_obj.id):
        await send_maintenance_notice(context, update.effective_chat.id)
        await delete_incoming(update)
        return

    if not await require_gate(update, context):
        await delete_incoming(update)
        return

    BOT_DATA["metrics"]["start_count"] = BOT_DATA["metrics"].get("start_count", 0) + 1
    save_data()

    await send_premium_emoji_greeting(context.bot, update.effective_chat.id)
    sent = await show_post_onboarding(context, update.effective_chat.id, str(user_obj.id))
    await track_and_refresh_panel(context, update.effective_chat.id, "start", sent)
    await delete_incoming(update)


async def cb_maint_notify_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The 🔔 Notify Me button under the maintenance message. Tapping it:
    1) confirms the chat_id is on the notify list (it already is, but this
       makes the user's intent explicit), 2) turns the button itself from
       red → a blue, checked "Notified" state so it's visually obvious the
       tap registered, and 3) explains in plain words what happens next."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    notified = BOT_DATA.setdefault("maintenance_notified", [])
    if chat_id not in notified:
        notified.append(chat_id)
        save_data()
    try:
        await query.answer(
            "🔔 " + to_small_caps("notifications on!") + "\n"
            + to_small_caps("we'll message you here the instant the bot is back — no need to check manually."),
            show_alert=True,
        )
    except Exception:
        pass
    try:
        confirmed_kb = InlineKeyboardMarkup(
            [[styled_button("✅ " + to_small_caps("you'll be notified"), callback_data="maint_notify_me_done", style="primary")]]
        )
        # Beyond the popup alert (which disappears in a couple seconds),
        # leave a permanent line inside the message itself so the
        # confirmation stays visible in the chat, not just flashed once.
        confirm_line = "\n\n🔔 " + to_small_caps("notification set — we'll message you the moment the bot is back online.")
        base_text = query.message.caption if query.message.photo else query.message.text
        base_text = base_text or ""
        new_text = base_text if confirm_line.strip() in base_text else base_text + confirm_line
        if query.message.photo:
            await query.edit_message_caption(caption=new_text, reply_markup=confirmed_kb)
        else:
            await query.edit_message_text(new_text, reply_markup=confirmed_kb)
    except Exception:
        pass


async def cb_maint_notify_me_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Button already shows the confirmed (blue ✅) state — a second tap
    just reassures the user, it doesn't need to do anything further."""
    try:
        await update.callback_query.answer(
            "✅ " + to_small_caps("you're all set — you'll be notified automatically."),
            show_alert=False,
        )
    except Exception:
        pass


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_obj = update.effective_user
    if is_blocked(user_obj.id) and not is_admin(user_obj.id):
        return
    touch_user(update)
    if not await require_gate(update, context):
        await delete_incoming(update)
        return
    menu_id = "help_admin" if is_admin(user_obj.id) else "help_user"
    await render_menu(context, update.effective_chat.id, menu_id)
    await delete_incoming(update)


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_obj = update.effective_user
    if is_blocked(user_obj.id) and not is_admin(user_obj.id):
        return
    touch_user(update)
    if not await require_gate(update, context):
        await delete_incoming(update)
        return
    menu = BOT_DATA["menus"].get("language", {})
    lang = BOT_DATA["users"].get(str(user_obj.id), {}).get("lang")
    translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the bot.py default, never a translation override
    banner = (translation or {}).get("text") or menu.get("text") or DEFAULT_MENUS["language"]["text"]
    # build_language_keyboard() always includes at least English + Default
    # (Hinglish), whether or not the owner has added any extra languages in
    # Settings > Languages — so the picker should always be shown, never
    # blocked behind an "extra languages" check.
    await _replace_rkb_screen(
        context, update.effective_chat.id, "language",
        banner, reply_markup=build_language_keyboard(lang or "en"), parse_mode=menu.get("parse_mode"),
    )


async def cb_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]
    uid = str(update.effective_user.id)
    # Accept any language the admin has actually enabled, not just "hi".
    enabled_langs = set(BOT_DATA.get("settings", {}).get("languages", []) or [])
    lang_value = code if (code == "en" or code in enabled_langs) else "en"
    if uid in BOT_DATA["users"]:
        BOT_DATA["users"][uid]["lang"] = lang_value
        # Belt-and-suspenders: a selection from any source means the picker
        # has now been shown/handled for this user.
        BOT_DATA["users"][uid]["lang_prompted"] = True
        save_data()
    # Onboarding order: language is picked BEFORE the disclaimer. So if this
    # user hasn't agreed to the terms yet, the next screen is the disclaimer
    # — now shown in whichever language they just picked — not the start
    # menu. Returning users who change their language later (already past
    # the disclaimer) still land straight on start, same as before.
    if not BOT_DATA["users"].get(uid, {}).get("accepted_terms"):
        await render_menu(context, query.message.chat_id, "disclaimer", existing_message=query.message, lang=lang_value)
        return
    await render_menu(context, query.message.chat_id, "start", existing_message=query.message)
    # Refresh the persistent keyboard too, so a returning user who changes
    # language immediately sees the new labels instead of the old language.
    try:
        await context.bot.send_message(
            query.message.chat_id,
            "⠀",
            reply_markup=main_reply_keyboard(is_admin(int(uid)), lang_value),
        )
        BOT_DATA["users"].setdefault(uid, {})["reply_kb_sent"] = True
        save_data()
    except Exception as e:
        log_error("language_keyboard_refresh", f"could not refresh reply keyboard: {e}")


async def cb_agree_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PDF #1 — 'I Agree & Continue' button on the disclaimer screen."""
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    if uid in BOT_DATA["users"]:
        BOT_DATA["users"][uid]["accepted_terms"] = True
        BOT_DATA["users"][uid]["accepted_terms_at"] = datetime.utcnow().isoformat()
        save_data()
    try:
        await query.message.delete()
    except Exception:
        pass
    # Disclaimer accepted — now check the OTHER half of the gate before
    # letting the user any further in. If a force-join channel is set, they
    # see the join prompt right here instead of skipping straight to the
    # start menu.
    if not await is_force_join_ok(context, update.effective_user.id):
        await show_force_join_prompt(update, context)
        return
    await show_post_onboarding(context, query.message.chat_id, uid)


# ----------------------------------------------------------------------------
# Reel download
# ----------------------------------------------------------------------------

def build_reel_delivered_card(user_name: str, user_id, reel_number, original_reel_url: str, username: str = None) -> str:
    """HTML card used for both the Activity Channel AND the admin-DM Live
    Activity feed — same layout in both places so admins never see two
    different formats for the same event.

    Layout:
        Rᴇᴇʟ Nᴏ : #2      <- underlined (label + value)
        Sᴛᴀᴛᴜs : Dᴇʟɪᴠᴇʀᴇᴅ <- underlined (label + value)

        Uꜱᴇʀ : <clickable name>
        Uꜱᴇʀɴᴀᴍᴇ : Not Set / @username
        Uꜱᴇʀ ID : 123456

        Click Here To View Reel   (bare link, no visible URL)

    All dynamic values are HTML-escaped before insertion, including the
    URL used in the href attribute. The user's name is a clickable link
    straight to their Telegram profile (via @username if set, otherwise
    tg://user?id), same pattern as clickable_user() elsewhere in the bot.
    """
    safe_name = html.escape(str(user_name or "—"))
    safe_uid = html.escape(str(user_id))
    safe_no = html.escape(str(reel_number))
    safe_url = html.escape(original_reel_url or "", quote=True)
    username_display = f"@{username}" if username else "Not Set"

    if username:
        name_html = f'<a href="https://t.me/{html.escape(username, quote=True)}">{safe_name}</a>'
    else:
        name_html = f'<a href="tg://user?id={safe_uid}">{safe_name}</a>'

    reel_no_line = f"<u>{to_title_small_caps('Reel No')} : #{safe_no}</u>"
    status_line = f"<u>{to_title_small_caps('Status')} : {to_title_small_caps('Delivered')}</u>"

    return (
        f"{reel_no_line}\n"
        f"{status_line}\n\n"
        f"{to_title_small_caps('User')} : {name_html}\n"
        f"{to_title_small_caps('Username')} : {html.escape(username_display)}\n"
        f"{to_title_small_caps('User Id')} : {safe_uid}\n\n"
        f'<a href="{safe_url}">{to_title_small_caps("Click Here To View Reel")}</a>'
    )


async def send_reel_delivered_card(context, user_name: str, user_id, reel_number, original_reel_url: str, username: str = None):
    """Posts the reel-delivered card to admin-facing destinations, per the
    admin-configurable "📡 Notify Route" (Settings & Admins > Live Feed):
      - "logger"   -> Logger Channel only
      - "activity" -> Activity Channel only
      - "dm"       -> Admin DM only
      - "all"      -> all three (default)
    Same card/format everywhere, so admins never see two different-looking
    messages for the same event."""
    card = build_reel_delivered_card(user_name, user_id, reel_number, original_reel_url, username=username)
    s = BOT_DATA["settings"]
    route = s.get("notify_route", "all")

    if route in ("activity", "all") and s.get("activity_channel_enabled") and s.get("activity_channel_id"):
        try:
            await context.bot.send_message(
                chat_id=s["activity_channel_id"],
                text=card,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            log.warning("Activity Channel reel-delivered post failed", exc_info=True)

    if route in ("dm", "all") and s.get("user_activity_dm", True):
        await dm_all_admins(context, card, parse_mode="HTML")

    if route in ("logger", "all"):
        await log_event(context, card, parse_mode="HTML")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # update.message is None for edited messages/channel posts, which this
    # handler also matches against — guard before touching update.message.
    if update.message is None:
        return
    user_obj = update.effective_user
    if is_blocked(user_obj.id) and not is_admin(user_obj.id):
        return  # blocked users get silence, not an error

    # Maintenance is a hard global lock for non-admins: no reply-keyboard
    # action, support flow, reel parsing, auto-reply or media flow can run.
    if BOT_DATA["settings"].get("maintenance") and not is_admin(user_obj.id):
        await send_maintenance_notice(context, update.effective_chat.id)
        return

    # An admin replying to a forwarded ticket message routes straight back
    # to that user, bypassing everything else below.
    if update.message.reply_to_message and is_admin(user_obj.id):
        support_uid = BOT_DATA.get("support_msg_map", {}).get(str(update.message.reply_to_message.message_id))
        if support_uid:
            # Prefix the reply with a quote of the user's original problem
            # so it's clear which issue this is about.
            reply_rid = BOT_DATA.get("support_admin_msg_map", {}).get(
                str(update.message.reply_to_message.message_id)
            )
            problem_text = None
            if reply_rid:
                problem_text = BOT_DATA.get("support_requests", {}).get(reply_rid, {}).get("text")
            try:
                if problem_text:
                    tag = (
                        "<blockquote>"
                        + f"«{html.escape(problem_text[:300])}»" + "\n\n"
                        + to_title_small_caps("Admin's Reply") + " ↩️"
                        + "</blockquote>"
                    )
                    await context.bot.send_message(chat_id=int(support_uid), text=tag, parse_mode="HTML")
                await context.bot.copy_message(
                    chat_id=int(support_uid),
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                )
                await update.message.reply_text("✅ " + to_title_small_caps("Reply sent to user."))
            except Exception:
                await update.message.reply_text(
                    "⚠️ " + to_title_small_caps("Couldn't deliver reply — the user may have blocked the bot.")
                )
            return
        tid = BOT_DATA["ticket_msg_map"].get(str(update.message.reply_to_message.message_id))
        if tid:
            await handle_admin_ticket_reply(update, context, tid)
            return

    touch_user(update)
    user_id = user_obj.id
    uid = str(user_id)

    # While a user has an open ticket, every message auto-forwards into it.
    open_tid = BOT_DATA["users"].get(uid, {}).get("open_ticket_id")
    if open_tid and str(open_tid) in BOT_DATA["tickets"] and BOT_DATA["tickets"][str(open_tid)]["status"] == "open":
        await forward_to_ticket(update, context, open_tid)
        return

    text = update.message.text or ""

    # Group safety: never answer normal group conversation. The bot only
    # reacts to an actual Instagram URL (with or without @BotUsername).
    # Private chats retain the normal helpful invalid-link feedback.
    if not _is_private_chat(update) and text:
        if not INSTAGRAM_URL_RE.search(text):
            return

    # Non-text media outside an active ticket/awaiting-input flow has
    # nothing to do here.
    if not text and not context.user_data.get("awaiting"):
        return

    # Nothing below runs until the disclaimer + force-join gate clears.
    if not await require_gate(update, context):
        return

    # Persistent reply-keyboard routing. Each branch below deletes the
    # user's own tapped-button message and replaces the same panel in
    # place, so repeat taps leave only the latest copy behind.
    # RKB_ADMINPANEL is excluded — cmd_admin() replies to this exact
    # message first, then deletes it itself.
    user_lang = BOT_DATA["users"].get(uid, {}).get("lang")
    rkb_action = _rkb_action_for_text(text, user_lang)
    if rkb_action in {"download", "usage", "gift", "language", "developer", "howto", "support"}:
        await delete_incoming(update)
        # Tapping a bottom-keyboard button cancels any pending text-input
        # state (e.g. Support's "awaiting": "support_message") so a later
        # unrelated message doesn't get routed into the old flow. Branches
        # that need their own awaiting state set it again right after this.
        context.user_data.pop("awaiting", None)
    if text == RKB_DOWNLOAD:
        # Now a fully admin-editable menu (text/image/buttons) via
        # Menu & UI → "download", instead of a hardcoded string — same
        # single-slot panel behavior as every other reply-keyboard screen.
        sent = await render_menu(context, update.effective_chat.id, "download")
        await track_and_refresh_panel(context, update.effective_chat.id, "rkb_latest", sent)
        return
    if rkb_action == "usage":
        await show_usage_screen(update, context)
        return
    if rkb_action == "gift":
        await show_gift_menu(update, context)
        return
    if rkb_action == "language":
        await cmd_language(update, context)
        return
    if rkb_action == "developer":
        await show_developer_button(update, context)
        return
    if rkb_action == "howto":
        # Same treatment as Download Reel above — admin-editable via
        # Menu & UI → "howto".
        sent = await render_menu(context, update.effective_chat.id, "howto")
        await track_and_refresh_panel(context, update.effective_chat.id, "rkb_latest", sent)
        return
    if rkb_action == "support":
        await support_button_entry(update, context)
        return
    if rkb_action == "admin" and is_admin(user_id):
        await cmd_admin(update, context)
        return

    awaiting = context.user_data.get("awaiting")

    if awaiting == "premium_emoji_capture" and is_admin(user_id):
        await handle_premium_emoji_capture(update, context)
        return

    # PDF #3 / #11 — user-facing text-collection flows (copyright report,
    # support message) run regardless of admin status, before the
    # admin-only dispatcher below.
    if awaiting in (
        "support_message", "copyright_report_link", "copyright_report_details",
        "ticket_new", "gift_stars_custom_amount", "gift_upi_amount",
    ):
        await handle_user_awaiting_input(update, context, awaiting)
        return

    if awaiting and is_admin(user_id):
        await handle_admin_text_input(update, context, awaiting)
        return

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ " + to_small_caps("slow down, too many requests too fast."))
        return

    match = INSTAGRAM_URL_RE.search(text)
    if match and not is_admin(user_id) and not check_daily_limit(uid):
        limit = BOT_DATA["settings"].get("daily_limit", 20)
        kb = InlineKeyboardMarkup([[styled_button(to_small_caps("🚀 upgrade for more"), callback_data="gift_menu", style="success")]])
        await update.message.reply_text(
            "🚫 " + to_small_caps(f"daily limit reached ({limit}/{limit}). try again tomorrow or upgrade."),
            reply_markup=kb,
        )
        return

    if not match:
        # Never spam groups for ordinary conversation. Auto-replies and the
        # invalid-link message are intentionally private-chat only.
        if not _is_private_chat(update):
            return
        low = text.lower()
        for phrase, reply in BOT_DATA["settings"].get("auto_replies", {}).items():
            if phrase in low:
                await update.message.reply_text(reply)
                return
        await update.message.reply_text(USER_ERR_WRONG_FORMAT)
        return

    # Maintenance is already enforced at the top of handle_text().

    # (disclaimer + force-join already verified by require_gate() above —
    # no need to re-check either one here)

    url = match.group(1)

    # Anti-misuse monitoring: every reel link a user pastes is logged and,
    # by default, forwarded live to admin DMs (+ logger group) with a
    # one-tap ban button — this is a check-only feed, no automatic action.
    if not is_admin(user_id):
        await log_user_activity(context, update, url)

    if is_link_blocked(url) and not is_admin(user_id):
        await update.message.reply_text("🚫 " + to_small_caps("this link/domain has been blocked by admin."))
        return

    status_msg = await update.message.reply_text(STR["processing"])

    # Live progress, fed by yt-dlp's progress_hooks from the worker thread.
    _progress = {"pct": 0, "stage": "fetching"}

    def _progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            _progress["pct"] = int(done / total * 100) if total else 0
            _progress["stage"] = "fetching"
        elif d.get("status") == "finished":
            _progress["pct"] = 100
            _progress["stage"] = "optimizing"

    async def _animate_status():
        try:
            while True:
                await asyncio.sleep(2)
                pct = _progress["pct"]
                filled = pct // 10
                bar = "▓" * filled + "░" * (10 - filled)
                stage_label = to_small_caps(_progress["stage"])
                try:
                    await status_msg.edit_text(
                        to_small_caps("⏳ processing your reel...") + f"\n📥 {stage_label}\n{bar} {pct}%"
                    )
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    anim_task = asyncio.create_task(_animate_status())
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
    except Exception:
        pass

    out_template = os.path.join(DOWNLOAD_DIR, f"%(id)s_{int(time.time())}.%(ext)s")

    def build_ydl_opts(use_merge: bool) -> dict:
        # The no-merge path requires a format with both video and audio
        # already muxed together, format_sort prefers mp4/h264/aac (plays
        # cleanly everywhere), and merged audio is re-encoded to AAC so an
        # odd opus/vorbis track from IG doesn't end up silent in Telegram.
        opts = {
            "format": (
                "bestvideo*+bestaudio/best"
                if use_merge
                else "best[vcodec!=none][acodec!=none]/best"
            ),
            "format_sort": ["res", "ext:mp4:m4a", "vcodec:h264", "acodec:aac"],
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [_progress_hook],
        }
        if use_merge:
            opts["merge_output_format"] = "mp4"
            opts["postprocessor_args"] = {
                "ffmpeg_merger": ["-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart"]
            }
            if FFMPEG_PATH:
                opts["ffmpeg_location"] = FFMPEG_PATH
        return opts

    def run_download(use_merge: bool):
        opts = build_ydl_opts(use_merge)
        try:
            info = _ytdlp_extract_with_retry(opts, url, download=True)
        except Exception as first_error:
            # Instagram occasionally exposes only one extractor-visible stream
            # for a reel. Retry once with yt-dlp's broadest format selector
            # instead of failing solely because our quality preference was too
            # strict. The real exception still reaches logs if this also fails.
            log.warning("Preferred Instagram format failed; retrying with plain best: %s", first_error)
            opts = {
                "format": "best/bestvideo+bestaudio",
                "outtmpl": out_template,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [_progress_hook],
            }
            if FFMPEG_PATH:
                opts["ffmpeg_location"] = FFMPEG_PATH
            info = _ytdlp_extract_with_retry(opts, url, download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            fp = ydl.prepare_filename(info)
        stem = fp.rsplit(".", 1)[0]
        for candidate in (fp, stem + ".mp4", stem + ".webm", stem + ".mkv"):
            if os.path.exists(candidate):
                fp = candidate
                break
        ig_caption = (info.get("description") or "").strip()
        uploader = (info.get("uploader") or info.get("uploader_id") or "").strip()
        return fp, ig_caption, uploader

    file_path = None
    try:
        try:
            # run_download() is a blocking yt-dlp call, so it runs in a
            # thread — otherwise it would freeze the event loop for
            # everyone during every download.
            file_path, ig_caption, ig_uploader = await asyncio.to_thread(run_download, FFMPEG_AVAILABLE)
        except Exception as e:
            # Self-heal: if a merge was attempted and ffmpeg turned out to be
            # the problem, retry once with a no-merge (progressive) format.
            if "ffmpeg" in str(e).lower():
                log.warning("Merge failed (ffmpeg issue), retrying with progressive format.")
                file_path, ig_caption, ig_uploader = await asyncio.to_thread(run_download, False)
            else:
                raise

        # Telegram bots can't upload files over 50MB — check upfront and
        # give a clear message instead of a raw exception mid-upload.
        MAX_UPLOAD_BYTES = 50 * 1024 * 1024
        file_size = os.path.getsize(file_path) if file_path and os.path.exists(file_path) else 0
        if file_size > MAX_UPLOAD_BYTES:
            anim_task.cancel()
            mb = file_size / (1024 * 1024)
            await status_msg.edit_text(
                "❌ " + to_small_caps(f"this reel is too large to send ({mb:.1f}mb, limit 50mb). try a shorter reel.")
            )
            if os.path.exists(file_path):
                os.remove(file_path)
            return

        uid = str(update.effective_user.id)
        lang = BOT_DATA["users"].get(uid, {}).get("lang")
        menu = BOT_DATA["menus"]["reel_result"]
        translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the default language, never a translation override
        base_caption = (translation or {}).get("text") or menu.get("text", "")
        # The delivered reel gets a purpose-built action row.  The old
        # Caption callback is intentionally removed: short captions use
        # Telegram's native CopyTextButton, while long captions fall back
        # to a callback that sends the complete caption for normal copy.
        parse_mode = menu.get("parse_mode") or None
        kb = None

        # Native Telegram blockquote with the reel's caption, HTML only.
        if parse_mode == "HTML":
            import html as _html
            # Keep the caption visibly quoted under the reel.  Telegram's
            # native copy button can copy up to 256 characters; longer
            # captions get a callback fallback below so nothing is lost.
            preview = ig_caption[:700] + ("…" if len(ig_caption) > 700 else "")
            bq = (
                "<blockquote expandable>"
                f"📋 {_html.escape(preview) or '(none)'}"
                "</blockquote>"
            )
            result_caption = f"{base_caption}\n\n{bq}"
        else:
            result_caption = base_caption

        # Compact reel controls: Caption + Audio stay together on the first
        # row, while the full-width Remove Buttons control sits underneath.
        # Labels use the bot's small-caps font so the controls match the rest
        # of the user-facing UI.
        if ig_caption:
            if len(ig_caption) <= 256:
                try:
                    copy_btn = InlineKeyboardButton(
                        to_small_caps("Caption"),
                        copy_text=CopyTextButton(text=ig_caption),
                        **({"style": "primary"} if SUPPORTS_BUTTON_STYLE else {}),
                    )
                except TypeError:
                    copy_btn = InlineKeyboardButton(
                        to_small_caps("Caption"),
                        copy_text=CopyTextButton(text=ig_caption),
                    )
            else:
                copy_btn = styled_button(
                    to_small_caps("Caption"),
                    callback_data="copy_caption", style="primary"
                )
        else:
            copy_btn = None

        top_row = []
        if copy_btn is not None:
            top_row.append(copy_btn)
        top_row.append(styled_button(
            to_small_caps("🎵 Audio"), callback_data="get_audio", style="primary"
        ))
        kb_rows = [top_row, [styled_button(
            to_small_caps("❌ Remove Buttons"),
            callback_data="remove_reel", style="danger"
        )]]
        kb = InlineKeyboardMarkup(kb_rows)

        anim_task.cancel()
        protect = bool(BOT_DATA["settings"].get("lock_all_content", False))
        # Send as a document when the admin forces it, or the file is close
        # to the 50MB cap (documents preserve quality better near the limit).
        threshold = BOT_DATA["settings"].get("document_mode_threshold_mb", 45) * 1024 * 1024
        as_document = BOT_DATA["settings"].get("send_as_document", False) or file_size > threshold
        # Tell the user the reel is ready immediately before delivering the
        # actual media. Keep this as a separate, clean message.
        try:
            await status_msg.edit_text(to_small_caps("Your reel is ready"))
        except Exception:
            pass

        with open(file_path, "rb") as vid:
            if as_document:
                sent = await update.message.reply_document(
                    document=vid, caption=result_caption, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )
            else:
                sent = await update.message.reply_video(
                    video=vid, caption=result_caption, parse_mode=parse_mode, reply_markup=kb, protect_content=protect
                )

        # The original Instagram link is only needed during processing. Once
        # the reel has been delivered successfully, remove that incoming link
        # from the user's chat, matching the chat-cleanup behavior used by
        # the admin input flows.
        await delete_incoming(update)

        # Cache the real Instagram caption + source URL so the Copy Caption
        # fallback, Audio button, and Remove button under THIS specific video
        # can use them, keyed
        # to this exact message. The video file itself is deleted right
        # after sending (see finally: below), so Audio re-downloads
        # audio-only from the cached URL rather than needing the video kept
        # around on disk.
        _caption_cache[(sent.chat_id, sent.message_id)] = {
            "caption": ig_caption,
            "url": url,
            "uploader": ig_uploader,
            "title": (ig_caption.splitlines()[0] if ig_caption else ig_uploader or "Instagram Audio"),
        }
        if len(_caption_cache) > CAPTION_CACHE_MAX:
            _caption_cache.pop(next(iter(_caption_cache)))

        track_sent_message(sent.chat_id, sent.message_id)
        bump_usage(uid)
        BOT_DATA["metrics"]["reels_downloaded"] = BOT_DATA["metrics"].get("reels_downloaded", 0) + 1
        BOT_DATA["users"].setdefault(uid, {})["reels_count"] = BOT_DATA["users"].get(uid, {}).get("reels_count", 0) + 1
        await instagram_monitor_success(context, user_id)
        save_data()
        await log_event(
            context,
            f"📥 New download — user {user_id} (@{user_obj.username or 'no username'}) — {url}",
        )
        await send_reel_delivered_card(
            context,
            user_name=user_obj.full_name or (f"@{user_obj.username}" if user_obj.username else str(user_id)),
            user_id=user_id,
            reel_number=BOT_DATA["metrics"]["reels_downloaded"],
            original_reel_url=url,
            username=user_obj.username,
        )

        seconds = menu.get("auto_delete_seconds")
        if seconds is None:
            seconds = BOT_DATA["settings"].get("global_auto_delete_seconds", 0)
        await schedule_delete(context, sent.chat_id, sent.message_id, seconds)
        await status_msg.delete()
    except Exception as e:  # noqa: BLE001
        anim_task.cancel()
        log.exception("Download failed")
        # Technical details stay in logs/admin activity only. Never expose
        # yt-dlp/Instagram/ffmpeg exceptions to the end user.
        if "no video formats found" in str(e).lower():
            log_error("ytdlp_no_formats", f"url={url} err={e} — yt-dlp may need updating (pip install -U yt-dlp)")
        log_error("download", f"url={url} err={e}")
        await instagram_monitor_failure(context, user_id, e)
        try:
            await status_msg.edit_text(USER_ERR_NOT_AVAILABLE, parse_mode="HTML")
        except Exception:
            try:
                await update.message.reply_text(USER_ERR_NOT_AVAILABLE, parse_mode="HTML")
            except Exception:
                pass
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


async def cb_get_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = (query.message.chat_id, query.message.message_id)
    entry = _caption_cache.get(key)
    caption = entry.get("caption") if entry else None
    if not caption:
        await query.message.reply_text("ℹ️ " + to_small_caps("no caption found for this post (or cache expired)."))
        return
    # Telegram message limit is 4096 chars — split if needed.
    for i in range(0, len(caption), 4000):
        await query.message.reply_text(caption[i:i + 4000])
    uid = str(query.from_user.id)
    u = BOT_DATA["users"].setdefault(uid, {})
    u["caption_count"] = u.get("caption_count", 0) + 1
    BOT_DATA["metrics"]["caption_gets"] = BOT_DATA["metrics"].get("caption_gets", 0) + 1
    save_data()


async def cb_copy_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback for captions longer than Telegram's 256-char native
    CopyTextButton limit. Sends the complete caption so the user can use
    Telegram's normal copy action without truncation."""
    query = update.callback_query
    await query.answer()
    key = (query.message.chat_id, query.message.message_id)
    entry = _caption_cache.get(key)
    caption = entry.get("caption") if entry else None
    if not caption:
        await query.message.reply_text("ℹ️ " + to_small_caps("caption cache expired."))
        return
    for i in range(0, len(caption), 4000):
        await query.message.reply_text(caption[i:i + 4000])
    uid = str(query.from_user.id)
    u = BOT_DATA["users"].setdefault(uid, {})
    u["caption_count"] = u.get("caption_count", 0) + 1
    BOT_DATA["metrics"]["caption_gets"] = BOT_DATA["metrics"].get("caption_gets", 0) + 1
    save_data()


async def cb_remove_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove only the caption and buttons; never delete the reel itself."""
    query = update.callback_query
    await query.answer(to_small_caps("Removed"))
    key = (query.message.chat_id, query.message.message_id)
    _caption_cache.pop(key, None)

    # The media message must remain untouched. Telegram lets us edit the
    # caption/reply markup of the delivered media message independently.
    try:
        await query.message.edit_caption(caption=None, reply_markup=None)
        return
    except Exception:
        pass
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def cb_get_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🎵 Audio button under a delivered reel. The video file is already
    deleted by the time this is tapped, so this re-downloads the source and
    runs ffmpeg directly to strip the audio track — bypassing yt-dlp's
    FFmpegExtractAudio postprocessor, which needs ffprobe and isn't
    available on hosts that only carry the portable ffmpeg binary."""
    query = update.callback_query
    await query.answer()
    key = (query.message.chat_id, query.message.message_id)
    entry = _caption_cache.get(key)
    url = entry.get("url") if entry else None
    if not url:
        await query.message.reply_text("ℹ️ " + to_small_caps("couldn't find the source link for this post (cache expired)."))
        return

    status_msg = await query.message.reply_text("🎵 " + to_small_caps("extracting audio..."))

    # Ask yt-dlp for an audio-only format first, falling back toward
    # muxed/video formats only if a post genuinely has no separate audio
    # track. Instagram's reported acodec metadata isn't reliable, so
    # instead of trusting it we download a candidate and ask ffmpeg itself
    # whether the file actually has an audio stream, trying the next
    # candidate if not.
    def probe_has_audio(path: str) -> bool:
        try:
            result = subprocess.run(
                [FFMPEG_PATH, "-i", path], capture_output=True, text=True, timeout=30
            )
            return bool(re.search(r"Stream #\d+:\d+.*Audio:", result.stderr))
        except Exception:
            return False

    def build_source_opts(fmt: str):
        opts = {
            "format": fmt,
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s_audiosrc_" + str(int(time.time())) + "_%(format_id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH
        return opts

    def download_format(fmt: str):
        opts = build_source_opts(fmt)
        info = _ytdlp_extract_with_retry(opts, url, download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            fp = ydl.prepare_filename(info)
        return fp if os.path.exists(fp) else None

    def run_source_download():
        # Try, in order: a dedicated audio-only stream; the best muxed
        # (video+audio) stream; then whatever "best" resolves to as a last
        # resort. Each candidate is verified against the real file, not
        # metadata, before we commit to it — failed candidates are cleaned
        # up immediately so we don't leave stray video-only files behind.
        candidates = ["bestaudio", "best[acodec!=none][vcodec!=none]", "best"]
        tried_paths = []
        for fmt in candidates:
            try:
                fp = download_format(fmt)
            except Exception as e:
                log.warning("audio-source download failed for format %r: %s", fmt, e)
                continue
            if not fp:
                continue
            tried_paths.append(fp)
            if probe_has_audio(fp):
                # Clean up any earlier failed attempts before returning.
                for p in tried_paths[:-1]:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                return fp
        # Nothing worked — clean up every attempt and report clearly.
        for p in tried_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        if tried_paths:
            raise RuntimeError("this post doesn't seem to have an audio track (checked multiple formats).")
        return None

    def extract_audio_ffmpeg(src_path: str) -> str:
        """Direct ffmpeg call — no ffprobe involved."""
        mp3_path = os.path.splitext(src_path)[0] + ".mp3"
        cmd = [
            FFMPEG_PATH, "-y", "-i", src_path,
            "-vn", "-acodec", "libmp3lame", "-q:a", "2",
            mp3_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not os.path.exists(mp3_path):
            raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr[-500:]}")
        return mp3_path

    source_path = None
    audio_path = None
    try:
        if not FFMPEG_AVAILABLE:
            # Audio extraction (muxing out just the audio track) genuinely
            # needs ffmpeg, unlike plain video download — no safe fallback.
            await status_msg.edit_text(
                "❌ " + to_small_caps("audio extraction needs ffmpeg, which isn't available on this server.")
            )
            return
        source_path = await asyncio.to_thread(run_source_download)
        if not source_path:
            await status_msg.edit_text(USER_ERR_AUDIO_NOT_AVAILABLE, parse_mode="HTML")
            return
        audio_path = await asyncio.to_thread(extract_audio_ffmpeg, source_path)
        if not audio_path or not os.path.exists(audio_path):
            await status_msg.edit_text(USER_ERR_AUDIO_NOT_AVAILABLE, parse_mode="HTML")
            return
        protect = bool(BOT_DATA["settings"].get("lock_all_content", False))
        # Give Telegram a clean, human-readable filename/title instead of the
        # temporary yt-dlp filename full of ids and timestamps.
        audio_title = _safe_filename((entry or {}).get("uploader") or (entry or {}).get("title") or "Instagram Audio")
        filename = _safe_filename((entry or {}).get("title") or audio_title) + ".mp3"
        with open(audio_path, "rb") as aud:
            await query.message.reply_audio(
                audio=aud, protect_content=protect, filename=filename,
                title=audio_title, performer="Instagram"
            )
        uid = str(query.from_user.id)
        u = BOT_DATA["users"].setdefault(uid, {})
        u["audio_count"] = u.get("audio_count", 0) + 1
        BOT_DATA["metrics"]["audio_gets"] = BOT_DATA["metrics"].get("audio_gets", 0) + 1
        save_data()
        await status_msg.delete()
    except Exception as e:
        # Full technical error is useful for debugging, but must never be
        # shown to users. Keep it in the server/admin log only.
        log.exception("Audio extraction failed for %s", url)
        log_error("audio", f"url={url} err={e}")
        try:
            await status_msg.edit_text(USER_ERR_AUDIO_NOT_AVAILABLE, parse_mode="HTML")
        except Exception:
            try:
                await query.message.reply_text(USER_ERR_AUDIO_NOT_AVAILABLE, parse_mode="HTML")
            except Exception:
                pass
    finally:
        for p in (source_path, audio_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


async def cb_check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ok = await is_force_join_ok(context, update.effective_user.id)
    if ok:
        await query.answer(to_small_caps("✅ verified!"), show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        # Both gates are clear now — land the user in the start menu (this
        # covers the onboarding path; if they were already past onboarding
        # and just got re-blocked later, show_post_onboarding is a no-op
        # past the language-picker/reply-keyboard first-run bits and just
        # re-renders start, which is fine here).
        uid = str(update.effective_user.id)
        await show_post_onboarding(context, query.message.chat_id, uid)
    else:
        await query.answer(to_small_caps("❌ still not joined."), show_alert=True)


async def cb_download_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🔗 " + to_small_caps("paste your next instagram reel link."))


# ----------------------------------------------------------------------------
# v11 — OWNER-ONLY Instagram Download Failure Monitor
# ----------------------------------------------------------------------------


def _ig_monitor_state() -> dict:
    state = BOT_DATA.setdefault("instagram_monitor", {})
    state.setdefault("failures", [])
    state.setdefault("successes", [])
    state.setdefault("outage_active", False)
    state.setdefault("last_alert_at", None)
    state.setdefault("last_recovery_at", None)
    state.setdefault("last_error_category", None)
    state.setdefault("last_error_detail", None)
    state.setdefault("alert_count", 0)
    state.setdefault("recovery_count", 0)
    return state


def _ig_monitor_cfg(key: str, default):
    return BOT_DATA.get("settings", {}).get(key, default)


def _ig_error_category(error: Exception | str) -> str:
    msg = str(error).lower()
    # These are normally properties of one URL, not an Instagram-wide outage.
    individual = (
        "private", "deleted", "not found", "does not exist", "invalid url",
        "unsupported url", "login required", "not available", "removed",
        "page isn't available", "page is unavailable",
    )
    if any(x in msg for x in individual):
        return "individual_link"
    if any(x in msg for x in ("timed out", "timeout", "connection", "network",
                              "dns", "temporarily unavailable", "502", "503",
                              "504", "429", "rate limit")):
        return "network_temporary"
    if any(x in msg for x in ("no video formats found", "unable to extract",
                              "requested format is not available",
                              "extractor", "instagram")):
        return "instagram_extractor"
    if "ffmpeg" in msg or "ffprobe" in msg:
        return "local_media"
    return "download_other"


def _ig_monitor_prune(now: datetime | None = None):
    now = now or datetime.utcnow()
    st = _ig_monitor_state()
    window = timedelta(minutes=int(_ig_monitor_cfg("instagram_monitor_window_minutes", 10)))
    cutoff = now - window
    for key in ("failures", "successes"):
        kept = []
        for e in st.get(key, []):
            try:
                dt = datetime.fromisoformat(e["time"])
                if dt >= cutoff:
                    kept.append(e)
            except Exception:
                continue
        st[key] = kept[-100:]


async def _ig_monitor_admin_ids(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    raw = BOT_DATA.get("settings", {}).get("instagram_monitor_owner_ids")
    ids = raw if isinstance(raw, list) else []
    if not ids and OWNER_ID:
        ids = [OWNER_ID]
    out = []
    for value in ids:
        try:
            iv = int(value)
            if iv and iv not in out:
                out.append(iv)
        except Exception:
            pass
    return out


async def _ig_monitor_send_alert(context: ContextTypes.DEFAULT_TYPE, recovered: bool = False):
    st = _ig_monitor_state()
    now = datetime.utcnow()
    if recovered:
        text = (
            "🟢 " + to_title_small_caps("Instagram Download System") + "\n\n"
            "✓ " + to_small_caps("downloading has recovered.") + "\n\n"
            + f"{to_title_small_caps('Status')} : 🟢 " + to_small_caps("Operational") + "\n"
            + f"{to_title_small_caps('Successful Checks')} : {len(st.get('successes', []))}\n"
            + f"{to_title_small_caps('Failures')} : {len(st.get('failures', []))}\n"
            + f"{to_title_small_caps('Time')} : {now_ist_str('%d %b %Y, %I:%M:%S %p')} IST\n\n"
            + to_small_caps("the Instagram downloader is working normally again.")
        )
    else:
        failures = st.get("failures", [])
        categories = {}
        for e in failures:
            categories[e.get("category", "unknown")] = categories.get(e.get("category", "unknown"), 0) + 1
        reason = max(categories, key=categories.get) if categories else "unknown"
        text = (
            "🚨 " + to_title_small_caps("Instagram Download Alert") + "\n\n"
            "⚠️ " + to_small_caps("possible system issue detected") + "\n\n"
            + to_small_caps("Instagram reel downloads are failing unusually.") + "\n\n"
            + f"{to_title_small_caps('Failures')} : {len(failures)}\n"
            + f"{to_title_small_caps('Affected Users')} : {len({e.get('user_id') for e in failures})}\n"
            + f"{to_title_small_caps('Status')} : 🔴 " + to_small_caps("Unstable") + "\n"
            + f"{to_title_small_caps('Category')} : {html.escape(reason.replace('_', ' ').title())}\n"
            + f"{to_title_small_caps('Window')} : {int(_ig_monitor_cfg('instagram_monitor_window_minutes', 10))} min\n"
            + f"{to_title_small_caps('Time')} : {now_ist_str('%d %b %Y, %I:%M:%S %p')} IST\n\n"
            + to_small_caps("the bot will continue monitoring the system.")
        )
    kb = InlineKeyboardMarkup([[styled_button("🔄 " + to_small_caps("Check Status"), callback_data="ai_check")]])
    for aid in await _ig_monitor_admin_ids(context):
        try:
            await context.bot.send_message(aid, text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            log.exception("Instagram monitor notification failed for admin %s", aid)


async def instagram_monitor_failure(context: ContextTypes.DEFAULT_TYPE, user_id: int, error: Exception | str):
    """Record a REAL Instagram Reel download failure without blocking the downloader."""
    try:
        now = datetime.utcnow()
        st = _ig_monitor_state()
        category = _ig_error_category(error)
        _ig_monitor_prune(now)
        # Ignore failures that are clearly local/individual when deciding on an IG-wide outage.
        event = {"time": now.isoformat(), "user_id": str(user_id), "category": category,
                 "detail": str(error)[:500]}
        st["failures"].append(event)
        st["last_error_category"] = category
        st["last_error_detail"] = str(error)[:500]
        _ig_monitor_prune(now)

        candidates = [e for e in st["failures"]
                      if e.get("category") == category
                      and category not in ("individual_link", "local_media", "network_temporary")]
        threshold = int(_ig_monitor_cfg("instagram_monitor_threshold", 5))
        distinct_users = len({e.get("user_id") for e in candidates})
        likely_systemic = len(candidates) >= threshold and (distinct_users >= 2 or len(candidates) >= threshold + 2)

        if likely_systemic and not st.get("outage_active"):
            cooldown = timedelta(minutes=int(_ig_monitor_cfg("instagram_monitor_cooldown_minutes", 60)))
            last = None
            try:
                last = datetime.fromisoformat(st.get("last_alert_at")) if st.get("last_alert_at") else None
            except Exception:
                pass
            if last is None or now - last >= cooldown:
                st["outage_active"] = True
                st["last_alert_at"] = now.isoformat()
                st["alert_count"] = int(st.get("alert_count", 0)) + 1
                save_data()
                await _ig_monitor_send_alert(context, recovered=False)
                return
        save_data()
    except Exception:
        # Monitoring must NEVER break the main Reel Downloader.
        log.exception("Instagram failure monitor crashed")


async def instagram_monitor_success(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Record a successful Reel delivery and detect recovery after an outage."""
    try:
        now = datetime.utcnow()
        st = _ig_monitor_state()
        _ig_monitor_prune(now)
        st["successes"].append({"time": now.isoformat(), "user_id": str(user_id)})
        _ig_monitor_prune(now)
        if st.get("outage_active"):
            threshold = int(_ig_monitor_cfg("instagram_monitor_recovery_successes", 3))
            if len(st["successes"]) >= threshold:
                st["outage_active"] = False
                st["last_recovery_at"] = now.isoformat()
                st["recovery_count"] = int(st.get("recovery_count", 0)) + 1
                save_data()
                await _ig_monitor_send_alert(context, recovered=True)
                return
        save_data()
    except Exception:
        log.exception("Instagram recovery monitor crashed")


async def _render_ai_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin live control-room dashboard with the bot-wide premium
    typography, pointer + underline convention, and a single Telegram
    blockquote card. Rendering is read-only and never blocks downloading."""
    query = update.callback_query
    if not is_admin(update.effective_user.id):
        await query.answer("🔒 " + to_small_caps("admin only."), show_alert=True)
        return

    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    _ig_monitor_prune(now)
    st = _ig_monitor_state()

    def recent(ts):
        dt = _parse_iso(ts)
        return bool(dt and dt >= day_ago)

    users = BOT_DATA.get("users", {})
    active_24h = sum(1 for u in users.values() if recent(u.get("last_active")))
    new_users_24h = sum(1 for u in users.values() if recent(u.get("joined")))
    events_24h = [e for e in BOT_DATA.get("activity_log", []) if recent(e.get("time"))]
    errors_24h = [e for e in BOT_DATA.get("error_log", []) if recent(e.get("time"))]
    download_errors_24h = [e for e in errors_24h if e.get("kind") in ("download", "ytdlp_no_formats")]

    request_count = len(events_24h)
    monitor_failures = st.get("failures", [])
    monitor_successes = st.get("successes", [])
    systemic = [e for e in monitor_failures if e.get("category") == "instagram_extractor"]
    distinct_failed_users = len({e.get("user_id") for e in systemic if e.get("user_id")})
    total_health_events = len(monitor_failures) + len(monitor_successes)
    health_rate = (len(monitor_successes) / total_health_events * 100) if total_health_events else 100.0

    if st.get("outage_active"):
        status = "🔴 " + to_small_caps("Instagram downloads unstable")
        state_label = "🔴 " + to_small_caps("Critical")
    elif systemic and len(systemic) >= max(1, int(_ig_monitor_cfg("instagram_monitor_threshold", 5)) - 1):
        status = "🟡 " + to_small_caps("Instagram being watched closely")
        state_label = "🟡 " + to_small_caps("Warning")
    else:
        status = "🟢 " + to_small_caps("Instagram downloads operational")
        state_label = "🟢 " + to_small_caps("Operational")

    last_failure = monitor_failures[-1] if monitor_failures else None
    last_error = html.escape(str(st.get("last_error_detail") or "—")[:120])
    last_category = html.escape(str((last_failure or {}).get("category") or "—"))

    def row(icon, label, value):
        return f"{icon} <u>➤ {to_small_caps(label)}</u> : {value}"

    lines = [
        "🤖 " + to_title_small_caps("AI Check"),
        "",
        "<u>📊 " + to_title_small_caps("Admin Dashboard") + "</u>",
        row("📡", "Instagram Status", status),
        row("⏱", "Bot Uptime", html.escape(human_uptime())),
        row("👥", "Total Users", len(users)),
        row("🆕", "New Users · 24h", new_users_24h),
        row("🟢", "Active Users · 24h", active_24h),
        row("🎬", "Reel Requests · 24h", request_count),
        row("❌", "Download Errors · 24h", len(download_errors_24h)),
        row("📈", "Lifetime Reels Delivered", BOT_DATA.get("metrics", {}).get("reels_downloaded", 0)),
        "",
        "<u>🧠 " + to_title_small_caps("Smart Instagram Monitor") + "</u>",
        row("🚦", "State", state_label),
        row("📉", "Failures · Window", len(monitor_failures)),
        row("✓", "Successes · Window", len(monitor_successes)),
        row("🎯", "Failure Threshold", int(_ig_monitor_cfg("instagram_monitor_threshold", 5))),
        row("🕒", "Detection Window", f"{int(_ig_monitor_cfg('instagram_monitor_window_minutes', 10))} min"),
        row("🔁", "Recovery Threshold", f"{int(_ig_monitor_cfg('instagram_monitor_recovery_successes', 3))} successes"),
        row("⏳", "Alert Cooldown", f"{int(_ig_monitor_cfg('instagram_monitor_cooldown_minutes', 60))} min"),
        row("👤", "Affected Users · Extractor", distinct_failed_users),
        row("📊", "Health Rate · Window", f"{health_rate:.0f}%"),
        row("🧩", "Last Error Type", last_category),
        row("📝", "Last Error", last_error),
    ]
    if st.get("last_alert_at"):
        lines.append(row("🚨", "Last Alert", html.escape(str(st.get("last_alert_at")))))
    if st.get("last_recovery_at"):
        lines.append(row("🟢", "Last Recovery", html.escape(str(st.get("last_recovery_at")))))

    # Keep the entire dashboard inside the same native Telegram quote/card,
    # matching the bot's existing premium message convention.
    text = "<blockquote>" + "\n".join(lines) + "</blockquote>"
    kb = InlineKeyboardMarkup([
        [styled_button("🔄 " + to_small_caps("Refresh"), callback_data="ai_check")],
        [styled_button("📊 " + to_small_caps("Statistics"), callback_data="adm_stats"),
         styled_button("📜 " + to_small_caps("Activity Log"), callback_data="adm_activity")],
        back_row(),
        home_row(),
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def cb_ai_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_ai_check(update, context)


# ----------------------------------------------------------------------------
# Support ticket system
# ----------------------------------------------------------------------------



__all__ = [_n for _n in dir() if not _n.startswith("__")]
