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
                print(f"📂 Loaded: {len(approved_users)} users, {len(all_numbers)} numbers, {len(otp_storage)} OTPs")
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
        r'(\d{5})',
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
                        print(f"🔐 New OTP: {otp} from {url.split('/')[2]}")
                        
        except Exception as e:
            print(f"Scrape error {url}: {e}")
    
    all_numbers = list(set(all_numbers))[:50]
    save_data()
    return new_otps

# ==================== ADMIN COMMANDS ====================

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
    
    await update.message.reply_text("🔧 *ADMIN PANEL*\n\nChoose an option:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct approve command: /approve user_id"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    try:
        target_id = context.args[0]
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
            
            await update.message.reply_text(f"✅ User `{target_id}` approved successfully!", parse_mode="Markdown")
            await context.bot.send_message(
                chat_id=int(target_id),
                text="✅ *APPROVED!*\n\nYour request has been approved by admin.\nSend /start to begin using the bot.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ User `{target_id}` not found in pending list!", parse_mode="Markdown")
    except IndexError:
        await update.message.reply_text("❌ Usage: `/approve [user_id]`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct reject command: /reject user_id"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    try:
        target_id = context.args[0]
        if target_id in pending_users:
            del pending_users[target_id]
            save_data()
            await update.message.reply_text(f"❌ User `{target_id}` rejected!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ User `{target_id}` not found!", parse_mode="Markdown")
    except IndexError:
        await update.message.reply_text("❌ Usage: `/reject [user_id]`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct block command: /block user_id"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    try:
        target_id = context.args[0]
        if target_id in approved_users:
            user_data = approved_users[target_id]
            blocked_users[target_id] = user_data
            del approved_users[target_id]
            save_data()
            await update.message.reply_text(f"🚫 User `{target_id}` blocked!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ User `{target_id}` not found!", parse_mode="Markdown")
    except IndexError:
        await update.message.reply_text("❌ Usage: `/block [user_id]`", parse_mode="Markdown")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct unblock command: /unblock user_id"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    try:
        target_id = context.args[0]
        if target_id in blocked_users:
            user_data = blocked_users[target_id]
            approved_users[target_id] = user_data
            del blocked_users[target_id]
            save_data()
            await update.message.reply_text(f"🔓 User `{target_id}` unblocked!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ User `{target_id}` not found in blocked list!", parse_mode="Markdown")
    except IndexError:
        await update.message.reply_text("❌ Usage: `/unblock [user_id]`", parse_mode="Markdown")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users: /users"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    if not approved_users:
        await update.message.reply_text("📭 No users found.")
        return
    
    msg = "👥 *ALL USERS*\n\n"
    for uid, u in approved_users.items():
        msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n  @{u.get('username', 'N/A')}\n  Numbers: {len(u.get('numbers', []))}\n\n"
        if len(msg) > 3500:
            msg += "..."
            break
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# ==================== ADMIN PANEL BUTTONS ====================

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "admin_users":
        if not approved_users:
            await query.edit_message_text("📭 No users found.")
            return
        msg = "👥 *USERS*\n\n"
        for uid, u in list(approved_users.items())[:20]:
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n  @{u.get('username', 'N/A')}\n  Numbers: {len(u.get('numbers', []))}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_pending":
        if not pending_users:
            await query.edit_message_text("📭 No pending requests.")
            return
        msg = "⏳ *PENDING REQUESTS*\n\n"
        for uid, u in pending_users.items():
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n  @{u.get('username', 'N/A')}\n  Time: {u.get('time', 'Unknown')[:16]}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_blocked":
        if not blocked_users:
            await query.edit_message_text("📭 No blocked users.")
            return
        msg = "🚫 *BLOCKED USERS*\n\n"
        for uid, u in blocked_users.items():
            msg += f"• {u.get('name', 'Unknown')}\n  ID: `{uid}`\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_stats":
        msg = f"📊 *STATISTICS*\n\n"
        msg += f"👥 Approved Users: {len(approved_users)}\n"
        msg += f"⏳ Pending Users: {len(pending_users)}\n"
        msg += f"🚫 Blocked Users: {len(blocked_users)}\n"
        msg += f"📱 Available Numbers: {len(all_numbers)}\n"
        msg += f"🔐 Total OTPs: {len(otp_storage)}\n"
        msg += f"🌐 Active Sites: 4\n"
        msg += f"🕐 Last Update: {datetime.now().strftime('%H:%M:%S')}"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_broadcast":
        await query.edit_message_text("📢 *BROADCAST*\n\nUse: `/msg [your message]`\n\nExample: `/msg Hello everyone!`", parse_mode="Markdown")
    
    elif data == "admin_numbers":
        if not all_numbers:
            await query.edit_message_text("📭 No numbers found.")
            return
        msg = "📱 *AVAILABLE NUMBERS*\n\n"
        for n in all_numbers[:20]:
            msg += f"• `{n}`\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_otps":
        if not otp_storage:
            await query.edit_message_text("🔐 No OTPs found.")
            return
        msg = "🔐 *RECENT OTPs*\n\n"
        for otp, info in list(otp_storage.items())[-15:]:
            msg += f"• `{otp}`\n  {info['time'][:16]}\n  {info['source']}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "admin_close":
        await query.edit_message_text("🔒 Admin panel closed.")

# ==================== USER COMMANDS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name = update.effective_user.first_name or "User"
    username = update.effective_user.username or ""
    
    if user_id in blocked_users:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    if user_id in approved_users:
        await main_menu(update, user_id)
        return
    
    if user_id in pending_users:
        await update.message.reply_text("⏳ Your request is pending. Please wait for admin approval.")
        return
    
    # Send to admin
    pending_users[user_id] = {"name": name, "username": username, "time": str(datetime.now())}
    save_data()
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 *NEW USER*\n\n👤 {name}\n🆔 `{user_id}`\n📛 @{username}\n🕐 {datetime.now().strftime('%H:%M:%S')}\n\nUse: /approve {user_id}",
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        "👋 *Welcome!*\n\nYour request has been sent to admin.\nYou will be notified when approved.\n\nThank you for your patience! 🙏",
        parse_mode="Markdown"
    )

async def main_menu(update, user_id):
    user_data = approved_users.get(user_id, {})
    num_count = len(user_data.get("numbers", []))
    otp_count = len(user_data.get("otp_history", []))
    
    keyboard = [
        [InlineKeyboardButton("📱 Get Number", callback_data="get_number")],
        [InlineKeyboardButton("📋 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("🔐 My OTPs", callback_data="my_otps")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="remove_number")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    msg = f"🤖 *OTP Bot*\n\n✅ Status: Active\n📱 Numbers: {num_count}/5\n🔐 Total OTPs: {otp_count}\n\n👇 Choose an option:"
    
    if isinstance(update, Update):
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        try:
            await update.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except:
            pass

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    data = query.data
    
    if user_id not in approved_users:
        await query.message.reply_text("❌ Not approved! Contact admin.")
        return
    
    if data == "get_number":
        # Scrape fresh
        scrape_sites()
        
        if not all_numbers:
            await query.edit_message_text("📭 No numbers available. Please try again in 30 seconds.")
            return
        
        user_nums = [n["number"] for n in approved_users[user_id].get("numbers", [])]
        available = [n for n in all_numbers if n not in user_nums][:10]
        
        if not available:
            await query.edit_message_text("📭 You have saved all available numbers! Remove one to add more.")
            return
        
        keyboard = []
        for n in available:
            keyboard.append([InlineKeyboardButton(f"📱 {n}", callback_data=f"view_{n}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_menu")])
        
        await query.edit_message_text("📱 *Available Numbers*\n\nClick a number to view its OTPs:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data.startswith("view_"):
        number = data.replace("view_", "")
        await show_otps(query, user_id, number, 0)
    
    elif data.startswith("save_"):
        number = data.replace("save_", "")
        user_data = approved_users[user_id]
        user_nums = user_data.get("numbers", [])
        
        if len(user_nums) >= 5:
            await query.edit_message_text("❌ Limit reached! Maximum 5 numbers per user.")
            return
        
        if number not in [n["number"] for n in user_nums]:
            user_nums.append({"number": number, "saved_at": str(datetime.now())})
            user_data["numbers"] = user_nums
            save_data()
            await query.edit_message_text(f"✅ Number `{number}` saved successfully!", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"⚠️ Number `{number}` already saved!", parse_mode="Markdown")
    
    elif data == "my_numbers":
        user_data = approved_users.get(user_id, {})
        user_nums = user_data.get("numbers", [])
        
        if not user_nums:
            await query.edit_message_text("📭 You haven't saved any numbers yet.\n\nUse 'Get Number' to add numbers.")
            return
        
        msg = "📱 *Your Saved Numbers*\n\n"
        for i, n in enumerate(user_nums, 1):
            otp_count = len([o for o in user_data.get("otp_history", []) if o["number"] == n["number"]])
            msg += f"{i}. `{n['number']}`\n   📅 Saved: {n['saved_at'][:16]}\n   🔐 OTPs: {otp_count}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔐 View All OTPs", callback_data="my_otps")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data == "my_otps":
        user_data = approved_users.get(user_id, {})
        otps = user_data.get("otp_history", [])
        
        if not otps:
            await query.edit_message_text("🔐 No OTPs received yet.\n\nSave a number and wait for OTPs to arrive.")
            return
        
        msg = "🔐 *Your OTP History* (Last 15)\n\n"
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
        
        await query.edit_message_text("🗑 *Remove Number*\n\nSelect which number to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("remove_"):
        idx = int(data.split("_")[1])
        user_data = approved_users[user_id]
        user_nums = user_data.get("numbers", [])
        
        if idx < len(user_nums):
            removed = user_nums.pop(idx)
            user_data["numbers"] = user_nums
            save_data()
            await query.edit_message_text(f"✅ Number `{removed['number']}` removed!", parse_mode="Markdown")
    
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
            "📖 *HOW TO USE*\n\n"
            "1️⃣ *Get Number* - View available numbers\n"
            "2️⃣ *View OTPs* - Click a number to see its OTPs\n"
            "3️⃣ *Save Number* - Add number to your list\n"
            "4️⃣ *My Numbers* - View your saved numbers\n"
            "5️⃣ *My OTPs* - See all OTPs you've received\n"
            "6️⃣ *Remove Number* - Delete a saved number\n\n"
            "⚠️ *Limits & Notes*\n"
            "• Maximum 5 numbers per user\n"
            "• Numbers are public (shared with others)\n"
            "• For testing/educational use only\n"
            "• New OTPs appear automatically every 15 seconds\n\n"
            "🔧 *Commands*\n"
            "/start - Main menu\n"
            "/admin - Admin panel (admin only)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]),
            parse_mode="Markdown"
        )

async def show_otps(query, user_id, number, page):
    # Find OTPs for this number
    otps = [o for o in otp_storage.values() if number in o.get("message", "")]
    
    if not otps:
        await query.edit_message_text(f"📭 No OTPs found for `{number}`\n\nCheck back later.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="get_number")]]), parse_mode="Markdown")
        return
    
    per_page = 8
    total = len(otps)
    start = page * per_page
    end = min(start + per_page, total)
    page_otps = otps[start:end]
    
    msg = f"🔐 *OTPs for {number}*\n\n"
    for i, o in enumerate(page_otps, start + 1):
        msg += f"{i}. `{o['otp']}`\n"
        msg += f"   🕐 {o['time'][:16]}\n"
        msg += f"   🌐 {o['source']}\n"
        msg += f"   📨 {o['message'][:60]}...\n\n"
    
    # Navigation buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Previous", callback_data=f"prev_{number}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"next_{number}_{page+1}"))
    
    keyboard = []
    if nav:
        keyboard.append(nav)
    
    # Save button
    user_nums = [n["number"] for n in approved_users.get(user_id, {}).get("numbers", [])]
    if number not in user_nums:
        keyboard.append([InlineKeyboardButton("💾 Save This Number", callback_data=f"save_{number}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Numbers", callback_data="get_number")])
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    # Save OTPs to user history
    user_data = approved_users.get(user_id, {})
    for o in page_otps:
        if o["otp"] not in [h["otp"] for h in user_data.get("otp_history", [])]:
            if "otp_history" not in user_data:
                user_data["otp_history"] = []
            user_data["otp_history"].append({
                "otp": o["otp"],
                "number": number,
                "time": o["time"],
                "source": o["source"],
                "message": o["message"][:100]
            })
    save_data()

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users: /msg message"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Admin only!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/msg [your message]`\n\nExample: `/msg Hello everyone!`", parse_mode="Markdown")
        return
    
    msg = " ".join(context.args)
    sent = 0
    failed = 0
    
    await update.message.reply_text(f"📢 Broadcasting...")
    
    for uid in approved_users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 *ANNOUNCEMENT*\n\n{msg}", parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1
    
    await update.message.reply_text(f"✅ Broadcast complete!\n\n📤 Sent: {sent}\n❌ Failed: {failed}")

async def scrape_loop():
    """Background scraper"""
    print("🔄 Auto-scrape started (every 15 seconds)")
    while True:
        try:
            new = scrape_sites()
            if new:
                print(f"✅ Found {len(new)} new OTPs at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"Scrape error: {e}")
        await asyncio.sleep(15)

# ==================== MAIN ====================

def main():
    print("=" * 55)
    print("🤖 OTP FORWARDER BOT v5.0")
    print("=" * 55)
    
    load_data()
    
    print(f"✅ Approved Users: {len(approved_users)}")
    print(f"⏳ Pending Users: {len(pending_users)}")
    print(f"🚫 Blocked Users: {len(blocked_users)}")
    print(f"📱 Available Numbers: {len(all_numbers)}")
    print(f"🔐 Stored OTPs: {len(otp_storage)}")
    print("=" * 55)
    
    # Start background scraper
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(scrape_loop())
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Admin commands
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("msg", broadcast_command))
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    
    # Handlers
    app.add_handler(CallbackQueryHandler(admin_buttons, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(buttons))
    
    print("✅ Bot is running!")
    print("📱 Commands: /start, /admin, /approve, /reject, /block, /unblock, /users, /msg")
    print("=" * 55)
    
    app.run_polling()

if __name__ == "__main__":
    main()
