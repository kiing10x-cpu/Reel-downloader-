from handlers_user import *


async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    uid = str(update.effective_user.id)
    tid = BOT_DATA["next_ticket_id"]
    BOT_DATA["next_ticket_id"] += 1
    ticket = {
        "id": tid, "user_id": update.effective_user.id, "status": "open",
        "created_at": datetime.utcnow().isoformat(), "closed_at": None,
    }
    BOT_DATA["tickets"][str(tid)] = ticket
    BOT_DATA["users"].setdefault(uid, {})["open_ticket_id"] = tid
    save_data()
    return ticket


async def post_ticket_card(context: ContextTypes.DEFAULT_TYPE, ticket: dict, user_obj):
    group_id = BOT_DATA["settings"].get("admin_group_id")
    targets = [group_id] if group_id else BOT_DATA.get("admins", [])
    card_text = f"👤 {user_obj.full_name} | 🆔 {user_obj.id} | 🎫 #{ticket['id']} | Status: 🟢 Open"
    kb = InlineKeyboardMarkup([[
        styled_button("✅ Close Ticket", callback_data=f"tk_close:{ticket['id']}"),
        styled_button("🔁 Reopen", callback_data=f"tk_reopen:{ticket['id']}"),
    ]])
    for target in targets:
        if not target:
            continue
        try:
            sent = await context.bot.send_message(chat_id=target, text=card_text, reply_markup=kb)
            BOT_DATA["ticket_msg_map"][str(sent.message_id)] = str(ticket["id"])
        except Exception:
            pass
    save_data()


async def forward_to_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    group_id = BOT_DATA["settings"].get("admin_group_id")
    targets = [group_id] if group_id else BOT_DATA.get("admins", [])
    for target in targets:
        if not target:
            continue
        try:
            copied = await context.bot.copy_message(
                chat_id=target, from_chat_id=update.effective_chat.id, message_id=update.message.message_id
            )
            BOT_DATA["ticket_msg_map"][str(copied.message_id)] = str(ticket_id)
        except Exception:
            pass
    save_data()


async def handle_admin_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, tid: str):
    ticket = BOT_DATA["tickets"].get(tid)
    if not ticket or ticket["status"] != "open":
        return
    # v10 — same confirmation-to-admin fix as the one-shot support flow above.
    try:
        await context.bot.copy_message(
            chat_id=ticket["user_id"], from_chat_id=update.effective_chat.id, message_id=update.message.message_id
        )
        await update.message.reply_text("✅ " + to_title_small_caps("Reply sent to user."))
    except Exception:
        await update.message.reply_text(
            "⚠️ " + to_title_small_caps("Couldn't deliver reply — the user may have blocked the bot.")
        )


def get_support_prompt_text(uid: str = None) -> str:
    """v10 — sourced from BOT_DATA['menus']['support'] so the admin can edit
    this from Menu & UI, falling back to the original default copy.
    v11 — now also respects the user's saved language, same lookup
    render_menu() uses, so Support shows the translated text instead of
    always falling back to the base/English copy."""
    menu = BOT_DATA["menus"].get("support", {})
    lang = BOT_DATA["users"].get(str(uid), {}).get("lang") if uid else None
    translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the bot.py default, never a translation override
    return (translation or {}).get("text") or menu.get("text") or DEFAULT_MENUS["support"]["text"]


