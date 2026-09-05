from handlers_billing import *


def get_admin_panel_title() -> str:
    """v10 — sourced from BOT_DATA['menus']['admin'] so the admin can edit
    this banner from Menu & UI too, falling back to the original default."""
    menu = BOT_DATA["menus"].get("admin", {})
    return menu.get("text") or DEFAULT_MENUS["admin"]["text"]


def admin_panel_keyboard(user_id: int = None):
    """Buttons are filtered per-caller: the owner sees everything; an admin
    only sees the sections they've actually been granted (see
    ADMIN_PERMISSIONS / get_admin_perms). 📦 Update Backup and ☠️ Danger
    Zone are owner-only and are never shown to admins at all, no matter
    what permissions they hold. Passing user_id=None shows every button
    (kept for any legacy caller that hasn't been updated to pass it)."""
    perms = get_admin_perms(user_id) if user_id is not None else set(ADMIN_PERMISSION_KEYS)

    def allowed(perm_key):
        return user_id is None or perm_key in perms

    all_buttons = [
        ("premium", styled_button("💎 Premium", callback_data="adm_premium")),
        ("leaderboard", styled_button("🏆 Leaderboard", callback_data="adm_leaderboard")),
        ("share", styled_button("🎚 Share Settings", callback_data="adm_share")),
        ("broadcast", styled_button("📢 Broadcast", callback_data="adm_broadcast")),
        ("devsettings", styled_button("😎 Developer Settings", callback_data="adm_devsettings")),
        ("support_settings", styled_button("🛠 Support Settings", callback_data="adm_support_settings")),
        ("tickets", styled_button("📬 Tickets", callback_data="adm_tickets")),
        ("stats", styled_button("📊 Statistics", callback_data="adm_stats")),
        ("users", styled_button("👥 Users & Groups", callback_data="adm_users")),
        ("live", styled_button("🍃 Live User Feed", callback_data="adm_live")),
        ("menu_ui", styled_button("🪄 Menu & UI", callback_data="adm_menu_ui")),
        ("cmdtest", styled_button("📟 Test Commands", callback_data="adm_cmdtest")),
        ("ai_check", styled_button("🤖 AI Check", callback_data="ai_check")),
        ("notifications", styled_button("🔔 Notifications", callback_data="adm_notifications")),
        ("activity", styled_button("📜 Activity Log", callback_data="adm_activity")),
        ("selftest", styled_button("🗽 Self-Test", callback_data="adm_selftest")),
        ("plugins", styled_button("🧩 Feature Plugins", callback_data="adm_plugins")),
        ("settings", styled_button("⚙️ Settings", callback_data="adm_settings")),
    ]

    rows, row = [], []
    for perm_key, btn in all_buttons:
        if not allowed(perm_key):
            continue
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Owner-only, always — never granted to admins via permissions.
    if user_id is None or is_owner(user_id):
        rows.append([styled_button("🍭 Update Backup", callback_data="adm_update_backup"),
                     styled_button("🚧 Danger Zone", callback_data="adm_danger")])

    if not rows:
        rows = [[styled_button("ℹ️ No Sections Granted Yet", callback_data="adm_home")]]

    return InlineKeyboardMarkup(rows)


def back_row(cb="adm_back", label="🔙 Back"):
    # v10 — colorless, same as every other Admin Panel button.
    return [styled_button(label, callback_data=cb)]


def home_row():
    """#3 — extra row shown only on top-level category screens, alongside
    the regular (stack-aware) 🔙 Back row.
    v10 — colorless, same as every other Admin Panel button."""
    return [styled_button("🏠 Admin Home", callback_data="adm_home")]


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await _clear_ephemeral(context, update.effective_chat.id)
    context.user_data["adm_nav_stack"] = ["adm_home"]
    sent = await update.message.reply_text(get_admin_panel_title(), reply_markup=admin_panel_keyboard(update.effective_user.id))
    await track_and_refresh_panel(context, update.effective_chat.id, "admin", sent)
    await delete_incoming(update)


async def _render_adm_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(get_admin_panel_title(), reply_markup=admin_panel_keyboard(update.effective_user.id))


async def cb_adm_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _clear_ephemeral(context, update.effective_chat.id)
    context.user_data.pop("awaiting", None)
    context.user_data["adm_nav_stack"] = ["adm_home"]
    await _render_adm_home(update, context)


# ---- Activity log + self-test ---------------------------------------

async def _render_adm_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entries = BOT_DATA.get("error_log", [])[-10:][::-1]
    if not entries:
        body = "✅ " + to_small_caps("activity log") + "\n\n" + to_small_caps("all clear — nothing to report.")
    else:
        # Group consecutive display by kind so repeats of the same issue
        # (e.g. force-join misconfigured) don't push everything else off
        # screen, and each entry explains what happened, why, and how to
        # fix it — not just a raw exception string.
        blocks = []
        fix_rows = []
        for n, e in enumerate(entries, 1):
            kind = e.get("kind", "unhandled")
            label, why, fix = ERROR_KIND_INFO.get(kind, ERROR_KIND_INFO["unhandled"])
            when = iso_to_ist_str(e.get("time"), "%Y-%m-%d %H:%M")
            detail = e.get("detail") or e.get("error") or ""
            blocks.append(
                f"{n}. {label}  •  {when} IST\n"
                f"What: {why}\n"
                f"Fix: {fix}\n"
                f"Detail: {detail[:180]}"
            )
            if e.get("id") is not None:
                fix_rows.append([styled_button(
                    f"🛠 Fix Now #{n} — {label}", callback_data=f"adm_fix:{e['id']}"
                )])
        body = (
            "📋 " + to_small_caps("activity log") + f" — {to_small_caps('last')} {len(entries)}\n\n"
            + "\n\n".join(blocks)
        )
    kb_rows = list(fix_rows) if entries else []
    kb_rows.append([styled_button("🗑 Clear Log", callback_data="adm_clear_activity")])
    kb_rows.append(back_row())
    kb_rows.append(home_row())
    kb = InlineKeyboardMarkup(kb_rows)
    await query.edit_message_text(body, reply_markup=kb)


