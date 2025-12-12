import os
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============== CONFIGURATION ===============
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
ADSGRAM_API_KEY = os.getenv('ADSGRAM_API_KEY')

# Social media links for tasks
TELEGRAM_CHANNEL = "https://t.me/your_channel"
TELEGRAM_GROUP = "https://t.me/your_group"
TWITTER_ACCOUNT = "https://twitter.com/your_account"

# Supabase headers
HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json'
}

# User states for conversation flow
user_states = {}

# =============== SUPABASE HELPER FUNCTIONS ===============

def supabase_get(table, filter_col=None, filter_val=None):
    """Get data from Supabase using REST API"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if filter_col and filter_val:
        url += f"?{filter_col}=eq.{filter_val}"
    
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        data = response.json()
        return data[0] if data else None
    return None

def supabase_insert(table, data):
    """Insert data to Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code == 201:
        return response.json()[0] if response.json() else None
    return None

def supabase_update(table, filter_col, filter_val, data):
    """Update data in Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filter_col}=eq.{filter_val}"
    response = requests.patch(url, headers=HEADERS, json=data)
    return response.status_code == 204

def supabase_rpc(function_name, params):
    """Call Supabase RPC function"""
    url = f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"
    response = requests.post(url, headers=HEADERS, json=params)
    return response.status_code == 204

# =============== HELPER FUNCTIONS ===============

def get_user(user_id):
    """Get user data from Supabase"""
    return supabase_get('users', 'telegram_id', user_id)

def create_user(user_id, username, referrer_id=None):
    """Create new user in database"""
    user_data = {
        'telegram_id': user_id,
        'username': username,
        'balance': 0.0,
        'last_daily': None,
        'last_ad_watch': None,
        'referrer_id': referrer_id,
        'referral_count': 0,
        'wallet_address': None,
        'has_withdrawn': False,
        'task_channel': False,
        'task_group': False,
        'task_twitter': False,
        'created_at': datetime.utcnow().isoformat()
    }
    
    result = supabase_insert('users', user_data)
    
    # Give referral bonus to referrer
    if referrer_id:
        supabase_rpc('add_balance', {'user_id': referrer_id, 'amount': 0.001})
        supabase_rpc('increment_referrals', {'user_id': referrer_id})
    
    return result

def update_balance(user_id, amount):
    """Add SUI coins to user balance"""
    supabase_rpc('add_balance', {'user_id': user_id, 'amount': amount})

def can_watch_ad(user_id):
    """Check if user can watch ad (3 hour cooldown)"""
    user = get_user(user_id)
    if not user or not user['last_ad_watch']:
        return True
    
    last_watch = datetime.fromisoformat(user['last_ad_watch'])
    now = datetime.utcnow()
    hours_passed = (now - last_watch).total_seconds() / 3600
    
    return hours_passed >= 3

def can_claim_daily(user_id):
    """Check if user can claim daily reward"""
    user = get_user(user_id)
    if not user or not user['last_daily']:
        return True
    
    last_daily = datetime.fromisoformat(user['last_daily'])
    now = datetime.utcnow()
    
    return now.date() > last_daily.date()

def get_time_until_next_ad(user_id):
    """Get time remaining until next ad watch"""
    user = get_user(user_id)
    if not user or not user['last_ad_watch']:
        return None
    
    last_watch = datetime.fromisoformat(user['last_ad_watch'])
    next_watch = last_watch + timedelta(hours=3)
    time_left = next_watch - datetime.utcnow()
    
    if time_left.total_seconds() <= 0:
        return None
    
    hours = int(time_left.total_seconds() // 3600)
    minutes = int((time_left.total_seconds() % 3600) // 60)
    
    return f"{hours}h {minutes}m"

# =============== KEYBOARD MENUS ===============

def main_menu_keyboard():
    """Main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data='balance'),
         InlineKeyboardButton("📋 Tasks", callback_data='tasks')],
        [InlineKeyboardButton("🎥 Watch Ad", callback_data='watch_ad'),
         InlineKeyboardButton("🎁 Daily Check-in", callback_data='daily')],
        [InlineKeyboardButton("👥 Referral", callback_data='referral'),
         InlineKeyboardButton("💳 Withdraw", callback_data='withdraw')],
        [InlineKeyboardButton("ℹ️ Info", callback_data='info')]
    ]
    return InlineKeyboardMarkup(keyboard)

