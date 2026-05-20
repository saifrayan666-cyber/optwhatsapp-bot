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
logging.basicConfig(
    format='%(asctime)s - %name)s - %(levelname)s - %(message)s',
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
all_numbers = {}  # {country_code: [numbers]}
otp_storage = {}  # {number: [{"otp": "...", "message": "...", ...}]}
user_last_otp_index = {}
user_sessions = {}
user_message_ids = {}  # ট্র্যাক রাখার জন্য মেসেজ আইডি

# কান্ট্রি কোড লিস্ট
COUNTRIES = {
    "US": {"flag": "🇺🇸", "name": "United States", "code": "+1", "priority": 1},
    "UK": {"flag": "🇬🇧", "name": "United Kingdom", "code": "+44", "priority": 2},
    "CA": {"flag": "🇨🇦", "name": "Canada", "code": "+1", "priority": 3},
    "AU": {"flag": "🇦🇺", "name": "Australia", "code": "+61", "priority": 4},
    "DE": {"flag": "🇩🇪", "name": "Germany", "code": "+49", "priority": 5},
    "FR": {"flag": "🇫🇷", "name": "France", "code": "+33", "priority": 6},
    "IN": {"flag": "🇮🇳", "name": "India", "code": "+91", "priority": 7}
}

# সাইট লিস্ট (কান্ট্রি অনুযায়ী নম্বর প্রদান করে)
SITES = [
    {"name": "getsms", "url": "https://getsms.cc", "countries": ["US", "UK", "CA", "AU", "DE", "FR"]},
    {"name": "esimplus", "url": "https://esimplus.me/temporary-numbers", "countries": ["US", "UK", "CA"]},
    {"name": "receive-sms", "url": "https://receive-sms-online.info/", "countries": ["US", "UK", "CA"]},
    {"name": "temp-number", "url": "https://temp-number.org/", "countries": ["US", "UK"]},
    {"name": "sms-receive", "url": "https://sms-receive.net/", "countries": ["US", "UK", "CA"]}
]

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
                logger.info(f"Loaded: {len(approved_users)} users")
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

def extract_phone_numbers(text, country_code="US"):
    """Extract phone numbers from text - improved"""
    # Remove common words and clean text
    text = re.sub(r'[^\d\+]', ' ', text)
    
    # US/Canada pattern (+1 or 1 followed by 10 digits)
    us_pattern = r'\+?1?\s*\(?(\d{3})\)?[\s-]?(\d{3})[\s-]?(\d{4})'
    us_matches = re.findall(us_pattern, text)
    
    # International pattern
    intl_pattern = r'\+?(\d{1,3})[\s-]?(\d{3,4})[\s-]?(\d{3,4})[\s-]?(\d{3,4})'
    intl_matches = re.findall(intl_pattern, text)
    
    numbers = []
    for match in us_matches:
        num = f"+1{''.join(match)}"
        numbers.append(num)
    
    for match in intl_matches:
        if len(''.join(match)) >= 8:
            num = f"+{''.join(match)}"
            numbers.append(num)
    
    return list(set(numbers))[:10]

def detect_service(message):
    """Detect which service sent the OTP"""
    services = {
        "META": ["facebook", "fb", "meta", "instagram", "ig"],
        "SHOPIFY": ["shopify", "store", "payment", "checkout"],
        "CARD": ["visa", "mastercard", "card", "bank", "credit"],
        "GOOGLE": ["google", "gmail", "youtube"],
        "AMAZON": ["amazon", "aws", "prime"],
        "APPLE": ["apple", "icloud", "ios"],
        "WHATSAPP": ["whatsapp", "wa"],
        "TELEGRAM": ["telegram", "tg"],
        "TWITTER": ["twitter", "x.com"],
        "TIKTOK": ["tiktok", "tt"],
        "MICROSOFT": ["microsoft", "outlook", "teams"],
        "DISCORD": ["discord", "dc"]
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
        r'[Pp][Ii][Nn][:\s]*(\d{4,6})',
        r'verification code[:\s]*(\d{4,6})',
        r'(\d{4,6}) is your',
        r'(\d{4,6})$',
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
        
        # If no numbers found, try to find from number elements
        if not numbers:
            number_elements = soup.find_all(['div', 'span', 'a', 'p'], string=re.compile(r'[\d\+\-\(\)]{10,}'))
            for elem in number_elements[:10]:
                txt = elem.get_text(strip=True)
                phone = re.sub(r'[^\d\+]', '', txt)
                if len(phone) >= 8:
                    numbers.append(phone)
        
        numbers = list(set(numbers))[:8]
        
        # Extract OTPs
        lines = page_text.split('\n')
        seen_otps = set()
        
        for line in lines:
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
                    print(f"🔐 [{site['name']}] OTP: {otp} ({service})")
        
        return numbers, otps
        
    except Exception as e:
        logger.error(f"Scrape error {site['name']}: {e}")
        return [], []

def scrape_all_sites():
    """Scrape all sites and organize by country"""
    global all_numbers, otp_storage
    
    logger.info("🔄 Starting scrape cycle...")
    all_new_otps = []
    
    # Reset numbers for each country
    temp_numbers = {country: [] for country in COUNTRIES.keys()}
    
    for site in SITES:
        numbers, otps = scrape_site(site)
        
        # Assign numbers to countries (based on area code)
        for num in numbers:
            assigned = False
            for country, info in COUNTRIES.items():
                country_code = info["code"]
                if num.startswith(country_code) or num.startswith(country_code.replace('+', '')):
                    if num not in temp_numbers[country]:
                        temp_numbers[country].append(num)
                    assigned = True
                    break
            # Default to US if no match
            if not assigned and "US" in temp_numbers:
                if num not in temp_numbers["US"]:
                    temp_numbers["US"].append(num)
        
        # Process OTPs
        for otp_info in otps:
            # Find which country this number belongs to
            for country, info in COUNTRIES.items():
                country_code = info["code"]
                if any(num.startswith(country_code) or num.startswith(country_code.replace('+', '')) for num in numbers):
                    pass
            
            # Store OTP
            number = otp_info.get("associated_number") or (numbers[0] if numbers else "unknown")
            if number not in otp_storage:
                otp_storage[number] = []
            
            if otp_info["otp"] not in [o["otp"] for o in otp_storage[number]]:
                otp_storage[number].append(otp_info)
                all_new_otps.append(otp_info)
    
    # Update global numbers
    for country in temp_numbers:
        temp_numbers[country] = list(set(temp_numbers[country]))[:15]
    all_numbers = temp_numbers
    
    # Limit OTP storage
    for num in otp_storage:
        otp_storage[num] = otp_storage[num][-50:]
    
    save_data()
    
    total_numbers = sum(len(n) for n in all_numbers.values())
    logger.info(f"✅ Scrape done: {total_numbers} numbers, {len(all_new_otps)} new OTPs")
    return all_new_otps

# ==================== TELEGRAM BOT ====================

async def send_or_edit_message(query, user_id, message_text, reply_markup, is_new=False):
    """Send new message or edit existing one - avoids 'Message not modified' error"""
    try:
        # Check if we have a message id for this user
        if not is_new and user_id in user_message_ids:
            try:
                await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
                return
            except Exception as e:
                if "Message is not modified" in str(e):
                    # Message same as before, just ignore
                    return
                else:
                    # Other error, send new message
                    pass
        
        # Send new message
        msg = await query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
        user_message_ids[user_id] = msg.message_id
        
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Send error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "User"
    username = update.effective_user.username or ""
    
    if user_id in approved_users:
        await show_main_menu(update, user_id)
        return
    
    if user_id in pending_users:
        await update.message.reply_text("⏳ *Request pending!*\n\nPlease wait for admin approval.", parse_mode="Markdown")
        return
    
    # Send to admin
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
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
        "👋 *Welcome!*\n\nRequest sent to admin. You'll be notified when approved.",
        parse_mode="Markdown"
    )

async def show_main_menu(update, user_id):
    user_data = approved_users.get(user_id, {})
    num_count = len(user_data.get("numbers", []))
    otp_count = len(user_data.get("otp_history", []))
    
    keyboard = [
        [InlineKeyboardButton("🌍 Select Country", callback_data="select_country")],
        [InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("🔐 My OTPs", callback_data="my_otps")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="remove_number")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    msg = f"🤖 *OTP Bot*\n\n✅ Active\n📱 {num_count}/5 numbers\n🔐 {otp_count} OTPs\n\n👇 Choose:"
    
    if isinstance(update, Update):
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await send_or_edit_message(update, user_id, msg, InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(update.effective_user.id)
    data = query.data
    
    await query.answer()
    
    # Admin actions
    if data.startswith("approve_"):
        target = data.replace("approve_", "")
        if target in pending_users:
            approved_users[target] = {
                "name": pending_users[target]["name"],
                "username": pending_users[target].get("username", ""),
                "approved_at": str(datetime.now()),
                "numbers": [],
                "otp_history": []
            }
            del pending_users[target]
            save_data()
            await query.edit_message_text(f"✅ User {target} approved!")
            await context.bot.send_message(chat_id=int(target), text="✅ *APPROVED!*\n\nSend /start", parse_mode="Markdown")
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
        await query.message.reply_text("❌ Access denied! Contact admin.")
        return
    
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
    
    elif data == "back_menu":
        await show_main_menu(query, user_id)
    
    elif data == "help":
        await show_help(query)

async def show_country_menu(query, user_id):
    keyboard = []
    for code, info in COUNTRIES.items():
        # Count available numbers for this country
        count = len(all_numbers.get(code, []))
        keyboard.append([InlineKeyboardButton(f"{info['flag']} {info['name']} ({info['code']}) - {count} nums", callback_data=f"country_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
    
    await send_or_edit_message(query, user_id, "🌍 *Select Country*\n\nChoose a country:", InlineKeyboardMarkup(keyboard))

async def show_numbers_for_country(query, user_id, country):
    # Scrape fresh data
    new_otps = scrape_all_sites()
    
    numbers = all_numbers.get(country, [])
    if not numbers:
        # Try to get from other countries as fallback
        for code, nums in all_numbers.items():
            if nums:
                numbers = nums
                break
    
    if not numbers:
        await send_or_edit_message(query, user_id, 
            f"📭 *No numbers for {COUNTRIES.get(country, {}).get('name', country)}!*\n\nTry again in 20 seconds.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_country_{country}")]]))
        return
    
    # Filter out user's saved numbers
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    available = [num for num in numbers if num not in user_numbers][:12]
    
    keyboard = []
    for num in available[:10]:
        keyboard.append([InlineKeyboardButton(f"📱 {num}", callback_data=f"view_{num}")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_country_{country}")])
    keyboard.append([InlineKeyboardButton("🌍 Change Country", callback_data="select_country")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
    
    await send_or_edit_message(query, user_id,
        f"📱 *Numbers from {COUNTRIES.get(country, {}).get('flag', '')} {COUNTRIES.get(country, {}).get('name', country)}*\n\n{len(available)} available. Click to view OTPs:",
        InlineKeyboardMarkup(keyboard))

async def show_number_otps(query, user_id, number):
    await show_number_otps_with_page(query, user_id, number, 0)

async def show_number_otps_with_page(query, user_id, number, page):
    otps = otp_storage.get(number, [])
    
    if not otps:
        await send_or_edit_message(query, user_id,
            f"📭 *No OTPs for {number}*\n\nNo messages received yet.\nTry again in 20 seconds.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data=f"view_{number}")]]))
        return
    
    # Pagination
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
    
    # Navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"prev_{number}_{page-1}"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"next_{number}_{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Save button
    user_numbers = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    if number not in user_numbers:
        keyboard.append([InlineKeyboardButton("💾 Save Number", callback_data=f"save_{number}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"view_{number}")])
    keyboard.append([InlineKeyboardButton("🌍 Back to Countries", callback_data="select_country")])
    
    await send_or_edit_message(query, user_id, msg, InlineKeyboardMarkup(keyboard))
    
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
                "service": otp_info.get("service", "GENERIC")
            })
    save_data()

async def save_user_number(query, user_id, number):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if len(user_numbers) >= 5:
        await send_or_edit_message(query, user_id,
            "❌ *Limit reached!* Maximum 5 numbers.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Remove", callback_data="remove_number")]]))
        return
    
    if number not in [n["number"] for n in user_numbers]:
        user_numbers.append({"number": number, "saved_at": str(datetime.now())})
        user_data["numbers"] = user_numbers
        save_data()
        
        await send_or_edit_message(query, user_id,
            f"✅ *Saved!*\n\n📱 `{number}`\n\nView from 'My Numbers'.",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")]]),
            parse_mode="Markdown")

async def show_my_numbers(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await send_or_edit_message(query, user_id,
            "📭 *No saved numbers*\n\nGo to 'Select Country' to add.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Select Country", callback_data="select_country")]]))
        return
    
    msg = f"📱 *Your Numbers* ({len(user_numbers)}/5)\n\n"
    for i, num_info in enumerate(user_numbers, 1):
        otp_count = len([h for h in user_data.get("otp_history", []) if h["number"] == num_info["number"]])
        msg += f"{i}. `{num_info['number']}`\n   └ {otp_count} OTPs\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔐 View My OTPs", callback_data="my_otps")],
        [InlineKeyboardButton("🗑 Remove", callback_data="remove_number")],
        [InlineKeyboardButton("🌍 Get More", callback_data="select_country")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_menu")]
    ]
    
    await send_or_edit_message(query, user_id, msg, InlineKeyboardMarkup(keyboard))