async def cb_adm_fix_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🛠 Fix Now — attempts a real, automatic remediation for the error
    kinds that actually have one (re-checks force-join channels live,
    forces a fresh MongoDB reconnect attempt). For kinds that have no code-
    level fix (a duplicate instance, a one-off download failure, a bug that
    needs a real code change), it explains exactly why and what a human
    needs to do instead — it never just claims success."""
    query = update.callback_query
    if not is_admin(update.effective_user.id):
        await query.answer()
        return
    try:
        err_id = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("⚠️ " + to_small_caps("bad fix reference."), show_alert=True)
        return
    entry = next((e for e in BOT_DATA.get("error_log", []) if e.get("id") == err_id), None)
    if entry is None:
        await query.answer("⚠️ " + to_small_caps("that log entry is gone — log was cleared."), show_alert=True)
        return
    kind = entry.get("kind", "unhandled")
    await query.answer("🛠 " + to_small_caps("running fix..."))

    if kind == "force_join":
        targets = _force_join_targets()
        if not targets:
            result = "ℹ️ " + to_small_caps("no force-join channel is configured — nothing to check.")
        else:
            lines = ["🔎 " + to_small_caps("re-checking force-join channel(s) now:")]
            for t in targets:
                chat_id = t.get("chat_id")
                if not chat_id:
                    lines.append(f"• {t.get('link')} — " + to_small_caps("link-only target, can't be auto-verified."))
                    continue
                try:
                    me = await context.bot.get_me()
                    member = await context.bot.get_chat_member(chat_id=chat_id, user_id=me.id)
                    if member.status in ("administrator", "creator"):
                        lines.append(f"• {chat_id} — ✅ " + to_small_caps("bot is admin here, looks correctly configured."))
                    else:
                        lines.append(f"• {chat_id} — ⚠️ " + to_small_caps(f"bot can see this chat but is only '{member.status}' — make it admin."))
                except Exception as e:
                    lines.append(f"• {chat_id} — ❌ " + to_small_caps(f"still failing: {e}"))
            result = "\n".join(lines)

    elif kind == "mongo":
        col = get_mongo_collection(force=True)  # force a fresh connection attempt
        if col is not None:
            result = "✅ " + to_small_caps("reconnected to mongodb successfully.")
        else:
            result = "❌ " + to_small_caps(f"still can't connect — {_mongo_last_error or 'unknown error'}")

    elif kind == "conflict":
        result = (
            "ℹ️ " + to_small_caps("this can't be fixed from inside this process.") + "\n"
            + to_small_caps("make sure no other copy of this bot (old deploy, second terminal, another server) is running with the same bot token, then stop it.")
        )

    else:
        result = "ℹ️ " + to_small_caps(f"'{kind}' has no automatic fix — see the fix hint above for the manual step.")

    try:
        await query.message.reply_text(result)
    except Exception:
        pass


async def cb_adm_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _render_adm_activity(update, context)


async def cb_adm_clear_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    BOT_DATA["error_log"] = []
    save_data()
    await _render_adm_activity(update, context)


async def _render_adm_selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("🧪 " + to_small_caps("running self-test..."))
    results = []
    results.append(("Bot token", "✅ OK" if BOT_TOKEN else "❌ missing"))
    try:
        me = await context.bot.get_me()
        results.append(("Telegram API", f"✅ OK (@{me.username})"))
    except Exception as e:
        results.append(("Telegram API", f"❌ {e}"))
    results.append(("ffmpeg", "✅ found" if FFMPEG_AVAILABLE else "⚠️ not found (merge downloads may fail)"))
    results.append(("ffprobe", "✅ found" if FFPROBE_AVAILABLE else "ℹ️ not found (not needed — audio uses direct ffmpeg)"))
    try:
        import yt_dlp as _yd
        results.append(("yt-dlp", f"✅ v{_yd.version.__version__}"))
    except Exception as e:
        results.append(("yt-dlp", f"❌ {e}"))
    results.append(("Download dir", "✅ writable" if os.access(DOWNLOAD_DIR, os.W_OK) else "❌ not writable"))
    body = "🧪 " + to_small_caps("self-test results") + "\n\n" + "\n".join(f"{k}: {v}" for k, v in results)
    await query.edit_message_text(body, reply_markup=InlineKeyboardMarkup([back_row(), home_row()]))


async def cb_adm_selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _render_adm_selftest(update, context)


# ---- 🧪 Test Commands — run/check every bot command straight from the panel --
# One small screen, one button per command the bot supports. Tapping a
# button runs that command's real, safe logic and drops the actual result
# right into this chat — no need to leave the admin panel or type anything
# to verify a command still works. Commands that need an argument (like
# /block <id>) show their usage instead of guessing one; owner-only
# commands only actually run for the owner.
COMMAND_TEST_LIST = [
    ("start", "🚀 /start"),
    ("help", "❓ /help"),
    ("language", "🌐 /language"),
    ("admin", "🛠 /admin"),
    ("ping", "🏓 /ping"),
    ("health", "🩺 /health"),
    ("dbstatus", "🗄 /dbstatus"),
    ("database", "💾 /database"),
    ("exportusers", "📤 /exportusers"),
    ("exportpdf", "📊 /exportpdf"),
    ("export", "📦 /export"),
    ("block", "🚫 /block"),
    ("unblock", "✅ /unblock"),
    ("cancel", "🧹 /cancel"),
]


def _cmdtest_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, label in COMMAND_TEST_LIST:
        row.append(styled_button(label, callback_data=f"run_cmd:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(back_row())
    rows.append(home_row())
    return InlineKeyboardMarkup(rows)


async def _render_adm_cmdtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    body = (
        "🧪 " + to_small_caps("test commands") + "\n\n"
        + to_small_caps("tap any command below to run/check it right now — the real result is sent here, exactly like typing it.") + "\n\n"
        + to_small_caps("owner-only commands only actually run for the owner; /block and /unblock need an argument, so they just show their usage.")
    )
    await query.edit_message_text(body, reply_markup=_cmdtest_kb())


async def cb_adm_cmdtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _render_adm_cmdtest(update, context)


async def cb_run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await query.answer()
        return
    key = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    # Auto-clean the Test Commands screen: delete whatever result the last
    # tap here left behind before running a new one, so repeatedly tapping
    # through commands doesn't fill the chat with old test output.
    for old_mid in context.user_data.get("last_test_msg_ids", []):
        try:
            await context.bot.delete_message(chat_id, old_mid)
        except Exception:
            pass
    context.user_data["last_test_msg_ids"] = []

    async def send(text, **kwargs):
        sent = await context.bot.send_message(chat_id, text, **kwargs)
        context.user_data.setdefault("last_test_msg_ids", []).append(sent.message_id)
        return sent

    async def track(sent_msg):
        """For calls that send via context.bot directly (documents, etc.)
        instead of the send() helper above — still gets cleaned up next run."""
        if sent_msg is not None:
            context.user_data.setdefault("last_test_msg_ids", []).append(sent_msg.message_id)
        return sent_msg

    try:
        if key == "start":
            await query.answer("✅ " + to_small_caps("running /start..."))
            await track(await render_menu(context, chat_id, "start"))

        elif key == "help":
            await query.answer("✅ " + to_small_caps("running /help..."))
            await track(await render_menu(context, chat_id, "help_admin" if is_admin(admin_id) else "help_user"))

        elif key == "language":
            await query.answer("✅ " + to_small_caps("running /language..."))
            cur_lang = BOT_DATA["users"].get(str(admin_id), {}).get("lang") or "en"
            await send("🌐 " + to_small_caps("choose a language:"), reply_markup=build_language_keyboard(cur_lang))

        elif key == "admin":
            await query.answer("✅ " + to_small_caps("running /admin..."))
            await send(get_admin_panel_title(), reply_markup=admin_panel_keyboard(admin_id))

        elif key == "ping":
            # Same live status data/format as the real /ping command.
            await query.answer()
            t0 = time.monotonic()
            msg = await context.bot.send_message(chat_id, "🏓 " + to_title_small_caps("Pong!"))
            await track(msg)
            ms = int((time.monotonic() - t0) * 1000)
            backend = "MongoDB" if get_mongo_collection() is not None else "Local JSON File"
            lines = [
                f"↬ {to_title_small_caps('Uptime')} : {human_uptime_full()}",
                f"↬ {to_title_small_caps('Storage')} : {to_title_small_caps(backend)}",
                f"↬ {to_title_small_caps('Server Time')} : {now_ist_str('%d %b %Y, %H:%M:%S')} IST",
            ]
            await msg.edit_text(
                f"🏓 <b>{to_title_small_caps('Pong!')}</b> {ms}ms\n\n<blockquote>{html.escape(chr(10).join(lines))}</blockquote>",
                parse_mode="HTML",
            )

        elif key == "health":
            await query.answer()
            await send(build_health_text())

        elif key == "dbstatus":
            if not is_owner(admin_id):
                await query.answer("🔒 " + to_small_caps("owner only."), show_alert=True)
            else:
                await query.answer()
                col = get_mongo_collection()
                if col is not None:
                    text = "✅ MongoDB: connected"
                elif MONGO_URI:
                    text = f"❌ MongoDB: not connected\nReason: {_mongo_last_error}"
                else:
                    text = "ℹ️ MongoDB not configured — using local JSON file."
                text += f"\n\nUsers: {len(BOT_DATA['users'])} | Groups: {len(BOT_DATA['groups'])} | Admins: {len(BOT_DATA['admins'])}"
                await send(text)

        elif key == "database":
            if not is_owner(admin_id):
                await query.answer("🔒 " + to_small_caps("owner only."), show_alert=True)
            else:
                await query.answer("✅ " + to_small_caps("building backup..."))
                raw = json.dumps(BOT_DATA, ensure_ascii=False, indent=2).encode("utf-8")
                payload, encrypted = encrypt_backup_bytes(raw)
                filename = "bot_data_backup.json.enc" if encrypted else "bot_data_backup.json"
                path = os.path.join(tempfile.gettempdir(), f"bot_data_export_{int(time.time())}_{filename}")
                with open(path, "wb") as f:
                    f.write(payload)
                with open(path, "rb") as f:
                    doc = await context.bot.send_document(chat_id, document=f, filename=filename)
                await track(doc)
                os.remove(path)

        elif key == "exportusers":
            if not is_owner(admin_id):
                await query.answer("🔒 " + to_small_caps("owner only."), show_alert=True)
            else:
                await query.answer("✅ " + to_small_caps("building csv..."))
                path = os.path.join(tempfile.gettempdir(), f"users_export_{int(time.time())}.csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["user_id", "name", "username", "joined", "last_active"])
                    for uid, info in BOT_DATA["users"].items():
                        writer.writerow([uid, info.get("name"), info.get("username"), info.get("joined"), info.get("last_active")])
                with open(path, "rb") as f:
                    doc = await context.bot.send_document(chat_id, document=f, filename="users_export.csv")
                await track(doc)
                os.remove(path)

        elif key == "exportpdf":
            if not is_owner(admin_id):
                await query.answer("🔒 " + to_small_caps("owner only."), show_alert=True)
            elif not PDF_REPORT_AVAILABLE:
                await query.answer()
                await send(to_small_caps("❌ pdf report needs matplotlib + reportlab — run `pip install matplotlib reportlab`."))
            else:
                await query.answer("✅ " + to_small_caps("building pdf report..."))
                pdf_path = await asyncio.to_thread(build_pdf_report)
                with open(pdf_path, "rb") as f:
                    doc = await context.bot.send_document(chat_id, document=f, filename="bot_report.pdf")
                await track(doc)
                os.remove(pdf_path)

        elif key == "export":
            if not is_owner(admin_id):
                await query.answer("🔒 " + to_small_caps("owner only."), show_alert=True)
            else:
                await query.answer()
                src_dir = os.path.dirname(os.path.abspath(__file__))
                zip_path = None
                try:
                    zip_path = _build_export_zip(src_dir)
                    size = os.path.getsize(zip_path)
                    if size > EXPORT_MAX_BYTES:
                        await send(
                            "⚠️ " + to_small_caps(
                                f"export would be {size / 1024 / 1024:.1f}mb — too large for telegram's ~50mb limit."
                            )
                        )
                    else:
                        await send(
                            "✅ " + to_small_caps(
                                f"export check passed — source zip builds fine at {size / 1024:.0f}kb."
                            ) + "\n" + to_small_caps("run the real /export command to actually receive the file.")
                        )
                finally:
                    if zip_path and os.path.exists(zip_path):
                        os.remove(zip_path)

        elif key == "block":
            await query.answer()
            await send(
                "ℹ️ " + to_small_caps("/block needs an argument, so it can't be run blindly from here.")
                + "\nUsage: /block <user_id | link | domain>"
            )

        elif key == "unblock":
            await query.answer()
            await send(
                "ℹ️ " + to_small_caps("/unblock needs an argument, so it can't be run blindly from here.")
                + "\nUsage: /unblock <user_id | link | domain>"
            )

        elif key == "cancel":
            await query.answer("✅ " + to_small_caps("running /cancel..."))
            for k in (
                "awaiting", "btn_flow", "style_source_text", "style_target",
                "message_target", "report_link_draft", "owner_contact_label_draft",
                "autoreply_key_draft",
            ):
                context.user_data.pop(k, None)
            await send("✅ " + to_small_caps("cancelled — any pending flow (for you) has been cleared."))

        else:
            await query.answer(to_small_caps("unknown command."), show_alert=True)
    except Exception as e:
        log.exception("cb_run_cmd failed for %s", key)
        try:
            await send("❌ " + to_small_caps(f"'{key}' check failed: {e}"))
        except Exception:
            pass


# ---- Live User Feed (anti-misuse monitoring) ---------------------------------

async def _render_adm_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    col = get_mongo_collection()
    backend = "MongoDB ✅ (synced)" if col is not None else "Local (in-memory/JSON, no Mongo connected)"
    entries = BOT_DATA.get("activity_log", [])[-15:][::-1]
    lines = [f"🕵️ Live User Feed\n🗄 Backend: {backend}\n👥 Total tracked users: {len(BOT_DATA['users'])}\n"]
    if not entries:
        lines.append(to_small_caps("no activity has been recorded yet."))
    else:
        for e in entries:
            uname = f"@{e['username']}" if e.get("username") else "(no username)"
            when = iso_to_ist_str(e.get("time"), "%H:%M:%S")
            lines.append(f"• {when} IST — {e.get('name')} {uname} [{e.get('user_id')}]\n  ↳ {e.get('url')}")
    body = "\n".join(lines)
    s = BOT_DATA["settings"]
    route = s.get("notify_route", "all")
    route_labels = {"logger": "📋 Logger", "activity": "📢 Activity", "dm": "📩 Admin Dm", "all": "🌐 All"}
    kb = InlineKeyboardMarkup(
        [
            [styled_button("🚫 Ban / Unban User (by ID)", callback_data="adm_quickban")],
            [styled_button(
                f"📡 Notify Route: {route_labels.get(route, 'All')}",
                callback_data="adm_notify_route_cycle",
            )],
            [styled_button(
                toggle_label("📡 Feed To Admin DM", s.get('user_activity_dm', True)),
                callback_data="stgl:user_activity_dm:adm_live",
            )],
            [styled_button(
                toggle_label("🆕 Detailed Join Alerts", s.get('detailed_join_alerts', True)),
                callback_data="stgl:detailed_join_alerts:adm_live",
            )],
            back_row("adm_home"),
        ]
    )
    await query.edit_message_text(body, reply_markup=kb)


async def cb_adm_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _render_adm_live(update, context)


async def cb_adm_notify_route_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cycles the Reel-Delivered notification destination: Logger ->
    Activity -> Admin DM -> All -> Logger ... one tap, no sub-menu needed."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    order = ["all", "logger", "activity", "dm"]
    current = BOT_DATA["settings"].get("notify_route", "all")
    nxt = order[(order.index(current) + 1) % len(order)] if current in order else "all"
    BOT_DATA["settings"]["notify_route"] = nxt
    save_data()
    await _render_adm_live(update, context)


async def cb_adm_quickban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban/Unban a user by ID, entered from the admin panel — this is the
    only place a ban actually happens; the Live Feed is view-only."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["awaiting"] = "adm_ban_unban_userid"
    await query.message.reply_text(
        to_small_caps("🚫 send the user's numeric id — if already banned they will be unbanned, otherwise they will be banned.")
    )


# ---- #3 — generic back-stack navigation --------------------------------------
# Screens registered here can be reached via the stack-aware "adm_back"
# button regardless of how deep the user has drilled in. Leaf actions (add /
# remove / toggle / confirm) intentionally aren't part of this table — they
# fall back to a hardcoded parent, same as before.
SCREEN_RENDERERS = {}  # populated just above build_app, once every screen fn exists


def nav_tracked(screen_key):
    """Wraps a screen's callback handler so entering it gets pushed onto the
    per-admin nav stack, so 'Back' can unwind through however many screens
    were visited, not just to a single hardcoded parent.

    Also doubles as the enforcement point for granular admin permissions:
    if screen_key maps to a key in ADMIN_PERMISSIONS, the caller must have
    that permission (owner always does). Nested/utility screens that
    aren't in the catalog (e.g. a broadcast sub-step) are left ungated
    here since reaching them already required passing the gated top-level
    screen first."""
    def deco(fn):
        async def wrapped(update, context):
            perm_key = _perm_key_for_screen(screen_key)
            if perm_key in ADMIN_PERMISSION_KEYS and not has_admin_perm(update.effective_user.id, perm_key):
                await update.callback_query.answer(
                    "🔒 " + to_small_caps("you don't have access to this section."), show_alert=True,
                )
                return
            stack = context.user_data.setdefault("adm_nav_stack", ["adm_home"])
            if not stack or stack[-1] != screen_key:
                stack.append(screen_key)
                if len(stack) > 15:
                    del stack[0]
            return await fn(update, context)
        return wrapped
    return deco


async def cb_adm_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Sweep away any leftover "send a value..." prompt / "✅ saved" confirmation
    # messages from whatever setup flow the admin is leaving — those should
    # not keep sitting in the chat once the admin navigates away.
    await _clear_ephemeral(context, update.effective_chat.id)
    context.user_data.pop("awaiting", None)
    stack = context.user_data.setdefault("adm_nav_stack", ["adm_home"])
    if len(stack) > 1:
        stack.pop()  # drop the screen we're currently on
    target = stack[-1] if stack else "adm_home"
    renderer = SCREEN_RENDERERS.get(target)
    if renderer is None:
        stack[:] = ["adm_home"]
        renderer = SCREEN_RENDERERS["adm_home"]
    await renderer(update, context)


# ---- Stats & Activity -------------------------------------------------------

async def _render_adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mem = get_memory_usage_mb()
    backend = "MongoDB" if get_mongo_collection() is not None else "Local JSON File"
    uptime = human_uptime()
    text = (
        "📊 " + to_title_small_caps("Stats & Activity") + "\n\n"
        + f"{to_title_small_caps('Users')} : {len(BOT_DATA['users'])}\n"
        + f"{to_title_small_caps('Groups')} : {len(BOT_DATA['groups'])}\n"
        + f"{to_title_small_caps('Blocked')} : {len(BOT_DATA.get('blocked_users', []))}\n"
        + f"{to_title_small_caps('Broadcasts Sent')} : {BOT_DATA['metrics'].get('broadcasts_sent', 0)}\n"
        + f"{to_title_small_caps('Reels Downloaded')} : {BOT_DATA['metrics'].get('reels_downloaded', 0)}\n"
        + f"{to_title_small_caps('/Start Count')} : {BOT_DATA['metrics'].get('start_count', 0)}\n"
        + f"{to_title_small_caps('Copyright Reports')} : {len(BOT_DATA['copyright_reports'])}\n\n"
        + f"{to_title_small_caps('Uptime')} : {uptime}\n"
        + f"{to_title_small_caps('Memory')} : {mem if mem is not None else 'N/A'} MB\n"
        + f"{to_title_small_caps('Storage')} : {to_title_small_caps(backend)}"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([back_row(), home_row()]))


async def cb_adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_stats(update, context)


# ---- 🔔 Notification Center ---------------------------------------------------
# A single live "what's going on" dashboard so the admin doesn't have to open
# Tickets, Activity Log, Users & Groups, and Settings separately just to see
# whether anything needs attention right now.

async def _render_adm_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)

    def _parse(ts):
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    # New users / groups in the last 24h.
    new_users_24h = sum(
        1 for u in BOT_DATA["users"].values()
        if (dt := _parse(u.get("joined"))) and dt >= day_ago
    )
    new_groups_24h = sum(
        1 for g in BOT_DATA["groups"].values()
        if (dt := _parse(g.get("added_at"))) and dt >= day_ago
    )
    reel_activity_24h = sum(
        1 for e in BOT_DATA.get("activity_log", [])
        if (dt := _parse(e.get("time"))) and dt >= day_ago
    )

    # Tickets / support requests still waiting on a reply.
    open_tickets = sum(1 for t in BOT_DATA.get("tickets", {}).values() if t.get("status") == "open")
    pending_support = sum(
        1 for r in BOT_DATA.get("support_requests", {}).values() if r.get("status") != "resolved"
    )

    # Errors logged in the last 24h, most recent first.
    recent_errors = [
        e for e in BOT_DATA.get("error_log", [])
        if (dt := _parse(e.get("time"))) and dt >= day_ago
    ]
    recent_errors.sort(key=lambda e: e.get("time") or "", reverse=True)
    last_error = recent_errors[0] if recent_errors else None

    maintenance_on = bool(BOT_DATA["settings"].get("maintenance"))
    blocked_count = len(BOT_DATA.get("blocked", []))

    lines = ["🔔 " + to_title_small_caps("Notification Center"), ""]

    # Needs-attention section first, so the admin sees anything urgent
    # without scrolling.
    alerts = []
    if maintenance_on:
        alerts.append("🔒 " + to_small_caps("maintenance mode is currently ON — users can't use the bot."))
    if open_tickets:
        alerts.append(f"🎫 {open_tickets} " + to_small_caps("open ticket(s) waiting for a reply."))
    if pending_support:
        alerts.append(f"🆘 {pending_support} " + to_small_caps("support request(s) still pending."))
    if recent_errors:
        alerts.append(f"⚠️ {len(recent_errors)} " + to_small_caps("error(s) logged in the last 24h."))
    if not alerts:
        alerts.append("✅ " + to_small_caps("all clear — nothing needs attention right now."))
    lines.extend(alerts)
    lines.append("")

    # Live activity snapshot.
    lines.append("📈 " + to_small_caps("last 24 hours"))
    lines.append(f"👤 " + to_small_caps("new users: ") + str(new_users_24h))
    lines.append(f"👨‍👩‍👧 " + to_small_caps("new groups: ") + str(new_groups_24h))
    lines.append(f"🎬 " + to_small_caps("reel activity: ") + str(reel_activity_24h))
    lines.append("")

    if last_error:
        kind = last_error.get("kind", "unhandled")
        label, _why, _fix = ERROR_KIND_INFO.get(kind, ERROR_KIND_INFO["unhandled"])
        when = iso_to_ist_str(last_error.get("time"), "%Y-%m-%d %H:%M")
        lines.append("🐞 " + to_small_caps("most recent error"))
        lines.append(f"{label} — {when} IST")
        lines.append("")

    lines.append("📊 " + to_small_caps("current totals"))
    lines.append(f"👥 " + to_small_caps("users: ") + str(len(BOT_DATA["users"])))
    lines.append(f"🚫 " + to_small_caps("blocked: ") + str(blocked_count))
    lines.append(f"🎬 " + to_small_caps("reels delivered: ") + str(BOT_DATA["metrics"].get("reels_downloaded", 0)))
    lines.append(f"⏱ " + to_small_caps("uptime: ") + human_uptime())

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(
        [
            [styled_button("🎫 Tickets", callback_data="adm_tickets"),
             styled_button("📜 Activity Log", callback_data="adm_activity")],
            [styled_button("🔄 Refresh", callback_data="adm_notifications")],
            back_row(),
            home_row(),
        ]
    )
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_notifications(update, context)


# ---- Users & Groups ----------------------------------------------------------

async def _render_adm_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kb = InlineKeyboardMarkup(
        [
            [styled_button("📋 List Users (last 20)", callback_data="adm_users_list")],
            [styled_button("👨‍👩‍👧 List Groups", callback_data="adm_groups_list")],
            [styled_button("🔍 Check User", callback_data="adm_check_user")],
            [styled_button("✉️ Message a User", callback_data="adm_users_msg")],
            back_row(),
            home_row(),
        ]
    )
    await query.edit_message_text("👥 Users & Groups", reply_markup=kb)


async def cb_adm_groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    groups = list(BOT_DATA["groups"].items())
    if not groups:
        text = to_small_caps("the bot is not in any group yet.")
    else:
        lines = [f"👨‍👩‍👧 Groups ({len(groups)})\n"]
        for gid, info in groups:
            lines.append(f"• {info.get('title', '(no title)')} — {gid}")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[styled_button("🔙 Back", callback_data="adm_users")]])
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_users(update, context)


async def cb_adm_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = list(BOT_DATA["users"].items())[-20:]
    if not users:
        text = to_small_caps("no user records found yet.")
    else:
        lines = ["📋 Last 20 Users\n"]
        for uid, info in users:
            uname = f"@{info.get('username')}" if info.get("username") else "(no username)"
            lines.append(f"• {uid} — {info.get('name')} {uname}")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[styled_button("🔙 Back", callback_data="adm_users")]])
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_users_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "message_user_id"
    await query.message.reply_text(to_small_caps("send the id of the user you want to message."))


async def cb_adm_check_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "check_user_id"
    await query.message.reply_text(to_small_caps("send the user id you want to check."))


async def build_user_details_card(context: ContextTypes.DEFAULT_TYPE, target_id: int) -> str:
    """Full live detail card for one user, shown to an admin from
    '🔍 Check User' — same sectioned house style as the New User Started
    alert / Stats screen, but pulled fresh from stored data + a live
    getChat call, and with a clickable Name."""
    lbl = to_title_small_caps
    uid = str(target_id)
    u = BOT_DATA["users"].get(uid, {})

    # Prefer a live getChat so name/username/premium reflect the user's
    # CURRENT profile, not whatever was cached at their last /start. Falls
    # back to stored data if the chat can't be fetched (user blocked the
    # bot, invalid id, never started it, etc.).
    chat_obj = None
    try:
        chat_obj = await context.bot.get_chat(target_id)
    except Exception:
        pass

    if chat_obj is not None:
        name = chat_obj.full_name if hasattr(chat_obj, "full_name") else (
            " ".join(filter(None, [getattr(chat_obj, "first_name", None), getattr(chat_obj, "last_name", None)]))
        )
        name = name or u.get("name") or str(target_id)
        username = getattr(chat_obj, "username", None) or u.get("username")
        is_premium = getattr(chat_obj, "is_premium", None)
        name_link = f'<a href="https://t.me/{username}">{html.escape(name)}</a>' if username else f'<a href="tg://user?id={target_id}">{html.escape(name)}</a>'
    else:
        name = u.get("name") or str(target_id)
        username = u.get("username")
        is_premium = None
        name_link = f'<a href="tg://user?id={target_id}">{html.escape(name)}</a>'

    if not u and chat_obj is None:
        return None  # unknown to the bot AND not resolvable live — caller shows "not found"

    username_display = f"@{username}" if username else "Not Set"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    used_today = u.get("downloads_today", 0) if u.get("downloads_today_date") == today else 0
    plan = u.get("plan", "Free")
    active_premium = is_premium_active(uid)
    joined = u.get("joined_at") or u.get("started_at")
    joined_display = iso_to_ist_str(joined, "%d %B %Y • %H:%M:%S") + " IST" if joined else "Unknown"
    banned = target_id in BOT_DATA.get("blocked", [])

    lines = [
        "🔍 " + lbl("User Details"),
        "",
        _CARD_SEP,
        "",
        "👤 " + lbl("User Information"),
        "",
        f"{lbl('Name')} : {name_link}",
        f"{lbl('Username')} : {html.escape(username_display)}",
        f"{lbl('User Id')} : {target_id}",
        "",
        "📊 " + lbl("Activity"),
        "",
        f"{lbl('Reels Downloaded')} : {u.get('reels_count', 0)}",
        f"{lbl('Audios Get')} : {u.get('audio_count', 0)}",
        f"{lbl('Captions Get')} : {u.get('caption_count', 0)}",
        f"{lbl('Used Today')} : {used_today}",
        "",
        "💎 " + lbl("Premium"),
        "",
        f"{lbl('Plan')} : {lbl(plan)}",
        f"{lbl('Status')} : {lbl('Active') if active_premium else lbl('Not Active')}",
        "",
        "⚙️ " + lbl("Account"),
        "",
        f"{lbl('Joined At')} : {joined_display}",
        f"{lbl('Banned')} : {lbl('Yes') if banned else lbl('No')}",
    ]
    if is_premium is not None:
        lines.append(f"{lbl('Telegram Premium')} : {lbl('Yes') if is_premium else lbl('No')}")
    lines += ["", _CARD_SEP]

    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


# ---- Broadcast (reliable delivery, admin copy, /broadcast command, and month-wise delete) ----
#
# What changed and why:
#  1. do_broadcast() used to fire every send back-to-back with zero pacing.
#     Telegram enforces a hard ~30 messages/second global rate limit; blast
#     past it and the API replies with 429 "Too Many Requests" (RetryAfter),
#     which the old code caught with a bare `except Exception` and simply
#     logged as a permanent failure. That's the "bar bar failed ho jata hai"
#     — most of those "failures" were really just flood-control hits that a
#     short pause and one retry would have delivered fine. Fixed by pacing
#     every send and giving a RetryAfter exactly one honoured retry.
#  2. Failures are now categorized (blocked the bot, invalid/deleted chat,
#     rate-limited-then-recovered, other) instead of one flat "failed"
#     number, so the admin can actually see *why* delivery didn't land.
#  3. Every successfully delivered message ID is now recorded per user
#     against the broadcast, so a broadcast can be pulled back out of every
#     recipient's chat later (see Delete Broadcast below).
BROADCAST_SEND_DELAY = 0.05  # ~20 msg/sec — safely under Telegram's cap


def _broadcast_report_text(entry: dict) -> str:
    """Build the normal broadcast completion report."""
    total = entry.get("total_targeted", 0)
    sent = entry.get("recipients", 0)
    blocked = entry.get("blocked", 0)
    invalid_chat = entry.get("invalid_chat", 0)
    other_failed = entry.get("other_failed", 0)
    recovered = entry.get("recovered", 0)
    failed_total = blocked + invalid_chat + other_failed
    return (
        "✅ " + to_small_caps("broadcast complete") + "\n\n"
        + to_small_caps("total targeted") + f": {total}\n"
        + to_small_caps("delivered successfully") + f": {sent}\n"
        + to_small_caps("not delivered") + f": {failed_total}\n\n"
        + to_small_caps("breakdown — why some were not delivered") + "\n"
        + "🚫 " + to_small_caps("blocked the bot / account deactivated") + f": {blocked}\n"
        + "⚠️ " + to_small_caps("chat unavailable / never started the bot") + f": {invalid_chat}\n"
        + "❓ " + to_small_caps("other delivery error") + f": {other_failed}\n"
        + ("🔁 " + to_small_caps("recovered after a brief rate-limit pause") + f": {recovered}\n" if recovered else "")
        + "\n🔐 " + to_small_caps("forward-lock") + f": {'✅ ON' if entry.get('protect') else '❌ OFF'}"
    )


async def cb_adm_start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation before sending the bot's normal /start experience to everyone."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    kb = InlineKeyboardMarkup([
        [styled_button("✅ Confirm /start Broadcast", callback_data="adm_start_broadcast_confirm")],
        [styled_button("❌ Cancel", callback_data="adm_broadcast")]
    ])
    await query.edit_message_text(
        "⚠️ " + to_small_caps("confirm /start broadcast") + "\n\n"
        + to_small_caps("this will send the bot's normal /start welcome message to every registered user, plus this admin chat.") + "\n"
        + to_small_caps("no custom broadcast content will be used."),
        reply_markup=kb,
    )


async def cb_adm_start_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the normal /start experience as a simple alive/working notification."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    status = await query.message.reply_text("🚀 " + to_small_caps("/start broadcast in progress..."))
    targets = set(BOT_DATA["users"].keys())
    targets.add(str(update.effective_user.id))
    sent = 0
    failed = 0

    for uid in targets:
        try:
            # Render the exact same start destination/menu users get from /start,
            # without pretending Telegram received a command from the bot.
            await context.bot.send_message(chat_id=int(uid), text="/start")
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                await context.bot.send_message(chat_id=int(uid), text="/start")
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_SEND_DELAY)

    try:
        await status.edit_text(
            "✅ " + to_small_caps("/start broadcast complete") + "\n\n"
            + to_small_caps("delivered") + f": {sent}\n"
            + to_small_caps("failed") + f": {failed}"
        )
    except Exception:
        pass
    await log_event(context, f"🚀 /start broadcast by {update.effective_user.id} — {sent} delivered, {failed} failed")


async def _render_adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    s = BOT_DATA["settings"]
    protect = s.get("protect_broadcasts", True)
    kb = InlineKeyboardMarkup(
        [
            [styled_button("📢 New Broadcast", callback_data="adm_bc_new"),
             styled_button("📜 Broadcast Log", callback_data="adm_bc_log")],
            [styled_button(
                toggle_label("🔐 Forward-Lock", protect),
                callback_data="stgl:protect_broadcasts:adm_broadcast",
            ),
             styled_button("🚀 /start Broadcast", callback_data="adm_start_broadcast")],
            [styled_button("🗑 Delete Broadcast", callback_data="adm_bc_delmenu")],
            back_row(),
            home_row(),
        ]
    )
    total_users = len(BOT_DATA["users"])
    body = (
        to_small_caps("📢 broadcast centre") + "\n"
        + to_small_caps("send an announcement to every registered user") + "\n\n"
        + to_small_caps("total reachable users") + f": {total_users}\n\n"
        + to_small_caps("/start broadcast sends the normal bot welcome message as an alive/working notification")
    )
    await query.edit_message_text(body, reply_markup=kb)


async def cb_adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_broadcast(update, context)


async def cb_adm_bc_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "broadcast_content"
    await query.message.reply_text(
        to_small_caps("📢 send your broadcast now") + "\n"
        + to_small_caps("text, photo or video — one single message") + "\n\n"
        + to_small_caps("it will be delivered to every registered user and this admin chat, respecting your forward-lock setting")
    )


async def cb_adm_bc_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    entries = BOT_DATA["broadcast_log"][-10:][::-1]
    if not entries:
        text = to_small_caps("📜 broadcast log") + "\n\n" + to_small_caps("no broadcasts have been sent yet.")
    else:
        lines = [to_small_caps("📜 last 10 broadcasts") + "\n"]
        for e in entries:
            when = iso_to_ist_str(e.get("at"), "%Y-%m-%d %H:%M") + " IST"
            line = (
                f"• {when} — "
                + to_small_caps("delivered") + f" {e.get('recipients', 0)} • "
                + to_small_caps("blocked") + f" {e.get('blocked', 0)} • "
                + to_small_caps("failed") + f" {e.get('other_failed', 0)}"
            )
            lines.append(line)
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup([back_row("adm_broadcast")])
    await query.edit_message_text(text, reply_markup=kb)


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # #4 — the master "lock everything" switch ORs together with the
    # broadcast-specific forward-lock toggle.
    s = BOT_DATA["settings"]
    protect = s.get("protect_broadcasts", True) or s.get("lock_all_content", False)
    broadcast_id = BOT_DATA.get("broadcast_next_id", 1)
    BOT_DATA["broadcast_next_id"] = broadcast_id + 1

    status_msg = await update.message.reply_text(
        "📢 " + to_small_caps("broadcast in progress...") + " 0%"
    )

    delivered_ids = {}
    sent = 0
    blocked = 0          # user blocked the bot / kicked it / deactivated account
    invalid_chat = 0     # chat no longer exists / never started the bot
    other_failed = 0     # anything else (unexpected)
    recovered = 0        # succeeded only after a flood-control retry

    user_ids = list(BOT_DATA["users"].keys())
    # The sending admin also receives a copy, so the broadcast is visible in
    # the admin chat exactly like it is for users.
    admin_uid = str(update.effective_user.id)
    if admin_uid not in user_ids:
        user_ids.append(admin_uid)
    total = len(user_ids)
    for i, uid in enumerate(user_ids):
        try:
            copied = await context.bot.copy_message(
                chat_id=int(uid), from_chat_id=msg.chat_id, message_id=msg.message_id,
                protect_content=protect,
            )
        except RetryAfter as e:
            # Flood control — Telegram itself tells us exactly how long to
            # wait. Honour it once, then retry this one user before giving
            # up, instead of silently counting a recoverable hit as failed.
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                copied = await context.bot.copy_message(
                    chat_id=int(uid), from_chat_id=msg.chat_id, message_id=msg.message_id,
                    protect_content=protect,
                )
                recovered += 1
            except Exception:
                other_failed += 1
                copied = None
        except Forbidden:
            # User blocked the bot, deleted their account, or kicked it
            # from a group — permanent, not worth retrying.
            blocked += 1
            copied = None
        except BadRequest:
            # Chat not found / user never actually opened a DM with the
            # bot — also permanent.
            invalid_chat += 1
            copied = None
        except TelegramError:
            other_failed += 1
            copied = None
        except Exception:
            other_failed += 1
            copied = None

        if copied:
            track_sent_message(int(uid), copied.message_id)
            # Broadcasts are exempt from the global auto-delete timer — they
            # only go away via an explicit 🗑 Delete Broadcast action.
            delivered_ids[uid] = copied.message_id
            sent += 1

        await asyncio.sleep(BROADCAST_SEND_DELAY)

        if total and (i + 1) % 25 == 0:
            pct = int(((i + 1) / total) * 100)
            try:
                await status_msg.edit_text("📢 " + to_small_caps("broadcast in progress...") + f" {pct}%")
            except Exception:
                pass

    failed_total = blocked + invalid_chat + other_failed
    at = datetime.utcnow().isoformat()
    entry = {
        "id": broadcast_id,
        "by": update.effective_user.id,
        "at": at,
        "recipients": sent,
        "blocked": blocked,
        "invalid_chat": invalid_chat,
        "other_failed": other_failed,
        "recovered": recovered,
        "total_targeted": total,
        "messages": delivered_ids,  # {user_id: message_id} — used by Delete Broadcast
        "protect": protect,
        "report_chat_id": None,
        "report_message_id": None,
    }
    BOT_DATA["broadcast_log"].append(entry)
    BOT_DATA["metrics"]["broadcasts_sent"] = BOT_DATA["metrics"].get("broadcasts_sent", 0) + 1
    save_data()

    report = _broadcast_report_text(entry)
    try:
        await status_msg.edit_text(report)
        # Remember where this report lives so cb_bc_start_now can keep it
        # live-updated as users tap 🚀 Start Bot, instead of the numbers
        # only ever being a one-time snapshot.
        entry["report_chat_id"] = status_msg.chat_id
        entry["report_message_id"] = status_msg.message_id
    except Exception:
        sent_report = await update.message.reply_text(report)
        entry["report_chat_id"] = sent_report.chat_id
        entry["report_message_id"] = sent_report.message_id
    save_data()
    await log_event(
        context,
        f"📢 Broadcast sent by {update.effective_user.id} — {sent}/{total} delivered "
        f"(blocked {blocked}, invalid {invalid_chat}, other {other_failed})",
    )


# ---- Delete Broadcast (month-wise) -------------------------------------------

def _broadcast_month_key(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts)
    except Exception:
        return "unknown"
    return dt.strftime("%B %Y")  # e.g. "September 2026"


async def _render_adm_bc_delmenu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entries = BOT_DATA["broadcast_log"]
    months = {}
    for idx, e in enumerate(entries):
        key = _broadcast_month_key(e.get("at", ""))
        months.setdefault(key, []).append(idx)

    if not months:
        text = to_small_caps("🗑 delete broadcast") + "\n\n" + to_small_caps("no broadcasts recorded yet.")
        kb = InlineKeyboardMarkup([back_row("adm_broadcast")])
        await query.edit_message_text(text, reply_markup=kb)
        return

    month_keys = list(months.keys())
    rows = []
    for i in range(0, len(month_keys), 2):
        pair = month_keys[i:i + 2]
        rows.append([
            styled_button(f"🗓 {mk} ({len(months[mk])})", callback_data=f"adm_bc_delmonth:{mk}")
            for mk in pair
        ])
    rows.append(back_row("adm_broadcast"))
    rows.append(home_row())
    text = (
        to_small_caps("🗑 delete broadcast") + "\n"
        + to_small_caps("pick a month to see broadcasts sent that month")
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_bc_delmenu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_bc_delmenu(update, context)


async def cb_adm_bc_delmonth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    month = query.data.split(":", 1)[1]
    entries = BOT_DATA["broadcast_log"]
    rows = []
    lines = [to_small_caps("🗓 broadcasts in") + f" {month}\n"]
    for idx, e in enumerate(entries):
        if _broadcast_month_key(e.get("at", "")) != month:
            continue
        when = e.get("at", "?")[:16].replace("T", " ")
        lines.append(f"#{idx} — {when} — " + to_small_caps("delivered") + f" {e.get('recipients', 0)}")
        rows.append([styled_button(f"🗑 #{idx} — {when}", callback_data=f"adm_bc_delconfirm:{idx}")])
    rows.append(back_row("adm_bc_delmenu"))
    rows.append(home_row())
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_bc_delconfirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    entries = BOT_DATA["broadcast_log"]
    if idx < 0 or idx >= len(entries):
        await query.edit_message_text(
            "❌ " + to_small_caps("that broadcast no longer exists."),
            reply_markup=InlineKeyboardMarkup([back_row("adm_bc_delmenu")]),
        )
        return
    e = entries[idx]
    when = e.get("at", "?")[:16].replace("T", " ")
    recipients = len(e.get("messages", {}))
    text = (
        "⚠️ " + to_small_caps("confirm delete") + "\n\n"
        + to_small_caps("broadcast") + f" #{idx} — {when}\n"
        + to_small_caps("this will remove it from") + f" {recipients} " + to_small_caps("recipient chats.")
        + "\n\n" + to_small_caps("this action cannot be undone.")
    )
    kb = InlineKeyboardMarkup(
        [
            [styled_button("✅ Yes, Delete", callback_data=f"adm_bc_deldo:{idx}"),
             styled_button("❌ Cancel", callback_data="adm_bc_delmenu")],
        ]
    )
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_bc_deldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    entries = BOT_DATA["broadcast_log"]
    if idx < 0 or idx >= len(entries):
        await query.edit_message_text(
            "❌ " + to_small_caps("that broadcast no longer exists."),
            reply_markup=InlineKeyboardMarkup([back_row("adm_bc_delmenu")]),
        )
        return
    e = entries[idx]
    messages = e.get("messages", {})
    removed = 0
    gone = 0
    for uid, mid in messages.items():
        try:
            await context.bot.delete_message(chat_id=int(uid), message_id=int(mid))
            removed += 1
        except Exception:
            gone += 1
        await asyncio.sleep(BROADCAST_SEND_DELAY)
    entries.pop(idx)
    save_data()
    text = (
        "✅ " + to_small_caps("broadcast deleted") + "\n\n"
        + to_small_caps("removed from chats") + f": {removed}\n"
        + to_small_caps("already gone / could not remove") + f": {gone}"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([back_row("adm_bc_delmenu"), home_row()]))
    await log_event(context, f"🗑 Broadcast #{idx} deleted by {update.effective_user.id} — {removed} removed")


# ---- Menu & UI (#1, #2, #4, #7 controls) -------------------------------------

MENU_DISPLAY_NAMES = {
    # v10 — short labels requested for the Menu & UI list, so a button
    # name never gets cut off / hard to read on a phone screen. Anything
    # not in this map falls back to its raw id (title-cased) below.
    "start": "Start",
    "disclaimer": "Disclaimer",
    "download": "Downld",
    "howto": "HTU",
    "gift": "Gift",
    "language": "Language",
    "developer": "Developer",
    "support": "Support",
    "admin": "Admin",
    "help_user": "Help User",
    "reel_result": "Reel Result",
    "maintenance": "Maintenance",
    "bot_live": "Bot Live",
    "help_admin": "Help Admin",
}


async def _render_adm_menu_ui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # 2-per-row grid, a single ✅ badge when the menu has an image set, and
    # short display names so nothing overflows on a phone screen.
    menu_ids = list(BOT_DATA["menus"])

    def _label(mid):
        has_image = bool(BOT_DATA["menus"][mid].get("image_file_id"))
        name = MENU_DISPLAY_NAMES.get(mid, mid.replace("_", " ").title())
        return f"{name} ✅" if has_image else name

    rows = [[styled_button("🖼️ Set Welcome Image", callback_data="adm_menu_img:start")]]
    for i in range(0, len(menu_ids), 2):
        pair = menu_ids[i:i + 2]
        rows.append([styled_button(_label(mid), callback_data=f"adm_menu_edit:{mid}") for mid in pair])
    rows.append(back_row())
    rows.append(home_row())
    text = (
        to_deco(to_title_small_caps("Menu & UI")) + "\n\n"
        + to_small_caps("tap a menu below to edit its text, image or buttons.") + "\n"
        + to_small_caps("✅ next to a menu means it already has an image set.")
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_menu_ui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_menu_ui(update, context)


def _build_menu_edit_screen(menu_id: str):
    """Single source of truth for the 'editing menu X' screen — used both
    when first opening it and when refreshing it in place after a save
    (e.g. right after an image upload), so the two never drift apart."""
    menu = BOT_DATA["menus"][menu_id]
    parse_mode_label = menu.get("parse_mode") or "OFF (Raw Text)"
    override = menu.get("auto_delete_seconds")
    override_label = f"{override}s" if override is not None else "Uses Global"
    has_image = bool(menu.get("image_file_id"))
    image_status = "✅ " + to_title_small_caps("Set") if has_image else "❌ " + to_title_small_caps("Not Set")
    image_btn_label = ("🖼️ Change Image" if has_image else "🖼️ Set Image")

    rows = [
        [styled_button("✏️ Edit Text", callback_data=f"adm_menu_txt:{menu_id}"),
         styled_button("🅰️ Style Text", callback_data=f"adm_menu_style:{menu_id}")],
        [styled_button(f"🔤 Parse Mode: {parse_mode_label}", callback_data=f"adm_menu_parsemode:{menu_id}"),
         styled_button("🔘 Manage Buttons", callback_data=f"adm_menu_btns:{menu_id}")],
    ]
    if has_image:
        rows.append([
            styled_button(image_btn_label, callback_data=f"adm_menu_img:{menu_id}"),
            styled_button("🗑️ Remove Image", callback_data=f"adm_menu_rmimg:{menu_id}"),
        ])
    else:
        rows.append([styled_button(image_btn_label, callback_data=f"adm_menu_img:{menu_id}")])
    rows.append([
        styled_button(f"⏱ Auto-Delete: {override_label}", callback_data=f"adm_menu_autodel:{menu_id}"),
        styled_button("🌐 Translations", callback_data=f"adm_menu_trans:{menu_id}"),
    ])
    rows.append([styled_button("🔙 Back", callback_data="adm_menu_ui")])

    # v10 — the header now names the menu with its short display name (not
    # a generic "Editing Menu" title with the id buried below), and a
    # quoted preview of the CURRENT text is shown right under the status
    # lines — so it's confirmed at a glance which menu this is and what's
    # already set for it, without needing to tap "Edit Text" first.
    display_name = MENU_DISPLAY_NAMES.get(menu_id, menu_id.replace("_", " ").title())
    current_text = menu.get("text") or ""
    preview = html.escape(re.sub(r"<[^>]+>", "", current_text)).strip()
    if len(preview) > 200:
        preview = preview[:200].rstrip() + "…"
    text = (
        to_deco(to_title_small_caps(f"Editing Menu: {display_name}")) + "\n\n"
        + f"<b>ID:</b> <code>{html.escape(menu_id)}</code>\n"
        + f"<b>Image:</b> {image_status}\n"
        + f"<b>Parse Mode:</b> {html.escape(parse_mode_label)}\n"
        + f"<b>Auto-Delete:</b> {html.escape(override_label)}\n\n"
        + "<b>" + to_title_small_caps("Currently Set") + ":</b>\n"
        + f"<blockquote>{preview or to_small_caps('(empty)')}</blockquote>\n\n"
        + to_small_caps("choose what you'd like to change below")
    )
    return text, InlineKeyboardMarkup(rows)


async def cb_adm_menu_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    text, kb = _build_menu_edit_screen(menu_id)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


async def cb_adm_menu_trans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    langs = BOT_DATA["settings"].get("languages", [])
    if not langs:
        await query.message.reply_text(
            to_small_caps("first add at least one language via settings & admins → 🌐 manage languages.")
        )
        return
    rows = []
    have = BOT_DATA["menus"][menu_id].get("translations", {})
    for code in langs:
        mark = "✅" if code in have else "➕"
        rows.append([styled_button(f"{mark} {LANG_NAMES.get(code, code)}", callback_data=f"adm_menu_trans_edit:{menu_id}:{code}")])
    rows.append([styled_button("🔙 Back", callback_data=f"adm_menu_edit:{menu_id}")])
    await query.edit_message_text(f"🌐 Translations for {menu_id}", reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_menu_trans_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, menu_id, code = query.data.split(":", 2)
    context.user_data["awaiting"] = f"menu_trans_text:{menu_id}:{code}"
    await query.message.reply_text(
        to_small_caps(f"send the {LANG_NAMES.get(code, code)} translation text for '{menu_id}'") + "\n"
        + to_small_caps("(buttons stay the same as the base menu — they are not translated.)")
    )


async def cb_adm_menu_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    context.user_data["awaiting"] = f"menu_text:{menu_id}"
    await query.message.reply_text(
        to_small_caps("send the new text — it will be saved exactly as sent, with no auto-reformatting.")
    )


async def cb_adm_menu_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    context.user_data["awaiting"] = f"menu_style_source:{menu_id}"
    await query.message.reply_text(to_small_caps("send plain text and a preview of every available style will be shown."))


async def cb_adm_menu_parsemode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    cycle = [None, "HTML", "MarkdownV2"]
    current = BOT_DATA["menus"][menu_id].get("parse_mode")
    nxt = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else None
    BOT_DATA["menus"][menu_id]["parse_mode"] = nxt
    save_data()
    await cb_adm_menu_edit(update, context)


async def cb_adm_menu_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    context.user_data["awaiting"] = f"menu_image:{menu_id}"
    # Remember this exact "editing menu" screen so that once the photo is
    # received, we can flip its 🖼️ status straight to ✅ Set in place,
    # instead of leaving the admin to guess whether it actually saved.
    remember_panel_message(context, query, f"menu_edit:{menu_id}")
    await query.message.reply_text(to_small_caps("send a photo (image only, not a video)."))


async def cb_adm_menu_rmimg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    BOT_DATA["menus"][menu_id]["image_file_id"] = None
    save_data()
    await query.message.reply_text(to_small_caps("✅ image removed — this is now a text-only menu."))
    await cb_adm_menu_edit(update, context)


async def cb_adm_menu_autodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    context.user_data["awaiting"] = f"menu_autodel:{menu_id}"
    await query.message.reply_text(
        to_small_caps("send the auto-delete time in seconds for this menu (0 = never, or type 'global' to use the global default).")
    )


def _menu_btns_keyboard(menu_id: str) -> InlineKeyboardMarkup:
    buttons = BOT_DATA["menus"][menu_id]["buttons"]
    rows = []
    for i, b in enumerate(buttons):
        rows.append([
            styled_button(f"{i}: {_short_btn_label(b['label'])}", callback_data="noop"),
            styled_button("✏️", callback_data=f"adm_btn_edit:{menu_id}:{i}"),
            styled_button("🅰️", callback_data=f"adm_btn_style:{menu_id}:{i}"),
            styled_button("❌", callback_data=f"adm_btn_del:{menu_id}:{i}"),
        ])
    rows.append([styled_button("➕ Add Button", callback_data=f"adm_btn_add:{menu_id}")])
    rows.append([styled_button("🔙 Back", callback_data=f"adm_menu_edit:{menu_id}")])
    return InlineKeyboardMarkup(rows)


async def cb_adm_menu_btns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    text = to_deco(to_title_small_caps(f"Buttons: {menu_id}"))
    await query.edit_message_text(text, reply_markup=_menu_btns_keyboard(menu_id))


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def cb_adm_btn_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, menu_id, idx = query.data.split(":", 2)
    idx = int(idx)
    if 0 <= idx < len(BOT_DATA["menus"][menu_id]["buttons"]):
        BOT_DATA["menus"][menu_id]["buttons"].pop(idx)
        save_data()
    await cb_adm_menu_btns_by_id(update, context, menu_id)


async def cb_adm_btn_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, menu_id, idx = query.data.split(":", 2)
    label = BOT_DATA["menus"][menu_id]["buttons"][int(idx)]["label"]
    context.user_data["style_source_text"] = label
    context.user_data["style_target"] = f"button_label:{menu_id}:{idx}"
    await send_style_preview(context, query.message.chat_id, label)


async def cb_adm_menu_btns_by_id(update, context, menu_id):
    """Helper to redraw the buttons list after a delete/edit, without a fresh query.data."""
    text = to_deco(to_title_small_caps(f"Buttons: {menu_id}"))
    await update.callback_query.edit_message_text(text, reply_markup=_menu_btns_keyboard(menu_id))


async def cb_adm_btn_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit-in-place: pre-fills the same label/type/value/row flow used by
    Add Button with the button's current values, so the admin can just send
    '-' at any step to keep it as-is instead of deleting + re-adding."""
    query = update.callback_query
    await query.answer()
    _, menu_id, idx = query.data.split(":", 2)
    idx = int(idx)
    buttons = BOT_DATA["menus"][menu_id]["buttons"]
    if not (0 <= idx < len(buttons)):
        await query.message.reply_text(to_small_caps("that button no longer exists — refresh the list."))
        return
    existing = dict(buttons[idx])
    context.user_data["btn_flow"] = {"menu_id": menu_id, "data": dict(existing), "edit_idx": idx}
    context.user_data["awaiting"] = "btn_step_label"
    await query.message.reply_text(
        to_small_caps(f"editing button {idx}. current label: {existing.get('label')}") + "\n"
        + to_small_caps("send the new label, or send - to keep it as-is.")
    )


