# Upload.ee Uploader Bot

A powerful Telegram bot that downloads files from **Upload.ee**, cleans them, adds your custom files, and re-uploads them.

## Features

*   **Download & Process**: Automatically downloads files from Upload.ee links.
*   **Auto-Clean**: Removes unwanted files from the downloaded archive.
*   **Copyright Injection**: Adds your custom copyright files (from `Copyright_files/` folder) into the archive.
*   **Repack**: Repacks everything into a clean ZIP file.
*   **Large File Support**: Handles files up to 2GB.
*   **Force Join Channel**: (Optional) Forces users to join specific channels before using the bot.
*   **Admin Auto-Post**: Admins can auto-post processed files to a configured channel.

## Commands

*   `/start` - Check if the bot is running.
*   `/settings` - (Admin only) View and configure bot settings.
*   `/check_channel` - (Admin only) Verify bot permissions in the configured channel.

## Deployment on Koyeb

This bot is ready for deployment on **Koyeb**.

1.  **Fork/Clone** this repository.
2.  Create a new App on Koyeb.
3.  Select **GitHub** as the deployment method and choose this repository.
4.  Set the **Builder** to **Dockerfile**.
5.  Add the following **Environment Variables** in Koyeb:

| Variable | Description |
| :--- | :--- |
| `TOKEN` | Your Telegram Bot Token (from @BotFather) |
| `API_ID` | Your Telegram API ID (from my.telegram.org) |
| `API_HASH` | Your Telegram API Hash (from my.telegram.org) |
| `MONGO_URI` | Your MongoDB Connection String |
| `ADMIN_ID` | Your Telegram User ID (for admin commands) |
| `CHANNEL_ID` | (Optional) Channel ID for auto-posting (e.g., `-100xxxx`) |
| `JOIN_CHANNELS` | (Optional) Space-separated Channel IDs users must join (e.g., `-100xxxx -100yyyy`) |

6.  Deploy!

## Local Development

1.  Clone the repo.
2.  Install dependencies: `pip install -r requirements.txt`
3.  Create a `.env` file with the variables listed above.
4.  Run the bot: `python bot.py`
