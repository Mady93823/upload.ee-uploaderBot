import os
import sys
import subprocess
import requests
import zipfile
import shutil
from bs4 import BeautifulSoup
import rarfile
import time

# Configuration
URL = "https://www.upload.ee/files/18774607/foodscan-26nulled.rar.html"
DOWNLOAD_DIR = "downloads"
EXTRACT_DIR = "extracted"
FINAL_FILENAME = "foodscan-26nulled_cleaned.zip"
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
UNRAR_INSTALLER_URL = "https://www.rarlab.com/rar/unrarw64.exe"
UNRAR_EXE_NAME = "UnRAR.exe"

def setup_dirs():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    if not os.path.exists(EXTRACT_DIR):
        os.makedirs(EXTRACT_DIR)
    if not os.path.exists(TOOLS_DIR):
        os.makedirs(TOOLS_DIR)

def get_direct_link(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            if '/download/' in a['href']:
                return a['href']
    except Exception as e:
        print(f"Error fetching page: {e}")
    return None

def download_file(url, dest_path, retries=3):
    print(f"Downloading {url}...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, headers=headers) as r:
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print("Download complete.")
            return True
        except Exception as e:
            print(f"Download attempt {attempt+1} failed: {e}")
            time.sleep(2)
            
    print("All download attempts failed.")
    return False

def get_unrar_path():
    exe_path = os.path.join(TOOLS_DIR, UNRAR_EXE_NAME)
    if os.path.exists(exe_path):
        return exe_path
    
    print("UnRAR executable not found locally. Bootstrapping...")
    installer_path = os.path.join(TOOLS_DIR, "unrar_installer.exe")
    
    try:
        if not download_file(UNRAR_INSTALLER_URL, installer_path):
            return None
        
        abs_tools_dir = os.path.abspath(TOOLS_DIR)
        print(f"Running installer silently to {abs_tools_dir}...")
        
        # WinRAR SFX silent install
        cmd = [installer_path, '/s', f'/d={abs_tools_dir}']
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if process.returncode != 0:
            print(f"Installer exited with {process.returncode}")
            
        # Check for UnRAR.exe or UnRAR.exe in a subfolder?
        # Sometimes it extracts to current folder.
        if os.path.exists(exe_path):
            print("UnRAR.exe found!")
            return exe_path
        else:
            print("UnRAR.exe not found in expected location.")
            # List files in tools to debug
            print(f"Files in {TOOLS_DIR}: {os.listdir(TOOLS_DIR)}")
            
    except Exception as e:
        print(f"Error bootstrapping UnRAR: {e}")
    
    return None

def extract_rar(rar_path, output_dir):
    unrar_path = get_unrar_path()
    if not unrar_path:
        print("Cannot extract without UnRAR.")
        return False
        
    rarfile.UNRAR_TOOL = unrar_path
    
    print(f"Extracting {rar_path}...")
    try:
        rf = rarfile.RarFile(rar_path)
        rf.extractall(output_dir)
        return True
    except Exception as e:
        print(f"Extraction Failed: {e}")
        return False

def clean_and_repack(extract_dir, output_zip_path):
    files_to_delete = [
        "Downloaded from CODELIST.CC.url",
        "codelist.cc.txt"
    ]
    
    print("Cleaning files...")
    for root, dirs, files in os.walk(extract_dir):
        for name in files:
            if name in files_to_delete:
                file_path = os.path.join(root, name)
                print(f"Deleting {file_path}")
                os.remove(file_path)

    print(f"Creating {output_zip_path}...")
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, extract_dir)
                zipf.write(file_path, arcname)
    print("Repack complete.")

def process_workflow():
    setup_dirs()
    
    # 1. Get Link
    direct_link = get_direct_link(URL)
    if not direct_link:
        print("Failed to find download link.")
        return

    # 2. Download
    filename = direct_link.split('/')[-1]
    rar_path = os.path.join(DOWNLOAD_DIR, filename)
    if not download_file(direct_link, rar_path):
        return
    
    # 3. Extract
    if extract_rar(rar_path, EXTRACT_DIR):
        # 4. Clean and Repack
        clean_and_repack(EXTRACT_DIR, FINAL_FILENAME)
        print("SUCCESS")
    else:
        print("Extraction failed.")

if __name__ == "__main__":
    process_workflow()