async def cb_adm_btn_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    menu_id = query.data.split(":", 1)[1]
    context.user_data["btn_flow"] = {"menu_id": menu_id, "data": {}}
    context.user_data["awaiting"] = "btn_step_label"
    await query.message.reply_text(to_small_caps("send the new button's label (emoji are welcome)."))


async def cb_btn_type_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, btype = query.data.split(":", 1)
    flow = context.user_data.get("btn_flow")
    if not flow:
        await query.message.reply_text(to_small_caps("session expired — please try again via /admin."))
        return
    if btype == "keep":
        # Edit flow only — type & value stay as they already are in flow["data"].
        context.user_data["awaiting"] = "btn_step_value"
        cur_val = flow["data"].get("value", "")
        await query.message.reply_text(
            to_small_caps(f"current value: {cur_val}") + "\n" + to_small_caps("send a new value, or send - to keep it.")
        )
        return
    flow["data"]["type"] = btype
    context.user_data["awaiting"] = "btn_step_value"
    prompts = {
        "menu": to_small_caps("which menu_id should this open? (e.g. start, help_user)"),
        "url": to_small_caps("send the url (must start with https://)."),
        "callback": to_small_caps("send the internal action's callback_data (e.g. adm_stats)."),
        "toggle": to_small_caps("send the settings key to toggle (e.g. maintenance)."),
    }
    await query.message.reply_text(prompts.get(btype, to_small_caps("send the value:")))


