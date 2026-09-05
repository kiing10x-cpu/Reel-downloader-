from admin_panel import *


# Text-input flows triggered from admin panel buttons
# ----------------------------------------------------------------------------

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str):
    text = (update.message.text or "").strip()
    # Every admin config-input message (plan steps, URLs, IDs, menu text,
    # etc.) is auto-deleted right after being read, same cleanup pattern
    # /start and /admin use — only the refreshed panel view stays in chat.
    await delete_incoming(update)

    if awaiting == "maintenance_set_msg":
        context.user_data.pop("awaiting", None)
        menu = BOT_DATA["menus"]["maintenance"]
        menu["text"] = text
        menu["updated_by"] = update.effective_user.id
        menu["updated_at"] = datetime.utcnow().isoformat()
        save_data()
        # Confirmation + the combined status/toggle screen right below it,
        # so the admin can flip maintenance on/off immediately without
        # hunting for a separate button.
        is_on = bool(BOT_DATA["settings"].get("maintenance"))
        await update.message.reply_text(
            "✅ " + to_small_caps("maintenance message updated.") + "\n\n"
            + to_small_caps("preview") + ":\n" + text,
            reply_markup=_maintenance_kb(is_on),
        )

    elif awaiting.startswith("menu_text:"):
        menu_id = awaiting.split(":", 1)[1]
        context.user_data.pop("awaiting", None)
        menu = BOT_DATA["menus"][menu_id]
        if menu.get("image_file_id") and len(text) > 1024:
            await update.message.reply_text(
                to_small_caps(f"⚠️ this menu has an image, so the caption limit is 1024 characters — your text is {len(text)}. ")
                + to_small_caps("please shorten it, or remove the image first.")
            )
            return
        menu["text"] = text
        menu["updated_by"] = update.effective_user.id
        menu["updated_at"] = datetime.utcnow().isoformat()
        save_data()
        await update.message.reply_text(to_small_caps(f"✅ '{menu_id}' text updated."))

    elif awaiting.startswith("menu_style_source:"):
        menu_id = awaiting.split(":", 1)[1]
        context.user_data.pop("awaiting", None)
        context.user_data["style_source_text"] = text
        context.user_data["style_target"] = f"menu_text:{menu_id}"
        await send_style_preview(context, update.effective_chat.id, text)

    elif awaiting.startswith("menu_autodel:"):
        menu_id = awaiting.split(":", 1)[1]
        context.user_data.pop("awaiting", None)
        if text.lower() == "global":
            BOT_DATA["menus"][menu_id]["auto_delete_seconds"] = None
        elif text.isdigit():
            BOT_DATA["menus"][menu_id]["auto_delete_seconds"] = int(text)
        else:
            await update.message.reply_text(to_small_caps("send a number, or type 'global'."))
            context.user_data["awaiting"] = awaiting
            return
        save_data()
        await update.message.reply_text(f"✅ Auto-delete override set for '{menu_id}'.")

    elif awaiting.startswith("menu_trans_text:"):
        _, menu_id, code = awaiting.split(":", 2)
        context.user_data.pop("awaiting", None)
        menu = BOT_DATA["menus"][menu_id]
        menu.setdefault("translations", {})
        menu["translations"][code] = {"text": text, "buttons": None}
        save_data()
        await update.message.reply_text(to_small_caps(f"✅ {LANG_NAMES.get(code, code)} translation for '{menu_id}' saved."))

    elif awaiting == "global_autodelete":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a number only."))
            context.user_data["awaiting"] = awaiting
            return
        BOT_DATA["settings"]["global_auto_delete_seconds"] = int(text)
        save_data()
        await update.message.reply_text(f"✅ Global auto-delete set to {text}s.")

    elif awaiting == "autoreply_key":
        context.user_data["autoreply_key_draft"] = text.lower()
        context.user_data["awaiting"] = "autoreply_value"
        await update.message.reply_text(to_small_caps("now send the reply text."))

    elif awaiting == "autoreply_value":
        context.user_data.pop("awaiting", None)
        key = context.user_data.pop("autoreply_key_draft", None)
        if key:
            BOT_DATA["settings"]["auto_replies"][key] = text
            save_data()
            await update.message.reply_text(f"✅ Auto-reply set for '{key}'.")

    elif awaiting == "autoreply_delkey":
        context.user_data.pop("awaiting", None)
        BOT_DATA["settings"]["auto_replies"].pop(text.lower(), None)
        save_data()
        await update.message.reply_text(to_small_caps("✅ removed, if that keyword existed."))

    elif awaiting == "add_admin_id":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid numeric user id."))
            return
        new_id = int(text)
        if new_id in BOT_DATA["admins"]:
            await update.message.reply_text(to_small_caps(f"{new_id} is already an admin — use ✏️ edit access instead."))
            return
        context.user_data["newadmin_id_draft"] = new_id
        context.user_data["newadmin_perms_draft"] = set()
        text_out = (
            "➕ " + to_small_caps(f"choose access for admin {new_id}") + "\n\n"
            + to_small_caps("tap a section to toggle it, then save. only what you tick here is what they'll be able to open.") + "\n\n"
            + _perm_summary_text(set())
        )
        await update.message.reply_text(
            text_out, reply_markup=_perm_picker_keyboard(set(), "newadmin_confirm", "newadmin_cancel", "newadmin_perm")
        )

    elif awaiting == "remove_admin_id":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid numeric user id."))
            return
        rem_id = int(text)
        if rem_id in BOT_DATA["admins"]:
            BOT_DATA["admins"].remove(rem_id)
            BOT_DATA.get("admin_permissions", {}).pop(str(rem_id), None)
            save_data()
        await update.message.reply_text(f"✅ {rem_id} admin list se hata diya.")
        await log_event(context, f"👤 Admin removed: {rem_id} (by {update.effective_user.id})")

    elif awaiting == "owner_contact_label":
        context.user_data["owner_contact_label_draft"] = text
        context.user_data["awaiting"] = "owner_contact_id"
        await update.message.reply_text(to_small_caps("now send the user id or @username the button should point to."))

    elif awaiting == "owner_contact_id":
        context.user_data.pop("awaiting", None)
        label = context.user_data.pop("owner_contact_label_draft", "👑 Developer")
        BOT_DATA["settings"]["owner_display_label"] = label
        BOT_DATA["settings"]["owner_display_user_id"] = text.lstrip("@")
        save_data()
        refreshed = await refresh_panel_after_save(context, "owner_contact", _build_adm_owner_contact_view)
        await update.message.reply_text(f"✅ Owner/Developer contact set: {label} → {text}" + ("" if refreshed else "\n(panel screen above may be stale — reopen it to confirm)"))

    elif awaiting == "force_join_channel":
        context.user_data.pop("awaiting", None)
        raw = text.strip()
        if not raw:
            await update.message.reply_text("❌ Please send a valid channel username, ID, or t.me link.")
            return
        target = {"chat_id": None, "link": None}
        if raw.startswith("http://") or raw.startswith("https://"):
            target["link"] = raw
            # Public t.me usernames can also be checked directly.
            m = re.match(r"https?://(?:t\.me|telegram\.me)/([^/?#]+)", raw)
            if m and not m.group(1).startswith("+") and m.group(1) not in ("joinchat",):
                target["chat_id"] = "@" + m.group(1).lstrip("@")
        else:
            channel = raw
            if not channel.lstrip("-").isdigit() and not channel.startswith("@"):
                channel = "@" + channel
            target["chat_id"] = normalize_channel_id(channel)
        targets = _force_join_targets()
        key = str(target.get("chat_id") or target.get("link"))
        if any(str(x.get("chat_id") or x.get("link")) == key for x in targets):
            await update.message.reply_text("⚠️ That force-join target is already added.")
            return
        targets.append(target)
        BOT_DATA["settings"]["force_join_channels"] = targets
        BOT_DATA["settings"]["force_join_channel"] = targets[0].get("chat_id") if targets else None
        save_data()
        refreshed = await refresh_panel_after_save(context, "force_join", lambda: _build_adm_force_join_view())
        confirm_msg = await update.message.reply_text(
            "✅ " + to_title_small_caps(f"Added Force-Join Target: {raw}") + "\n\n"
            + "<blockquote>"
            + to_title_small_caps(
                "Add Another From The Panel If Needed. For Private Link-Only Channels, "
                "Membership Can Be Confirmed Through Join-Request Updates; For Normal "
                "Membership Checks, Configure The Channel ID/@Username And Make The Bot Admin."
            )
            + "</blockquote>"
            + ("" if refreshed else "\n" + to_small_caps("(reopen the panel to confirm.)")),
            parse_mode="HTML",
        )
        _track_ephemeral(context, confirm_msg)

    elif awaiting == "share_url":
        context.user_data.pop("awaiting", None)
        url = text.strip()
        if url.lower() in ("/cancel", "cancel", "-"):
            await update.message.reply_text("Cancelled — share URL left unchanged.")
            return
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
            url = "https://t.me/" + url.lstrip("@")
        BOT_DATA["settings"]["share_url"] = url
        save_data()
        refreshed = await refresh_panel_after_save(context, "share", _build_adm_share_view)
        await update.message.reply_text(f"✅ Share URL set: {url}" + ("" if refreshed else "\n(reopen the share panel to confirm)"))

    elif awaiting == "logger_channel_id":
        context.user_data.pop("awaiting", None)
        chat_id = None
        forward_origin = getattr(update.message, "forward_origin", None)
        if forward_origin is not None:
            chat_obj = getattr(forward_origin, "chat", None)
            if chat_obj is not None:
                chat_id = chat_obj.id
        if chat_id is None:
            legacy_fwd = getattr(update.message, "forward_from_chat", None)
            if legacy_fwd is not None:
                chat_id = legacy_fwd.id
        if chat_id is None and text.lstrip("-").isdigit():
            chat_id = int(text)
        if chat_id is None:
            await update.message.reply_text(
                to_small_caps("channel not detected. either forward a message from the channel, ")
                + to_small_caps("or type the numeric id (-100...).")
            )
            context.user_data["awaiting"] = "logger_channel_id"
            return
        BOT_DATA["settings"]["logger_channel_id"] = chat_id
        BOT_DATA["settings"]["logger_enabled"] = True
        save_data()
        refreshed = await refresh_panel_after_save(context, "logger_channel", _build_adm_logger_channel_view)
        await update.message.reply_text(f"✅ Logger channel set to {chat_id} and enabled." + ("" if refreshed else "\n(reopen the logger panel to confirm)"))

    elif awaiting == "activity_channel_id":
        context.user_data.pop("awaiting", None)
        chat_id = None
        forward_origin = getattr(update.message, "forward_origin", None)
        if forward_origin is not None:
            chat_obj = getattr(forward_origin, "chat", None)
            if chat_obj is not None:
                chat_id = chat_obj.id
        if chat_id is None:
            legacy_fwd = getattr(update.message, "forward_from_chat", None)
            if legacy_fwd is not None:
                chat_id = legacy_fwd.id
        if chat_id is None and text.lstrip("-").isdigit():
            chat_id = int(text)
        if chat_id is None:
            await update.message.reply_text(
                to_small_caps("channel not detected. either forward a message from the channel, ")
                + to_small_caps("or type the numeric id (-100...).")
            )
            context.user_data["awaiting"] = "activity_channel_id"
            return
        BOT_DATA["settings"]["activity_channel_id"] = chat_id
        BOT_DATA["settings"]["activity_channel_enabled"] = True
        save_data()
        refreshed = await refresh_panel_after_save(context, "activity_channel", _build_adm_activity_channel_view)
        await update.message.reply_text(f"✅ Activity channel set to {chat_id} and enabled." + ("" if refreshed else "\n(reopen the activity panel to confirm)"))

    elif awaiting == "daily_limit":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid number."))
            return
        BOT_DATA["settings"]["daily_limit"] = int(text)
        save_data()
        refreshed = await refresh_panel_after_save(context, "premium", _build_adm_premium_view)
        await update.message.reply_text(f"✅ Daily limit set to {text}." + ("" if refreshed else "\n(reopen the premium panel to confirm)"))

    elif awaiting == "upi_id":
        context.user_data.pop("awaiting", None)
        BOT_DATA["settings"]["upi_id"] = text
        save_data()
        refreshed = await refresh_panel_after_save(context, "upi", _build_adm_upi_view)
        await update.message.reply_text(f"✅ UPI ID set: {text}" + ("" if refreshed else "\n(reopen the UPI panel to confirm)"))

    elif awaiting == "mongo_uri":
        context.user_data.pop("awaiting", None)
        uri = text.strip()
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            await update.message.reply_text(
                "❌ " + to_small_caps("that doesn't look like a mongodb connection string — it should start with mongodb:// or mongodb+srv://. nothing was changed.")
            )
        else:
            status_msg = await update.message.reply_text("🔎 " + to_small_caps("testing connection..."))
            ok, msg = await asyncio.get_running_loop().run_in_executor(None, set_mongo_uri, uri)
            if ok:
                await log_event(context, "🗄 MongoDB connected by admin " + str(update.effective_user.id) + ".")
                await status_msg.edit_text("✅ " + to_small_caps(msg))
            else:
                await status_msg.edit_text("❌ " + to_small_caps("connection failed") + f":\n{html.escape(msg[:300])}")
            await refresh_panel_after_save(context, "mongo_plugin", _build_mongo_plugin_view, parse_mode="HTML")

    elif awaiting == "developer_id":
        context.user_data.pop("awaiting", None)
        raw = text.strip()
        # Accept either a numeric user id OR an @username in the same
        # prompt, instead of forcing the admin into a separate "link
        # override" flow just to use a username.
        if raw.lstrip("@").isdigit() and not raw.startswith("@"):
            BOT_DATA["settings"]["developer_id"] = int(raw)
            BOT_DATA["settings"]["developer_link"] = None
            save_data()
            note = ""
            try:
                chat = await context.bot.get_chat(int(raw))
                if not chat.username:
                    note = "\n⚠️ " + to_small_caps("this account has no @username — the button may not always open reliably.")
            except Exception:
                note = "\n⚠️ " + to_small_caps("the bot hasn't seen this id yet (the developer has never messaged the bot) — the button won't open reliably until they do, or until you set an @username instead.")
            shown = raw
        else:
            uname = raw.lstrip("@")
            BOT_DATA["settings"]["developer_link"] = f"https://t.me/{uname}"
            BOT_DATA["settings"]["developer_id"] = None
            save_data()
            note = ""
            shown = f"@{uname}"
        refreshed = await refresh_panel_after_save(context, "devsettings", _build_adm_devsettings_view)
        await update.message.reply_text(f"✅ Developer contact set: {shown}{note}" + ("" if refreshed else "\n(reopen the developer panel to confirm)"))

    elif awaiting == "developer_link":
        context.user_data.pop("awaiting", None)
        BOT_DATA["settings"]["developer_link"] = None if text.lower() == "clear" else text
        save_data()
        refreshed = await refresh_panel_after_save(context, "devsettings", _build_adm_devsettings_view)
        await update.message.reply_text("✅ Developer link updated." + ("" if refreshed else "\n(reopen the developer panel to confirm)"))

    elif awaiting == "admin_group_id":
        context.user_data.pop("awaiting", None)
        chat_id = None
        forward_origin = getattr(update.message, "forward_origin", None)
        if forward_origin is not None:
            chat_obj = getattr(forward_origin, "chat", None)
            if chat_obj is not None:
                chat_id = chat_obj.id
        if chat_id is None:
            legacy_fwd = getattr(update.message, "forward_from_chat", None)
            if legacy_fwd is not None:
                chat_id = legacy_fwd.id
        if chat_id is None and text.lstrip("-").isdigit():
            chat_id = int(text)
        if chat_id is None:
            await update.message.reply_text(to_small_caps("group not detected. forward a message from it, or type the numeric id."))
            context.user_data["awaiting"] = "admin_group_id"
            return
        BOT_DATA["settings"]["admin_group_id"] = chat_id
        save_data()
        refreshed = await refresh_panel_after_save(context, "support_settings", _build_adm_support_settings_view)
        await update.message.reply_text(f"✅ Ticket group set to {chat_id}." + ("" if refreshed else "\n(reopen the support panel to confirm)"))

    elif awaiting == "premium_grant_userid":
        context.user_data.pop("awaiting", None)
        parts = text.strip().split()
        if not parts or not parts[0].isdigit():
            await update.message.reply_text(to_small_caps("⚠️ please send a valid numeric user id (e.g. 123456789 or 123456789 90)."))
            context.user_data["awaiting"] = "premium_grant_userid"
            return
        target_uid = parts[0]
        days = 30
        if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) > 0:
            days = int(parts[1])
        grant_premium(target_uid, days)
        refreshed = await refresh_panel_after_save(context, "premium", _build_adm_premium_view)
        await update.message.reply_text(
            f"✅ Premium unlocked for user {target_uid} — {days} days."
            + ("" if refreshed else "\n(reopen the premium panel to confirm)")
        )
        try:
            await context.bot.send_message(
                int(target_uid),
                "🎉 " + to_small_caps("premium has been unlocked for your account!") + f"\n⏳ {to_small_caps('valid for')} {days} {to_small_caps('days')}",
            )
        except Exception:
            pass
        await log_event(context, f"💎 Premium manually granted to {target_uid} ({days}d) by admin {update.effective_user.id}")

    elif awaiting == "plan_step_name":
        name = text.strip()
        if not name:
            await update.message.reply_text(to_small_caps("a blank name won't work. please send the plan's name."))
            return
        context.user_data.setdefault("new_plan", {})["name"] = name
        context.user_data["awaiting"] = "plan_step_days"
        await update.message.reply_text("Step 2/4 — Plan kitne din chalega? (e.g. 30)")

    elif awaiting == "plan_step_days":
        if not text.strip().isdigit() or int(text.strip()) <= 0:
            await update.message.reply_text(to_small_caps("please send a valid number (e.g. 30)."))
            return
        context.user_data["new_plan"]["days"] = int(text.strip())
        context.user_data["awaiting"] = "plan_step_inr"
        await update.message.reply_text(
            to_small_caps("step 3/4 — send the ₹ (inr) price for upi payment.") + " "
            + to_small_caps("if this plan isn't sold via upi, send '0'.")
        )

    elif awaiting == "plan_step_inr":
        cleaned = text.strip().replace("₹", "")
        if not cleaned.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid number (0 is fine if you don't want a upi price)."))
            return
        context.user_data["new_plan"]["price_inr"] = int(cleaned)
        context.user_data["awaiting"] = "plan_step_stars"
        await update.message.reply_text(
            to_small_caps("step 4/4 — send the ⭐ telegram stars price.") + " "
            + to_small_caps("if this plan isn't sold via stars, send '0'.")
        )

    elif awaiting == "plan_step_stars":
        context.user_data.pop("awaiting", None)
        cleaned = text.strip()
        if not cleaned.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid number (0 is fine)."))
            context.user_data["awaiting"] = "plan_step_stars"
            return
        draft = context.user_data.pop("new_plan", {})
        draft["price_stars"] = int(cleaned)
        if not draft.get("price_inr") and not draft.get("price_stars"):
            await update.message.reply_text(
                to_small_caps("⚠️ plan cancelled — at least one price (₹ or ⭐) must be set.") + " "
                + to_small_caps("please try again via ➕ add plan.")
            )
        else:
            pid = str(BOT_DATA.get("next_plan_id", 1))
            BOT_DATA["next_plan_id"] = BOT_DATA.get("next_plan_id", 1) + 1
            plan = {
                "id": pid,
                "name": draft.get("name", "Plan"),
                "days": draft.get("days", 30),
                "price_inr": draft.get("price_inr", 0),
                "price_stars": draft.get("price_stars", 0),
                "enabled": True,
            }
            BOT_DATA["settings"].setdefault("premium_plans", []).append(plan)
            save_data()
            await log_event(context, f"💎 New plan added: {plan['name']} by {update.effective_user.id}")
            price_bits = []
            if plan["price_inr"]:
                price_bits.append(f"₹{plan['price_inr']}")
            if plan["price_stars"]:
                price_bits.append(f"{plan['price_stars']}⭐")
            refreshed = await refresh_panel_after_save(context, "premium", _build_adm_premium_view)
            await update.message.reply_text(
                f"✅ Plan added: {plan['name']} — {' / '.join(price_bits)} — {plan['days']}d — turned ON.\n"
                "It's now visible to users in 📊 My Usage (above the Share button)."
                + ("" if refreshed else "\n(reopen the premium panel to confirm)")
            )

    elif awaiting == "reset_all_passcode":
        context.user_data.pop("awaiting", None)
        if text.strip() != RESET_ALL_PASSCODE:
            await update.message.reply_text(
                "❌ " + to_small_caps("wrong passcode — reset cancelled. nothing was touched.")
            )
            return
        await _do_reset_all(update, context)

    elif awaiting == "adm_ban_unban_userid":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid numeric user id."))
            return
        uid_int = int(text)
        if uid_int in BOT_DATA["blocked"]:
            BOT_DATA["blocked"].remove(uid_int)
            save_data()
            await update.message.reply_text(f"✅ User {uid_int} unbanned.")
            await log_event(context, f"✅ Admin unbanned user {uid_int} (via panel)")
        else:
            BOT_DATA["blocked"].append(uid_int)
            save_data()
            await update.message.reply_text(f"🚫 User {uid_int} banned.")
            await log_event(context, f"🚫 Admin banned user {uid_int} (via panel)")

    elif awaiting == "check_user_id":
        context.user_data.pop("awaiting", None)
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid numeric user id."))
            return
        card = await build_user_details_card(context, int(text))
        if card is None:
            await update.message.reply_text(to_small_caps("no record found for this user id."))
            return
        await update.message.reply_text(card, parse_mode="HTML")

    elif awaiting == "message_user_id":
        if not text.isdigit():
            await update.message.reply_text(to_small_caps("please send a valid numeric user id."))
            return
        context.user_data["awaiting"] = "message_user_body"
        context.user_data["message_target"] = int(text)
        await update.message.reply_text(to_small_caps("now send the message you want to deliver to this user."))

    elif awaiting == "message_user_body":
        context.user_data.pop("awaiting", None)
        target = context.user_data.pop("message_target", None)
        if target is None:
            await update.message.reply_text(to_small_caps("something went wrong — please try again."))
            return
        try:
            await context.bot.send_message(chat_id=target, text=text)
            await update.message.reply_text(to_small_caps("✅ message delivered."))
        except Exception as e:  # noqa: BLE001
            log.exception("Admin message delivery failed for target %s", target)
            log_error("message_user", f"target={target} err={e}")
            await update.message.reply_text(USER_ERR_GENERIC)

    elif awaiting == "broadcast_content":
        context.user_data.pop("awaiting", None)
        await do_broadcast(update, context)

    elif awaiting == "btn_step_label":
        flow = context.user_data.get("btn_flow")
        if not flow:
            context.user_data.pop("awaiting", None)
            return
        is_edit = flow.get("edit_idx") is not None
        if not (is_edit and text.strip() == "-"):
            label = text
            if BOT_DATA["settings"].get("small_caps_buttons_default", True):
                label = to_small_caps(label)
            flow["data"]["label"] = label
        context.user_data["awaiting"] = None
        rows = [
            [styled_button("📄 Open Menu", callback_data="btntype:menu")],
            [styled_button("🔗 URL Link", callback_data="btntype:url")],
            [styled_button("⚙️ Run Action", callback_data="btntype:callback")],
            [styled_button("🔀 Toggle Setting", callback_data="btntype:toggle")],
        ]
        if is_edit:
            cur_type = flow["data"].get("type", "?")
            rows.append([styled_button(f"↩️ Keep Current Type ({cur_type})", callback_data="btntype:keep")])
        await update.message.reply_text(to_small_caps("what type of button is this?"), reply_markup=InlineKeyboardMarkup(rows))

    elif awaiting == "btn_step_value":
        flow = context.user_data.get("btn_flow")
        if not flow:
            context.user_data.pop("awaiting", None)
            return
        is_edit = flow.get("edit_idx") is not None
        if not (is_edit and text.strip() == "-"):
            flow["data"]["value"] = text
        context.user_data["awaiting"] = "btn_step_row"
        cur_row = flow["data"].get("row")
        hint = f" (currently row {cur_row} — send - to keep it)" if is_edit and cur_row is not None else ""
        await update.message.reply_text(to_small_caps("which row should this button appear in? (1, 2, 3...)") + hint)

    elif awaiting == "btn_step_row":
        flow = context.user_data.pop("btn_flow", None)
        context.user_data.pop("awaiting", None)
        if not flow:
            return
        is_edit = flow.get("edit_idx") is not None
        keep_row = is_edit and text.strip() == "-"
        if not keep_row:
            if not text.isdigit():
                await update.message.reply_text(to_small_caps("please send a number."))
                context.user_data["btn_flow"] = flow
                context.user_data["awaiting"] = "btn_step_row"
                return
            flow["data"]["row"] = int(text)
        menu_id = flow["menu_id"]
        if is_edit:
            idx = flow["edit_idx"]
            buttons = BOT_DATA["menus"][menu_id]["buttons"]
            if 0 <= idx < len(buttons):
                buttons[idx] = flow["data"]
                save_data()
                await update.message.reply_text(to_small_caps(f"✅ button {idx} updated in '{menu_id}'."))
            else:
                await update.message.reply_text(to_small_caps("that button no longer exists — nothing changed."))
        else:
            BOT_DATA["menus"][menu_id]["buttons"].append(flow["data"])
            save_data()
            await update.message.reply_text(to_small_caps(f"✅ button added to '{menu_id}'."))

    else:
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(to_small_caps("that wasn't understood — please try /admin again."))


async def handle_admin_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    user_id = update.effective_user.id
    if not awaiting or not is_admin(user_id):
        return
    # Same chat-cleanup as handle_admin_text_input — the admin's uploaded
    # photo/video used to set a menu image is deleted right after being read.
    await delete_incoming(update)

    if awaiting.startswith("menu_image:") and update.message.photo:
        menu_id = awaiting.split(":", 1)[1]
        context.user_data.pop("awaiting", None)
        file_id = update.message.photo[-1].file_id
        menu = BOT_DATA["menus"][menu_id]
        if len(menu.get("text", "")) > 1024:
            await update.message.reply_text(
                to_small_caps("⚠️ this menu's text is longer than 1024 characters and won't fit as an image caption. ")
                + to_small_caps("please shorten the text first, then add the image.")
            )
            return
        menu["image_file_id"] = file_id
        save_data()
        refreshed = await refresh_panel_after_save(
            context, f"menu_edit:{menu_id}", lambda: _build_menu_edit_screen(menu_id), parse_mode="HTML"
        )
        if not refreshed:
            await update.message.reply_text(to_small_caps(f"✅ '{menu_id}' image updated."))
        return

    if awaiting == "broadcast_content":
        context.user_data.pop("awaiting", None)
        await do_broadcast(update, context)
        return


# ----------------------------------------------------------------------------
# Health / DB status / export / restore  (#11, #12, #13)
# ----------------------------------------------------------------------------



__all__ = [_n for _n in dir() if not _n.startswith("__")]