async def show_my_otps(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_otps = user_data.get("otp_history", [])
    
    if not user_otps:
        await send_or_edit_message(query, user_id,
            "📭 *No OTPs yet*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Get Numbers", callback_data="select_country")]]))
        return
    
    msg = f"🔐 *Your OTP History* (Last 15)\n\n"
    for i, otp_info in enumerate(user_otps[-15:], 1):
        msg += f"{i}. `{otp_info['otp']}`\n"
        msg += f"   ├ 📱 {otp_info['number']}\n"
        msg += f"   ├ 🏷️ {otp_info.get('service', 'GENERIC')}\n"
        msg += f"   └ 🕐 {otp_info['time'][:16]}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="my_numbers")]]
    await send_or_edit_message(query, user_id, msg, InlineKeyboardMarkup(keyboard))

async def show_remove_menu(query, user_id):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if not user_numbers:
        await send_or_edit_message(query, user_id, "📭 No numbers to remove!",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]))
        return
    
    keyboard = []
    for i, num_info in enumerate(user_numbers):
        keyboard.append([InlineKeyboardButton(f"🗑 {num_info['number']}", callback_data=f"remove_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="my_numbers")])
    
    await send_or_edit_message(query, user_id, "🗑 *Select number to remove:*", InlineKeyboardMarkup(keyboard))

async def remove_user_number(query, user_id, index):
    user_data = approved_users.get(user_id, {})
    user_numbers = user_data.get("numbers", [])
    
    if index < len(user_numbers):
        removed = user_numbers.pop(index)
        user_data["numbers"] = user_numbers
        save_data()
        
        await send_or_edit_message(query, user_id,
            f"✅ *Removed*\n\n`{removed['number']}`",
            InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Get More", callback_data="select_country")]]),
            parse_mode="Markdown")

async def show_help(query):
    await send_or_edit_message(query, "help",
        "📖 *Help*\n\n"
        "1. Select Country → Choose a country\n"
        "2. Pick a number → View its OTPs\n"
        "3. Save Number → Add to your list\n"
        "4. My Numbers → View saved numbers\n"
        "5. My OTPs → See all OTPs received\n\n"
        "*Limits:* 5 numbers max\n"
        "*Note:* Numbers are public (shared)",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
        parse_mode="Markdown")

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
        f"📊 *ADMIN STATUS*\n\n"
        f"👥 Users: {total_users}\n"
        f"⏳ Pending: {len(pending_users)}\n"
        f"📱 Saved: {total_numbers}\n"
        f"🔐 OTPs: {total_otps}\n"
        f"📡 Available: {available}\n"
        f"✅ Running!",
        parse_mode="Markdown"
    )

async def auto_scrape():
    """Background scraper - runs every 15 seconds"""
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
    print("=" * 50)
    print("🤖 OTP FORWARDER BOT")
    print("=" * 50)
    
    load_data()
    
    print(f"✅ Users: {len(approved_users)}")
    print(f"🌐 Sites: {len(SITES)}")
    print("=" * 50)
    
    # Start background scraper
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(auto_scrape())
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot running!")
    app.run_polling()

if __name__ == "__main__":
    main()
