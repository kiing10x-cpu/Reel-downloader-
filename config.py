"""Env vars, paths, logging and optional-dependency detection. See README.md for setup."""

import os
import io
import html
import re
import json
import csv
import time
import shutil
import subprocess
import asyncio
import logging
import tempfile
from datetime import datetime, timedelta
from urllib.parse import quote

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    CopyTextButton,
    MessageEntity,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import Forbidden, BadRequest, RetryAfter, TelegramError

import yt_dlp

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
BACKUP_INTERVAL_HOURS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "12"))

DATA_FILE = "bot_data.json"
# "Update Backup" seed files — see _apply_seed_files_if_present() and the
# 📦 Update Backup admin-panel button. Drop both, with these EXACT names,
# next to bot.py in the GitHub repo before pushing a code update. If the
# host wipes local storage on deploy (no bot_data.json, empty MongoDB),
# the bot auto-loads these back in on startup — no manual restore needed.
SEED_SETTINGS_FILE = "bot_settings_seed.json"
SEED_USERS_FILE = "bot_users_seed.json"
BACKUP_DIR = "backups"
DOWNLOAD_DIR = "downloads"
PLUGIN_DIR = "plugins"
MAX_LOCAL_BACKUPS = 10
BACKUP_KEY_FILE = "backup.key"  # local Fernet key — never put this in the repo/git

# ----------------------------------------------------------------------------
# 🗄 Mongo Plugin — lets the owner paste a MongoDB URI live from the Admin
# Panel (🍭 Update Backup > 🗄 Mongo Plugin) instead of only via the
# MONGO_URI env var. Precedence: MONGO_URI env var ALWAYS wins if set (it's
# the infra-managed path) — the panel-set URI is only used when no env var
# is present. Whatever is set via the panel is persisted to this small
# local file (separate from bot_data.json) so it survives a restart even
# before BOT_DATA itself has loaded — same pattern as BACKUP_KEY_FILE.
# ----------------------------------------------------------------------------
MONGO_CONFIG_FILE = "mongo_config.json"
MONGO_URI_SOURCE = "env" if MONGO_URI else None   # "env" | "admin_panel" | None
MONGO_CONNECTED_AT = None   # ISO timestamp of when this URI was first attached
if not MONGO_URI and os.path.exists(MONGO_CONFIG_FILE):
    try:
        with open(MONGO_CONFIG_FILE, "r", encoding="utf-8") as _f:
            _mc = json.load(_f)
        if _mc.get("uri"):
            MONGO_URI = _mc["uri"].strip()
            MONGO_URI_SOURCE = "admin_panel"
            MONGO_CONNECTED_AT = _mc.get("connected_at")
    except Exception:
        pass  # corrupt/unreadable file — just start unconfigured, never fatal

os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PLUGIN_DIR, exist_ok=True)


# ffmpeg is only needed when yt-dlp has to merge separate video+audio
# streams. Most reels are already muxed, so try a system install first and
# fall back to the portable imageio-ffmpeg binary if that's missing.
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")
if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg

        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_PATH = None
FFMPEG_AVAILABLE = bool(FFMPEG_PATH)
# imageio-ffmpeg only ships the ffmpeg binary, not ffprobe, so we track this
# separately and do audio extraction via a direct ffmpeg call (cb_get_audio)
# instead of yt-dlp's ffprobe-dependent postprocessor.
FFPROBE_AVAILABLE = bool(FFPROBE_PATH)