# ---- Settings & Admins --------------------------------------------------------

async def _render_adm_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    s = BOT_DATA["settings"]
    # v6 — same 2-per-row grid treatment as the top-level Admin Panel, so
    # deep submenus stay just as easy to scan and control.
    rows = [
        [styled_button("🔒 Maintenance", callback_data="adm_maintenance")],
        [styled_button(f"⏱ Global Auto-Delete: {s.get('global_auto_delete_seconds', 0)}s", callback_data="adm_set_autodelete"),
         styled_button("💬 Auto-Replies", callback_data="adm_autoreply_list")],
    ]
    # 👤 Manage Admins can hand out access to everything, so — like the
    # whole 🍭 Update Backup section / ☠️ Danger Zone — it stays owner-only
    # even though "settings" itself is a grantable permission.
    # 📥 Restore Backup lives on the consolidated 🍭 Update Backup screen
    # along with every other backup/database action (Mongo Plugin, full DB
    # export, etc.), not here.
    if is_owner(update.effective_user.id):
        rows.append([styled_button("👤 Manage Admins", callback_data="adm_manage_admins")])
    rows += [
        [styled_button(
             toggle_label("🔐 Lock All Forwarding", s.get('lock_all_content')),
             callback_data="stgl:lock_all_content:adm_settings",
         ),
         styled_button("👑 Owner/Developer Contact", callback_data="adm_owner_contact")],
        [styled_button("📋 Logger Channel", callback_data="adm_logger_channel"),
         styled_button("📣 Activity Channel", callback_data="adm_activity_channel")],
        [styled_button(f"📢 Force-Join: {s.get('force_join_channel') or 'OFF'}", callback_data="adm_force_join")],
        [styled_button(
            toggle_label("📄 Send As Document", s.get('send_as_document')),
            callback_data="stgl:send_as_document:adm_settings",
        )],
        [styled_button(
             toggle_label("🌟 Premium Emoji Greeting", s.get('premium_emoji_enabled')),
             callback_data="stgl:premium_emoji_enabled:adm_settings",
         ),
         styled_button("✏️ Set Premium Emoji", callback_data="adm_set_premium_emoji")],
        back_row(),
        home_row(),
    ]
    kb = InlineKeyboardMarkup(rows)
    await query.edit_message_text(
        "⚙️ " + to_small_caps("settings") + "\n"
        + to_small_caps("configure core bot behaviour below."),
        reply_markup=kb,
    )


