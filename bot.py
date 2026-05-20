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
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== LOGGING ====================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8947431324:AAEtIHkk_TTAmWEOIcY11_9FP3Xiv0FelIY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 1978055060))
PORT = int(os.environ.get("PORT", 8080))
# ===============================================

DATA_FILE = "bot_data.json"

# Data structures
pending_users = {}
approved_users = {}
all_numbers = {}  # {country_code: [numbers]}
otp_storage = {}  # {number: [{"otp": "123", "message": "", "time": "", "source": "", "service": ""}]}
user_last_otp_index = {}
user_sessions = {}

# سাইট লিস্ট (৭টি সাইট)
SITES = {
    "esimplus": {
        "url": "https://esimplus.me/temporary-numbers",
        "countries": ["US", "UK", "CA"],
        "type": "html"
    },
    "getsms": {
        "url": "https://getsms.cc",
        "countries": ["US", "UK", "CA", "AU", "DE", "FR"],
        "type": "html"
    },
    "receive-sms": {
        "url": "https://receive-sms-online.info/",
        "countries": ["US", "UK", "CA"],
        "type": "html"
    },
    "temp-number": {
        "url": "https://temp-number.org/",
        "countries": ["US", "UK"],
        "type": "html"
    },
    "sms-receive": {
        "url": "https://sms-receive.net/",
        "countries": ["US", "UK", "CA"],
        "type": "html"
    },
    "free-sms": {
        "url": "https://free-sms-receive.com/",
        "countries": ["US", "UK"],
        "type": "html"
    },
    "receive-sms-online": {
        "url": "https://receive-sms-online.cc/",
        "countries": ["US", "UK", "CA", "AU"],
        "type": "html"
    }
}

# কান্ট্রি কোড লিস্ট
COUNTRIES = {
    "US": {"flag": "🇺🇸", "name": "United States", "code": "+1"},
    "UK": {"flag": "🇬🇧", "name": "United Kingdom", "code": "+44"},
    "CA": {"flag": "🇨🇦", "name": "Canada", "code": "+1"},
    "AU": {"flag": "🇦🇺", "name": "Australia", "code": "+61"},
    "DE": {"flag": "🇩🇪", "name": "Germany", "code": "+49"},
    "FR": {"flag": "🇫🇷", "name": "France", "code": "+33"},
    "IN": {"flag": "🇮🇳", "name": "India", "code": "+91"}
}