async def support_button_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-shot support flow: user gets exactly one message to submit.
    The admin receives a mention and can reply directly to that single support
    message; there is no lingering open-ticket state.

    NOTE — this prompt is intentionally the ONLY thing sent through
    _replace_rkb_screen (the shared "rkb_latest" panel slot). The
    confirmation sent after submission is sent separately (see
    handle_user_awaiting_input) and is never tracked under that slot, so
    switching to another bottom-keyboard button later can never delete the
    user's submission confirmation. The prompt itself IS explicitly deleted
    the moment the user submits their message — see the "support_message"
    branch of handle_user_awaiting_input."""
    chat_id = update.effective_chat.id
    context.user_data["awaiting"] = "support_message"
    await _replace_rkb_screen(context, chat_id, "support", get_support_prompt_text(uid=chat_id), parse_mode="HTML")


async def cb_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    tid = query.data.split(":", 1)[1]
    ticket = BOT_DATA["tickets"].get(tid)
    if not ticket:
        return
    ticket["status"] = "closed"
    ticket["closed_at"] = datetime.utcnow().isoformat()
    uid = str(ticket["user_id"])
    if BOT_DATA["users"].get(uid, {}).get("open_ticket_id") == int(tid):
        BOT_DATA["users"][uid]["open_ticket_id"] = None
    save_data()
    try:
        await context.bot.send_message(chat_id=ticket["user_id"], text=STR["ticket_closed"](tid))
    except Exception:
        pass
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup([[styled_button("🔁 Reopen", callback_data=f"tk_reopen:{tid}")]])
        )
    except Exception:
        pass
    await log_event(context, f"🎫 Ticket #{tid} closed by {update.effective_user.id}")


async def cb_ticket_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    tid = query.data.split(":", 1)[1]
    ticket = BOT_DATA["tickets"].get(tid)
    if not ticket:
        return
    ticket["status"] = "open"
    ticket["closed_at"] = None
    uid = str(ticket["user_id"])
    BOT_DATA["users"].setdefault(uid, {})["open_ticket_id"] = int(tid)
    save_data()
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup([[styled_button("✅ Close Ticket", callback_data=f"tk_close:{tid}")]])
        )
    except Exception:
        pass
    await log_event(context, f"🎫 Ticket #{tid} reopened by {update.effective_user.id}")


_CARD_SEP = "──────────────────"


def _build_support_admin_card(rid: str) -> tuple:
    """Admin-facing 'New Support Request' card — sectioned layout, message
    quoted in « », live Pending/Resolved status, name is a clickable link
    to the user's profile. Reused both when the request first comes in and
    when an admin marks it resolved, so the card always reflects the live
    status."""
    req = BOT_DATA["support_requests"][rid]
    lbl = to_title_small_caps
    is_open = req["status"] == "pending"
    status_word = lbl("Pending") if is_open else lbl("Resolved")
    received = iso_to_ist_str(req["created_at"], "%d %B %Y") + " • " + iso_to_ist_str(req["created_at"], "%H:%M:%S") + " IST"
    payload = (
        "📩 " + lbl("New Support Request") + "\n\n"
        f"{_CARD_SEP}\n\n"
        "👤 " + lbl("User Information") + "\n\n"
        f"{lbl('Name')} : {req['user_mention']}\n"
        f"{lbl('Username')} : {html.escape(req['username_display'])}\n"
        f"{lbl('User Id')} : {req['user_id']}\n\n"
        "💬 " + lbl("Support Message") + "\n\n"
        f"«{html.escape(req['text'])}»\n\n"
        "🕒 " + lbl("Received At") + "\n\n"
        f"{received}\n\n"
        f"{_CARD_SEP}\n\n"
        "📌 " + f"{lbl('Status')} : {status_word}"
    )
    kb = None
    if is_open:
        kb = InlineKeyboardMarkup([[
            styled_button("✅ Mark Resolved", callback_data=f"sup_resolve:{rid}"),
        ]])
    return payload, kb


def _build_support_user_confirmation(rid: str) -> str:
    """User-facing confirmation — the exact requested copy, with the live
    status swapped between the just-submitted card and the resolved card."""
    req = BOT_DATA["support_requests"][rid]
    lbl = to_title_small_caps
    if req["status"] == "pending":
        body = (
            "✅ " + lbl("Message Submitted") + "\n\n"
            + lbl("Thank you for contacting support.") + "\n\n"
            + "📩 " + lbl("Your message has been sent to our support team.") + "\n\n"
            + lbl("We'll review it and get back to you as soon as possible.") + "\n\n"
            + "❤️ " + lbl("Thank you for your patience.")
        )
    else:
        body = (
            "✅ " + lbl("Support Request Resolved") + "\n\n"
            + lbl("Thank you for contacting support.") + "\n\n"
            + "📩 " + lbl("Your issue has been reviewed and marked as resolved.") + "\n\n"
            + lbl("Need anything else? Just send us a new message anytime.") + "\n\n"
            + "❤️ " + lbl("Thank you for your patience.")
        )
    return "<blockquote>" + body + "</blockquote>"


async def cb_support_resolve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin taps '✅ Mark Resolved' on a support card. This is what makes
    the user-facing status live instead of frozen on PENDING forever — we
    edit the SAME confirmation message in the user's chat in place, and
    edit this same admin card too, rather than sending fresh clutter."""
    query = update.callback_query
    if not is_admin(update.effective_user.id):
        await query.answer()
        return
    rid = query.data.split(":", 1)[1]
    req = BOT_DATA["support_requests"].get(rid)
    if not req:
        await query.answer("Request not found.", show_alert=True)
        return
    if req["status"] != "pending":
        await query.answer("Already resolved.")
        return

    req["status"] = "resolved"
    req["resolved_at"] = datetime.utcnow().isoformat()
    req["resolved_by"] = update.effective_user.id
    save_data()

    # Live-update the user's own confirmation message: PENDING -> SOLVED.
    try:
        await context.bot.edit_message_text(
            chat_id=req["confirm_chat_id"],
            message_id=req["confirm_message_id"],
            text=_build_support_user_confirmation(rid),
            parse_mode="HTML",
        )
    except Exception:
        # Message may have been deleted by the user / too old to edit —
        # fall back to a fresh "resolved" message in the same style.
        try:
            msg = await context.bot.send_message(
                chat_id=req["confirm_chat_id"], text=_build_support_user_confirmation(rid), parse_mode="HTML"
            )
            req["confirm_chat_id"] = msg.chat_id
            req["confirm_message_id"] = msg.message_id
            save_data()
        except Exception:
            pass

    # Live-update this admin card too (Pending -> Resolved, button removed).
    card_text, card_kb = _build_support_admin_card(rid)
    try:
        await query.edit_message_text(card_text, parse_mode="HTML", reply_markup=card_kb)
    except Exception:
        pass

    await query.answer("✅ Marked resolved.")
    await log_event(context, f"🎧 Support request #{rid} resolved by {update.effective_user.id}")


# ----------------------------------------------------------------------------
# My usage
# ----------------------------------------------------------------------------