async def cb_adm_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_settings(update, context)


async def cb_adm_set_premium_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "premium_emoji_capture"
    await query.message.reply_text(
        to_small_caps("🌟 send (or forward) a message that contains ONE premium custom emoji.") + "\n"
        + to_small_caps("i'll grab that emoji's id and use it in the start greeting when premium emoji is turned on.") + "\n\n"
        + to_small_caps("note: this only works if the sender actually has telegram premium — that's a telegram limit, not this bot's.")
    )


async def handle_premium_emoji_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reads MessageEntity(type='custom_emoji') off the admin's sample
    message. Registered as its own MessageHandler (entities aren't plain
    text) rather than folded into handle_admin_text_input."""
    if context.user_data.get("awaiting") != "premium_emoji_capture":
        return
    if not is_admin(update.effective_user.id):
        return
    context.user_data["awaiting"] = None
    msg = update.message
    entities = msg.entities or msg.caption_entities or []
    ce = next((e for e in entities if e.type == MessageEntity.CUSTOM_EMOJI), None)
    if not ce:
        await msg.reply_text(
            to_small_caps("❌ no custom emoji found in that message — make sure it's an actual premium animated emoji, not a regular unicode emoji.")
        )
        return
    text_src = msg.text or msg.caption or ""
    # offset/length are UTF-16 code units per the Bot API spec.
    utf16 = text_src.encode("utf-16-le")
    glyph_bytes = utf16[ce.offset * 2: (ce.offset + ce.length) * 2]
    glyph = glyph_bytes.decode("utf-16-le", errors="ignore") or "🌟"
    BOT_DATA["settings"]["premium_emoji_id"] = ce.custom_emoji_id
    BOT_DATA["settings"]["premium_emoji_char"] = glyph
    save_data()
    await msg.reply_text(
        to_small_caps("✅ premium emoji saved.") + "\n"
        + to_small_caps("turn on '🌟 premium emoji greeting' in settings to use it on /start.")
    )


async def send_premium_emoji_greeting(bot, chat_id: int):
    """Sends a short standalone greeting line with the admin-configured
    Premium custom emoji, right before the normal /start menu. Kept as its
    own message (entities-based, no HTML) so it never conflicts with the
    HTML parse_mode used everywhere else. Non-Premium viewers automatically
    see the fallback glyph — that's Telegram's own behaviour, not ours."""
    s = BOT_DATA["settings"]
    if not s.get("premium_emoji_enabled") or not s.get("premium_emoji_id"):
        return
    glyph = s.get("premium_emoji_char") or "🌟"
    caption = to_small_caps(" welcome!")
    text = glyph + caption
    glyph_len = len(glyph.encode("utf-16-le")) // 2
    entities = [MessageEntity(type=MessageEntity.CUSTOM_EMOJI, offset=0, length=glyph_len, custom_emoji_id=s["premium_emoji_id"])]
    try:
        await bot.send_message(chat_id, text, entities=entities)
    except Exception:
        log.warning("Premium emoji greeting failed (id may be stale/invalid)", exc_info=True)


# ---- Maintenance (single combined screen: status + toggle + set message) ---

def _maintenance_kb(is_on: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [styled_button(toggle_label("Maintenance", is_on), callback_data="stgl:maintenance:adm_maintenance")],
            [styled_button("✏️ Set New Message", callback_data="adm_maint_setmsg")],
            back_row("adm_settings"),
            home_row(),
        ]
    )


async def _render_adm_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    is_on = bool(BOT_DATA["settings"].get("maintenance"))
    current_text = BOT_DATA["menus"].get("maintenance", {}).get("text", "")
    preview = (current_text[:250] + "…") if len(current_text) > 250 else current_text
    status_line = (
        "🔴 " + to_small_caps("active — only admins can use the bot right now")
        if is_on else
        "🟢 " + to_small_caps("off — bot is live and working normally")
    )
    body = (
        "🔒 " + to_small_caps("maintenance") + "\n\n"
        + status_line + "\n\n"
        + to_small_caps("current message shown to users") + ":\n"
        + preview
    )
    await query.edit_message_text(body, reply_markup=_maintenance_kb(is_on))


async def cb_adm_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_maintenance(update, context)


async def cb_adm_maint_setmsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "maintenance_set_msg"
    await query.message.reply_text(
        "✏️ " + to_small_caps("send the new maintenance message now") + "\n"
        + to_small_caps("this is exactly what users will see while maintenance is on.")
    )


# ---- Owner/Developer credit button (#10) --------------------------------------

def _build_adm_owner_contact_view():
    s = BOT_DATA["settings"]
    current = s.get("owner_display_user_id")
    label = s.get("owner_display_label") or "👑 Developer"
    text = (
        "👑 Owner/Developer Contact\n\n"
        f"Current target: {current or '(not set)'}\n"
        f"Button label: {label}\n\n"
        "This shows a display/credit button on Start & Help — it does NOT "
        "grant that user any bot-admin permissions."
    )
    kb = InlineKeyboardMarkup(
        [
            [styled_button("✏️ Set Contact", callback_data="adm_owner_contact_set")],
            [styled_button("❌ Clear", callback_data="adm_owner_contact_clear")],
            back_row(),
        ]
    )
    return text, kb


async def _render_adm_owner_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_owner_contact_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_owner_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_owner_contact(update, context)


async def cb_adm_owner_contact_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "owner_contact")
    context.user_data["awaiting"] = "owner_contact_label"
    await query.message.reply_text(to_small_caps("send the button label (e.g. '👑 developer' or '💬 contact us')."))


async def cb_adm_owner_contact_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    BOT_DATA["settings"]["owner_display_user_id"] = None
    BOT_DATA["settings"]["owner_display_label"] = None
    save_data()
    await query.edit_message_text("✅ Owner/Developer contact button cleared.", reply_markup=InlineKeyboardMarkup([back_row()]))


# ---- Logger channel (#14) ------------------------------------------------------

def _build_adm_logger_channel_view():
    s = BOT_DATA["settings"]
    text = (
        "📋 Logger Channel\n\n"
        f"Channel ID: {s.get('logger_channel_id') or '(not set)'}\n"
        f"Enabled: {'✅ ON' if s.get('logger_enabled') else '❌ OFF'}\n\n"
        "Logs new users, downloads, broadcasts, admin changes, copyright "
        "reports, and errors here."
    )
    kb = InlineKeyboardMarkup(
        [
            [styled_button("✏️ Set Channel", callback_data="adm_logger_channel_set")],
            [styled_button(
                toggle_label("🔀 Enabled", s.get('logger_enabled')),
                callback_data="stgl:logger_enabled:adm_logger_channel",
            )],
            back_row(),
        ]
    )
    return text, kb


async def _render_adm_logger_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_logger_channel_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_logger_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_logger_channel(update, context)


async def cb_adm_logger_channel_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "logger_channel")
    context.user_data["awaiting"] = "logger_channel_id"
    await query.message.reply_text(
        "Forward any message from the target channel here (bot must be an "
        "admin there), or just type its numeric ID (looks like -100xxxxxxxxxx)."
    )


# ---- #18 — Activity Channel (dedicated home for the Reel Delivered card) ------

def _build_adm_activity_channel_view():
    s = BOT_DATA["settings"]
    text = (
        "📣 Activity Channel\n\n"
        f"Channel ID: {s.get('activity_channel_id') or '(not set)'}\n"
        f"Enabled: {'✅ ON' if s.get('activity_channel_enabled') else '❌ OFF'}\n\n"
        "Every delivered reel posts a clean 'Reel Delivered' card here — "
        "separate from the general Logger Channel, so this stays a pure "
        "delivery feed with no error/debug noise mixed in."
    )
    kb = InlineKeyboardMarkup(
        [
            [styled_button("✏️ Set Channel", callback_data="adm_activity_channel_set")],
            [styled_button(
                toggle_label("🔀 Enabled", s.get('activity_channel_enabled')),
                callback_data="stgl:activity_channel_enabled:adm_activity_channel",
            )],
            back_row(),
        ]
    )
    return text, kb


async def _render_adm_activity_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_activity_channel_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_activity_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_activity_channel(update, context)


async def cb_adm_activity_channel_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "activity_channel")
    context.user_data["awaiting"] = "activity_channel_id"
    await query.message.reply_text(
        "Forward any message from the target channel here (bot must be an "
        "admin there), or just type its numeric ID (looks like -100xxxxxxxxxx)."
    )


# ---- Force-join channel ------------------------------------------------

def _build_adm_force_join_view():
    targets = _force_join_targets()
    lines = []
    for i, t in enumerate(targets, 1):
        lines.append(f"{i}. {t.get('chat_id') or '(link-only)'}\n   🔗 {t.get('link') or 'auto-resolve'}")
    text = (
        "📢 " + to_title_small_caps("Multiple Force-Join") + "\n\n"
        + ("\n\n".join(lines) if lines else to_small_caps("no channels set — force-join disabled."))
        + "\n\n<blockquote>"
        + to_title_small_caps(
            "Users Must Satisfy All Listed Channels. Public @Usernames, Numeric "
            "Channel IDs And t.me/Invite Links Are Supported. Join Requests Are Also "
            "Accepted When Telegram Delivers The Request Update To This Bot."
        )
        + "</blockquote>"
    )
    kb_rows = [
        [styled_button("➕ Add Channel / Link", callback_data="adm_force_join_set")],
        [styled_button("🗑 Remove Last", callback_data="adm_force_join_remove")] if targets else [],
        [styled_button("❌ Disable All", callback_data="adm_force_join_clear")],
        back_row(),
    ]
    kb_rows = [r for r in kb_rows if r]
    return text, InlineKeyboardMarkup(kb_rows)


async def _render_adm_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_force_join_view()
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


async def cb_adm_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_force_join(update, context)


async def cb_adm_force_join_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "force_join")
    context.user_data["awaiting"] = "force_join_channel"
    msg = await query.message.reply_text(
        "<blockquote>"
        + to_title_small_caps("Send A Public") + " @ChannelUsername, "
        + to_title_small_caps("Numeric Channel") + " ID (-100xxxxxxxxxx), "
        + to_title_small_caps("Or A Full") + " https://t.me/... "
        + to_title_small_caps("Invite/Join Link. You Can Add Multiple Channels One By One. "
                               "For Reliable Membership Checking, The Bot Should Be An Admin "
                               "In Each Channel.")
        + "</blockquote>",
        parse_mode="HTML",
    )
    _track_ephemeral(context, msg)


async def cb_adm_force_join_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    BOT_DATA["settings"]["force_join_channel"] = None
    BOT_DATA["settings"]["force_join_channels"] = []
    save_data()
    await _render_adm_force_join(update, context)


async def cb_adm_force_join_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    targets = _force_join_targets()
    if targets:
        targets.pop()
        BOT_DATA["settings"]["force_join_channels"] = targets
        BOT_DATA["settings"]["force_join_channel"] = targets[0].get("chat_id") if targets else None
        save_data()
    await _render_adm_force_join(update, context)


async def cb_adm_force_join_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live diagnostic — actually calls the Bot API right now and shows the
    exact result/error, instead of the admin having to guess why nobody is
    getting blocked. This is the #1 real-world cause of 'force-join doesn't
    work': the bot silently isn't an admin in the target channel, or the
    channel string is wrong — and that used to only get logged, never shown."""
    query = update.callback_query
    await query.answer()
    channel = BOT_DATA["settings"].get("force_join_channel")
    if not channel:
        await query.message.reply_text("⚠️ No force-join channel is set.")
        return
    lines = [f"🧪 Testing force-join channel: {channel}\n"]
    try:
        me = await context.bot.get_me()
        chat = await context.bot.get_chat(channel)
        lines.append(f"✅ Bot can see the channel: {chat.title or chat.id}")
        member = await context.bot.get_chat_member(chat_id=channel, user_id=me.id)
        if member.status in ("administrator", "creator"):
            lines.append("✅ Bot IS an admin there — membership checks will work.")
        else:
            lines.append(
                "❌ Bot is a MEMBER but NOT an admin there — get_chat_member calls for "
                "other users will fail and force-join will silently fail OPEN "
                "(let everyone through). Make the bot an admin in this channel."
            )
    except Exception as e:
        lines.append(
            f"❌ Bot could NOT access this channel at all ({e}).\n"
            "This is almost always the reason force-join 'doesn't work' — the bot "
            "must be added to the channel as an ADMIN first. Double-check the "
            "username/ID too."
        )
    await query.message.reply_text("\n".join(lines))