def _ytdlp_extract_with_retry(opts: dict, url: str, download: bool = True):
    """Run yt-dlp's extract_info with one automatic retry.

    A stale extractor cache is a common cause of "No video formats found"
    or "Unable to extract" errors after Instagram changes something on
    their end. On those known-transient signatures we clear the cache once
    and retry before giving up. Genuinely private/deleted/invalid links
    still fail immediately since retrying can't help those.
    """
    transient_markers = (
        "no video formats found",
        "requested format is not available",
        "unable to extract",
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            return ydl.extract_info(url, download=download)
        except Exception as e:
            msg = str(e).lower()
            if not any(m in msg for m in transient_markers):
                raise
            log.warning("yt-dlp extraction hit a possibly-stale-cache error, clearing cache and retrying once: %s", e)
            try:
                ydl.cache.remove()
            except Exception:
                pass
    # Retry with a fresh YoutubeDL instance so the cleared cache actually takes effect.
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

if FFMPEG_AVAILABLE:
    log.info("ffmpeg found at: %s", FFMPEG_PATH)
else:
    log.warning(
        "ffmpeg not found. Downloads will use a no-merge format (still works, "
        "occasionally slightly lower max quality). Install ffmpeg or "
        "`pip install imageio-ffmpeg` to always get the absolute best quality."
    )

# ----------------------------------------------------------------------------
# Local branded QR generation (replaces the old api.qrserver.com URL, which
# gave a plain black-on-white square and depended on a third-party service
# being reachable, separately from the bot itself). Same graceful-fallback
# pattern as ffmpeg above: works best with `qrcode[pil]` installed, degrades
# to a plain local QR if only `qrcode` is present, and falls all the way
# back to the old remote-URL QR only if `qrcode` isn't installed at all.
# ----------------------------------------------------------------------------
QRCODE_AVAILABLE = False
QRCODE_STYLED_AVAILABLE = False
try:
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    from qrcode.image.styles.colormasks import SolidFillColorMask

    QRCODE_AVAILABLE = True
    QRCODE_STYLED_AVAILABLE = True
except ImportError:
    try:
        import qrcode

        QRCODE_AVAILABLE = True
    except ImportError:
        pass

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

if QRCODE_AVAILABLE and PIL_AVAILABLE:
    log.info(
        "QR generation: local %s QR enabled.",
        "styled (rounded + branded)" if QRCODE_STYLED_AVAILABLE else "plain",
    )
else:
    log.warning(
        "qrcode/Pillow not found — payment QR codes will fall back to the "
        "remote api.qrserver.com URL. Run `pip install \"qrcode[pil]\"` for "
        "nicer, fully local QR codes that don't depend on a third party."
    )

# ----------------------------------------------------------------------------
# PDF report (charts) + encrypted backup — same graceful-fallback pattern as
# qrcode/Pillow above. Neither is a hard requirement to run the bot; the
# admin panel just tells you what to `pip install` if a feature is missing.
# ----------------------------------------------------------------------------
PDF_REPORT_AVAILABLE = False
try:
    import matplotlib
    matplotlib.use("Agg")  # headless — no display server on a bot host
    import matplotlib.pyplot as plt
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage,
    )
    from reportlab.lib.styles import getSampleStyleSheet

    PDF_REPORT_AVAILABLE = True
except ImportError:
    log.warning(
        "matplotlib/reportlab not found — 📊 PDF Report will be unavailable. "
        "Run `pip install matplotlib reportlab` to enable it."
    )

BACKUP_ENCRYPTION_AVAILABLE = False
try:
    from cryptography.fernet import Fernet, InvalidToken

    BACKUP_ENCRYPTION_AVAILABLE = True
except ImportError:
    log.warning(
        "`cryptography` not found — backups will be saved unencrypted. "
        "Run `pip install cryptography` to enable encrypted backups."
    )


UPI_QR_BRAND_COLOR = (0, 135, 90)  # UPI-style green (kept as a fallback tint)

# Dark neon-card look (matches the requested reference design): near-black
# card, purple -> cyan gradient border, white rounded panel holding the
# actual black-on-white QR (max contrast = most reliably scannable), and a
# circular center logo with a soft colored ring.
QR_CARD_BG = (10, 10, 14)
QR_GRADIENT_A = (147, 51, 234)   # purple
QR_GRADIENT_B = (56, 189, 248)   # cyan
QR_TEXT_LIGHT = (235, 235, 245)
QR_TEXT_MUTED = (150, 150, 165)

