import re
import asyncio
import time
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database import file_store
from utils import process_and_post_to_channel
from processor import search_codelist
from config import CHANNEL_ID

# Rate Limiting Configuration
RATE_LIMIT_DELAY = 60  # Seconds between requests per user
user_last_request = {}

def check_rate_limit(user_id: int) -> bool:
    """
    Check if the user is rate limited.
    Returns True if allowed, False if rate limited.
    """
    now = time.time()
    last_request = user_last_request.get(user_id, 0)
    
    if now - last_request < RATE_LIMIT_DELAY:
        return False
    
    user_last_request[user_id] = now
    return True

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.forwarded)
async def handle_codecanyon_link(client: Client, message: Message):
    """
    Monitors chats for CodeCanyon links.
    1. Verifies user.
    2. Checks DB for existing content.
    3. Searches & Uploads if new.
    """
    # 1. Verify user (ignore channel posts or anonymous admins)
    # message.sender_chat is usually set for channel posts in groups
    if message.sender_chat or not message.from_user:
        return

    text = message.text
    # 2. Extract CodeCanyon URL
    # Regex to capture valid CodeCanyon item URLs
    # Matches: https://codecanyon.net/item/item-name/123456
    match = re.search(r'(https?://(?:www\.)?codecanyon\.net/item/[^/\s]+/\d+)', text)
    if not match:
        # If it's a private chat and NOT a CodeCanyon link, we let bot.py handle it
        # (which handles upload.ee/codelist.cc links)
        if message.chat.type == "private":
            message.continue_propagation()
        return

    # Rate Limit Check
    if not check_rate_limit(message.from_user.id):
        # Optional: Reply to user about rate limit (or just ignore to reduce spam)
        # await message.reply_text(f"⏳ Please wait {RATE_LIMIT_DELAY} seconds between requests.", quote=True)
        return

    codecanyon_url = match.group(1)
    
    # Extract Title/ID for search
    # url format: .../item/title-here/123456
    try:
        parts = codecanyon_url.split('/')
        if len(parts) >= 6:
            # Title is usually the 5th element (index 4) if splitting by /
            item_name = parts[4].replace('-', ' ')
        else:
            return
    except Exception:
        return

    status_msg = await message.reply_text(f"🔎 Checking database for: **{item_name}**...", quote=True)

    try:
        # 3. Search Codelist.cc for the item
        loop = asyncio.get_running_loop()
        # Run synchronous search in executor to avoid blocking the event loop
        codelist_url = await loop.run_in_executor(None, search_codelist, item_name)
        
        if not codelist_url:
            await status_msg.edit_text("❌ **Item not found in our sources.**\n\nWe will add it to our request list.")
            return

        # 4. Database Check
        # Check if the SOURCE url (codelist url) has been processed.
        # This acts as our deduplication cache.
        processed = await file_store.is_url_processed(codelist_url)
        
        if processed:
            # Item exists in DB/Channel
            channel_link = "https://t.me/freephplaravel" 
            await status_msg.edit_text(
                "✅ **This item is already uploaded!**\n\n"
                f"Please check the channel for details: {channel_link}",
                disable_web_page_preview=True
            )
        else:
            # 5. New Item Handling
            await status_msg.edit_text("✅ Item found in database (source). Upload in progress >> 🚀")
            
            # Initiate Upload Process
            # We pass the Codelist URL to the processor
            me = await client.get_me()
            post_msg = await process_and_post_to_channel(client, codelist_url, me.username)
            
            if post_msg:
                # Mark as processed in DB to prevent duplicate uploads
                await file_store.add_processed_url(codelist_url)
                
                post_link = post_msg.link
                await status_msg.edit_text(
                    "🎉 **Upload complete!**",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("👉 View Post 👈", url=post_link)]
                    ])
                )
            else:
                await status_msg.edit_text("⚠️ **Upload failed.**\n\nPlease try again later or contact an admin.")

    except Exception as e:
        logging.error(f"Link Handler Error: {e}")
        await status_msg.edit_text("❌ An error occurred while processing your request.")