def _build_adm_leaderboard_view():
    # Leaderboard-only screen; share settings live in _build_adm_share_view.
    s = BOT_DATA["settings"]
    lb_on = s.get("leaderboard_enabled", False)
    donor_count = len([d for d in BOT_DATA.get("donations", {}).values() if d.get("score", 0) > 0])
    text = (
        "🏆 Leaderboard\n\n"
        f"Status: {'✅ ON' if lb_on else '❌ OFF'} — shown inside 🎁 Send Gift, "
        f"{donor_count} donor(s) ranked so far.\n\n"
        "Only voluntary 🎁 Send Gift donations count here — Premium Plan "
        "purchases are subscriptions, not gifts, so they're never counted.\n\n"
        + build_leaderboard_text()
    )
    kb_rows = [
        [styled_button(
            f"{'✅' if lb_on else '❌'} Leaderboard",
            callback_data="stgl:leaderboard_enabled:adm_leaderboard",
        )],
        [styled_button("📢 Post Leaderboard to All Users", callback_data="adm_post_leaderboard")],
        back_row(),
    ]
    return text, InlineKeyboardMarkup(kb_rows)


async def _render_adm_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_leaderboard_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_leaderboard(update, context)


async def cb_adm_post_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcasts the leaderboard to every known user (same delivery path
    as /broadcast) and cross-posts to the logger channel if one is set."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    text = build_leaderboard_text()
    sent, failed = 0, 0
    for uid in list(BOT_DATA["users"].keys()):
        try:
            m = await context.bot.send_message(int(uid), text)
            track_sent_message(int(uid), m.message_id)
            await schedule_delete(context, int(uid), m.message_id, BOT_DATA["settings"].get("global_auto_delete_seconds", 0))
            sent += 1
        except Exception:
            failed += 1
    channel = BOT_DATA["settings"].get("logger_channel_id") if BOT_DATA["settings"].get("logger_enabled") else None
    if channel:
        try:
            await context.bot.send_message(channel, text)
        except Exception:
            pass
    await query.message.reply_text(f"✅ {to_small_caps('leaderboard posted to all users')}\nSent: {sent} | Failed: {failed}")
    await log_event(context, f"🏆 Leaderboard posted to users by {update.effective_user.id} — {sent} recipients")


def _build_adm_share_view():
    s = BOT_DATA["settings"]
    share_on = s.get("share_enabled", True)
    share_url = s.get("share_url") or to_small_caps("(default — bot's own link)")
    text = (
        "📤 Share Settings\n\n"
        f"Share button (under My Usage): {'✅ ON' if share_on else '❌ OFF'}\n"
        f"Share URL: {share_url}"
    )
    kb_rows = [
        [styled_button(
            f"{'✅' if share_on else '❌'} Share Button",
            callback_data="stgl:share_enabled:adm_share",
        )],
        [styled_button("✏️ Set Share URL", callback_data="adm_share_url_set")],
    ]
    if s.get("share_url"):
        kb_rows.append([styled_button("🗑️ Reset Share URL", callback_data="adm_share_url_clear")])
    kb_rows.append(back_row())
    return text, InlineKeyboardMarkup(kb_rows)


async def _render_adm_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_share_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_share(update, context)


async def cb_adm_share_url_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "share")
    context.user_data["awaiting"] = "share_url"
    await query.message.reply_text(
        "Type the URL the '📤 Share' button (under My Usage) should open — "
        "e.g. your channel link or a landing page. Send /cancel to leave it as-is."
    )


