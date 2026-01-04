# Auto File Processor Bot

A powerful Telegram bot designed to automate the downloading, processing, and re-uploading of files. It includes advanced features like RSS monitoring, user management, and an admin control panel.

## 🚀 Features

*   **Automated Monitoring**: Monitors configured sources for new content and processes it automatically.
*   **Smart Deduplication**: Uses a database to track processed posts, ensuring no duplicates even after restarts.
*   **File Processing**: Downloads files, cleans unwanted content, and injects custom copyright files.
*   **Admin Control Panel**: manage the bot directly from Telegram via `/settings`.
*   **User Management**: Tracks users and allows broadcasting messages to all users.
*   **Force Join**: (Optional) Forces users to join specific channels to access files.
*   **Large File Support**: Handles files up to 2GB.

## 🤖 Commands

### User Commands
*   `/start` - Start the bot or access a file via deep link.

### Admin Commands
*   `/settings` - Open the Admin Control Panel (Live Stats, Toggles, Actions).
*   `/broadcast <message>` - Send a message to all bot users.
*   `/users` - Check the total number of users.
*   `/logs` - Get the current bot log file.
*   `/restart` - Restart the bot process.
*   `/check_channel` - Verify bot permissions in the configured channel.

## 🛠 Deployment (VPS / Koyeb)

### 1. Prerequisites
*   **Python 3.9+**
*   **MongoDB** (Atlas or Local)
*   **Telegram API Credentials** (API_ID, API_HASH, TOKEN)

### 2. Environment Variables
Set the following variables in your `.env` file or VPS/Koyeb environment settings:

| Variable | Description |
| :--- | :--- |
| `TOKEN` | Your Telegram Bot Token (from @BotFather) |
| `API_ID` | Your Telegram API ID (from my.telegram.org) |
| `API_HASH` | Your Telegram API Hash (from my.telegram.org) |
| `MONGO_URI` | Your MongoDB Connection String |
| `ADMIN_ID` | Your Telegram User ID (for admin commands) |
| `CHANNEL_ID` | (Optional) Channel ID for auto-posting (e.g., `-100xxxx`) |
| `JOIN_CHANNELS` | (Optional) Space-separated Channel IDs for Force Join (e.g., `-100xxxx -100yyyy`) |

### 3. VPS Deployment (Ubuntu/Debian)

1.  **Update & Install Dependencies**:
    ```bash
    sudo apt update && sudo apt upgrade -y
    sudo apt install python3-pip python3-venv git p7zip-full p7zip-rar -y
    ```

2.  **Clone Repository**:
    ```bash
    git clone <your-repo-url>
    cd <your-repo-folder>
    ```

3.  **Setup Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Install Python Packages**:
    ```bash
    pip install -r requirements.txt
    ```

5.  **Run the Bot**:
    *   **Directly**: `python bot.py`
    *   **As Service (Recommended)**: Use `systemd` or `screen`/`tmux`.

### 4. Koyeb Deployment

1.  **Fork/Clone** this repository.
2.  Create a new App on Koyeb.
3.  Select **GitHub** as the deployment method.
4.  Set **Builder** to **Dockerfile**.
5.  Add the **Environment Variables** listed above.
6.  Deploy!

## 📁 Project Structure

*   `bot.py`: Main bot logic (Telegram handlers, RSS monitor, Admin panel).
*   `processor.py`: Core file processing logic (Download, Extract, Clean, Repack).
*   `Copyright_files/`: Folder containing files to be injected into every processed archive.
*   `requirements.txt`: Python dependencies.
*   `Dockerfile`: Configuration for containerized deployment.

## ⚠️ Notes for VPS Users
*   Ensure `p7zip-full` and `p7zip-rar` are installed for handling RAR/ZIP files.
*   If you encounter `403 Forbidden` errors during scraping, the bot uses `curl_cffi` to bypass protections, which is pre-configured.

---
**Developed for automation and efficiency.**
