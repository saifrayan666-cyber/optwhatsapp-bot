#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters,
    ContextTypes
)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8947431324:AAEtIHkk_TTAmWEOIcY11_9FP3Xiv0FelIY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 1978055060))
# ===============================================

DATA_FILE = "bot_data.json"

# Data structures
pending_users = {}
approved_users = {}
blocked_users = {}
all_numbers = {}
otp_storage = {}
user_last_otp_index = {}
user_sessions = {}
banned_words = []
allowed_sites = []

# কান্ট্রি লিস্ট
COUNTRIES = {
    "US": {"flag": "🇺🇸", "name": "United States", "code": "+1"},
    "UK": {"flag": "🇬🇧", "name": "United Kingdom", "code": "+44"},
    "CA": {"flag": "🇨🇦", "name": "Canada", "code": "+1"},
    "AU": {"flag": "🇦🇺", "name": "Australia", "code": "+61"},
    "DE": {"flag": "🇩🇪", "name": "Germany", "code": "+49"},
    "FR": {"flag": "🇫🇷", "name": "France", "code": "+33"},
    "IN": {"flag": "🇮🇳", "name": "India", "code": "+91"}
}

# সাইট লিস্ট
SITES = [
    {"name": "getsms", "url": "https://getsms.cc", "countries": ["US", "UK", "CA", "AU", "DE", "FR"], "enabled": True},
    {"name": "esimplus", "url": "https://esimplus.me/temporary-numbers", "countries": ["US", "UK", "CA"], "enabled": True},
    {"name": "receive-sms", "url": "https://receive-sms-online.info/", "countries": ["US", "UK", "CA"], "enabled": True},
    {"name": "temp-number", "url": "https://temp-number.org/", "countries": ["US", "UK"], "enabled": True},
    {"name": "sms-receive", "url": "https://sms-receive.net/", "countries": ["US", "UK", "CA"], "enabled": True}
]