async def cb_adm_share_url_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    BOT_DATA["settings"]["share_url"] = None
    save_data()
    await _render_adm_share(update, context)


async def cb_settings_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Looks up the target screen via SCREEN_RENDERERS so any toggle button,
    on any admin screen, re-renders after flipping its setting."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    _, key, return_to = query.data.split(":", 2)
    was_on = bool(BOT_DATA["settings"].get(key, False))
    BOT_DATA["settings"][key] = not was_on
    save_data()

    if key == "maintenance":
        # Single combined screen now (status + toggle + set-message all in
        # one place) — toggling just re-renders that same screen instead of
        # showing a separate bulky "MAINTENANCE ON" / "BOT IS LIVE" card.
        if BOT_DATA["settings"]["maintenance"]:
            await query.answer("🔒 " + to_small_caps("maintenance enabled."), show_alert=False)
        else:
            await query.answer("🟢 " + to_small_caps("bot is live again."), show_alert=False)
            # Tell every user who actually hit the maintenance wall — not
            # just the admin looking at this panel — that the bot is back.
            await broadcast_bot_live(context)
        await _render_adm_maintenance(update, context)
        return

    renderer = SCREEN_RENDERERS.get(return_to)
    if renderer is not None:
        await renderer(update, context)
    else:
        await query.answer(to_small_caps("✅ updated."), show_alert=False)


async def cb_adm_lang_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    langs = BOT_DATA["settings"].get("languages", [])
    pack_names = _load_language_pack().get("languages", {})
    text = "🌐 Enabled Languages\n\n" + ("\n".join(f"• {pack_names.get(c) or LANG_NAMES.get(c, c)}" for c in langs) if langs else to_small_caps("none — default language only."))
    kb = InlineKeyboardMarkup(
        [
            [styled_button("➕ Add Language", callback_data="adm_lang_add")],
            [styled_button("➖ Remove Language", callback_data="adm_lang_remove")],
            [styled_button("🔙 Back", callback_data="adm_settings")],
        ]
    )
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_lang_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pack_names = _load_language_pack().get("languages", {})
    all_known = {**LANG_NAMES, **pack_names}
    available = [c for c in all_known if c not in BOT_DATA["settings"].get("languages", []) and c != "en"]
    if not available:
        await query.message.reply_text(to_small_caps("all available languages are already added."))
        return
    rows = [[styled_button(all_known[c], callback_data=f"adm_lang_add_do:{c}")] for c in available]
    await query.message.reply_text(to_small_caps("which language would you like to add?"), reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_lang_add_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]
    pack_names = _load_language_pack().get("languages", {})
    if code not in BOT_DATA["settings"]["languages"]:
        BOT_DATA["settings"]["languages"].append(code)
        save_data()
    await query.edit_message_text(to_small_caps(f"✅ {pack_names.get(code) or LANG_NAMES.get(code, code)} added. you can now add text for it via 🌐 translations in any menu."))


async def cb_adm_lang_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    langs = BOT_DATA["settings"].get("languages", [])
    if not langs:
        await query.message.reply_text(to_small_caps("no languages have been added yet."))
        return
    pack_names = _load_language_pack().get("languages", {})
    rows = [[styled_button(pack_names.get(c) or LANG_NAMES.get(c, c), callback_data=f"adm_lang_remove_do:{c}")] for c in langs]
    await query.message.reply_text(to_small_caps("which language would you like to remove?"), reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_lang_remove_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]
    if code in BOT_DATA["settings"]["languages"]:
        BOT_DATA["settings"]["languages"].remove(code)
        save_data()
    await query.edit_message_text(to_small_caps(f"✅ {LANG_NAMES.get(code, code)} removed."))


async def cb_adm_set_autodelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "global_autodelete"
    await query.message.reply_text("Global auto-delete kitne seconds ka ho (0 = disable)?")


async def cb_adm_autoreply_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    replies = BOT_DATA["settings"].get("auto_replies", {})
    lines = ["💬 Auto-Replies\n"] + (
        [f"• `{k}` → {v[:30]}" for k, v in replies.items()] or [to_small_caps("no auto-reply has been set.")]
    )
    kb = InlineKeyboardMarkup(
        [
            [styled_button("➕ Add", callback_data="adm_autoreply_add")],
            [styled_button("❌ Remove", callback_data="adm_autoreply_del")],
            [styled_button("🔙 Back", callback_data="adm_settings")],
        ]
    )
    await query.edit_message_text("\n".join(lines), reply_markup=kb)


async def cb_adm_autoreply_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "autoreply_key"
    await query.message.reply_text(to_small_caps("send the trigger keyword or phrase — it will auto-reply whenever a message contains it."))


async def cb_adm_autoreply_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "autoreply_delkey"
    await query.message.reply_text(to_small_caps("send the keyword you want to remove."))


def _perm_summary_text(selected: set) -> str:
    if not selected:
        return to_small_caps("no sections selected — this admin won't see anything in the panel yet.")
    lines = [f"• {ADMIN_PERMISSION_LABELS[k]}" for k in ADMIN_PERMISSION_KEYS if k in selected]
    return to_small_caps("access granted") + ":\n" + "\n".join(lines)


def _perm_picker_keyboard(selected: set, confirm_cb: str, cancel_cb: str, toggle_prefix: str) -> InlineKeyboardMarkup:
    """Shared toggle-grid used both when adding a new admin and when
    editing an existing one's access. ✅/⬜ next to each grantable section
    (see ADMIN_PERMISSIONS) — 📦 Update Backup, ☠️ Danger Zone, and 👤
    Manage Admins are deliberately absent: they're owner-only forever."""
    rows, row = [], []
    for key, label in ADMIN_PERMISSIONS:
        mark = "✅" if key in selected else "⬜"
        row.append(styled_button(f"{mark} {label}", callback_data=f"{toggle_prefix}:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([styled_button("✅ Select All", callback_data=f"{toggle_prefix}_all"),
                 styled_button("⬜ Clear All", callback_data=f"{toggle_prefix}_none")])
    rows.append([styled_button("💾 Save", callback_data=confirm_cb),
                 styled_button("🚫 Cancel", callback_data=cancel_cb)])
    return InlineKeyboardMarkup(rows)


async def cb_adm_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("🔒 " + to_small_caps("only the owner can access this."), show_alert=True)
        return
    admins = BOT_DATA.get("admins", [])
    lines = ["👤 " + to_small_caps("current admins") + "\n"]
    rows = []
    for a in admins:
        n_perms = len(get_admin_perms(a))
        lines.append(f"• {a} — {n_perms}/{len(ADMIN_PERMISSION_KEYS)} " + to_small_caps("sections"))
        rows.append([styled_button(f"✏️ {to_small_caps('edit access')} — {a}", callback_data=f"admperm_edit:{a}")])
    rows.append([styled_button("➕ Add Admin", callback_data="adm_add_admin")])
    rows.append([styled_button("➖ Remove Admin", callback_data="adm_remove_admin")])
    rows.append([styled_button("🔙 Back", callback_data="adm_settings")])
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


async def cb_adm_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.message.reply_text(to_small_caps("only the owner can add a new admin."))
        return
    context.user_data["awaiting"] = "add_admin_id"
    await query.message.reply_text(to_small_caps("send the new admin's user id."))


async def cb_adm_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.message.reply_text(to_small_caps("only the owner can remove an admin."))
        return
    context.user_data["awaiting"] = "remove_admin_id"
    await query.message.reply_text(to_small_caps("send the user id of the admin to remove."))


# ---- New-admin access picker: shown right after /add_admin_id is entered ----

async def _render_newadmin_picker(query, context):
    draft = context.user_data.setdefault("newadmin_perms_draft", set())
    new_id = context.user_data.get("newadmin_id_draft")
    text = (
        "➕ " + to_small_caps(f"choose access for admin {new_id}") + "\n\n"
        + to_small_caps("tap a section to toggle it, then save. only what you tick here is what they'll be able to open.") + "\n\n"
        + _perm_summary_text(draft)
    )
    await query.edit_message_text(text, reply_markup=_perm_picker_keyboard(draft, "newadmin_confirm", "newadmin_cancel", "newadmin_perm"))


async def cb_newadmin_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    key = query.data.split(":", 1)[1]
    draft = context.user_data.setdefault("newadmin_perms_draft", set())
    draft.symmetric_difference_update({key})
    await _render_newadmin_picker(query, context)


async def cb_newadmin_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    context.user_data["newadmin_perms_draft"] = set(ADMIN_PERMISSION_KEYS)
    await _render_newadmin_picker(query, context)


async def cb_newadmin_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    context.user_data["newadmin_perms_draft"] = set()
    await _render_newadmin_picker(query, context)


async def cb_newadmin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    new_id = context.user_data.pop("newadmin_id_draft", None)
    draft = context.user_data.pop("newadmin_perms_draft", set())
    if new_id is None:
        await query.edit_message_text(to_small_caps("this expired — please try adding the admin again."))
        return
    if new_id not in BOT_DATA["admins"]:
        BOT_DATA["admins"].append(new_id)
    BOT_DATA.setdefault("admin_permissions", {})[str(new_id)] = sorted(draft)
    save_data()
    await query.edit_message_text("✅ " + to_small_caps(f"{new_id} is now an admin.") + "\n\n" + _perm_summary_text(draft))
    await log_event(context, f"👤 Admin added: {new_id} — {len(draft)}/{len(ADMIN_PERMISSION_KEYS)} section(s) (by {update.effective_user.id})")


async def cb_newadmin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("newadmin_id_draft", None)
    context.user_data.pop("newadmin_perms_draft", None)
    await query.edit_message_text(to_small_caps("cancelled — no admin was added."))


# ---- Edit-existing-admin access picker (from Manage Admins ✏️) -------------

async def _render_editperm_picker(query, context):
    draft = context.user_data.setdefault("editperm_draft", set())
    target_id = context.user_data.get("editperm_target_id")
    text = (
        "✏️ " + to_small_caps(f"editing access for admin {target_id}") + "\n\n"
        + to_small_caps("tap a section to toggle it, then save.") + "\n\n"
        + _perm_summary_text(draft)
    )
    await query.edit_message_text(text, reply_markup=_perm_picker_keyboard(draft, "editperm_confirm", "editperm_cancel", "editperm_perm"))


async def cb_admperm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    target_id = int(query.data.split(":", 1)[1])
    context.user_data["editperm_target_id"] = target_id
    context.user_data["editperm_draft"] = get_admin_perms(target_id)
    await _render_editperm_picker(query, context)


async def cb_editperm_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    key = query.data.split(":", 1)[1]
    draft = context.user_data.setdefault("editperm_draft", set())
    draft.symmetric_difference_update({key})
    await _render_editperm_picker(query, context)


async def cb_editperm_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    context.user_data["editperm_draft"] = set(ADMIN_PERMISSION_KEYS)
    await _render_editperm_picker(query, context)


async def cb_editperm_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    context.user_data["editperm_draft"] = set()
    await _render_editperm_picker(query, context)


async def cb_editperm_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return
    target_id = context.user_data.pop("editperm_target_id", None)
    draft = context.user_data.pop("editperm_draft", set())
    if target_id is None:
        await query.edit_message_text(to_small_caps("this expired — please try again."))
        return
    BOT_DATA.setdefault("admin_permissions", {})[str(target_id)] = sorted(draft)
    save_data()
    await query.edit_message_text("✅ " + to_small_caps(f"access updated for {target_id}.") + "\n\n" + _perm_summary_text(draft))
    await log_event(context, f"🔧 Admin access updated: {target_id} -> {len(draft)}/{len(ADMIN_PERMISSION_KEYS)} section(s) (by {update.effective_user.id})")


async def cb_editperm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("editperm_target_id", None)
    context.user_data.pop("editperm_draft", None)
    await query.edit_message_text(to_small_caps("cancelled — no changes made."))