# Keep the logo comfortably inside the ~30% recovery budget of
# ERROR_CORRECT_H so the code stays scannable even after we cover the
# center with a photo. 20% of the QR's own width (not the outer card) is a
# safe, well-tested ratio.
QR_LOGO_RATIO = 0.20


def _diagonal_gradient(size, c1, c2):
    """A simple top-left -> bottom-right gradient image, built with row/col
    interpolation (fast enough for a one-off card, no numpy dependency)."""
    w, h = size
    grad = Image.new("RGB", size)
    max_t = (w - 1) + (h - 1) or 1
    row_cache = {}
    pixels = grad.load()
    for y in range(h):
        for x in range(w):
            key = x + y
            rgb = row_cache.get(key)
            if rgb is None:
                t = key / max_t
                rgb = (
                    int(c1[0] + (c2[0] - c1[0]) * t),
                    int(c1[1] + (c2[1] - c1[1]) * t),
                    int(c1[2] + (c2[2] - c1[2]) * t),
                )
                row_cache[key] = rgb
            pixels[x, y] = rgb
    return grad


def _default_center_logo(size: int) -> "Image.Image":
    """Vector-drawn circular fallback logo (gradient ring + simple bolt
    icon), used whenever no user avatar is available — e.g. the user has
    no Telegram profile photo, get_user_profile_photos fails, or
    logo_bytes is None. This is drawn with plain PIL shapes, not text, so
    it never depends on a font being present and the QR center is never
    left blank/plain."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = _diagonal_gradient((size, size), QR_GRADIENT_A, QR_GRADIENT_B).convert("RGBA")
    ring_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(ring_mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.paste(grad, (0, 0), ring_mask)

    inner_pad = max(2, int(size * 0.09))
    d = ImageDraw.Draw(img)
    d.ellipse(
        (inner_pad, inner_pad, size - 1 - inner_pad, size - 1 - inner_pad),
        fill=QR_CARD_BG + (255,),
    )

    # simple bolt icon, pure vector — no font/glyph dependency at all
    cx, cy = size / 2, size / 2
    s = size * 0.20
    points = [
        (cx + s * 0.15, cy - s), (cx - s * 0.55, cy + s * 0.15), (cx - s * 0.05, cy + s * 0.15),
        (cx - s * 0.15, cy + s), (cx + s * 0.55, cy - s * 0.15), (cx + s * 0.05, cy - s * 0.15),
    ]
    d.polygon(points, fill=QR_TEXT_LIGHT + (255,))
    return img


def _paste_center_logo(qr_img: "Image.Image", logo_bytes: bytes = None):
    """Paste a circular avatar (or the vector fallback logo, if no avatar
    bytes were given/loadable) in the middle of the QR with a white buffer
    ring underneath it, sized so the code is still reliably scannable."""
    logo_size = int(qr_img.width * QR_LOGO_RATIO)
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
            logo = ImageOps.fit(logo, (logo_size, logo_size), Image.LANCZOS)
        except Exception:
            log.exception("Could not decode avatar bytes for QR center logo — using fallback logo")
            logo = _default_center_logo(logo_size)
    else:
        logo = _default_center_logo(logo_size)

    mask = Image.new("L", (logo_size, logo_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, logo_size, logo_size), fill=255)

    # white buffer ring so no QR module directly under the logo's edge is
    # left half-covered/ambiguous to a scanner
    ring_size = int(logo_size * 1.22)
    ring_mask = Image.new("L", (ring_size, ring_size), 0)
    ImageDraw.Draw(ring_mask).ellipse((0, 0, ring_size, ring_size), fill=255)

    qr_rgba = qr_img.convert("RGBA")
    rx = (qr_rgba.width - ring_size) // 2
    ry = (qr_rgba.height - ring_size) // 2
    white_ring = Image.new("RGBA", (ring_size, ring_size), (255, 255, 255, 255))
    qr_rgba.paste(white_ring, (rx, ry), ring_mask)

    lx = (qr_rgba.width - logo_size) // 2
    ly = (qr_rgba.height - logo_size) // 2
    qr_rgba.paste(logo, (lx, ly), mask)
    return qr_rgba.convert("RGB")


_QR_FONT_CACHE = {}


def _find_unicode_font(bold: bool):
    """Search common install locations for a DejaVu Sans TTF that can
    render the glyphs the QR card needs (₹, and the small-caps Unicode
    phonetic-extension letters used throughout the bot's UI).

    ImageFont.truetype("DejaVuSans-Bold.ttf") — a bare filename — only
    resolves when that file happens to sit in the current working
    directory or a couple of PIL-internal dirs. It does NOT search the
    system's actual font directories (Pillow has no fontconfig
    integration), so on most servers/containers this silently raises and
    the caller falls back to PIL's tiny built-in bitmap font, which can't
    render ₹ or small-caps at all — hence the ▯▯▯▯ boxes. Returns a real
    path to a working font, or None if nothing usable was found."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        name,
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/usr/share/fonts/dejavu/{name}",
        f"/usr/share/fonts/truetype/ttf-dejavu/{name}",
        f"/usr/share/fonts/TTF/{name}",
        f"/usr/local/share/fonts/{name}",
        f"/Library/Fonts/{name}",
        os.path.expanduser(f"~/.fonts/{name}"),
        f"C:\\Windows\\Fonts\\{name}",
    ]
    # matplotlib bundles DejaVu Sans and is present in a lot of environments
    # even when the OS-level font packages aren't installed — cheap extra
    # chance at a real unicode-capable font before giving up.
    try:
        import matplotlib
        candidates.insert(1, os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name))
    except Exception:
        pass

    for path in candidates:
        try:
            ImageFont.truetype(path, 10)
            return path
        except Exception:
            continue
    return None