async def show_usage_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 Stats screen. Premium status/expiry are hidden unless a Premium
    plan has actually been assigned to this user from the Admin Panel."""
    await _clear_ephemeral(context, update.effective_chat.id)
    user = update.effective_user
    uid = str(user.id)
    u = BOT_DATA["users"].setdefault(uid, {})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    used = u.get("downloads_today", 0) if u.get("downloads_today_date") == today else 0
    assigned_premium = u.get("plan", "Free") != "Free"
    active = is_premium_active(uid)
    limit = BOT_DATA["settings"].get("daily_limit", 20)
    username = f"@{user.username}" if user.username else "Not set"
    limit_text = "Unlimited" if assigned_premium else str(limit)
    remaining = "Unlimited" if assigned_premium else str(max(0, limit - used))

    lines = [
        "<u>" + to_title_small_caps("My Usage") + "</u>", "",
        f"Nᴀᴍᴇ : {html.escape(user.full_name)}",
        f"Uꜱᴇʀɴᴀᴍᴇ : {html.escape(username)}",
        f"Uꜱᴇʀ Iᴅ : {user.id}",
        f"Rᴇᴇʟs Dᴏᴡɴʟᴏᴀᴅᴇᴅ : {u.get('reels_count', 0)}",
        f"Aᴜᴅɪᴏs Gᴇᴛ : {u.get('audio_count', 0)}",
        f"Cᴀᴘᴛɪᴏɴs Gᴇᴛ : {u.get('caption_count', 0)}",
        f"Lɪᴍɪᴛ : {limit_text}",
        f"Uꜱᴇᴅ : {used}",
        f"Rᴇᴍᴀɪɴɪɴɢ : {remaining}",
    ]
    if assigned_premium:
        expiry = u.get("plan_expires_at")
        if expiry:
            try:
                expiry_text = to_ist(datetime.fromisoformat(expiry)).strftime("%d %b %Y, %I:%M %p") + " IST"
            except Exception:
                expiry_text = expiry
        else:
            expiry_text = "No expiry"
        lines += ["", f"💎 Pʀᴇᴍɪᴜᴍ Sᴛᴀᴛᴜꜱ : {'Active' if active else 'Expired'}", f"Eхᴘɪʀʏ : {html.escape(expiry_text)}"]

    text = "<blockquote>" + "\n".join(lines) + "</blockquote>"
    kb = None
    if BOT_DATA["settings"].get("share_enabled", True):
        share_url = await resolve_share_url(context)
        kb = InlineKeyboardMarkup([[styled_button("📤 " + to_small_caps("Share Bot"), url=share_url, style="primary")]])
    await _replace_rkb_screen(context, update.effective_chat.id, "usage", text, reply_markup=kb, parse_mode="HTML")


# ----------------------------------------------------------------------------
# Developer button
# ----------------------------------------------------------------------------

def _normalize_username_link(value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://") or value.startswith("tg://"):
        return value
    return f"https://t.me/{value.lstrip('@')}"


async def resolve_share_url(context: ContextTypes.DEFAULT_TYPE) -> str:
    """v11 — the My Usage Share button now opens Telegram's real share
    composer instead of simply opening the bot profile. The configured
    share_url remains the content being shared; when unset, the live bot
    username is resolved automatically."""
    target = BOT_DATA["settings"].get("share_url")
    try:
        if not target:
            me = await context.bot.get_me()
            target = f"https://t.me/{me.username}" if me.username else "https://t.me/"
    except Exception:
        target = "https://t.me/"
    text = BOT_DATA["settings"].get("share_text") or "Try this Instagram Reel Downloader bot."
    return "https://t.me/share/url?url=" + quote(target, safe="") + "&text=" + quote(text, safe="")


async def resolve_developer_url(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    link = BOT_DATA["settings"].get("developer_link")
    if link:
        return _normalize_username_link(link)
    dev_id = BOT_DATA["settings"].get("developer_id")
    if not dev_id:
        return None
    # tg://user?id=... only opens if the tapping user's Telegram client already
    # has that account cached (shared group, contact, etc.) — it silently does
    # nothing otherwise, which is the "click nahi khulta" bug. Resolving the
    # real @username via getChat and linking to t.me/username always works.
    try:
        chat = await context.bot.get_chat(dev_id)
        if chat.username:
            return f"https://t.me/{chat.username}"
    except Exception:
        pass
    return f"tg://user?id={dev_id}"


async def show_developer_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = await resolve_developer_url(context)
    if not url:
        await context.bot.send_message(update.effective_chat.id, to_small_caps("developer contact not set up yet."))
        return
    kb = InlineKeyboardMarkup([[styled_button("👨‍💻 " + to_small_caps("message developer"), url=url, style="primary")]])
    menu = BOT_DATA["menus"].get("developer", {})
    lang = BOT_DATA["users"].get(str(update.effective_chat.id), {}).get("lang")
    translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the bot.py default, never a translation override
    banner = (translation or {}).get("text") or menu.get("text") or DEFAULT_MENUS["developer"]["text"]
    await _replace_rkb_screen(
        context, update.effective_chat.id, "developer",
        banner, reply_markup=kb, parse_mode=menu.get("parse_mode"),
    )


# ----------------------------------------------------------------------------
# Gift flow (Telegram Stars + UPI)
# ----------------------------------------------------------------------------

async def show_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v4 — pure voluntary support/tip flow. This is separate from Premium
    Plans (those live under Usage now) — this is just 'send a gift to
    support the bot', any amount, no plan attached.
    v5 — the top-donor leaderboard now lives right inside this screen
    (not a separate top-level menu button), and only when the admin has
    turned it on in the Admin Panel.
    v6 — redesigned copy/buttons for a cleaner, more premium feel. Amount
    selection logic (Stars fixed buttons, UPI free-text entry) is left
    exactly as it already works — only the wording/labels changed here."""
    await _clear_ephemeral(context, update.effective_chat.id)
    kb_rows = [[styled_button("⭐ Support With Stars", callback_data="gift_stars", style="success")]]
    if BOT_DATA["settings"].get("upi_id"):
        kb_rows.append([styled_button("💳 Support Via UPI", callback_data="gift_upi", style="primary")])

    # v10 — banner text now comes from BOT_DATA["menus"]["gift"] so the
    # admin can edit it from Menu & UI like any other menu, instead of it
    # being hardcoded here. The Stars/UPI buttons above stay code-driven
    # since they carry real payment logic.
    # v11 — also respects the user's saved language (same lookup
    # render_menu() uses), so Send A Gift shows the translated text
    # instead of always falling back to the base/English copy.
    menu = BOT_DATA["menus"].get("gift", {})
    lang = BOT_DATA["users"].get(str(update.effective_chat.id), {}).get("lang")
    translation = menu.get("translations", {}).get(lang) if (lang and lang != "en") else None  # "en" is the bot.py default, never a translation override
    text = (translation or {}).get("text") or menu.get("text") or DEFAULT_MENUS["gift"]["text"]

    if BOT_DATA["settings"].get("leaderboard_enabled"):
        text += "\n\n" + build_leaderboard_text(limit=3)
        kb_rows.append([styled_button("🏆 Full Leaderboard", callback_data="view_leaderboard", style="primary")])
    await _replace_rkb_screen(
        context, update.effective_chat.id, "gift", text, reply_markup=InlineKeyboardMarkup(kb_rows),
        parse_mode=menu.get("parse_mode") or "HTML",
    )


