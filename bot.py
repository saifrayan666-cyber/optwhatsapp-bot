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

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8947431324:AAEtIHkk_TTAmWEOIcY11_9FP3Xiv0FelIY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 1978055060))
# ===============================================

DATA_FILE = "bot_data.json"

# Data storage
pending_users = {}
approved_users = {}
blocked_users = {}
all_numbers = []
otp_storage = {}

# Country list
COUNTRIES = ["US", "UK", "CA", "AU", "DE", "FR", "IN"]

def load_data():
    global pending_users, approved_users, blocked_users, all_numbers, otp_storage
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                pending_users = data.get("pending_users", {})
                approved_users = data.get("approved_users", {})
                blocked_users = data.get("blocked_users", {})
                all_numbers = data.get("all_numbers", [])
                otp_storage = data.get("otp_storage", {})
    except Exception as e:
        print(f"Load error: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "pending_users": pending_users,
                "approved_users": approved_users,
                "blocked_users": blocked_users,
                "all_numbers": all_numbers,
                "otp_storage": otp_storage
            }, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

def extract_otp(text):
    if not text:
        return None
    patterns = [
        r'\b(\d{5,6})\b',
        r'[Oo][Tt][Pp][:\s]*(\d{4,6})',
        r'[Cc][Oo][Dd][Ee][:\s]*(\d{4,6})',
        r'verification code[:\s]*(\d{4,6})',
        r'(\d{6})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            otp = match.group(1)
            if otp and otp.isdigit() and 4 <= len(otp) <= 6:
                return otp
    return None

def extract_numbers(text):
    phones = re.findall(r'\+?[\d\s\-\(\)]{10,20}', text)
    clean = []
    for p in phones:
        num = re.sub(r'[^\d\+]', '', p)
        if len(num) >= 10 and num not in clean:
            clean.append(num)
    return clean[:10]

def scrape_sites():
    global all_numbers, otp_storage
    
    urls = [
        "https://getsms.cc",
        "https://receive-sms-online.info/",
        "https://temp-number.org/",
        "https://sms-receive.net/"
    ]
    
    new_otps = []
    
    for url in urls:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            r = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            text = soup.get_text()
            
            # Get numbers
            nums = extract_numbers(text)
            for n in nums:
                if n not in all_numbers:
                    all_numbers.append(n)
            
            # Get OTPs
            lines = text.split('\n')
            for line in lines:
                otp = extract_otp(line)
                if otp:
                    if otp not in otp_storage:
                        otp_storage[otp] = {
                            "otp": otp,
                            "message": line[:200],
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "source": url.split('/')[2]
                        }
                        new_otps.append(otp)
                        
        except Exception as e:
            print(f"Scrape error {url}: {e}")
    
    all_numbers = list(set(all_numbers))[:50]
    save_data()
    return new_otps

# ==================== ADMIN PANEL ====================

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("⏳ Pending", callback_data="admin_pending")],
        [InlineKeyboardButton("🚫 Blocked", callback_data="admin_blocked")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📱 Numbers", callback_data="admin_numbers")],
        [InlineKeyboardButton("🔐 OTPs", callback_data="admin_otps")],
        [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ]
    
    await update.message.reply_text("🔧 *ADMIN PANEL*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "admin_users":
        if not approved_users:
            await query.edit_message_text("📭 No users found.")
            return
        msg = "👥 *USERS*\n\n"
        for uid, u in approved_users.items():
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n  @{u.get('username', 'N/A')}\n  Numbers: {len(u.get('numbers', []))}\n\n"
        await query.edit_message_text(msg[:4000], parse_mode="Markdown")
    
    elif data == "admin_pending":
        if not pending_users:
            await query.edit_message_text("📭 No pending requests.")
            return
        msg = "⏳ *PENDING*\n\n"
        for uid, u in pending_users.items():
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n  @{u.get('username', 'N/A')}\n\n"
        await query.edit_message_text(msg[:4000], parse_mode="Markdown")
    
    elif data == "admin_blocked":
        if not blocked_users:
            await query.edit_message_text("📭 No blocked users.")
            return
        msg = "🚫 *BLOCKED*\n\n"
        for uid, u in blocked_users.items():
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n\n"
        await query.edit_message_text(msg[:4000], parse_mode="Markdown")
    
    elif data == "admin_stats":
        msg = f"📊 *STATS*\n\n"
        msg += f"👥 Users: {len(approved_users)}\n"
        msg += f"⏳ Pending: {len(pending_users)}\n"
        msg += f"🚫 Blocked: {len(blocked_users)}\n"
        msg += f"📱 Numbers: {len(all_numbers)}\n"
        msg += f"🔐 OTPs: {len(otp_storage)}\n"
        msg += f"🌐 Sites: 4\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_broadcast":
        await query.edit_message_text("📢 *BROADCAST*\n\nSend: /msg [your message]")
    
    elif data == "admin_numbers":
        if not all_numbers:
            await query.edit_message_text("📭 No numbers found.")
            return
        msg = "📱 *NUMBERS*\n\n"
        for n in all_numbers[:20]:
            msg += f"• `{n}`\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_otps":
        if not otp_storage:
            await query.edit_message_text("🔐 No OTPs found.")
            return
        msg = "🔐 *OTPs*\n\n"
        for otp, info in list(otp_storage.items())[-15:]:
            msg += f"• `{otp}`\n  {info['time'][:16]}\n  {info['source']}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_close":
        await query.edit_message_text("🔒 Panel closed.")

# ==================== USER COMMANDS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name = update.effective_user.first_name or "User"
    username = update.effective_user.username or ""
    
    if user_id in blocked_users:
        await update.message.reply_text("🚫 You are blocked!")
        return
    
    if user_id in approved_users:
        await main_menu(update, user_id)
        return
    
    if user_id in pending_users:
        await update.message.reply_text("⏳ Request pending. Wait for admin approval.")
        return
    
    pending_users[user_id] = {"name": name, "username": username, "time": str(datetime.now())}
    save_data()
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 *NEW USER*\n👤 {name}\n🆔 `{user_id}`\n📛 @{username}",
        parse_mode="Markdown"
    )
    
    await update.message.reply_text("👋 Request sent to admin. You'll be notified when approved.")

async def main_menu(update, user_id):
    user_data = approved_users.get(user_id, {})
    num_count = len(user_data.get("numbers", []))
    
    keyboard = [
        [InlineKeyboardButton("📱 Get Number", callback_data="get_number")],
        [InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("🔐 My OTPs", callback_data="my_otps")],
        [InlineKeyboardButton("❌ Remove Number", callback_data="remove_number")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    msg = f"🤖 *OTP Bot*\n✅ Active\n📱 {num_count}/5 numbers\n\nChoose:"
    
    if isinstance(update, Update):
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    data = query.data
    
    if user_id not in approved_users:
        await query.message.reply_text("❌ Not approved! Contact admin.")
        return
    
    if data == "get_number":
        if not all_numbers:
            await query.edit_message_text("📭 No numbers. Fetching...")
            scrape_sites()
        
        if not all_numbers:
            await query.edit_message_text("📭 No numbers available. Try again.")
            return
        
        user_nums = [n["number"] for n in approved_users[user_id].get("numbers", [])]
        available = [n for n in all_numbers if n not in user_nums][:10]
        
        if not available:
            await query.edit_message_text("📭 You saved all numbers! Remove one first.")
            return
        
        keyboard = []
        for n in available:
            keyboard.append([InlineKeyboardButton(f"📱 {n}", callback_data=f"view_{n}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
        
        await query.edit_message_text("📱 *Available Numbers*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data.startswith("view_"):
        number = data.replace("view_", "")
        await show_otps(query, user_id, number, 0)
    
    elif data.startswith("save_"):
        number = data.replace("save_", "")
        user_data = approved_users[user_id]
        user_nums = user_data.get("numbers", [])
        
        if len(user_nums) >= 5:
            await query.edit_message_text("❌ Max 5 numbers!")
            return
        
        if number not in [n["number"] for n in user_nums]:
            user_nums.append({"number": number, "saved_at": str(datetime.now())})
            user_data["numbers"] = user_nums
            save_data()
            await query.edit_message_text(f"✅ Saved `{number}`", parse_mode="Markdown")
    
    elif data == "my_numbers":
        user_data = approved_users.get(user_id, {})
        user_nums = user_data.get("numbers", [])
        
        if not user_nums:
            await query.edit_message_text("📭 No saved numbers.")
            return
        
        msg = "📱 *Your Numbers*\n\n"
        for i, n in enumerate(user_nums, 1):
            otp_count = len([o for o in user_data.get("otp_history", []) if o["number"] == n["number"]])
            msg += f"{i}. `{n['number']}`\n   Saved: {n['saved_at'][:16]}\n   OTPs: {otp_count}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔐 View OTPs", callback_data="my_otps")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data == "my_otps":
        user_data = approved_users.get(user_id, {})
        otps = user_data.get("otp_history", [])
        
        if not otps:
            await query.edit_message_text("🔐 No OTPs yet.")
            return
        
        msg = "🔐 *Your OTPs*\n\n"
        for o in otps[-15:]:
            msg += f"• `{o['otp']}`\n  📱 {o['number']}\n  🕐 {o['time'][:16]}\n  🌐 {o.get('source', 'Unknown')}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "remove_number":
        user_data = approved_users.get(user_id, {})
        user_nums = user_data.get("numbers", [])
        
        if not user_nums:
            await query.edit_message_text("📭 No numbers to remove.")
            return
        
        keyboard = []
        for i, n in enumerate(user_nums):
            keyboard.append([InlineKeyboardButton(f"🗑 {n['number']}", callback_data=f"remove_{i}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
        
        await query.edit_message_text("🗑 *Remove Number*", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("remove_"):
        idx = int(data.split("_")[1])
        user_data = approved_users[user_id]
        user_nums = user_data.get("numbers", [])
        
        if idx < len(user_nums):
            removed = user_nums.pop(idx)
            user_data["numbers"] = user_nums
            save_data()
            await query.edit_message_text(f"✅ Removed `{removed['number']}`", parse_mode="Markdown")
    
    elif data.startswith("next_"):
        parts = data.split("_")
        if len(parts) >= 3:
            number = parts[1]
            page = int(parts[2])
            await show_otps(query, user_id, number, page)
    
    elif data.startswith("prev_"):
        parts = data.split("_")
        if len(parts) >= 3:
            number = parts[1]
            page = int(parts[2])
            await show_otps(query, user_id, number, page)
    
    elif data == "back_menu":
        await main_menu(query, user_id)
    
    elif data == "help":
        await query.edit_message_text(
            "📖 *HELP*\n\n"
            "1. Get Number → Choose a number\n"
            "2. View OTPs → See codes\n"
            "3. Save Number → Add to your list\n"
            "4. My Numbers → View saved\n"
            "5. My OTPs → Your history\n\n"
            "Max 5 numbers.\nNumbers are public.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="Markdown"
        )

async def show_otps(query, user_id, number, page):
    otps = [o for o in otp_storage.values() if o.get("message", "").find(number) != -1]
    
    if not otps:
        await query.edit_message_text(f"📭 No OTPs for {number}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="get_number")]]))
        return
    
    per_page = 8
    total = len(otps)
    start = page * per_page
    end = min(start + per_page, total)
    page_otps = otps[start:end]
    
    msg = f"🔐 *OTPs for {number}*\n\n"
    for i, o in enumerate(page_otps, start + 1):
        msg += f"{i}. `{o['otp']}`\n   🕐 {o['time'][:16]}\n   🌐 {o['source']}\n\n"
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"prev_{number}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"next_{number}_{page+1}"))
    
    keyboard = []
    if nav:
        keyboard.append(nav)
    
    user_nums = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    if number not in user_nums:
        keyboard.append([InlineKeyboardButton("💾 Save Number", callback_data=f"save_{number}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="get_number")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    # Save to history
    user_data = approved_users.get(user_id, {})
    for o in page_otps:
        if o["otp"] not in [h["otp"] for h in user_data.get("otp_history", [])]:
            if "otp_history" not in user_data:
                user_data["otp_history"] = []
            user_data["otp_history"].append({
                "otp": o["otp"],
                "number": number,
                "time": o["time"],
                "source": o["source"]
            })
    save_data()

async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    
    if user_id == str(ADMIN_ID) and text.startswith("/msg "):
        msg = text.replace("/msg ", "")
        sent = 0
        for uid in approved_users.keys():
            try:
                await context.bot.send_message(chat_id=int(uid), text=f"📢 {msg}")
                sent += 1
                await asyncio.sleep(0.1)
            except:
                pass
        await update.message.reply_text(f"✅ Sent to {sent} users")
    
    elif user_id not in approved_users and user_id not in pending_users:
        await update.message.reply_text("❌ Use /start to request access")

async def scrape_loop():
    while True:
        try:
            new = scrape_sites()
            if new:
                print(f"Found {len(new)} new OTPs")
        except Exception as e:
            print(f"Scrape error: {e}")
        await asyncio.sleep(15)

def main():
    print("=" * 50)
    print("🤖 OTP BOT STARTING...")
    print("=" * 50)
    
    load_data()
    
    print(f"✅ Users: {len(approved_users)}")
    print(f"📱 Numbers: {len(all_numbers)}")
    print(f"🔐 OTPs: {len(otp_storage)}")
    print("=" * 50)
    
    # Start scraper
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(scrape_loop())
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(admin_buttons, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(CommandHandler("msg", msg_handler))
    
    print("✅ Bot running! /start to begin")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