def tasks_keyboard():
    """Tasks menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", callback_data='task_channel')],
        [InlineKeyboardButton("👥 Join Group", callback_data='task_group')],
        [InlineKeyboardButton("🐦 Follow Twitter", callback_data='task_twitter')],
        [InlineKeyboardButton("« Back", callback_data='back_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard():
    """Simple back button"""
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data='back_main')]]
    return InlineKeyboardMarkup(keyboard)

# =============== COMMAND HANDLERS ===============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"
    
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id == user_id:
                referrer_id = None
        except:
            pass
    
    user = get_user(user_id)
    if not user:
        user = create_user(user_id, username, referrer_id)
        welcome_msg = (
            f"🎉 *Welcome to SUI Airdrop Bot!*\n\n"
            f"Get ready to earn real SUI coins! 💎\n\n"
            f"🪙 Starting balance: *0.0 SUI*\n"
        )
        if referrer_id:
            welcome_msg += f"✅ Referral bonus added to your referrer!\n"
    else:
        welcome_msg = (
            f"👋 *Welcome back, {username}!*\n\n"
            f"Continue earning SUI coins! 🚀\n"
        )
    
    welcome_msg += (
        f"\n📊 *Your Stats:*\n"
        f"💰 Balance: `{user['balance']:.4f} SUI`\n"
        f"👥 Referrals: `{user['referral_count']}`\n\n"
        f"Choose an option below:"
    )
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("Please start the bot first with /start")
        return
    
    total_earned = user['referral_count'] * 0.001
    
    msg = (
        f"💰 *Your Balance*\n\n"
        f"🪙 Total: `{user['balance']:.4f} SUI`\n"
        f"👥 Referrals: `{user['referral_count']} users`\n"
        f"🎁 Referral Earnings: `{total_earned:.4f} SUI`\n"
        f"💳 Wallet: `{user['wallet_address'] or 'Not set'}`\n"
    )
    
    await update.message.reply_text(
        msg,
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )

# =============== CALLBACK HANDLERS ===============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await query.edit_message_text("Please start the bot first with /start")
        return
    
    if query.data == 'balance':
        total_earned = user['referral_count'] * 0.001
        msg = (
            f"💰 *Your Balance*\n\n"
            f"🪙 Total: `{user['balance']:.4f} SUI`\n"
            f"👥 Referrals: `{user['referral_count']} users`\n"
            f"🎁 Referral Earnings: `{total_earned:.4f} SUI`\n"
            f"💳 Wallet: `{user['wallet_address'] or 'Not set'}`\n"
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
    
    elif query.data == 'daily':
        if can_claim_daily(user_id):
            update_balance(user_id, 0.1)
            supabase_update('users', 'telegram_id', user_id, {
                'last_daily': datetime.utcnow().isoformat()
            })
            
            new_balance = user['balance'] + 0.1
            msg = (
                f"🎁 *Daily Check-in Successful!*\n\n"
                f"✅ Reward: `+0.1 SUI`\n"
                f"💰 New Balance: `{new_balance:.4f} SUI`\n\n"
                f"⏰ Come back tomorrow for more SUI!"
            )
        else:
            msg = (
                f"⏰ *Already Claimed Today!*\n\n"
                f"You've already claimed your daily reward.\n"
                f"Come back tomorrow for another 0.1 SUI!\n\n"
                f"💰 Current Balance: `{user['balance']:.4f} SUI`"
            )
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
    
    elif query.data == 'tasks':
        channel_status = "✅" if user['task_channel'] else "⏳"
        group_status = "✅" if user['task_group'] else "⏳"
        twitter_status = "✅" if user['task_twitter'] else "⏳"
        
        tasks_completed = sum([user['task_channel'], user['task_group'], user['task_twitter']])
        all_tasks_done = user['task_channel'] and user['task_group'] and user['task_twitter']
        
        msg = (
            f"📋 *Available Tasks*\n\n"
            f"{channel_status} Join Telegram Channel\n"
            f"{group_status} Join Telegram Group\n"
            f"{twitter_status} Follow Twitter\n\n"
            f"Progress: {tasks_completed}/3 tasks completed\n\n"
        )
        
        if all_tasks_done:
            msg += f"✅ All tasks completed! Reward claimed: 0.1 SUI"
        else:
            msg += f"⚠️ Complete ALL 3 tasks to earn 0.1 SUI!"
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=tasks_keyboard())
    
    elif query.data == 'task_channel':
        if user['task_channel']:
            msg = "✅ You've already completed this task!"
            await query.edit_message_text(msg, reply_markup=tasks_keyboard())
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Join Channel", url=TELEGRAM_CHANNEL)],
                [InlineKeyboardButton("✅ Verify", callback_data='verify_channel')],
                [InlineKeyboardButton("« Back", callback_data='tasks')]
            ]
            msg = (
                f"📢 *Join Telegram Channel*\n\n"
                f"1️⃣ Click 'Join Channel' button below\n"
                f"2️⃣ Join our official channel\n"
                f"3️⃣ Click 'Verify'\n"
            )
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'verify_channel':
        if not user['task_channel']:
            supabase_update('users', 'telegram_id', user_id, {'task_channel': True})
            
            user = get_user(user_id)
            all_completed = user['task_channel'] and user['task_group'] and user['task_twitter']
            
            if all_completed:
                update_balance(user_id, 0.1)
                new_balance = user['balance'] + 0.1
                msg = (
                    f"🎉 *ALL TASKS COMPLETED!*\n\n"
                    f"✅ Channel Task Verified\n\n"
                    f"Reward: `+0.1 SUI`\n"
                    f"💰 New Balance: `{new_balance:.4f} SUI`"
                )
            else:
                msg = f"✅ *Channel Task Verified!*\n\nComplete the remaining tasks to earn 0.1 SUI!"
        else:
            msg = "✅ You've already verified this task!"
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=tasks_keyboard())
    
    elif query.data == 'task_group':
        if user['task_group']:
            msg = "✅ You've already completed this task!"
            await query.edit_message_text(msg, reply_markup=tasks_keyboard())
        else:
            keyboard = [
                [InlineKeyboardButton("👥 Join Group", url=TELEGRAM_GROUP)],
                [InlineKeyboardButton("✅ Verify", callback_data='verify_group')],
                [InlineKeyboardButton("« Back", callback_data='tasks')]
            ]
            msg = (
                f"👥 *Join Telegram Group*\n\n"
                f"1️⃣ Click 'Join Group' button below\n"
                f"2️⃣ Join our community group\n"
                f"3️⃣ Click 'Verify'\n"
            )
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'verify_group':
        if not user['task_group']:
            supabase_update('users', 'telegram_id', user_id, {'task_group': True})
            
            user = get_user(user_id)
            all_completed = user['task_channel'] and user['task_group'] and user['task_twitter']
            
            if all_completed:
                update_balance(user_id, 0.1)
                new_balance = user['balance'] + 0.1
                msg = (
                    f"🎉 *ALL TASKS COMPLETED!*\n\n"
                    f"✅ Group Task Verified\n\n"
                    f"Reward: `+0.1 SUI`\n"
                    f"💰 New Balance: `{new_balance:.4f} SUI`"
                )
            else:
                msg = f"✅ *Group Task Verified!*\n\nComplete the remaining tasks to earn 0.1 SUI!"
        else:
            msg = "✅ You've already verified this task!"
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=tasks_keyboard())
    
    elif query.data == 'task_twitter':
        if user['task_twitter']:
            msg = "✅ You've already completed this task!"
            await query.edit_message_text(msg, reply_markup=tasks_keyboard())
        else:
            keyboard = [
                [InlineKeyboardButton("🐦 Follow Twitter", url=TWITTER_ACCOUNT)],
                [InlineKeyboardButton("✅ Verify", callback_data='verify_twitter')],
                [InlineKeyboardButton("« Back", callback_data='tasks')]
            ]
            msg = (
                f"🐦 *Follow Twitter Account*\n\n"
                f"1️⃣ Click 'Follow Twitter' button below\n"
                f"2️⃣ Follow our official account\n"
                f"3️⃣ Click 'Verify'\n"
            )
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'verify_twitter':
        if not user['task_twitter']:
            supabase_update('users', 'telegram_id', user_id, {'task_twitter': True})
            
            user = get_user(user_id)
            all_completed = user['task_channel'] and user['task_group'] and user['task_twitter']
            
            if all_completed:
                update_balance(user_id, 0.1)
                new_balance = user['balance'] + 0.1
                msg = (
                    f"🎉 *ALL TASKS COMPLETED!*\n\n"
                    f"✅ Twitter Task Verified\n\n"
                    f"Reward: `+0.1 SUI`\n"
                    f"💰 New Balance: `{new_balance:.4f} SUI`"
                )
            else:
                msg = f"✅ *Twitter Task Verified!*\n\nComplete the remaining tasks to earn 0.1 SUI!"
        else:
            msg = "✅ You've already verified this task!"
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=tasks_keyboard())
    
    elif query.data == 'watch_ad':
        if can_watch_ad(user_id):
            ad_link = f"https://adsgram.ai/watch?userId={user_id}&botId={context.bot.id}"
            
            keyboard = [
                [InlineKeyboardButton("🎥 Watch Ad Now", url=ad_link)],
                [InlineKeyboardButton("🔄 Refresh", callback_data='watch_ad')],
                [InlineKeyboardButton("« Back", callback_data='back_main')]
            ]
            
            msg = (
                f"🎥 *Watch Advertisement*\n\n"
                f"💰 Reward: `0.05 SUI`\n"
                f"⏰ Cooldown: 3 hours\n\n"
                f"✅ You can watch an ad now!\n\n"
                f"Click the button below to watch a short ad.\n"
                f"After watching, you'll receive 0.05 SUI automatically."
            )
            
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            time_left = get_time_until_next_ad(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data='watch_ad')],
                [InlineKeyboardButton("« Back", callback_data='back_main')]
            ]
            
            msg = (
                f"⏰ *Cooldown Active*\n\n"
                f"⏳ Next ad available in:\n"
                f"**{time_left}**\n\n"
                f"💡 Tip: You can watch ads every 3 hours!\n"
                f"Come back later to earn 0.05 SUI.\n\n"
                f"Click 'Refresh' to check again."
            )
            
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'referral':
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        total_earned = user['referral_count'] * 0.001
        
        msg = (
            f"👥 *Referral Program*\n\n"
            f"💰 Earn 0.001 SUI per referral!\n"
            f"👥 Your Referrals: `{user['referral_count']}`\n"
            f"🎁 Total Earned: `{total_earned:.4f} SUI`\n\n"
            f"🔗 *Your Referral Link:*\n"
            f"`{ref_link}`\n\n"
            f"Share this link with friends to earn SUI!"
        )
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
    
    elif query.data == 'withdraw':
        if user['wallet_address']:
            if user['balance'] >= 0.5:
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Withdrawal", callback_data='confirm_withdraw')],
                    [InlineKeyboardButton("« Back", callback_data='back_main')]
                ]
                
                msg = (
                    f"💳 *Withdraw SUI Coins*\n\n"
                    f"💰 Available: `{user['balance']:.4f} SUI`\n"
                    f"💳 Wallet: `{user['wallet_address']}`\n\n"
                    f"⚠️ Minimum withdrawal: 0.5 SUI\n"
                    f"⏰ Processing time: 24-48 hours\n\n"
                    f"Click 'Confirm' to proceed."
                )
                
                await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                msg = (
                    f"❌ *Insufficient Balance*\n\n"
                    f"💰 Your Balance: `{user['balance']:.4f} SUI`\n"
                    f"📊 Minimum Required: `0.5 SUI`\n\n"
                    f"Keep earning to reach the minimum!"
                )
                await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
        else:
            user_states[user_id] = 'awaiting_wallet'
            msg = (
                f"💳 *Set Wallet Address*\n\n"
                f"Please send your SUI wallet address.\n\n"
                f"⚠️ Make sure it's correct!\n"
                f"Wrong address = lost coins.\n\n"
                f"Send your wallet address now:"
            )
            await query.edit_message_text(msg, parse_mode='Markdown')
    
    elif query.data == 'confirm_withdraw':
        if user['balance'] >= 0.5:
            # Create withdrawal request
            withdrawal_data = {
                'telegram_id': user_id,
                'amount': user['balance'],
                'wallet_address': user['wallet_address'],
                'status': 'pending',
                'requested_at': datetime.utcnow().isoformat()
            }
            supabase_insert('withdrawals', withdrawal_data)
            
            # Reset balance
            supabase_update('users', 'telegram_id', user_id, {
                'balance': 0.0,
                'has_withdrawn': True
            })
            
            msg = (
                f"✅ *Withdrawal Requested!*\n\n"
                f"💰 Amount: `{user['balance']:.4f} SUI`\n"
                f"💳 Wallet: `{user['wallet_address']}`\n\n"
                f"⏰ Processing time: 24-48 hours\n"
                f"📧 You'll receive a notification when processed.\n\n"
                f"Thank you for using our bot! 🎉"
            )
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
        else:
            msg = "❌ Insufficient balance for withdrawal."
            await query.edit_message_text(msg, reply_markup=back_keyboard())
    
    elif query.data == 'info':
        msg = (
            f"ℹ️ *Bot Information*\n\n"
            f"🤖 *About This Bot:*\n"
            f"This is a SUI Airdrop Bot where you can earn real SUI coins!\n\n"
            f"💰 *Ways to Earn:*\n"
            f"• Daily check-in: 0.1 SUI\n"
            f"• Watch ads: 0.05 SUI (every 3 hours)\n"
            f"• Complete tasks: 0.1 SUI\n"
            f"• Referrals: 0.001 SUI per user\n\n"
            f"💳 *Withdrawal:*\n"
            f"• Minimum: 0.5 SUI\n"
            f"• Processing: 24-48 hours\n\n"
            f"❓ *Support:* @your_support\n"
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_keyboard())
    
    elif query.data == 'back_main':
        msg = (
            f"🏠 *Main Menu*\n\n"
            f"💰 Balance: `{user['balance']:.4f} SUI`\n"
            f"👥 Referrals: `{user['referral_count']}`\n\n"
            f"Choose an option below:"
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=main_menu_keyboard())

# =============== MESSAGE HANDLERS ===============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for wallet address input)"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id in user_states and user_states[user_id] == 'awaiting_wallet':
        # Validate SUI wallet address (basic validation)
        if len(text) == 66 and text.startswith('0x'):
            supabase_update('users', 'telegram_id', user_id, {'wallet_address': text})
            
            msg = (
                f"✅ *Wallet Address Saved!*\n\n"
                f"💳 Wallet: `{text}`\n\n"
                f"You can now withdraw your SUI coins when you reach 0.5 SUI minimum.\n\n"
                f"Keep earning! 🚀"
            )
            
            del user_states[user_id]
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=main_menu_keyboard())
        else:
            msg = (
                f"❌ *Invalid Wallet Address*\n\n"
                f"Please send a valid SUI wallet address.\n"
                f"Format: 0x followed by 64 characters\n\n"
                f"Try again:"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "Use the menu buttons to interact with the bot, or type /start to begin.",
            reply_markup=main_menu_keyboard()
        )

# =============== ADSGRAM WEBHOOK ===============

async def adsgram_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Adsgram ad completion webhook"""
    # This would be called by Adsgram when user completes watching an ad
    # Implementation depends on Adsgram's webhook specification
    pass

# =============== MAIN ===============

def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in environment variables")
        return
    
    # Create application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    print("🤖 Bot is starting...")
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