async def cb_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_gift_menu(update, context)


async def cb_view_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not BOT_DATA["settings"].get("leaderboard_enabled"):
        return
    await query.message.reply_text(build_leaderboard_text())


async def cb_gift_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [
            styled_button("⭐ 50", callback_data="gift_stars_amt:50", style="success"),
            styled_button("⭐ 100", callback_data="gift_stars_amt:100", style="success"),
            styled_button("⭐ 500", callback_data="gift_stars_amt:500", style="success"),
        ],
        [
            styled_button("➕ Another Amount", callback_data="gift_stars_custom", style="primary"),
            styled_button("🗑 Dismiss", callback_data="gift_dismiss", style="danger"),
        ],
    ])
    msg = await query.message.reply_text("⭐ " + to_title_small_caps("Choose an amount:"), reply_markup=kb)
    _track_ephemeral(context, msg)


async def cb_gift_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass


async def cb_gift_stars_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "gift_stars_custom_amount"
    msg = await query.message.reply_text("✏️ " + to_small_caps("enter a numeric star amount (e.g. 150)."))
    _track_ephemeral(context, msg)


def record_donation(uid: str, name: str, amount: float, kind: str):
    """v5 — leaderboard bookkeeping. kind is 'stars' or 'inr'. Both
    currencies are combined into one 'score' for ranking purposes (1 star
    == 1 rupee of ranking weight — simple and good enough for a fun
    leaderboard; admin can adjust the weighting later if it ever matters)."""
    if amount <= 0:
        return
    entry = BOT_DATA["donations"].setdefault(uid, {"name": name, "stars": 0, "inr": 0, "score": 0})
    entry["name"] = name or entry.get("name") or f"User {uid}"
    if kind == "stars":
        entry["stars"] = entry.get("stars", 0) + amount
    else:
        entry["inr"] = entry.get("inr", 0) + amount
    entry["score"] = entry.get("stars", 0) + entry.get("inr", 0)
    save_data()


def build_leaderboard_text(limit: int = 10) -> str:
    """Ranked list of top supporters, medal-styled for the top 3, with a
    warm note at the bottom so donating actually feels good to see — not
    just a bare list of numbers."""
    donors = [d for d in BOT_DATA.get("donations", {}).values() if d.get("score", 0) > 0]
    donors.sort(key=lambda d: d.get("score", 0), reverse=True)
    donors = donors[:limit]
    if not donors:
        return (
            "🏆 " + to_small_caps("top supporters") + "\n\n"
            + to_small_caps("no donations yet — be the first to make the list!")
        )
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 " + to_small_caps("top supporters"), to_small_caps("our amazing community, ranked"), ""]
    for i, d in enumerate(donors):
        rank = medals[i] if i < 3 else f"{i + 1}."
        bits = []
        if d.get("stars"):
            bits.append(f"{int(d['stars'])}⭐")
        if d.get("inr"):
            bits.append(f"₹{int(d['inr'])}")
        lines.append(f"{rank} {d.get('name', 'Anonymous')} — {' + '.join(bits)}")
    lines.append("")
    lines.append(to_small_caps("every gift helps keep this bot alive — thank you for the love! 💛"))
    return "\n".join(lines)


def find_premium_plan(pid: str):
    for p in BOT_DATA["settings"].get("premium_plans", []):
        if p["id"] == pid:
            return p
    return None


