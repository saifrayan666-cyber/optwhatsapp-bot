#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import asyncio
import subprocess
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==================== কনফিগারেশন ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8947431324:AAEtIHkk_TTAmWEOIcY11_9FP3Xiv0FelIY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 1978055060))
# ====================================================

DATA_FILE = "whatsapp_data.json"
user_sessions = {}
selected_number = None  # বর্তমানে সিলেক্টেড নম্বর

def load_data():
    """ডাটা লোড"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {"numbers": {}, "otp_history": [], "selected_number": None}

def save_data(data):
    """ডাটা সেভ"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except:
        pass

# ডাটা লোড
saved_data = load_data()
active_numbers = saved_data.get("numbers", {})
otp_history = saved_data.get("otp_history", [])
selected_number = saved_data.get("selected_number", None)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """স্টার্ট কমান্ড"""
    user_id = str(update.effective_user.id)
    
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("⛔ অনুমতি নেই!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📱 নম্বর সিলেক্ট করুন", callback_data="select_number")],
        [InlineKeyboardButton("➕ নতুন নম্বর যোগ করুন", callback_data="add_number")],
        [InlineKeyboardButton("📋 সব নম্বর দেখুন", callback_data="all_numbers")],
        [InlineKeyboardButton(f"🎯 সক্রিয়: {selected_number or 'কোনোটি নয়'}", callback_data="active_info")],
        [InlineKeyboardButton("📜 OTP ইতিহাস", callback_data="history")],
        [InlineKeyboardButton("🗑 নম্বর ডিলিট করুন", callback_data="delete_number")],
        [InlineKeyboardButton("❌ সব মনিটরিং বন্ধ", callback_data="stop_all")]
    ]
    
    active_count = sum(1 for n in active_numbers.values() if n.get("status") == "active")
    
    # বর্তমান সিলেক্টেড নম্বরের OTP কাউন্ট
    selected_otp_count = 0
    if selected_number and selected_number in active_numbers:
        selected_otp_count = len(active_numbers[selected_number].get("otps", []))
    
    await update.message.reply_text(
        f"🤖 **ওয়াটসঅ্যাপ OTP বট (মাল্টি-নম্বর)**\n\n"
        f"📊 **পরিসংখ্যান:**\n"
        f"├ 📱 মোট নম্বর: {len(active_numbers)}\n"
        f"├ ✅ সক্রিয়: {active_count}\n"
        f"├ 📜 মোট OTP: {len(otp_history)}\n"
        f"└ 🎯 সিলেক্টেড: {selected_number or 'না'}\n\n"
        f"✨ **বর্তমান সেটিংস:**\n"
        f"├ শুধু সিলেক্টেড নম্বরের OTP দেখাবে\n"
        f"├ বাকি নম্বরের OTP সেভ হবে কিন্তু দেখাবে না\n"
        f"└ সর্বোচ্চ ২৫+ নম্বর সাপোর্ট করে\n\n"
        f"🎯 **সিলেক্টেড নম্বরে OTP:** {selected_otp_count} টি\n\n"
        f"👇 নিচের অপশন থেকে বেছে নিন:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """বাটন হ্যান্ডলার"""
    global selected_number
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    
    if query.data == "select_number":
        if not active_numbers:
            await query.edit_message_text("❌ প্রথমে একটি নম্বর যোগ করুন!")
            return
        
        keyboard = []
        for number in active_numbers.keys():
            status = "✅" if active_numbers[number].get("status") == "active" else "❌"
            keyboard.append([InlineKeyboardButton(f"{status} {number}", callback_data=f"select_{number}")])
        keyboard.append([InlineKeyboardButton("🔙 পেছনে", callback_data="back")])
        
        await query.edit_message_text(
            "🎯 **নম্বর সিলেক্ট করুন**\n\n"
            "যে নম্বরের OTP দেখতে চান সেটি বেছে নিন:\n"
            "✅ = সক্রিয় | ❌ = নিষ্ক্রিয়",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("select_"):
        number = query.data.replace("select_", "")
        selected_number = number
        saved_data["selected_number"] = number
        save_data(saved_data)
        
        await query.edit_message_text(
            f"✅ **সিলেক্টেড:** `{number}`\n\n"
            f"এখন থেকে শুধুমাত্র এই নম্বরের OTP দেখাবে।\n"
            f"অন্য নম্বরের OTP সেভ হবে কিন্তু দেখাবে না।",
            parse_mode="Markdown"
        )
    
    elif query.data == "add_number":
        user_sessions[user_id] = {"step": "waiting_country"}
        await query.edit_message_text(
            "🌍 **নতুন নম্বর যোগ করুন**\n\n"
            "**কান্ট্রি কোড লিখুন:**\n\n"
            "🇧🇩 বাংলাদেশ → BD\n"
            "🇺🇸 যুক্তরাষ্ট্র → US\n"
            "🇮🇳 ভারত → IN\n"
            "🇬🇧 যুক্তরাজ্য → GB\n"
            "🇦🇪 সংযুক্ত আরব → AE\n"
            "🇸🇦 সৌদি আরব → SA\n\n"
            "কোড লিখুন:"
        )
    
    elif query.data == "all_numbers":
        await show_all_numbers(update, context)
    
    elif query.data == "history":
        await show_otp_history(update, context)
    
    elif query.data == "delete_number":
        if not active_numbers:
            await query.edit_message_text("❌ কোনো নম্বর নেই!")
            return
        
        keyboard = []
        for number in active_numbers.keys():
            keyboard.append([InlineKeyboardButton(f"🗑 {number}", callback_data=f"del_{number}")])
        keyboard.append([InlineKeyboardButton("🔙 পেছনে", callback_data="back")])
        
        await query.edit_message_text(
            "🗑 **নম্বর ডিলিট করুন**\n\n"
            "যে নম্বর ডিলিট করতে চান সেটি বেছে নিন:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("del_"):
        number = query.data.replace("del_", "")
        if number in active_numbers:
            del active_numbers[number]
            # ওটিপি হিস্ট্রি থেকে ওই নম্বরের ডাটা রিমুভ
            global otp_history
            otp_history = [h for h in otp_history if h.get("number") != number]
            
            if selected_number == number:
                selected_number = None
                saved_data["selected_number"] = None
            
            save_data({"numbers": active_numbers, "otp_history": otp_history, "selected_number": selected_number})
            await query.edit_message_text(f"✅ `{number}` ডিলিট করা হয়েছে!", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ `{number}` পাওয়া যায়নি!", parse_mode="Markdown")
    
    elif query.data == "stop_all":
        for num in active_numbers:
            active_numbers[num]["status"] = "stopped"
        save_data({"numbers": active_numbers, "otp_history": otp_history, "selected_number": selected_number})
        await query.edit_message_text("✅ সব নম্বরের মনিটরিং বন্ধ করা হয়েছে।")
    
    elif query.data == "active_info":
        if selected_number and selected_number in active_numbers:
            data = active_numbers[selected_number]
            await query.edit_message_text(
                f"🎯 **সক্রিয় নম্বর তথ্য**\n\n"
                f"📱 নম্বর: `{selected_number}`\n"
                f"├ স্ট্যাটাস: {data.get('status')}\n"
                f"├ সংযুক্ত: {data.get('connected_at', 'N/A')[:16]}\n"
                f"├ OTP পাওয়া: {len(data.get('otps', []))} টি\n"
                f"└ সর্বশেষ OTP: {data.get('otps', [])[-1].get('otp') if data.get('otps') else 'N/A'}\n\n"
                f"✅ শুধুমাত্র এই নম্বরের OTP দেখানো হবে।",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ কোনো নম্বর সিলেক্ট করা নেই!")

async def show_all_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """সব নম্বর দেখানো"""
    if not active_numbers:
        await update.callback_query.edit_message_text("📭 কোনো নম্বর যোগ করা হয়নি!")
        return
    
    message = "📱 **সব নম্বর সমূহ:**\n\n"
    for number, data in active_numbers.items():
        status_icon = "✅" if data.get("status") == "active" else "❌"
        selected_icon = "🎯" if selected_number == number else "  "
        message += f"{selected_icon} {status_icon} `{number}`\n"
        message += f"   ├ OTP: {len(data.get('otps', []))} টি\n"
        message += f"   └ যোগ: {data.get('connected_at', 'N/A')[:16]}\n\n"
    
    await update.callback_query.edit_message_text(message, parse_mode="Markdown")

async def show_otp_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OTP ইতিহাস দেখানো"""
    if not otp_history:
        await update.callback_query.edit_message_text("📭 এখনো কোনো OTP পাওয়া যায়নি!")
        return
    
    # শুধু সিলেক্টেড নম্বরের ইতিহাস দেখাবে
    if selected_number:
        filtered_history = [h for h in otp_history if h.get("number") == selected_number]
    else:
        filtered_history = otp_history
    
    if not filtered_history:
        await update.callback_query.edit_message_text(f"📭 `{selected_number}` নম্বরে এখনো কোনো OTP আসেনি!", parse_mode="Markdown")
        return
    
    message = f"📜 **OTP ইতিহাস**\n"
    if selected_number:
        message += f"🎯 নম্বর: `{selected_number}`\n\n"
    else:
        message += f"🎯 সব নম্বর\n\n"
    
    for i, otp_data in enumerate(filtered_history[-15:], 1):
        message += f"{i}. `{otp_data['otp']}`\n"
        message += f"   ├ 📱 {otp_data['number']}\n"
        message += f"   └ 🕐 {otp_data['time']}\n\n"
    
    buttons = [[InlineKeyboardButton("🔙 পেছনে", callback_data="back")]]
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """টেক্সট মেসেজ হ্যান্ডলার"""
    user_id = str(update.effective_user.id)
    msg_text = update.message.text.strip().upper()
    
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("⛔ অনুমতি নেই!")
        return
    
    if user_id not in user_sessions:
        await update.message.reply_text("❌ /start দিন এবং মেনু থেকে বেছে নিন।")
        return
    
    step = user_sessions[user_id].get("step")
    
    if step == "waiting_country":
        if len(msg_text) == 2 and msg_text.isalpha():
            user_sessions[user_id]["country"] = msg_text
            user_sessions[user_id]["step"] = "waiting_number"
            await update.message.reply_text(
                f"✅ কান্ট্রি: {msg_text}\n\n"
                f"📞 **নম্বর লিখুন** (কান্ট্রি কোড ছাড়া):\n"
                f"উদাহরণ: `14343597530`\n\nনম্বর লিখুন:",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ ২ ডিজিটের কান্ট্রি কোড দিন! (BD, US, IN...)")
    
    elif step == "waiting_number":
        if msg_text.isdigit() and len(msg_text) >= 9:
            full_number = f"{user_sessions[user_id]['country']}{msg_text}"
            
            if full_number not in active_numbers and len(active_numbers) < 30:
                active_numbers[full_number] = {
                    "status": "active",
                    "connected_at": str(datetime.now()),
                    "otps": []
                }
                save_data({"numbers": active_numbers, "otp_history": otp_history, "selected_number": selected_number})
                await update.message.reply_text(
                    f"✅ **নম্বর যোগ করা হয়েছে:** `{full_number}`\n\n"
                    f"এখন এই নম্বরটি সিলেক্ট করুন OTP দেখার জন্য।\n"
                    f"/start → 'নম্বর সিলেক্ট করুন' মেনু ব্যবহার করুন।",
                    parse_mode="Markdown"
                )
            elif full_number in active_numbers:
                await update.message.reply_text(f"⚠️ `{full_number}` ইতিমধ্যে আছে!", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ সর্বোচ্চ ২৫টি নম্বর যোগ করা যাবে!\nবর্তমানে {len(active_numbers)} টি আছে।")
            
            del user_sessions[user_id]
        else:
            await update.message.reply_text("❌ সঠিক নম্বর দিন! (কমপক্ষে ৯ ডিজিট)")

# এমুলেটর কন্ট্রোল ফাংশন
async def add_to_emulator(number):
    """এমুলেটরে নম্বর যোগ করা"""
    try:
        # এমুলেটর কমান্ড
        cmd = f'adb shell am start -a android.intent.action.VIEW -d "https://wa.me/{number}"'
        subprocess.run(cmd, shell=True)
        return True
    except:
        return False

# এমুলেটর থেকে ওটিপি পড়ার ফাংশন (ADB + OCR)
async def get_otp_from_emulator():
    """এমুলেটর থেকে OTP পড়া"""
    try:
        # স্ক্রিনশট নেওয়া
        subprocess.run("adb shell screencap /sdcard/screen.png", shell=True)
        subprocess.run("adb pull /sdcard/screen.png screen.png", shell=True)
        
        # OCR ব্যবহার (যদি পাই-টেসেরাক্ট থাকে)
        try:
            import pytesseract
            from PIL import Image
            img = Image.open('screen.png')
            text = pytesseract.image_to_string(img)
            
            # OTP খোঁজা
            otp = extract_otp(text)
            if otp:
                return otp
        except:
            pass
        
        # নোটিফিকেশন চেক
        result = subprocess.run("adb shell dumpsys notification | grep -i 'whatsapp'", shell=True, capture_output=True, text=True)
        if result.stdout:
            otp = extract_otp(result.stdout)
            if otp:
                return otp
                
    except Exception as e:
        print(f"এমুলেটর ত্রুটি: {e}")
    
    return None

def extract_otp(text):
    """OTP বের করা"""
    if not text:
        return None
    
    patterns = [
        r'\b(\d{4,6})\b',
        r'[Oo][Tt][Pp][:\s]*(\d{4,6})',
        r'[Cc][Oo][Dd][Ee][:\s]*(\d{4,6})',
        r'[Pp][Ii][Nn][:\s]*(\d{4,6})',
        r'(\d{4,6}) is your',
        r'verification code[:\s]*(\d{4,6})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            otp = match.group(1)
            if otp and otp.isdigit() and 4 <= len(otp) <= 6:
                return otp
    return None

async def monitor_emulator():
    """এমুলেটর মনিটরিং"""
    global otp_history, selected_number
    
    seen_otps = set()
    
    while True:
        try:
            otp = await get_otp_from_emulator()
            
            if otp and otp not in seen_otps:
                seen_otps.add(otp)
                time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # কোন নম্বর থেকে এসেছে তা শনাক্ত করার চেষ্টা
                number = "অজানা"
                for num in active_numbers:
                    if num in str(otp) or num in str(seen_otps):
                        number = num
                        break
                
                # OTP সেভ করা
                otp_history.append({
                    "number": number,
                    "otp": otp,
                    "time": time_now
                })
                
                # নম্বরের নিজস্ব হিস্ট্রিতে যোগ
                if number in active_numbers:
                    active_numbers[number]["otps"].append({"otp": otp, "time": time_now})
                
                save_data({"numbers": active_numbers, "otp_history": otp_history, "selected_number": selected_number})
                
                # শুধু সিলেক্টেড নম্বরের OTP দেখানো
                if selected_number and number == selected_number:
                    await send_otp_to_telegram(otp, number, time_now)
                elif not selected_number:
                    await send_otp_to_telegram(otp, number, time_now)
                else:
                    # সিলেক্টেড না হলে শুধু সেভ করবে, দেখাবে না
                    print(f"OTP সেভ করা হয়েছে (দেখানো হয়নি): {otp} - {number}")
                    
        except Exception as e:
            print(f"মনিটরিং ত্রুটি: {e}")
        
        await asyncio.sleep(3)

async def send_otp_to_telegram(otp, number, time):
    """OTP টেলিগ্রামে পাঠানো"""
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔐 **নতুন OTP!**\n\n"
             f"╔══════════════════════╗\n"
             f"║                      ║\n"
             f"║     `{otp}`      ║\n"
             f"║                      ║\n"
             f"╚══════════════════════╝\n\n"
             f"📱 **নম্বর:** `{number}`\n"
             f"🕐 **সময়:** {time}\n\n"
             f"📋 **কপি করুন:** `{otp}`",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("⛔ অনুমতি নেই!")
        return
    
    await update.message.reply_text(
        f"📊 **বট স্ট্যাটাস**\n\n"
        f"├ 📱 নম্বর: {len(active_numbers)}/30\n"
        f"├ 📜 OTP: {len(otp_history)} টি\n"
        f"├ 🎯 সিলেক্টেড: {selected_number or 'না'}\n"
        f"└ 🕐 সময়: {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"✅ বট চালু আছে!\n"
        f"📱 এমুলেটর: {'চালু' if check_emulator() else 'বন্ধ'}",
        parse_mode="Markdown"
    )

def check_emulator():
    """এমুলেটর চেক"""
    try:
        result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
        return "emulator" in result.stdout or "device" in result.stdout
    except:
        return False

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **কমান্ড সমূহ:**\n\n"
        "/start - মেনু দেখুন\n"
        "/status - বটের অবস্থা\n"
        "/help - এই হেল্প\n\n"
        "🎯 **নম্বর সিলেক্ট করুন:**\n"
        "├ সিলেক্ট করার পর শুধু ওই নম্বরের OTP দেখাবে\n"
        "├ অন্য নম্বরের OTP সেভ থাকবে কিন্তু দেখাবে না\n"
        "└ যেকোনো সময় পরিবর্তন করা যায়\n\n"
        "📱 **সর্বোচ্চ ২৫+ নম্বর সাপোর্ট করে**",
        parse_mode="Markdown"
    )

def main():
    print("=" * 50)
    print("🤖 মাল্টি-নম্বর ওয়াটসঅ্যাপ OTP বট")
    print("=" * 50)
    print(f"📱 নম্বর: {len(active_numbers)} টি")
    print(f"🎯 সিলেক্টেড: {selected_number}")
    print(f"📜 OTP: {len(otp_history)} টি")
    print(f"🔌 এমুলেটর: {'✅' if check_emulator() else '❌'}")
    print("=" * 50)
    
    # এমুলেটর মনিটরিং শুরু
    asyncio.create_task(monitor_emulator())
    
    # টেলিগ্রাম বট
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("✅ বট প্রস্তুত! রেলওয়েতে চলছে...")
    app.run_polling()

if __name__ == "__main__":
    main()