def load_data():
    global pending_users, approved_users, blocked_users, all_numbers, otp_storage, user_last_otp_index, banned_words, allowed_sites
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                pending_users = data.get("pending_users", {})
                approved_users = data.get("approved_users", {})
                blocked_users = data.get("blocked_users", {})
                all_numbers = data.get("all_numbers", {})
                otp_storage = data.get("otp_storage", {})
                user_last_otp_index = data.get("user_last_otp_index", {})
                banned_words = data.get("banned_words", [])
                allowed_sites = data.get("allowed_sites", [s["name"] for s in SITES])
                logger.info(f"Loaded: {len(approved_users)} users, {len(blocked_users)} blocked")
    except Exception as e:
        logger.error(f"Load error: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "pending_users": pending_users,
                "approved_users": approved_users,
                "blocked_users": blocked_users,
                "all_numbers": all_numbers,
                "otp_storage": otp_storage,
                "user_last_otp_index": user_last_otp_index,
                "banned_words": banned_words,
                "allowed_sites": allowed_sites,
                "last_update": str(datetime.now())
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save error: {e}")

def extract_phone_numbers(text):
    """Extract phone numbers from text"""
    if not text:
        return []
    
    # Clean text
    text = re.sub(r'[^\d\+]', ' ', text)
    
    # US/Canada pattern
    us_pattern = r'\+?1?\s*\(?(\d{3})\)?[\s-]?(\d{3})[\s-]?(\d{4})'
    us_matches = re.findall(us_pattern, text)
    
    # International pattern
    intl_pattern = r'\+?(\d{1,3})[\s-]?(\d{2,4})[\s-]?(\d{3,4})[\s-]?(\d{3,4})'
    intl_matches = re.findall(intl_pattern, text)
    
    numbers = []
    for match in us_matches:
        num = f"+1{''.join(match)}"
        if len(num) >= 10:
            numbers.append(num)
    
    for match in intl_matches:
        num = f"+{''.join(match)}"
        if len(num) >= 8:
            numbers.append(num)
    
    # Simple 10-digit numbers
    simple = re.findall(r'\b\d{10,11}\b', text)
    for num in simple:
        if num not in numbers:
            numbers.append(f"+{num}")
    
    return list(set(numbers))[:10]

def detect_service(message):
    """Detect service from message"""
    services = {
        "FACEBOOK": ["facebook", "fb", "meta", "face"],
        "INSTAGRAM": ["instagram", "ig", "insta"],
        "GOOGLE": ["google", "gmail", "youtube"],
        "WHATSAPP": ["whatsapp", "wa"],
        "TELEGRAM": ["telegram", "tg"],
        "AMAZON": ["amazon", "aws", "prime"],
        "APPLE": ["apple", "icloud", "ios"],
        "MICROSOFT": ["microsoft", "outlook", "teams"],
        "TWITTER": ["twitter", "x.com", "x"],
        "TIKTOK": ["tiktok", "tt"],
        "DISCORD": ["discord", "dc"],
        "SHOPIFY": ["shopify", "store", "shop"],
        "PAYPAL": ["paypal", "pay"],
        "BANK": ["bank", "visa", "mastercard", "card", "credit"],
        "VERIFICATION": ["verification", "verify", "code", "otp", "pin"]
    }
    
    msg_lower = message.lower()
    for service, keywords in services.items():
        for keyword in keywords:
            if keyword in msg_lower:
                return service
    return "GENERIC"

def extract_otp(text):
    """Extract OTP from text"""
    if not text:
        return None
    
    patterns = [
        r'\b(\d{5,6})\b',
        r'[Oo][Tt][Pp][:\s]*(\d{4,6})',
        r'[Cc][Oo][Dd][Ee][:\s]*(\d{4,6})',
        r'verification code[:\s]*(\d{4,6})',
        r'(\d{4,6}) is your',
        r'(\d{6})',
        r'(\d{5})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            otp = match.group(1)
            if otp and otp.isdigit() and 4 <= len(otp) <= 6:
                return otp
    return None

def scrape_site(site):
    """Scrape a single site"""
    if not site.get("enabled", True):
        return [], []
    
    numbers = []
    otps = []
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(site["url"], headers=headers, timeout=12)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        # Extract numbers
        phones = extract_phone_numbers(page_text)
        numbers = phones[:8]
        
        # Extract OTPs
        lines = page_text.split('\n')
        seen_otps = set()
        
        for line in lines:
            # Check for banned words
            if banned_words:
                skip = False
                for bw in banned_words:
                    if bw.lower() in line.lower():
                        skip = True
                        break
                if skip:
                    continue
            
            otp = extract_otp(line)
            if otp and otp not in seen_otps:
                seen_otps.add(otp)
                service = detect_service(line)
                
                # Find associated number
                associated_number = None
                for num in numbers:
                    if num in line:
                        associated_number = num
                        break
                
                if not associated_number and numbers:
                    associated_number = numbers[0]
                
                if associated_number:
                    otps.append({
                        "otp": otp,
                        "message": line[:250],
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "source": site["name"],
                        "service": service
                    })
        
        return numbers[:8], otps
        
    except Exception as e:
        logger.error(f"Scrape error {site['name']}: {e}")
        return [], []

def scrape_all_sites():
    """Scrape all sites"""
    global all_numbers, otp_storage
    
    logger.info("🔄 Scraping...")
    temp_numbers = {country: [] for country in COUNTRIES.keys()}
    new_otps = []
    
    for site in SITES:
        if not site.get("enabled", True):
            continue
            
        numbers, otps = scrape_site(site)
        
        # Assign numbers to countries
        for num in numbers:
            assigned = False
            for country, info in COUNTRIES.items():
                country_code = info["code"]
                if num.startswith(country_code) or num.startswith(country_code.replace('+', '')):
                    if num not in temp_numbers[country]:
                        temp_numbers[country].append(num)
                    assigned = True
                    break
            if not assigned and "US" in temp_numbers:
                if num not in temp_numbers["US"]:
                    temp_numbers["US"].append(num)
        
        # Process OTPs
        for otp_info in otps:
            number = otp_info.get("associated_number") or (numbers[0] if numbers else "unknown")
            if number not in otp_storage:
                otp_storage[number] = []
            
            if otp_info["otp"] not in [o["otp"] for o in otp_storage[number]]:
                otp_storage[number].append(otp_info)
                new_otps.append(otp_info)
    
    # Update global numbers
    for country in temp_numbers:
        temp_numbers[country] = list(set(temp_numbers[country]))[:15]
    all_numbers = temp_numbers
    
    # Clean old OTPs (keep last 100 per number)
    for num in otp_storage:
        otp_storage[num] = otp_storage[num][-100:]
    
    save_data()
    
    total_numbers = sum(len(n) for n in all_numbers.values())
    logger.info(f"✅ Scraped: {total_numbers} numbers, {len(new_otps)} new OTPs")
    return new_otps

# ==================== ADMIN PANEL ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel command"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
        [InlineKeyboardButton("⏳ Pending Requests", callback_data="admin_pending")],
        [InlineKeyboardButton("🚫 Blocked Users", callback_data="admin_blocked")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🌐 Site Manager", callback_data="admin_sites")],
        [InlineKeyboardButton("🔨 Banned Words", callback_data="admin_banned")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ]
    
    await update.message.reply_text(
        "🔧 *ADMIN PANEL*\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button clicks"""
    query = update.callback_query
    user_id = str(update.effective_user.id)
    data = query.data
    
    await query.answer()
    
    # Admin callbacks
    if data == "admin_users":
        await show_user_list(query)
    elif data == "admin_pending":
        await show_pending_list(query)
    elif data == "admin_blocked":
        await show_blocked_list(query)
    elif data == "admin_stats":
        await show_stats(query)
    elif data == "admin_sites":
        await show_site_manager(query)
    elif data == "admin_banned":
        await show_banned_words(query)
    elif data == "admin_broadcast":
        await show_broadcast_menu(query)
    elif data == "admin_settings":
        await show_settings(query)
    elif data == "admin_close":
        await query.edit_message_text("🔒 Admin panel closed.")
    
    # User callbacks
    elif data == "user_select_country":
        await show_country_menu(query, user_id)
    elif data.startswith("user_country_"):
        country = data.replace("user_country_", "")
        await show_numbers_for_country(query, user_id, country)
    elif data.startswith("user_view_"):
        number = data.replace("user_view_", "")
        await show_number_otps(query, user_id, number)
    elif data.startswith("user_save_"):
        number = data.replace("user_save_", "")
        await save_user_number(query, user_id, number)
    elif data == "user_my_numbers":
        await show_my_numbers(query, user_id)
    elif data == "user_my_otps":
        await show_my_otps(query, user_id)
    elif data == "user_remove_number":
        await show_remove_menu(query, user_id)
    elif data.startswith("user_remove_"):
        idx = int(data.split("_")[2])
        await remove_user_number(query, user_id, idx)
    elif data.startswith("user_refresh_country_"):
        country = data.replace("user_refresh_country_", "")
        await show_numbers_for_country(query, user_id, country)
    elif data == "user_back_menu":
        await show_main_menu(query, user_id)
    elif data == "user_help":
        await show_user_help(query)
    
    # User management callbacks
    elif data.startswith("view_user_"):
        uid = data.replace("view_user_", "")
        await show_user_details(query, uid)
    elif data.startswith("approve_user_"):
        uid = data.replace("approve_user_", "")
        await approve_user(query, context, uid)
    elif data.startswith("reject_user_"):
        uid = data.replace("reject_user_", "")
        await reject_user(query, uid)
    elif data.startswith("block_user_"):
        uid = data.replace("block_user_", "")
        await block_user(query, uid)
    elif data.startswith("unblock_user_"):
        uid = data.replace("unblock_user_", "")
        await unblock_user(query, uid)
    elif data.startswith("delete_user_"):
        uid = data.replace("delete_user_", "")
        await delete_user(query, uid)
    elif data.startswith("toggle_site_"):
        site_name = data.replace("toggle_site_", "")
        await toggle_site(query, site_name)
    elif data.startswith("remove_banned_"):
        word = data.replace("remove_banned_", "")
        await remove_banned_word(query, word)
    elif data.startswith("user_next_"):
        parts = data.split("_")
        if len(parts) >= 4:
            number = parts[2]
            page = int(parts[3])
            await show_number_otps_with_page(query, user_id, number, page)
    elif data.startswith("user_prev_"):
        parts = data.split("_")
        if len(parts) >= 4:
            number = parts[2]
            page = int(parts[3])
            await show_number_otps_with_page(query, user_id, number, page)

async def show_user_list(query):
    users = approved_users.items()
    if not users:
        await query.edit_message_text("📭 No users found.")
        return
    
    keyboard = []
    for uid, data in users:
        name = data.get("name", "Unknown")[:20]
        num_count = len(data.get("numbers", []))
        keyboard.append([InlineKeyboardButton(f"👤 {name} ({num_count} nums)", callback_data=f"view_user_{uid}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_close")])
    
    await query.edit_message_text(
        f"👥 *User List* ({len(users)} total)\n\nClick to view details:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_pending_list(query):
    if not pending_users:
        await query.edit_message_text("📭 No pending requests.")
        return
    
    keyboard = []
    for uid, data in pending_users.items():
        name = data.get("name", "Unknown")[:20]
        keyboard.append([
            InlineKeyboardButton(f"✅ {name}", callback_data=f"approve_user_{uid}"),
            InlineKeyboardButton(f"❌", callback_data=f"reject_user_{uid}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_close")])
    
    await query.edit_message_text(
        f"⏳ *Pending Requests* ({len(pending_users)})\n\nApprove or reject:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_blocked_list(query):
    if not blocked_users:
        await query.edit_message_text("📭 No blocked users.")
        return
    
    keyboard = []
    for uid, data in blocked_users.items():
        name = data.get("name", "Unknown")[:20]
        keyboard.append([InlineKeyboardButton(f"🔓 Unblock {name}", callback_data=f"unblock_user_{uid}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_close")])
    
    await query.edit_message_text(
        f"🚫 *Blocked Users* ({len(blocked_users)})\n\nClick to unblock:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_stats(query):
    total_users = len(approved_users)
    total_blocks = len(blocked_users)
    total_numbers = sum(len(u.get("numbers", [])) for u in approved_users.values())
    total_otps = sum(len(u.get("otp_history", [])) for u in approved_users.values())
    available_numbers = sum(len(n) for n in all_numbers.values())
    total_otp_storage = sum(len(otps) for otps in otp_storage.values())
    
    stats_msg = (
        f"📊 *STATISTICS*\n\n"
        f"👥 *Users:* {total_users}\n"
        f"🚫 *Blocked:* {total_blocks}\n"
        f"📱 *Saved Numbers:* {total_numbers}\n"
        f"🔐 *User OTPs:* {total_otps}\n"
        f"📡 *Available Numbers:* {available_numbers}\n"
        f"💾 *Storage OTPs:* {total_otp_storage}\n"
        f"🌐 *Active Sites:* {len([s for s in SITES if s.get('enabled', True)])}\n"
        f"🕐 *Updated:* {datetime.now().strftime('%H:%M:%S')}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_close")]]
    await query.edit_message_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_site_manager(query):
    keyboard = []
    for site in SITES:
        status = "✅" if site.get("enabled", True) else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} {site['name']}", callback_data=f"toggle_site_{site['name']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_close")])
    
    await query.edit_message_text(
        "🌐 *Site Manager*\n\nToggle sites ON/OFF:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_banned_words(query):
    keyboard = []
    for word in banned_words:
        keyboard.append([InlineKeyboardButton(f"❌ {word}", callback_data=f"remove_banned_{word}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_close")])
    
    msg = "🔨 *Banned Words*\n\nMessages containing these words will be filtered:\n\n"
    if not banned_words:
        msg += "No banned words yet."
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_broadcast_menu(query):
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_close")]]
    
    await query.edit_message_text(
        "📢 *Broadcast*\n\nSend a message to all users.\n\n"
        "Use: /send [your message]",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_settings(query):
    settings_msg = (
        "⚙️ *SETTINGS*\n\n"
        f"🔹 Max numbers per user: 5\n"
        f"🔹 Scrape interval: 15 seconds\n"
        f"🔹 Sites active: {len([s for s in SITES if s.get('enabled', True)])}/{len(SITES)}\n"
        f"🔹 Banned words: {len(banned_words)}\n"
        f"🔹 Total users: {len(approved_users)}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_close")]]
    await query.edit_message_text(settings_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_user_details(query, target_id):
    user = approved_users.get(target_id)
    if not user:
        await query.edit_message_text("User not found!")
        return
    
    numbers = user.get("numbers", [])
    otps = user.get("otp_history", [])
    
    msg = (
        f"👤 *USER DETAILS*\n\n"
        f"🆔 ID: `{target_id}`\n"
        f"📛 Name: {user.get('name', 'Unknown')}\n"
        f"👤 Username: @{user.get('username', 'N/A')}\n"
        f"🕐 Joined: {user.get('approved_at', 'Unknown')[:16]}\n"
        f"📱 Numbers: {len(numbers)}/5\n"
        f"🔐 OTPs: {len(otps)}\n\n"
        f"*Saved Numbers:*\n"
    )
    
    for num in numbers:
        msg += f"• `{num['number']}`\n"
    
    keyboard = [
        [InlineKeyboardButton("🚫 Block User", callback_data=f"block_user_{target_id}")],
        [InlineKeyboardButton("🗑 Delete User", callback_data=f"delete_user_{target_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_users")]
    ]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def delete_user(query, target_id):
    if target_id in approved_users:
        del approved_users[target_id]
        save_data()
        await query.edit_message_text(f"✅ User `{target_id}` deleted!", parse_mode="Markdown")
    else:
        await query.edit_message_text("User not found!")

async def approve_user(query, context, target_id):
    if target_id in pending_users:
        user_data = pending_users[target_id]
        approved_users[target_id] = {
            "name": user_data.get("name", "Unknown"),
            "username": user_data.get("username", ""),
            "approved_at": str(datetime.now()),
            "numbers": [],
            "otp_history": []
        }
        del pending_users[target_id]
        save_data()
        
        await query.edit_message_text(f"✅ User `{target_id}` approved!")
        await context.bot.send_message(
            chat_id=int(target_id),
            text="✅ *APPROVED!*\n\nSend /start to begin using the bot.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("User not found!")

async def reject_user(query, target_id):
    if target_id in pending_users:
        del pending_users[target_id]
        save_data()
        await query.edit_message_text(f"❌ User `{target_id}` rejected!", parse_mode="Markdown")

async def block_user(query, target_id):
    if target_id in approved_users:
        user_data = approved_users[target_id]
        blocked_users[target_id] = user_data
        del approved_users[target_id]
        save_data()
        await query.edit_message_text(f"🚫 User `{target_id}` blocked!", parse_mode="Markdown")

async def unblock_user(query, target_id):
    if target_id in blocked_users:
        user_data = blocked_users[target_id]
        approved_users[target_id] = user_data
        del blocked_users[target_id]
        save_data()
        await query.edit_message_text(f"🔓 User `{target_id}` unblocked!", parse_mode="Markdown")

async def toggle_site(query, site_name):
    for site in SITES:
        if site["name"] == site_name:
            site["enabled"] = not site.get("enabled", True)
            save_data()
            status = "enabled" if site["enabled"] else "disabled"
            await query.edit_message_text(f"✅ Site `{site_name}` {status}!")
            await show_site_manager(query)
            return

async def add_banned_word(query):
    await query.edit_message_text(
        "➕ *Add Banned Word*\n\n"
        "Reply with /addword [word]\n\n"
        "Example: /addword spam",
        parse_mode="Markdown"
    )

async def remove_banned_word(query, word):
    if word in banned_words:
        banned_words.remove(word)
        save_data()
        await query.edit_message_text(f"✅ Removed `{word}` from banned words!", parse_mode="Markdown")
        await show_banned_words(query)

# ==================== USER BOT COMMANDS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "User"
    username = update.effective_user.username or ""
    
    # Check if blocked
    if user_id in blocked_users:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    if user_id in approved_users:
        await show_main_menu(update, user_id)
        return
    
    if user_id in pending_users:
        await update.message.reply_text("⏳ *Request pending!*\n\nWait for admin approval.", parse_mode="Markdown")
        return
    
    # Send request to admin
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_user_{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_user_{user_id}")
    ]]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 *NEW USER*\n\n👤 {user_name}\n🆔 `{user_id}`\n📛 @{username}\n🕐 {datetime.now().strftime('%H:%M:%S')}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    pending_users[user_id] = {"name": user_name, "username": username, "request_time": str(datetime.now())}
    save_data()
    
    await update.message.reply_text(
        "👋 *Welcome!*\n\nRequest sent to admin.\nYou'll be notified when approved.",
        parse_mode="Markdown"
    )

async def show_main_menu(update, user_id):
    user_data = approved_users.get(user_id, {})
    num_count = len(user_data.get("numbers", []))
    otp_count = len(user_data.get("otp_history", []))
    
    keyboard = [
        [InlineKeyboardButton("🌍 Select Country", callback_data="user_select_country")],
        [InlineKeyboardButton("📋 My Numbers", callback_data="user_my_numbers")],
        [InlineKeyboardButton("🔐 My OTPs", callback_data="user_my_otps")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="user_remove_number")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="user_help")]
    ]
    
    msg = f"🤖 *OTP Bot*\n\n✅ Active\n📱 {num_count}/5 numbers\n🔐 {otp_count} OTPs\n\n👇 Choose:"
    
    if isinstance(update, Update):
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        try:
            await update.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except:
            pass

async def show_country_menu(query, user_id):
    keyboard = []
    for code, info in COUNTRIES.items():
        count = len(all_numbers.get(code, []))
        keyboard.append([InlineKeyboardButton(f"{info['flag']} {info['name']} ({count})", callback_data=f"user_country_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_back_menu")])
    
    try:
        await query.edit_message_text(
            "🌍 *Select Country*\n\nChoose a country to get numbers:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except:
        await query.message.reply_text(
            "🌍 *Select Country*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def show_numbers_for_country(query, user_id, country):
    # Scrape fresh
    new_otps = scrape_all_sites()
    
    numbers = all_numbers.get(country, [])
    if not numbers:
        for code, nums in all_numbers.items():
            if nums:
                numbers = nums
                break
    
    if not numbers:
        await query.edit_message_text(
            f"📭 *No numbers for {COUNTRIES.get(country, {}).get('name', country)}!*\n\nTry again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data=f"user_refresh_country_{country}")]])
        )
        return
    
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    available = [num for num in numbers if num not in user_numbers][:12]
    
    if not available:
        await query.edit_message_text(
            "📭 *All numbers saved!*\n\nRemove some numbers first.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Remove", callback_data="user_remove_number")]])
        )
        return
    
    keyboard = []
    for num in available[:10]:
        keyboard.append([InlineKeyboardButton(f"📱 {num}", callback_data=f"user_view_{num}")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"user_refresh_country_{country}")])
    keyboard.append([InlineKeyboardButton("🌍 Change Country", callback_data="user_select_country")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_back_menu")])
    
    await query.edit_message_text(
        f"📱 *Numbers from {COUNTRIES.get(country, {}).get('flag', '')} {COUNTRIES.get(country, {}).get('name', country)}*\n\n{len(available)} available:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_number_otps(query, user_id, number):
    await show_number_otps_with_page(query, user_id, number, 0)

async def show_number_otps_with_page(query, user_id, number, page):
    otps = otp_storage.get(number, [])
    
    if not otps:
        await query.edit_message_text(
            f"📭 *No OTPs for {number}*\n\nNo messages yet.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data=f"user_view_{number}")]])
        )
        return
    
    items_per_page = 8
    total_pages = (len(otps) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(otps))
    page_otps = otps[start_idx:end_idx]
    
    msg = f"🔐 *OTPs for {number}*\n\n"
    for i, otp_info in enumerate(page_otps, start_idx + 1):
        msg += f"*{i}.* `{otp_info['otp']}`\n"
        msg += f"   🏷️ {otp_info.get('service', 'GENERIC')}\n"
        msg += f"   🕐 {otp_info['time'][:16]}\n"
        msg += f"   🌐 {otp_info['source']}\n\n"
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"user_prev_{number}_{page-1}"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"user_next_{number}_{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Save button
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    if number not in user_numbers:
        keyboard.append([InlineKeyboardButton("💾 Save Number", callback_data=f"user_save_{number}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"user_view_{number}")])
    keyboard.append([InlineKeyboardButton("🌍 Back to Countries", callback_data="user_select_country")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    # Save to history
    user_data = approved_users.get(user_id, {})
    for otp_info in page_otps:
        if otp_info["otp"] not in [h["otp"] for h in user_data.get("otp_history", [])]:
            if "otp_history" not in user_data:
                user_data["otp_history"] = []
            user_data["otp_history"].append({
                "otp": otp_info["otp"],
                "number": number,
                "time": otp_info["time"],
                "source": otp_info["source"],
                "service": otp_info.get("service", "GENERIC")
            })
    save_data()

async def save_user_number(query, user_id, number):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if len(user_numbers) >= 5:
        await query.edit_message_text(
            "❌ *Limit reached!* (5 numbers max)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Remove", callback_data="user_remove_number")]])
        )
        return
    
    if number not in [n["number"] for n in user_numbers]:
        user_numbers.append({"number": number, "saved_at": str(datetime.now())})
        user_data["numbers"] = user_numbers
        save_data()
        
        await query.edit_message_text(
            f"✅ *Saved!*\n\n📱 `{number}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 My Numbers", callback_data="user_my_numbers")]]),
            parse_mode="Markdown"
        )

async def show_my_numbers(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await query.edit_message_text(
            "📭 *No saved numbers*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Get Numbers", callback_data="user_select_country")]])
        )
        return
    
    msg = f"📱 *Your Numbers* ({len(user_numbers)}/5)\n\n"
    for i, num_info in enumerate(user_numbers, 1):
        otp_count = len([h for h in user_data.get("otp_history", []) if h["number"] == num_info["number"]])
        msg += f"{i}. `{num_info['number']}`\n   └ {otp_count} OTPs\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔐 View OTPs", callback_data="user_my_otps")],
        [InlineKeyboardButton("🗑 Remove", callback_data="user_remove_number")],
        [InlineKeyboardButton("🌍 Get More", callback_data="user_select_country")],
        [InlineKeyboardButton("🔙 Back", callback_data="user_back_menu")]
    ]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_my_otps(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_otps = user_data.get("otp_history", [])
    
    if not user_otps:
        await query.edit_message_text(
            "📭 *No OTPs yet*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Get Numbers", callback_data="user_select_country")]])
        )
        return
    
    msg = f"🔐 *Your OTPs* (Last 15)\n\n"
    for i, otp_info in enumerate(user_otps[-15:], 1):
        msg += f"{i}. `{otp_info['otp']}`\n"
        msg += f"   ├ 📱 {otp_info['number']}\n"
        msg += f"   ├ 🏷️ {otp_info.get('service', 'GENERIC')}\n"
        msg += f"   └ 🕐 {otp_info['time'][:16]}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="user_my_numbers")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_remove_menu(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await query.edit_message_text("📭 No numbers to remove!")
        return
    
    keyboard = []
    for i, num_info in enumerate(user_numbers):
        keyboard.append([InlineKeyboardButton(f"🗑 {num_info['number']}", callback_data=f"user_remove_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_my_numbers")])
    
    await query.edit_message_text("🗑 *Select number to remove:*", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_user_number(query, user_id, index):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if index < len(user_numbers):
        removed = user_numbers.pop(index)
        user_data["numbers"] = user_numbers
        save_data()
        
        await query.edit_message_text(
            f"✅ *Removed* `{removed['number']}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Get More", callback_data="user_select_country")]]),
            parse_mode="Markdown"
        )