async def cb_gift_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User tapped a specific admin-defined plan in the gift menu — show only
    the payment methods the admin actually priced for this plan."""
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":", 1)[1]
    plan = find_premium_plan(pid)
    if not plan or not plan.get("enabled"):
        await query.message.reply_text("⚠️ " + to_small_caps("this plan is no longer available."))
        return
    kb_rows = []
    if plan.get("price_stars"):
        kb_rows.append([styled_button(f"⭐ Pay {plan['price_stars']} Stars", callback_data=f"gift_plan_stars:{pid}", style="success")])
    if plan.get("price_inr") and BOT_DATA["settings"].get("upi_id"):
        kb_rows.append([styled_button(f"💳 Pay ₹{plan['price_inr']} via UPI", callback_data=f"gift_plan_upi:{pid}", style="primary")])
    if not kb_rows:
        await query.message.reply_text("⚠️ " + to_small_caps("no payment method available for this plan right now."))
        return
    await query.message.reply_text(
        f"💎 {plan['name']} — {plan.get('days', 30)} days\nChoose how to pay:",
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def cb_gift_plan_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":", 1)[1]
    plan = find_premium_plan(pid)
    if not plan or not plan.get("enabled") or not plan.get("price_stars"):
        await query.message.reply_text("⚠️ " + to_small_caps("this plan is no longer available."))
        return
    await send_stars_invoice(context, query.message.chat_id, plan["price_stars"], plan_id=pid, plan_name=plan["name"])


async def cb_gift_plan_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":", 1)[1]
    plan = find_premium_plan(pid)
    if not plan or not plan.get("enabled") or not plan.get("price_inr"):
        await query.message.reply_text("⚠️ " + to_small_caps("this plan is no longer available."))
        return
    await start_upi_order(update, context, plan["price_inr"], plan_id=pid)


async def send_stars_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, amount: int, plan_id: str = None, plan_name: str = None):
    title = to_title_small_caps(f"{plan_name} — Premium ⭐") if plan_name else to_title_small_caps("Gift The Developer ⭐")
    desc = to_title_small_caps(f"Unlock {plan_name}.") if plan_name else to_title_small_caps(f"Send {amount} Telegram Stars as a gift.")
    return await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=desc,
        payload=f"stars_gift:{amount}:{chat_id}:{int(time.time())}:{plan_id or ''}",
        provider_token="",  # not used for XTR
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} Stars", amount=amount)],
    )


async def cb_gift_stars_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    amount = int(query.data.split(":", 1)[1])
    # Free-form tip invoice (no plan attached) — tracked as ephemeral so it
    # gets swept away the moment another menu is opened.
    msg = await send_stars_invoice(context, query.message.chat_id, amount)
    _track_ephemeral(context, msg)


async def cmd_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def cmd_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    uid = str(update.effective_user.id)
    # A star payment tied to an admin-defined plan grants that plan's day
    # count; a generic/free-amount gift doesn't unlock anything.
    plan_id = None
    parts = (sp.invoice_payload or "").split(":")
    if len(parts) >= 5 and parts[4]:
        plan_id = parts[4]
    plan = find_premium_plan(plan_id) if plan_id else None
    if plan:
        days = plan.get("days", 30)
        grant_premium(uid, days)
        text = (
            "✅ " + to_small_caps("payment successful!") + "\n\n"
            f"💎 {to_small_caps('plan')}: {plan['name']}\n"
            f"⭐ {to_small_caps('paid')}: {sp.total_amount} {to_small_caps('stars')}\n"
            f"⏳ {to_small_caps('premium unlocked for')} {days} {to_small_caps('days')}"
        )
        log_line = f"⭐ Plan purchased — {sp.total_amount} stars from {update.effective_user.id} ({plan['name']}), premium granted"
    else:
        # A voluntary tip (no plan attached) is a pure thank-you — nothing
        # is unlocked, and only real gifts count toward the leaderboard.
        record_donation(uid, update.effective_user.full_name, sp.total_amount, "stars")
        text = (
            "🎉 " + to_small_caps("thank you so much for the support!") + "\n\n"
            f"💫 {to_small_caps('you sent')}: {sp.total_amount} ⭐\n\n"
            + to_small_caps("it really means a lot — thank you! ❤️")
        )
        log_line = f"⭐ Gift received — {sp.total_amount} stars from {update.effective_user.id}"
    await update.message.reply_text(text)
    await log_event(context, log_line)
    # Stars payments settle instantly with no manual admin verification, so
    # every admin also gets a direct DM regardless of logger-channel setup.
    await dm_all_admins(context, "💰 " + log_line)


async def cb_gift_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not BOT_DATA["settings"].get("upi_id"):
        await query.message.reply_text("⚠️ " + to_small_caps("upi is not configured yet."))
        return
    context.user_data["awaiting"] = "gift_upi_amount"
    await query.message.reply_text("💳 " + to_small_caps("enter amount (₹):"))


async def start_upi_order(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int, plan_id: str = None):
    upi_id = BOT_DATA["settings"].get("upi_id")
    oid = str(BOT_DATA["next_gift_id"])
    BOT_DATA["next_gift_id"] += 1
    expires_at = time.time() + 600  # 10 minutes
    order = {
        "id": oid, "user_id": update.effective_user.id, "amount": amount,
        "expires_at": expires_at, "status": "pending", "plan_id": plan_id,
    }
    BOT_DATA["gift_orders"][oid] = order
    save_data()
    upi_uri = f"upi://pay?pa={upi_id}&am={amount}&cu=INR&tn=Gift%20Order%20{oid}"
    # Locally-generated branded QR (gradient card, amount/caption baked in,
    # payer's own Telegram avatar as center logo). Falls back to the remote
    # api.qrserver.com URL if qrcode/Pillow aren't installed.
    avatar_bytes = await fetch_user_avatar_bytes(context, update.effective_user.id)
    qr_photo = generate_branded_qr(
        upi_uri, amount=amount, caption=to_small_caps("scan with any upi app"),
        logo_bytes=avatar_bytes,
    )
    if qr_photo is None:
        qr_photo = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(upi_uri)}"
    kb = InlineKeyboardMarkup([[styled_button("✅ Done", callback_data=f"gift_upi_paid:{oid}", style="success")]])
    msg = await context.bot.send_photo(
        chat_id=update.effective_chat.id, photo=qr_photo,
        caption=f"💳 ₹{amount} — {to_small_caps('scan to pay via upi')}\n⏳ expires in 10:00",
        reply_markup=kb,
    )
    context.job_queue.run_repeating(
        upi_countdown_job, interval=20, first=20,
        data={"oid": oid, "chat_id": msg.chat_id, "message_id": msg.message_id},
        name=f"upi_countdown_{oid}",
    )


async def upi_countdown_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    oid, chat_id, message_id = job.data["oid"], job.data["chat_id"], job.data["message_id"]
    order = BOT_DATA["gift_orders"].get(oid)
    if not order or order["status"] != "pending":
        job.schedule_removal()
        return
    remaining = int(order["expires_at"] - time.time())
    if remaining <= 0:
        order["status"] = "expired"
        save_data()
        # Auto-delete the QR photo from the chat on expiry (10 min), rather
        # than leaving a dead/expired QR sitting there. A small follow-up
        # notice replaces it so the user still has a way to retry.
        deleted = False
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            deleted = True
        except Exception:
            log.exception("Could not delete expired QR message %s/%s, falling back to caption edit", chat_id, message_id)
        kb = InlineKeyboardMarkup([[styled_button("🔁 Generate New QR", callback_data="gift_upi", style="primary")]])
        if deleted:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ " + to_small_caps("qr expired and was removed. generate a new one:"),
                    reply_markup=kb,
                )
            except Exception:
                pass
        else:
            try:
                await context.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption="❌ QR expired, generate new one", reply_markup=kb)
            except Exception:
                pass
        job.schedule_removal()
        return
    mm, ss = remaining // 60, remaining % 60
    try:
        await context.bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption=f"💳 ₹{order['amount']} — {to_small_caps('scan to pay via upi')}\n⏳ expires in {mm:02d}:{ss:02d}",
            reply_markup=InlineKeyboardMarkup([[styled_button("✅ Done", callback_data=f"gift_upi_paid:{oid}", style="success")]]),
        )
    except Exception:
        pass


async def cb_gift_upi_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = query.data.split(":", 1)[1]
    order = BOT_DATA["gift_orders"].get(oid)
    if not order:
        return
    if order["expires_at"] < time.time():
        await query.message.reply_text("❌ " + to_small_caps("qr expired, generate a new one via 🎁 send a gift."))
        return
    order["status"] = "claimed_pending_verify"
    save_data()
    plan = find_premium_plan(order.get("plan_id")) if order.get("plan_id") else None
    # Delete the QR photo immediately on tap rather than leaving it sitting
    # there with a "marked as paid" note stacked below it.
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.edit_message_reply_markup(None)
        except Exception:
            pass
    user_text = (
        "✅ " + to_small_caps("your payment has been sent to admin.") + "\n"
        + to_small_caps("admin will verify and notify you shortly.")
    )
    await context.bot.send_message(chat_id=query.message.chat_id, text=user_text)
    targets = BOT_DATA.get("admins", [])
    kind = f"Plan purchase ({plan['name']})" if plan else "Support gift"
    # Approve/Decline for a plan purchase, Received/Not Received for a
    # free-amount gift.
    approve_label = "✅ Approve Payment" if plan else "✅ Received"
    decline_label = "❌ Decline Payment" if plan else "❌ Not Received"
    admin_kb = InlineKeyboardMarkup([[
        styled_button(approve_label, callback_data=f"gift_upi_confirm:{oid}", style="success"),
        styled_button(decline_label, callback_data=f"gift_upi_decline:{oid}", style="danger"),
    ]])
    for target in targets:
        try:
            await context.bot.send_message(
                target,
                f"💳 UPI order #{oid} — {kind} — ₹{order['amount']} — user {order['user_id']} claims paid.",
                reply_markup=admin_kb,
            )
        except Exception:
            pass


async def cb_gift_upi_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin taps Approve (plan order) or Received (free-amount gift)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    oid = query.data.split(":", 1)[1]
    order = BOT_DATA["gift_orders"].get(oid)
    if not order or order["status"] == "paid":
        await query.answer("Already handled or not found.", show_alert=True)
        return
    order["status"] = "paid"
    save_data()
    uid = str(order["user_id"])
    donor_name = BOT_DATA["users"].get(uid, {}).get("name") or f"User {uid}"
    plan = find_premium_plan(order.get("plan_id")) if order.get("plan_id") else None
    if plan:
        days = plan.get("days", 30)
        grant_premium(uid, days)
        user_text = (
            "✅ " + to_small_caps("payment approved!") + "\n\n"
            f"💎 {to_small_caps('plan')}: {plan['name']}\n"
            f"💳 {to_small_caps('paid')}: ₹{order['amount']}\n"
            f"⏳ {to_small_caps('premium unlocked for')} {days} {to_small_caps('days')}"
        )
        log_line = f"💳 UPI order #{oid} approved by admin {update.effective_user.id} ({plan['name']}), premium granted"
        admin_ack = f"✅ Order #{oid} approved, plan unlocked for the user."
    else:
        # A free-amount payment doesn't unlock premium on its own —
        # "Received" just confirms the money arrived and says thanks.
        record_donation(uid, donor_name, order["amount"], "inr")
        user_text = (
            "🎉 " + to_small_caps("thank you so much for the support!") + "\n\n"
            f"💫 {to_small_caps('you sent')}: ₹{order['amount']}\n\n"
            + to_small_caps("it really means a lot — thank you! ❤️")
        )
        log_line = f"💳 UPI gift #{oid} marked received by admin {update.effective_user.id}"
        admin_ack = f"✅ Order #{oid} marked received."
    try:
        await context.bot.send_message(order["user_id"], user_text)
    except Exception:
        pass
    try:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(admin_ack)
    except Exception:
        pass
    await log_event(context, log_line)


async def cb_gift_upi_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Decline Payment (plan order) or Not Received (free-amount gift) —
    nothing is granted, no donation is recorded, and the user is told."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    oid = query.data.split(":", 1)[1]
    order = BOT_DATA["gift_orders"].get(oid)
    if not order or order["status"] in ("paid", "declined"):
        await query.answer("Already handled or not found.", show_alert=True)
        return
    order["status"] = "declined"
    save_data()
    plan = find_premium_plan(order.get("plan_id")) if order.get("plan_id") else None
    user_text = (
        "❌ " + to_small_caps("your payment could not be verified.") + "\n"
        + to_small_caps("if you believe this is a mistake, please contact support.")
    )
    log_line = (
        f"💳 UPI order #{oid} declined by admin {update.effective_user.id}"
        + (f" ({plan['name']})" if plan else " (gift)")
    )
    try:
        await context.bot.send_message(order["user_id"], user_text)
    except Exception:
        pass
    try:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"❌ Order #{oid} declined.")
    except Exception:
        pass
    await log_event(context, log_line)


# ----------------------------------------------------------------------------
# PDF #3 / #11 — Copyright report + Support flows (user-facing, not admin-only)
# ----------------------------------------------------------------------------

async def cb_report_copyright(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "copyright_report_link"
    await query.message.reply_text(
        "🚫 Report Copyright Issue\n\nPlease paste the link to the content you believe infringes your copyright."
    )


async def cb_support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "support_message"
    await query.message.reply_text(get_support_prompt_text(uid=update.effective_user.id), parse_mode="HTML")


async def handle_user_awaiting_input(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str):
    text = (update.message.text or "").strip()
    user_obj = update.effective_user

    if awaiting == "support_message":
        # NOTE — pop "awaiting" first thing, unconditionally, so a support
        # request can never accidentally re-trigger on a later message even
        # if something below raises.
        context.user_data.pop("awaiting", None)

        # The "please type your message below" prompt is only ever needed
        # up until this exact moment — the user just submitted it. Delete
        # it now so the chat doesn't keep showing a now-stale instruction
        # sitting above the confirmation. It's the same "rkb_latest" panel
        # message _replace_rkb_screen tracked when the prompt was shown.
        _prompt_key = f"rkb_latest:{update.effective_chat.id}"
        _prompt_msg_id = BOT_DATA.get("panel_msg", {}).pop(_prompt_key, None)
        if _prompt_msg_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=_prompt_msg_id)
            except Exception:
                pass
            save_data()

        rid = str(BOT_DATA["next_support_id"])
        BOT_DATA["next_support_id"] += 1
        created_at = datetime.utcnow().isoformat()
        req = {
            "user_id": user_obj.id,
            "user_mention": clickable_user(user_obj),
            "username_display": f"@{user_obj.username}" if user_obj.username else "No Username",
            "text": text,
            "status": "pending",
            "created_at": created_at,
            "resolved_at": None,
            "resolved_by": None,
            "confirm_chat_id": update.effective_chat.id,
            "confirm_message_id": None,
            "admin_message_ids": [],
        }
        BOT_DATA["support_requests"][rid] = req

        # Notify admins / the configured support chat with the live card.
        card_text, card_kb = _build_support_admin_card(rid)
        support_chat_id = BOT_DATA["settings"].get("support_chat_id")
        targets = [support_chat_id] if support_chat_id else BOT_DATA.get("admins", [])
        for target in targets:
            if not target:
                continue
            try:
                sent = await context.bot.send_message(
                    chat_id=target, text=card_text, parse_mode="HTML", reply_markup=card_kb
                )
                # Replying to this message still routes an admin's reply
                # straight to the user (unchanged), AND it's linked back to
                # this request for the live-status "Mark Resolved" button.
                BOT_DATA.setdefault("support_msg_map", {})[str(sent.message_id)] = str(user_obj.id)
                BOT_DATA.setdefault("support_admin_msg_map", {})[str(sent.message_id)] = rid
                req["admin_message_ids"].append(sent.message_id)
            except Exception:
                pass
        save_data()
        await log_event(context, f"🆘 Support request #{rid} from {user_obj.id}")

        # Sent instantly, fully HTML-parsed — no typewriter animation here,
        # since intermediate frames would show raw <blockquote> markup on
        # some clients mid-reveal.
        confirm_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_build_support_user_confirmation(rid),
            parse_mode="HTML",
        )
        if confirm_msg:
            req["confirm_message_id"] = confirm_msg.message_id
            req["confirm_chat_id"] = confirm_msg.chat_id
            save_data()

    elif awaiting == "ticket_new":
        context.user_data.pop("awaiting", None)
        ticket = await create_ticket(update, context)
        await update.message.reply_text(STR["ticket_created"](ticket["id"]))
        await post_ticket_card(context, ticket, user_obj)
        await forward_to_ticket(update, context, ticket["id"])
        await log_event(context, f"🎫 Ticket #{ticket['id']} opened by {user_obj.id}")

    elif awaiting == "gift_stars_custom_amount":
        context.user_data.pop("awaiting", None)
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("⚠️ " + to_small_caps("please send a valid star number."))
            return
        msg = await send_stars_invoice(context, update.effective_chat.id, int(text))
        _track_ephemeral(context, msg)

    elif awaiting == "gift_upi_amount":
        context.user_data.pop("awaiting", None)
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("⚠️ " + to_small_caps("please send a valid ₹ amount."))
            return
        await start_upi_order(update, context, int(text))

    elif awaiting == "copyright_report_link":
        context.user_data["report_link_draft"] = text
        context.user_data["awaiting"] = "copyright_report_details"
        await update.message.reply_text(
            "Thanks. Now briefly describe your ownership / proof of rights (or paste a link to proof)."
        )

    elif awaiting == "copyright_report_details":
        context.user_data.pop("awaiting", None)
        link = context.user_data.pop("report_link_draft", "")
        report = {
            "id": len(BOT_DATA["copyright_reports"]) + 1,
            "reporter_id": user_obj.id,
            "reporter_username": user_obj.username,
            "link": link,
            "details": text,
            "at": datetime.utcnow().isoformat(),
            "status": "open",
        }
        BOT_DATA["copyright_reports"].append(report)
        save_data()
        await update.message.reply_text(
            "✅ Thanks — your report has been received and will be reviewed and acted upon promptly."
        )

        domain = None
        try:
            from urllib.parse import urlparse
            domain = urlparse(link).netloc or None
        except Exception:
            domain = None

        alert_lines = [
            f"🚫 New copyright report #{report['id']}",
            f"From: {user_obj.id} (@{user_obj.username or 'no username'})",
            f"Link: {link or '(none given)'}",
            f"Details: {text[:500]}",
        ]
        kb_rows = []
        if link:
            kb_rows.append([styled_button("🚫 Block This Link", callback_data=f"adm_block_link:{report['id']}")])
        if domain:
            kb_rows.append([styled_button(f"🚫 Block Domain ({domain})", callback_data=f"adm_block_domain:{report['id']}")])
        kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None

        support_chat_id = BOT_DATA["settings"].get("support_chat_id")
        targets = [support_chat_id] if support_chat_id else BOT_DATA.get("admins", [])
        for target in targets:
            if not target:
                continue
            try:
                await context.bot.send_message(chat_id=target, text="\n".join(alert_lines), reply_markup=kb)
            except Exception:
                pass
        await log_event(context, f"🚫 Copyright report #{report['id']} filed against {link or '(no link)'}")


async def cb_adm_block_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    report_id = int(query.data.split(":", 1)[1])
    report = next((r for r in BOT_DATA["copyright_reports"] if r["id"] == report_id), None)
    if not report or not report.get("link"):
        await query.message.reply_text("⚠️ Report/link not found.")
        return
    link = report["link"]
    if link not in BOT_DATA["blocked_links"]:
        BOT_DATA["blocked_links"].append(link)
    report["status"] = "link_blocked"
    save_data()
    await query.message.reply_text(f"✅ Blocked link: {link}")
    await log_event(context, f"🚫 Admin blocked link: {link}")


async def cb_adm_block_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    report_id = int(query.data.split(":", 1)[1])
    report = next((r for r in BOT_DATA["copyright_reports"] if r["id"] == report_id), None)
    if not report or not report.get("link"):
        await query.message.reply_text("⚠️ Report/link not found.")
        return
    try:
        from urllib.parse import urlparse
        domain = urlparse(report["link"]).netloc
    except Exception:
        domain = None
    if not domain:
        await query.message.reply_text("⚠️ Couldn't parse a domain from that link.")
        return
    if domain not in BOT_DATA["blocked_domains"]:
        BOT_DATA["blocked_domains"].append(domain)
    report["status"] = "domain_blocked"
    save_data()
    await query.message.reply_text(f"✅ Blocked domain: {domain}")
    await log_event(context, f"🚫 Admin blocked domain: {domain}")


# ----------------------------------------------------------------------------
# Admin panel — top level (#9 categorized, functional dispatcher — not a
# content menu, since these are actions, not editable copy)
# ----------------------------------------------------------------------------



__all__ = [_n for _n in dir() if not _n.startswith("__")]