def load_data():
    global pending_users, approved_users, all_numbers, otp_storage, user_last_otp_index
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                pending_users = data.get("pending_users", {})
                approved_users = data.get("approved_users", {})
                all_numbers = data.get("all_numbers", {})
                otp_storage = data.get("otp_storage", {})
                user_last_otp_index = data.get("user_last_otp_index", {})
                logger.info(f"Loaded: {len(approved_users)} users, {sum(len(v) for v in all_numbers.values())} numbers")
    except Exception as e:
        logger.error(f"Load error: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "pending_users": pending_users,
                "approved_users": approved_users,
                "all_numbers": all_numbers,
                "otp_storage": otp_storage,
                "user_last_otp_index": user_last_otp_index,
                "last_update": str(datetime.now())
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save error: {e}")

def extract_phone_numbers(text, country_code=""):
    """Extract phone numbers from text"""
    patterns = [
        r'\+?1?\s*\(?[0-9]{3}\)?[\s.-]?[0-9]{3}[\s.-]?[0-9]{4}',
        r'\+?[0-9]{1,3}[\s.-]?[0-9]{3,4}[\s.-]?[0-9]{3,4}',
        r'[0-9]{3}[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}',
    ]
    numbers = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        numbers.extend(matches)
    return list(set(numbers))[:10]

def detect_service(message):
    """Detect which service sent the OTP"""
    services = {
        "meta": ["facebook", "fb", "meta", "instagram", "ig"],
        "shopify": ["shopify", "store", "payment", "checkout"],
        "card": ["visa", "mastercard", "card", "bank", "credit"],
        "whatsapp": ["whatsapp", "wa"],
        "telegram": ["telegram", "tg"],
        "google": ["google", "gmail", "youtube"],
        "amazon": ["amazon", "aws"],
        "apple": ["apple", "icloud", "ios"],
        "twitter": ["twitter", "x.com"],
        "tiktok": ["tiktok", "tt"],
        "verification": ["verification", "verify", "code", "otp", "pin"]
    }
    
    msg_lower = message.lower()
    for service, keywords in services.items():
        for keyword in keywords:
            if keyword in msg_lower:
                return service.upper()
    return "GENERIC"

def extract_otp(text):
    """Extract OTP from text"""
    if not text:
        return None
    patterns = [
        r'\b(\d{5,6})\b',
        r'[Oo][Tt][Pp][:\s]*(\d{4,6})',
        r'[Cc][Oo][Dd][Ee][:\s]*(\d{4,6})',
        r'[Pp][Ii][Nn][:\s]*(\d{4,6})',
        r'verification code[:\s]*(\d{4,6})',
        r'(\d{4,6}) is your',
        r'code[:\s]*(\d{4,6})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            otp = match.group(1)
            if otp and otp.isdigit() and 4 <= len(otp) <= 6:
                return otp
    return None

def scrape_site(site_name, site_config):
    """Scrape a single site for numbers and OTPs"""
    numbers = []
    otps = []
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(site_config["url"], headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        # Extract numbers
        all_phones = extract_phone_numbers(page_text)
        numbers = all_phones[:10]
        
        # Extract OTPs from page
        lines = page_text.split('\n')
        for line in lines:
            otp = extract_otp(line)
            if otp:
                # Detect service
                service = detect_service(line)
                
                otps.append({
                    "otp": otp,
                    "message": line[:300],
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": site_name,
                    "service": service,
                    "url": site_config["url"]
                })
        
        return numbers, otps
        
    except Exception as e:
        logger.error(f"Scrape error {site_name}: {e}")
        return [], []

def scrape_all_sites():
    """Scrape all sites"""
    global all_numbers, otp_storage
    
    logger.info("Starting scrape cycle...")
    new_otp_count = 0
    all_new_otps = []
    
    for site_name, site_config in SITES.items():
        numbers, otps = scrape_site(site_name, site_config)
        
        # Store numbers by country (simplified)
        for country in site_config.get("countries", ["US"]):
            if country not in all_numbers:
                all_numbers[country] = []
            for num in numbers[:5]:
                if num not in all_numbers[country]:
                    all_numbers[country].append(num)
            # Keep only 20 per country
            all_numbers[country] = all_numbers[country][:20]
        
        # Process OTPs
        for otp_info in otps:
            # Find associated number
            associated_number = None
            for num in numbers[:3]:
                if num in otp_info["message"]:
                    associated_number = num
                    break
            
            if not associated_number and numbers:
                associated_number = numbers[0]
            
            if associated_number:
                if associated_number not in otp_storage:
                    otp_storage[associated_number] = []
                
                if otp_info["otp"] not in [o["otp"] for o in otp_storage[associated_number]]:
                    otp_storage[associated_number].append(otp_info)
                    new_otp_count += 1
                    all_new_otps.append(otp_info)
    
    # Limit storage
    for num in otp_storage:
        otp_storage[num] = otp_storage[num][-40:]
    
    if new_otp_count > 0:
        logger.info(f"Found {new_otp_count} new OTPs")
    
    save_data()
    return new_otp_count, all_new_otps

# ==================== TELEGRAM BOT ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "User"
    username = update.effective_user.username or "No username"
    
    if user_id in approved_users:
        await show_main_menu(update, user_id)
        return
    
    if user_id in pending_users:
        await update.message.reply_text("⏳ *Request pending!*\n\nPlease wait for admin approval.", parse_mode="Markdown")
        return
    
    # Send to admin
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 *NEW USER REQUEST*\n\n"
             f"👤 Name: {user_name}\n"
             f"🆔 ID: `{user_id}`\n"
             f"📛 Username: @{username}\n"
             f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    pending_users[user_id] = {"name": user_name, "username": username, "request_time": str(datetime.now())}
    save_data()
    
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "Your request has been sent to admin.\n"
        "You will be notified when approved.\n\n"
        "Thanks for your patience! 🙏",
        parse_mode="Markdown"
    )

async def show_main_menu(update, user_id):
    user_data = approved_users.get(user_id, {})
    num_count = len(user_data.get("numbers", []))
    otp_count = len(user_data.get("otp_history", []))
    
    keyboard = [
        [InlineKeyboardButton("🌍 Get Numbers by Country", callback_data="select_country")],
        [InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("🔐 My OTP History", callback_data="my_otps")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="remove_number")],
        [InlineKeyboardButton("🌐 Active Sites", callback_data="show_sites")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    message = (
        f"🤖 *OTP FORWARDER BOT v3.0*\n\n"
        f"✅ Status: *Active*\n"
        f"📱 Numbers Saved: {num_count}/5\n"
        f"🔐 Total OTPs: {otp_count}\n"
        f"🌐 Active Sites: {len(SITES)}\n\n"
        f"👇 *Choose an option:*"
    )
    
    if isinstance(update, Update):
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        try:
            await update.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except:
            pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(update.effective_user.id)
    data = query.data
    
    # Admin approval
    if data.startswith("approve_"):
        target = data.replace("approve_", "")
        if target in pending_users:
            user_info = pending_users[target]
            approved_users[target] = {
                "name": user_info["name"],
                "username": user_info.get("username", ""),
                "approved_at": str(datetime.now()),
                "numbers": [],
                "otp_history": []
            }
            del pending_users[target]
            save_data()
            await query.edit_message_text(f"✅ User {target} approved!")
            await context.bot.send_message(
                chat_id=int(target),
                text="✅ *APPROVED!*\n\nSend /start to begin using the bot.",
                parse_mode="Markdown"
            )
        return
    
    if data.startswith("reject_"):
        target = data.replace("reject_", "")
        if target in pending_users:
            del pending_users[target]
            save_data()
            await query.edit_message_text(f"❌ User {target} rejected!")
        return
    
    # Check approval
    if user_id not in approved_users:
        await query.answer("Access denied!", show_alert=True)
        return
    
    await query.answer()
    
    # User actions
    if data == "select_country":
        await show_country_menu(query, user_id)
    
    elif data.startswith("country_"):
        country = data.replace("country_", "")
        user_sessions[user_id] = {"country": country}
        await show_numbers_for_country(query, user_id, country)
    
    elif data.startswith("view_"):
        number = data.replace("view_", "")
        await show_number_otps(query, user_id, number)
    
    elif data.startswith("save_"):
        number = data.replace("save_", "")
        await save_user_number(query, user_id, number)
    
    elif data == "my_numbers":
        await show_my_numbers(query, user_id)
    
    elif data == "my_otps":
        await show_my_otps(query, user_id)
    
    elif data == "remove_number":
        await show_remove_menu(query, user_id)
    
    elif data.startswith("remove_"):
        idx = int(data.split("_")[1])
        await remove_user_number(query, user_id, idx)
    
    elif data == "show_sites":
        await show_sites_info(query)
    
    elif data == "refresh_numbers":
        await refresh_numbers(query, user_id)
    
    elif data.startswith("refresh_country_"):
        country = data.replace("refresh_country_", "")
        await show_numbers_for_country(query, user_id, country)
    
    elif data.startswith("next_"):
        parts = data.split("_")
        if len(parts) >= 3:
            number = parts[1]
            page = int(parts[2])
            await show_number_otps_with_page(query, user_id, number, page)
    
    elif data.startswith("prev_"):
        parts = data.split("_")
        if len(parts) >= 3:
            number = parts[1]
            page = int(parts[2])
            await show_number_otps_with_page(query, user_id, number, page)
    
    elif data == "back":
        await show_main_menu(query, user_id)
    
    elif data == "help":
        await show_help(query)

async def show_country_menu(query, user_id):
    keyboard = []
    for code, info in COUNTRIES.items():
        keyboard.append([InlineKeyboardButton(f"{info['flag']} {info['name']} ({info['code']})", callback_data=f"country_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    
    await query.edit_message_text(
        "🌍 *Select Country*\n\nChoose a country to get numbers from:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_numbers_for_country(query, user_id, country):
    global all_numbers
    
    # Scrape fresh data
    scrape_all_sites()
    
    numbers = all_numbers.get(country, [])
    if not numbers:
        numbers = all_numbers.get("US", [])  # Fallback to US
    
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    available = [num for num in numbers if num not in user_numbers][:15]
    
    if not available:
        await query.edit_message_text(
            f"📭 *No numbers available for {COUNTRIES.get(country, {}).get('name', country)}!*\n\n"
            f"Try another country or wait 30 seconds.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_country_{country}")],
                [InlineKeyboardButton("🌍 Change Country", callback_data="select_country")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    keyboard = []
    for num in available:
        keyboard.append([InlineKeyboardButton(f"📱 {num}", callback_data=f"view_{num}")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_country_{country}")])
    keyboard.append([InlineKeyboardButton("🌍 Change Country", callback_data="select_country")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    
    await query.edit_message_text(
        f"📱 *Numbers from {COUNTRIES.get(country, {}).get('flag', '')} {COUNTRIES.get(country, {}).get('name', country)}*\n\n"
        f"Found {len(available)} numbers.\n"
        f"Click on a number to view its OTPs:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def show_number_otps(query, user_id, number):
    await show_number_otps_with_page(query, user_id, number, 0)

async def show_number_otps_with_page(query, user_id, number, page):
    otps = otp_storage.get(number, [])
    
    if not otps:
        await query.edit_message_text(
            f"📭 *No OTPs for {number}*\n\n"
            f"This number has no OTPs yet.\n"
            f"Try again in 20 seconds.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"view_{number}")],
                [InlineKeyboardButton("🔙 Back", callback_data="select_country")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    # Pagination (10 per page)
    items_per_page = 10
    total_pages = (len(otps) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(otps))
    page_otps = otps[start_idx:end_idx]
    
    message = f"🔐 *OTPs for {number}*\n\n"
    for i, otp_info in enumerate(page_otps, start_idx + 1):
        message += f"*{i}.* `{otp_info['otp']}`\n"
        message += f"   🕐 {otp_info['time'][:16]}\n"
        message += f"   🌐 Source: {otp_info['source']}\n"
        message += f"   🏷️ Service: {otp_info.get('service', 'Unknown')}\n"
        message += f"   📨 {otp_info['message'][:70]}...\n\n"
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"prev_{number}_{page-1}"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"next_{number}_{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Save button
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    if number not in user_numbers and len(user_numbers) < 5:
        keyboard.append([InlineKeyboardButton("💾 Save This Number", callback_data=f"save_{number}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"view_{number}")])
    keyboard.append([InlineKeyboardButton("🌍 Back to Countries", callback_data="select_country")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back")])
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    # Save to user history
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
                "service": otp_info.get("service", "GENERIC"),
                "message": otp_info["message"][:100]
            })
    save_data()

async def save_user_number(query, user_id, number):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if len(user_numbers) >= 5:
        await query.edit_message_text(
            "❌ *Limit reached!*\n\nYou can only save 5 numbers.\nRemove one first.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Remove Number", callback_data="remove_number")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    if number not in [n["number"] for n in user_numbers]:
        user_numbers.append({
            "number": number,
            "saved_at": str(datetime.now())
        })
        user_data["numbers"] = user_numbers
        save_data()
        
        await query.edit_message_text(
            f"✅ *Number Saved!*\n\n"
            f"📱 `{number}`\n\n"
            f"You can now view its OTPs from 'My Numbers'.\n"
            f"OTPs will appear automatically when received.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")],
                [InlineKeyboardButton("🔐 View OTPs", callback_data=f"view_{number}")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )

async def show_my_numbers(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await query.edit_message_text(
            "📭 *No saved numbers*\n\nGo to 'Get Numbers by Country' to add some.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌍 Get Numbers", callback_data="select_country")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    message = f"📱 *Your Numbers* ({len(user_numbers)}/5)\n\n"
    for i, num_info in enumerate(user_numbers, 1):
        otp_count = len([h for h in user_data.get("otp_history", []) if h["number"] == num_info["number"]])
        message += f"{i}. `{num_info['number']}`\n"
        message += f"   ├ Saved: {num_info['saved_at'][:16]}\n"
        message += f"   └ OTPs: {otp_count}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔐 View All OTPs", callback_data="my_otps")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="remove_number")],
        [InlineKeyboardButton("🌍 Get More Numbers", callback_data="select_country")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ]
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_my_otps(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_otps = user_data.get("otp_history", [])
    
    if not user_otps:
        await query.edit_message_text(
            "📭 *No OTPs yet*\n\nSave a number and wait for OTPs to arrive.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Get Numbers", callback_data="select_country")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )
        return
    
    message = f"🔐 *Your OTP History* (Last 20)\n\n"
    for i, otp_info in enumerate(user_otps[-20:], 1):
        message += f"{i}. `{otp_info['otp']}`\n"
        message += f"   ├ 📱 {otp_info['number']}\n"
        message += f"   ├ 🕐 {otp_info['time'][:16]}\n"
        message += f"   ├ 🌐 {otp_info.get('source', 'Unknown')}\n"
        message += f"   └ 🏷️ {otp_info.get('service', 'GENERIC')}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="my_numbers")]]
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_remove_menu(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await query.edit_message_text("📭 No numbers to remove!", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]))
        return
    
    keyboard = []
    for i, num_info in enumerate(user_numbers):
        keyboard.append([InlineKeyboardButton(f"🗑 {num_info['number']}", callback_data=f"remove_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    
    await query.edit_message_text("🗑 *Remove Number*\n\nSelect which number to remove:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def remove_user_number(query, user_id, index):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if index < len(user_numbers):
        removed = user_numbers.pop(index)
        user_data["numbers"] = user_numbers
        save_data()
        
        await query.edit_message_text(
            f"✅ *Removed!*\n\n`{removed['number']}`\n\nYou can now add {5 - len(user_numbers)} more numbers.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Get New Number", callback_data="select_country")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back")]
            ]),
            parse_mode="Markdown"
        )

async def refresh_numbers(query, user_id):
    await query.edit_message_text("🔄 *Fetching fresh numbers...*\n\nPlease wait 10 seconds.", parse_mode="Markdown")
    scrape_all_sites()
    await show_country_menu(query, user_id)

async def show_sites_info(query):
    active_sites = len(SITES)
    message = f"🌐 *Active Sites* ({active_sites})\n\n"
    
    for site_name, site_config in SITES.items():
        message += f"• `{site_name}`\n"
        message += f"  └ Countries: {', '.join(site_config.get('countries', ['US']))}\n\n"
    
    message += f"\n📊 *Total numbers available:* {sum(len(v) for v in all_numbers.values())}\n"
    message += f"🔐 *Total OTPs in storage:* {sum(len(v) for v in otp_storage.values())}\n"
    message += f"⏱️ *Last update:* {datetime.now().strftime('%H:%M:%S')}"
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ]), parse_mode="Markdown")

async def show_help(query):
    await query.edit_message_text(
        "📖 *Complete User Guide*\n\n"
        "*1. GET NUMBERS*\n"
        "   → Select 'Get Numbers by Country'\n"
        "   → Choose a country (US, UK, CA, etc.)\n"
        "   → Pick a number from the list\n"
        "   → Click 'Save This Number' to keep it\n\n"
        "*2. VIEW OTPs*\n"
        "   → Click on any number to see its OTPs\n"
        "   → OTPs are shown with service name\n"
        "   → Use Previous/Next to see all OTPs\n\n"
        "*3. YOUR NUMBERS*\n"
        "   → 'My Numbers' - See saved numbers\n"
        "   → 'My OTP History' - All OTPs received\n"
        "   → 'Remove Number' - Delete saved number\n\n"
        "*4. OTP SOURCES DETECTED*\n"
        "   • META (Facebook/Instagram)\n"
        "   • SHOPIFY (Store verification)\n"
        "   • CARD (Bank/Credit card)\n"
        "   • WHATSAPP, TELEGRAM\n"
        "   • GOOGLE, AMAZON, APPLE\n"
        "   • TWITTER, TIKTOK\n\n"
        "*5. LIMITS*\n"
        "   ⚠️ 5 numbers maximum per user\n"
        "   ⚠️ Numbers are PUBLIC (shared)\n"
        "   ⚠️ For testing/educational use only\n\n"
        "*Commands:*\n"
        "/start - Main menu\n"
        "/status - Bot status (admin only)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]),
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ *Admin only command!*", parse_mode="Markdown")
        return
    
    total_users = len(approved_users)
    total_numbers = sum(len(u.get("numbers", [])) for u in approved_users.values())
    total_otps = sum(len(u.get("otp_history", [])) for u in approved_users.values())
    
    user_list = "👥 *User List:*\n\n"
    for uid, data in approved_users.items():
        user_list += f"• {data.get('name', 'Unknown')}\n"
        user_list += f"  ├ ID: `{uid}`\n"
        user_list += f"  ├ Username: @{data.get('username', 'N/A')}\n"
        user_list += f"  ├ Numbers: {len(data.get('numbers', []))}\n"
        user_list += f"  └ OTPs: {len(data.get('otp_history', []))}\n\n"
    
    await update.message.reply_text(
        f"📊 *ADMIN STATUS*\n\n"
        f"👥 Total Users: {total_users}\n"
        f"⏳ Pending: {len(pending_users)}\n"
        f"📱 Numbers: {total_numbers}\n"
        f"🔐 OTPs: {total_otps}\n"
        f"🌐 Active Sites: {len(SITES)}\n"
        f"📡 Available: {sum(len(v) for v in all_numbers.values())}\n\n"
        f"{user_list}\n"
        f"✅ Bot running smoothly!\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode="Markdown"
    )

async def auto_scrape():
    """Background scraper - runs every 12 seconds"""
    while True:
        try:
            start = time.time()
            new_count, new_otps = scrape_all_sites()
            if new_count > 0:
                logger.info(f"Auto-scrape: {new_count} new OTPs found in {time.time()-start:.1f}s")
        except Exception as e:
            logger.error(f"Auto scrape error: {e}")
        await asyncio.sleep(12)  # প্রতি ১২ সেকেন্ডে স্ক্র্যাপ

def main():
    print("=" * 55)
    print("🤖 OTP FORWARDER BOT v3.0 - 7 SITES + COUNTRY SELECT")
    print("=" * 55)
    
    load_data()
    
    print(f"✅ Approved Users: {len(approved_users)}")
    print(f"⏳ Pending Users: {len(pending_users)}")
    print(f"🌐 Active Sites: {len(SITES)}")
    print(f"📱 Available Numbers: {sum(len(v) for v in all_numbers.values())}")
    print("=" * 55)
    
    # Start background scraper
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(auto_scrape())
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot is running! Press Ctrl+C to stop.")
    print("=" * 55)
    
    app.run_polling()

if __name__ == "__main__":
    main()