def _load_qr_fonts():
    """Load (and cache) the fonts used on the QR card. Returns
    (font_big, font_small, unicode_ok). unicode_ok is False only when no
    real TTF could be found anywhere and we had to fall back to PIL's
    default bitmap font — callers must then ASCII-ify any ₹/small-caps
    text before drawing it, or it renders as ▯▯▯▯ boxes."""
    if _QR_FONT_CACHE:
        c = _QR_FONT_CACHE
        return c["big"], c["small"], c["unicode_ok"]

    bold_path = _find_unicode_font(bold=True)
    reg_path = _find_unicode_font(bold=False)
    try:
        if not (bold_path and reg_path):
            raise OSError("no unicode-capable TTF found on this system")
        font_big = ImageFont.truetype(bold_path, 30)
        font_small = ImageFont.truetype(reg_path, 16)
        unicode_ok = True
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()
        unicode_ok = False
        log.warning(
            "No DejaVu/unicode-capable TTF found on this system — QR card "
            "text (₹ amount, small-caps caption) will render as plain "
            "ASCII via PIL's default bitmap font instead of showing "
            "▯▯▯▯ boxes. Install the 'fonts-dejavu-core' package (or any "
            "TTF with those glyphs) for the real symbols."
        )

    _QR_FONT_CACHE.update(big=font_big, small=font_small, unicode_ok=unicode_ok)
    return font_big, font_small, unicode_ok


def _ascii_safe(text: str) -> str:
    """Best-effort plain-ASCII rendering of QR card text, used only when
    _load_qr_fonts() couldn't find a real unicode-capable font. Undoes the
    bot's small-caps styling (ᴀʙᴄ.. -> abc..) and swaps ₹ for 'Rs.' so the
    card shows readable text instead of ▯▯▯▯ tofu boxes."""
    reverse = {v: k for k, v in SMALL_CAPS_MAP.items()}
    out = "".join(reverse.get(ch, ch) for ch in text)
    return out.replace("₹", "Rs.")