async def cb_help_update_backup_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_own = is_owner(update.effective_user.id)
    text = (
        "<blockquote expandable>"
        "<u>📦 " + to_small_caps("update backup — how it works") + "</u>\n\n"
        + to_small_caps("normally, pushing a new bot.py to github wipes the live data — every setting, every menu edit, every saved user — because most free hosts start from a clean, empty disk on every deploy.") + "\n\n"
        "<u>➤ " + to_small_caps("step 1 — export") + "</u>\n"
        + to_small_caps("before you push a code update, run 📦 update backup from the admin panel (or /updatebackup). the bot sends you 2 files:") + "\n"
        "  • <code>" + SEED_SETTINGS_FILE + "</code> — " + to_small_caps("every setting, menu, admin, group, ticket etc. (no users)") + "\n"
        "  • <code>" + SEED_USERS_FILE + "</code> — " + to_small_caps("the full user list") + "\n\n"
        "<u>➤ " + to_small_caps("step 2 — commit") + "</u>\n"
        + to_small_caps("add both files into your github repo, in the same folder as bot.py, using those exact names, then push your updated code.") + "\n\n"
        "<u>➤ " + to_small_caps("step 3 — auto-restore") + "</u>\n"
        + to_small_caps("on the next startup, if the host has no existing data (fresh/wiped disk), the bot automatically reads both files and restores everything by itself — no restore command, no manual upload.") + "\n\n"
        "<u>➤ " + to_small_caps("safety") + "</u>\n"
        + to_small_caps("if the bot already has live data (a host with persistent storage), the seed files are ignored — your current live data is never overwritten automatically.")
        + ("\n\n🔒 " + to_small_caps("only the owner can actually run the export (📦 update backup / /updatebackup) — this help screen is visible to every admin.") if not is_own else "")
        + "</blockquote>"
    )
    kb = InlineKeyboardMarkup(
        [[styled_button("🔙 Back", callback_data="nav:help_admin")]]
        if not is_own else
        [[styled_button("📦 Run Update Backup Now", callback_data="adm_update_backup_run")],
         [styled_button("🔙 Back", callback_data="nav:help_admin")]]
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def cb_adm_restore_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("🔒 " + to_small_caps("only the owner can restore a backup."), show_alert=True)
        return
    await query.message.reply_text(
        to_small_caps("📥 restore backup") + "\n\n"
        + to_small_caps("send me the .json or .json.enc backup file directly in this dm (the one exported via /database). ")
        + to_small_caps("an automatic backup of the current data will be taken first, then a confirmation screen will be shown.") + "\n\n"
        + (to_small_caps("🔒 encrypted (.json.enc) backups only restore on this same bot instance, unless you copied backup.key over first.") if BACKUP_ENCRYPTION_AVAILABLE else "")
    )


# ---- Danger Zone --------------------------------------------------------------

async def _render_adm_danger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kb = InlineKeyboardMarkup(
        [
            [styled_button("🧹 Clear Broadcast Log", callback_data="adm_clear_bclog")],
            [styled_button("🧹 Delete All Bot Messages In This Chat", callback_data="adm_delete_chat_msgs")],
            [styled_button("🔄 Reset Menus to Default", callback_data="adm_reset_menus_confirm")],
            [styled_button("❌ Reset ALL Bot Data", callback_data="adm_reset_confirm")],
            back_row(),
            home_row(),
        ]
    )
    await query.edit_message_text("🛑 Danger Zone\n(Ye actions destructive hain.)", reply_markup=kb)


# ---- Premium / UPI / Developer / Support / Tickets --

def _build_adm_premium_view():
    s = BOT_DATA["settings"]
    plans = s.get("premium_plans", [])
    premium_count = sum(1 for uid in BOT_DATA["users"] if is_premium_active(uid))
    lines = [
        f"💎 Premium\n\nMaster switch: {'✅ ON' if s.get('premium_enabled') else '❌ OFF'}",
        f"Daily free limit: {s.get('daily_limit', 20)}",
        f"👥 Active premium users: {premium_count}",
        "",
    ]
    # Main controls stay at the top; every ➕ Add action is grouped at the
    # bottom so the management flow is cleaner on mobile.
    kb_rows = [
        [styled_button(toggle_label("🔀 Master Switch", s.get('premium_enabled')),
                        callback_data="stgl:premium_enabled:adm_premium")],
        [styled_button("✏️ Set Daily Limit", callback_data="adm_set_dailylimit")],
        [styled_button("👥 See Premium Users", callback_data="adm_premium_users")],
        [styled_button("💳 UPI Settings", callback_data="adm_upi")],
    ]
    if not plans:
        lines.append("No plans yet — tap ➕ Add Plan below.")
    else:
        lines.append("Your plans (tap a plan's row buttons to toggle/delete):")
        for p in plans:
            state = "🟢 ON" if p.get("enabled") else "🔴 OFF"
            price_bits = []
            if p.get("price_inr"):
                price_bits.append(f"₹{p['price_inr']}")
            if p.get("price_stars"):
                price_bits.append(f"{p['price_stars']}⭐")
            price_str = " / ".join(price_bits) if price_bits else "(no price set)"
            lines.append(f"• {p['name']} — {price_str} — {p.get('days', 30)}d — {state}")
            kb_rows.append([
                styled_button(f"{'🔴 Turn Off' if p.get('enabled') else '🟢 Turn On'} · {p['name']}",
                              callback_data=f"adm_plan_toggle:{p['id']}",
                              style="success" if p.get("enabled") else "danger"),
                styled_button("🗑", callback_data=f"adm_plan_del:{p['id']}", style="danger"),
            ])
    # Keep all Add actions together at the bottom.
    kb_rows.append([styled_button("➕ Add Premium User (By ID)", callback_data="adm_premium_grant")])
    kb_rows.append([styled_button("➕ Add Plan", callback_data="adm_plan_add")])
    kb_rows.append(back_row())
    kb_rows.append(home_row())
    text = "\n".join(lines) + (
        "\n\nWhen master switch is ON and a plan is toggled ON, that plan shows up "
        "immediately to every user in the 🎁 gift/upgrade menu."
    )
    return text, InlineKeyboardMarkup(kb_rows)


async def _render_adm_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_premium_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_premium(update, context)


# ---- See Premium Users / manually grant premium by user ID --------------

async def cb_adm_premium_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👥 See Premium Users — lists every user currently marked premium,
    with days remaining (or 'no expiry' for lifetime grants)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = []
    now = datetime.utcnow()
    for uid, u in BOT_DATA["users"].items():
        if not is_premium_active(uid):
            continue
        name = u.get("name") or f"User {uid}"
        exp = u.get("plan_expires_at")
        if exp:
            try:
                remaining = (datetime.fromisoformat(exp) - now).days
                when = f"{remaining}d left" if remaining >= 0 else "expiring"
            except Exception:
                when = "unknown expiry"
        else:
            when = "no expiry"
        rows.append(f"• {name} (`{uid}`) — {when}")
    if rows:
        text = "👥 " + to_small_caps("premium users") + f" ({len(rows)})\n\n" + "\n".join(rows[:60])
        if len(rows) > 60:
            text += f"\n… and {len(rows) - 60} more"
    else:
        text = "👥 " + to_small_caps("no premium users right now.")
    kb = InlineKeyboardMarkup([back_row("adm_premium")])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def cb_adm_premium_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """➕ Add Premium User (by ID) — admin types a Telegram user ID (and
    optionally how many days) and premium unlocks automatically, no
    payment/plan flow needed. Same manual-override tool admins expect for
    comps, testers, or fixing a missed payment."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    remember_panel_message(context, query, "premium")
    context.user_data["awaiting"] = "premium_grant_userid"
    await query.message.reply_text(
        "👤 Send the user's Telegram ID to unlock Premium for.\n"
        "Optionally add days after a space (default 30) — e.g. `123456789 90`.",
        parse_mode="Markdown",
    )


# ---- Premium plan CRUD (add / toggle / delete) ---------------------------------

async def cb_adm_plan_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "premium")
    context.user_data["new_plan"] = {}
    context.user_data["awaiting"] = "plan_step_name"
    await query.message.reply_text(
        to_small_caps("➕ new plan — step 1/4") + "\n" + to_small_caps("send the plan name (e.g. 'monthly', 'weekly pro').")
    )


async def cb_adm_plan_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":", 1)[1]
    for p in BOT_DATA["settings"].get("premium_plans", []):
        if p["id"] == pid:
            p["enabled"] = not p.get("enabled")
            save_data()
            await log_event(context, f"💎 Plan '{p['name']}' toggled {'✅ ON' if p['enabled'] else '❌ OFF'} by {update.effective_user.id}")
            break
    await _render_adm_premium(update, context)


async def cb_adm_plan_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split(":", 1)[1]
    plans = BOT_DATA["settings"].get("premium_plans", [])
    BOT_DATA["settings"]["premium_plans"] = [p for p in plans if p["id"] != pid]
    save_data()
    await _render_adm_premium(update, context)


async def cb_adm_set_dailylimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "premium")
    context.user_data["awaiting"] = "daily_limit"
    await query.message.reply_text(to_small_caps("send the new daily free-download limit (a number)."))


def _build_adm_upi_view():
    upi = BOT_DATA["settings"].get("upi_id")
    kb = InlineKeyboardMarkup([
        [styled_button("✏️ Set UPI ID", callback_data="adm_upi_set")],
        [styled_button("❌ Clear", callback_data="adm_upi_clear")],
        back_row("adm_premium"), home_row(),
    ])
    return f"💳 UPI Settings\n\nCurrent: {upi or '(not set)'}", kb


async def _render_adm_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_upi_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_upi(update, context)


async def cb_adm_upi_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "upi")
    context.user_data["awaiting"] = "upi_id"
    await query.message.reply_text(to_small_caps("send the upi id (e.g. name@bank)."))


async def cb_adm_upi_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    BOT_DATA["settings"]["upi_id"] = None
    save_data()
    await query.edit_message_text("✅ UPI ID cleared.", reply_markup=InlineKeyboardMarkup([back_row()]))


def _build_adm_devsettings_view():
    s = BOT_DATA["settings"]
    dev_id = s.get("developer_id")
    dev_link = s.get("developer_link")
    current = f"@{dev_link.rstrip('/').rsplit('/', 1)[-1]}" if dev_link else (str(dev_id) if dev_id else "(not set)")
    text = (
        "👨‍💻 Developer Settings\n\n"
        f"Current: {current}\n\n"
        "Set by numeric user ID or by @username — either works."
    )
    kb = InlineKeyboardMarkup([
        [styled_button("✏️ Set Developer (ID or @username)", callback_data="adm_dev_id")],
        [styled_button("🔗 Set Custom Link (advanced)", callback_data="adm_dev_link")],
        back_row(), home_row(),
    ])
    return text, kb


async def _render_adm_devsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_devsettings_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_devsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_devsettings(update, context)


async def cb_adm_dev_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "devsettings")
    context.user_data["awaiting"] = "developer_id"
    await query.message.reply_text(
        to_small_caps("send the developer's numeric user id, OR their @username — either works.")
    )


async def cb_adm_dev_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "devsettings")
    context.user_data["awaiting"] = "developer_link"
    await query.message.reply_text(to_small_caps("send the t.me/username link (or type 'clear' to remove it)."))


def _build_adm_support_settings_view():
    gid = BOT_DATA["settings"].get("admin_group_id")
    kb = InlineKeyboardMarkup([
        [styled_button("✏️ Set Ticket Group", callback_data="adm_group_set")],
        back_row(), home_row(),
    ])
    return f"🎧 Support Settings\n\nTicket group: {gid or '(not set — falls back to admin DMs)'}", kb


async def _render_adm_support_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text, kb = _build_adm_support_settings_view()
    await query.edit_message_text(text, reply_markup=kb)


async def cb_adm_support_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_support_settings(update, context)


async def cb_adm_group_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    remember_panel_message(context, query, "support_settings")
    context.user_data["awaiting"] = "admin_group_id"
    await query.message.reply_text(
        "Forward any message from the ticket group here (bot must be admin there), "
        "or type its numeric ID (-100...)."
    )


async def _render_adm_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tickets = list(BOT_DATA["tickets"].values())
    open_n = sum(1 for t in tickets if t["status"] == "open")
    lines = [f"🎫 Tickets — {open_n} open / {len(tickets)} total\n"]
    for t in tickets[-15:]:
        icon = "🟢" if t["status"] == "open" else "🔴"
        lines.append(f"#{t['id']} — user {t['user_id']} — {icon} {t['status']}")
    kb = InlineKeyboardMarkup([back_row(), home_row()])
    await query.edit_message_text("\n".join(lines), reply_markup=kb)


async def cb_adm_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_tickets(update, context)


async def cb_adm_danger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _render_adm_danger(update, context)


async def cb_adm_delete_chat_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """#5 — wipes only the chat the admin runs this from (Telegram allows
    deleting messages up to 48h old; older ones fail silently)."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    ids = BOT_DATA.get("sent_messages", {}).pop(str(chat_id), [])
    save_data()
    deleted = 0
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            deleted += 1
        except Exception:
            pass
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(chat_id, f"✅ Deleted {deleted}/{len(ids)} tracked bot messages in this chat.")


async def cb_adm_clear_bclog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    BOT_DATA["broadcast_log"] = []
    save_data()
    await query.message.reply_text(to_small_caps("✅ broadcast log cleared."))


async def cb_adm_reset_menus_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup(
        [[styled_button(to_small_caps("⚠️ yes, reset"), callback_data="adm_reset_menus_do"),
          styled_button("Cancel", callback_data="adm_danger")]]
    )
    await query.edit_message_text("⚠️ Sab menus (text/image/buttons) default pe reset ho jayenge. Pakka?", reply_markup=kb)


async def cb_adm_reset_menus_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    make_backup_snapshot(reason="pre_menu_reset")
    BOT_DATA["menus"] = json.loads(json.dumps(DEFAULT_MENUS))
    save_data()
    await query.edit_message_text("✅ Menus default pe reset ho gaye.")


async def cb_adm_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup(
        [[styled_button(to_small_caps("⚠️ yes, reset everything"), callback_data="adm_reset_do"),
          styled_button("Cancel", callback_data="adm_danger")]]
    )
    await query.edit_message_text(
        to_small_caps("⚠️ are you sure? this will delete ALL bot data — users, settings, menus, everything.") + "\n" + to_small_caps("an auto-backup will be taken first."),
        reply_markup=kb,
    )


RESET_ALL_PASSCODE = "03"


async def cb_adm_reset_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A destructive, irreversible action gets one extra layer beyond the
    button confirm — a short passcode the admin has to type, so a stray or
    mis-tapped click can never wipe the bot on its own."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "reset_all_passcode"
    await query.message.reply_text(
        "🔐 " + to_small_caps("last step — send the reset passcode to confirm.")
    )


async def _do_reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    make_backup_snapshot(reason="pre_reset")
    _replace_bot_data(json.loads(json.dumps(DEFAULT_DATA)))
    save_data()
    await update.message.reply_text(to_small_caps("✅ reset complete. the previous data is safely stored in a backup."))


# ----------------------------------------------------------------------------



__all__ = [_n for _n in dir() if not _n.startswith("__")]
