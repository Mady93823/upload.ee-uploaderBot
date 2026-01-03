import requests
from bs4 import BeautifulSoup
import rarfile
import os
import zipfile
import shutil

# Configuration
URL = "https://www.upload.ee/files/18774607/foodscan-26nulled.rar.html"
DOWNLOAD_DIR = "downloads"
EXTRACT_DIR = "extracted"
FINAL_FILENAME = "foodscan-26nulled_cleaned.zip"

def setup_dirs():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    if not os.path.exists(EXTRACT_DIR):
        os.makedirs(EXTRACT_DIR)

def get_direct_link(url):
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        if '/download/' in a['href']:
            return a['href']
    return None

def download_file(url, dest_path):
    print(f"Downloading from {url}...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    with requests.get(url, stream=True, headers=headers) as r:
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("Download complete.")

def process_archive(rar_path):
    # rarfile.UNRAR_TOOL = "path/to/unrar.exe" # If needed
    
    print(f"Extracting {rar_path}...")
    try:
        rf = rarfile.RarFile(rar_path)
        rf.extractall(EXTRACT_DIR)
    except rarfile.RarCannotExec as e:
        print(f"Error: {e}")
        print("Please install UnRAR or put unrar.exe in the path.")
        return False
    except Exception as e:
        print(f"Error extracting: {e}")
        return False
    
    # Delete specific files
    files_to_delete = [
        "Downloaded from CODELIST.CC.url",
        "codelist.cc.txt"
    ]
    
    print("Cleaning files...")
    for root, dirs, files in os.walk(EXTRACT_DIR):
        for name in files:
            if name in files_to_delete:
                file_path = os.path.join(root, name)
                print(f"Deleting {file_path}")
                os.remove(file_path)

    # Re-package as ZIP
    print(f"Creating {FINAL_FILENAME}...")
    with zipfile.ZipFile(FINAL_FILENAME, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(EXTRACT_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, EXTRACT_DIR)
                zipf.write(file_path, arcname)
    
    print("Done.")
    return True

def cleanup():
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
    if os.path.exists(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)

if __name__ == "__main__":
    setup_dirs()
    direct_link = get_direct_link(URL)
    if direct_link:
        filename = direct_link.split('/')[-1]
        rar_path = os.path.join(DOWNLOAD_DIR, filename)
        download_file(direct_link, rar_path)
        if process_archive(rar_path):
            print("Process finished successfully.")
            # cleanup() # Optional, keep for inspection
        else:
            print("Process failed.")
    else:
        print("Could not find download link.")