def generate_branded_qr(data: str, amount=None, caption: str = "Scan with any UPI app", logo_bytes: bytes = None):
    """Build the dark, gradient-bordered branded QR card (amount + caption
    baked into the image), optionally with a circular logo (e.g. the paying
    user's Telegram profile photo) in the center. Returns an in-memory PNG,
    or None if qrcode/Pillow aren't installed so callers can fall back to
    the old remote-URL QR."""
    if not (QRCODE_AVAILABLE and PIL_AVAILABLE):
        return None
    try:
        # ERROR_CORRECT_H = up to ~30% of the code can be damaged/covered
        # and it still scans — required here since the center gets covered
        # by the logo. Plain black-on-white modules (not colored/rounded)
        # keep contrast at its safest maximum for real-world UPI scanners.
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=3,
        )
        qr.add_data(data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        # Always paste a center logo — the real avatar when we have it,
        # otherwise the vector fallback baked into _paste_center_logo, so
        # the card never renders with a plain blank center.
        try:
            qr_img = _paste_center_logo(qr_img, logo_bytes)
        except Exception:
            log.exception("Failed to paste center logo onto QR — continuing without it")

        pad = 36
        panel_pad = 20  # white rounded panel margin around the raw QR
        header_h = 56 if amount is not None else 0
        footer_h = 40
        border_w = 6
        radius = 40

        panel_w = qr_img.width + panel_pad * 2
        panel_h = qr_img.height + panel_pad * 2
        canvas_w = panel_w + pad * 2
        canvas_h = panel_h + pad * 2 + header_h + footer_h

        canvas = Image.new("RGB", (canvas_w, canvas_h), QR_CARD_BG)
        draw = ImageDraw.Draw(canvas)

        # gradient border (purple -> cyan), drawn as a stroke via a mask so
        # it only affects the outline, not the whole card
        border_mask = Image.new("L", (canvas_w, canvas_h), 0)
        ImageDraw.Draw(border_mask).rounded_rectangle(
            [0, 0, canvas_w - 1, canvas_h - 1], radius=radius, outline=255, width=border_w
        )
        gradient = _diagonal_gradient((canvas_w, canvas_h), QR_GRADIENT_A, QR_GRADIENT_B)
        canvas.paste(gradient, (0, 0), border_mask)

        font_big, font_small, unicode_ok = _load_qr_fonts()
        safe_caption = caption if unicode_ok else _ascii_safe(caption)

        y = pad // 2 + 6
        if amount is not None:
            amt_text = f"₹{amount}" if unicode_ok else f"Rs.{amount}"
            w = draw.textlength(amt_text, font=font_big)
            draw.text(((canvas_w - w) / 2, y), amt_text, fill=QR_TEXT_LIGHT, font=font_big)
            y += header_h

        # white rounded panel behind the QR — maximum contrast for scanning,
        # matches the reference card's "white square in a dark frame" look
        panel_x, panel_y = pad, y
        draw.rounded_rectangle(
            [panel_x, panel_y, panel_x + panel_w - 1, panel_y + panel_h - 1],
            radius=24, fill=(255, 255, 255),
        )
        canvas.paste(qr_img, (panel_x + panel_pad, panel_y + panel_pad))
        y = panel_y + panel_h + 14

        w = draw.textlength(safe_caption, font=font_small)
        draw.text(((canvas_w - w) / 2, y), safe_caption, fill=QR_TEXT_MUTED, font=font_small)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "payment_qr.png"
        return buf
    except Exception:
        log.exception("Local QR generation failed, falling back to remote QR service")
        return None


async def fetch_user_avatar_bytes(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Fetch the user's current Telegram profile photo (highest available
    resolution) as raw bytes, for use as the QR's center logo. Returns None
    if the user has no profile photo or it can't be fetched — callers must
    treat that as "no logo" and continue, never as an error."""
    try:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if not photos or not photos.photos:
            return None
        file_id = photos.photos[0][-1].file_id  # last = largest size available
        tg_file = await context.bot.get_file(file_id)
        data = await tg_file.download_as_bytearray()
        return bytes(data)
    except Exception:
        log.exception("Could not fetch Telegram avatar for user %s, QR will use no logo", user_id)
        return None



__all__ = [_n for _n in dir() if not _n.startswith("__")]