async def show_user_help(query):
    await query.edit_message_text(
        "📖 *Help*\n\n"
        "1. *Select Country* → Choose a country\n"
        "2. *Pick number* → View its OTPs\n"
        "3. *Save number* → Add to your list\n"
        "4. *My Numbers* → View saved numbers\n"
        "5. *My OTPs* → See all OTPs\n\n"
        "*Limits:* 5 numbers max\n"
        "*Note:* Numbers are public",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="user_back_menu")]]),
        parse_mode="Markdown"
    )

# ==================== MESSAGE HANDLER ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = str(update.effective_user.id)
    text = update.message.text
    
    # Admin broadcast
    if user_id == str(ADMIN_ID) and text.startswith("/send "):
        msg = text.replace("/send ", "")
        sent = 0
        for uid in approved_users.keys():
            try:
                await context.bot.send_message(chat_id=int(uid), text=f"📢 *ANNOUNCEMENT*\n\n{msg}", parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.1)
            except:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to {sent} users!")
        return
    
    # Add banned word
    if user_id == str(ADMIN_ID) and text.startswith("/addword "):
        word = text.replace("/addword ", "").strip().lower()
        if word and word not in banned_words:
            banned_words.append(word)
            save_data()
            await update.message.reply_text(f"✅ Added `{word}` to banned words!", parse_mode="Markdown")
        return
    
    # If user is not approved, remind them
    if user_id not in approved_users and user_id not in pending_users:
        await update.message.reply_text("❌ Please use /start to request access.")
        return

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    total_users = len(approved_users)
    total_numbers = sum(len(u.get("numbers", [])) for u in approved_users.values())
    total_otps = sum(len(u.get("otp_history", [])) for u in approved_users.values())
    available = sum(len(n) for n in all_numbers.values())
    
    await update.message.reply_text(
        f"📊 *STATUS*\n\n"
        f"👥 Users: {total_users}\n"
        f"⏳ Pending: {len(pending_users)}\n"
        f"🚫 Blocked: {len(blocked_users)}\n"
        f"📱 Saved: {total_numbers}\n"
        f"🔐 OTPs: {total_otps}\n"
        f"📡 Available: {available}\n"
        f"✅ Running!",
        parse_mode="Markdown"
    )

async def auto_scrape():
    """Background scraper"""
    while True:
        try:
            start = time.time()
            new_otps = scrape_all_sites()
            if new_otps:
                logger.info(f"Found {len(new_otps)} new OTPs in {time.time()-start:.1f}s")
        except Exception as e:
            logger.error(f"Auto scrape error: {e}")
        await asyncio.sleep(15)

def main():
    print("=" * 55)
    print("🤖 OTP FORWARDER BOT v4.0 - FULL ADMIN PANEL")
    print("=" * 55)
    
    load_data()
    
    print(f"✅ Users: {len(approved_users)}")
    print(f"🚫 Blocked: {len(blocked_users)}")
    print(f"⏳ Pending: {len(pending_users)}")
    print(f"🌐 Sites: {len(SITES)}")
    print("=" * 55)
    
    # Start background scraper
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(auto_scrape())
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("status", status_command))
    
    # Message handler for text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Callback handler for all buttons
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot running! Admin panel available via /admin")
    print("=" * 55)
    
    app.run_polling()

if __name__ == "__main__":
    main()
