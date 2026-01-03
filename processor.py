import os
import requests
import zipfile
import shutil
from bs4 import BeautifulSoup
import time
import subprocess
import rarfile
import re
from PIL import Image
import io
from curl_cffi import requests

# Configuration
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
COPYRIGHT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Copyright_files")
LEGACY_7Z_URL = "https://www.7-zip.org/a/7za920.zip"
MODERN_7Z_INSTALLER_URL = "https://www.7-zip.org/a/7z2301-x64.exe"
SEVEN_ZIP_EXE = "7z.exe"

def setup_tools():
    # Check if running on Linux/Docker
    if os.name == 'posix':
        # On Linux, expect 7z to be installed via apt/package manager
        # Common names: 7z, 7za
        if shutil.which('7z'):
            return '7z'
        if shutil.which('7za'):
            return '7za'
        print("Warning: 7-Zip (7z or 7za) not found in PATH.")
        return None

    if not os.path.exists(TOOLS_DIR):
        os.makedirs(TOOLS_DIR)
        
    final_exe = os.path.join(TOOLS_DIR, SEVEN_ZIP_EXE)
    if os.path.exists(final_exe):
        return final_exe
        
    print("Modern 7-Zip not found. Bootstrapping...")
    
    # 1. Download Legacy 7-Zip (Zip format)
    legacy_zip = os.path.join(TOOLS_DIR, "legacy.zip")
    legacy_exe = os.path.join(TOOLS_DIR, "7za.exe")
    
    if not os.path.exists(legacy_exe):
        print("Downloading Legacy 7-Zip...")
        download_file(LEGACY_7Z_URL, legacy_zip)
        with zipfile.ZipFile(legacy_zip, 'r') as z:
            for file in z.namelist():
                if file == "7za.exe" or file.endswith("7za.exe"):
                    with open(legacy_exe, 'wb') as f:
                        f.write(z.read(file))
        if os.path.exists(legacy_zip): os.remove(legacy_zip)

    # 2. Download Modern 7-Zip Installer (EXE format, extractable by 7-Zip)
    installer_exe = os.path.join(TOOLS_DIR, "installer.exe")
    print("Downloading Modern 7-Zip Installer...")
    download_file(MODERN_7Z_INSTALLER_URL, installer_exe)
    
    # 3. Extract Installer using Legacy 7-Zip
    print("Extracting Modern 7-Zip...")
    cmd = [legacy_exe, 'x', installer_exe, f'-o{TOOLS_DIR}', '-y']
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if os.path.exists(installer_exe): os.remove(installer_exe)
    
    if os.path.exists(final_exe):
        print("7-Zip Bootstrapped successfully!")
        return final_exe
    else:
        print("Failed to bootstrap 7-Zip.")
        return None

# Helper to create a robust scraper
def get_scraper_session():
    # curl_cffi requests doesn't need a session for simple gets, but we can use one
    # to maintain headers/cookies if needed. For now we can just use requests directly
    # with impersonate parameter.
    return requests.Session()

def download_file(url, dest_path, retries=3, progress_callback=None):
    print(f"Downloading {url}...")
    for attempt in range(retries):
        try:
            # Using curl_cffi with impersonate
            response = requests.get(url, stream=True, impersonate="chrome")
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded_size, total_size)
            return True
        except Exception as e:
            print(f"Download attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return False

def get_direct_link(url):
    try:
        response = requests.get(url, impersonate="chrome")
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            if '/download/' in a['href']:
                return a['href']
    except Exception as e:
        print(f"Error fetching page: {e}")
    return None

def process_and_save_image(img_url, work_dir, session=None, referer=None):
    try:
        if not work_dir:
            return None
            
        print(f"Processing image: {img_url}")
        
        # Add Referer to pass hotlink protection
        headers = {
            "Referer": referer if referer else "https://codelist.cc/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }

        print(f"Downloading image with headers: {headers['User-Agent']}")
        
        # Retry with different impersonations if first attempt fails
        impersonations = ["chrome", "chrome110", "safari15_3"]
        
        for imp in impersonations:
            try:
                print(f"Attempting download with impersonate='{imp}'...")
                if session:
                    # Update session headers temporarily
                    response = session.get(img_url, stream=True, timeout=15, headers=headers, impersonate=imp)
                else:
                     response = requests.get(img_url, stream=True, timeout=15, impersonate=imp, headers=headers)
                
                if response.status_code == 200:
                    # Check content type
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'image' in content_type:
                        break # Success!
                    else:
                        print(f"Got {content_type}, retrying...")
                
            except Exception as e:
                print(f"Attempt failed: {e}")
                time.sleep(1)
             
        response.raise_for_status()
        
        # Debug info
        content_type = response.headers.get('Content-Type', '')
        
        # Strict check: If it's definitely text/html, reject it.
        if 'text' in content_type.lower() or 'html' in content_type.lower():
            print(f"Warning: URL returned {content_type} instead of image. First 200 bytes: {response.content[:200]}")
            return None
            
        try:
            img = Image.open(io.BytesIO(response.content))
            img.verify() # Verify it's actually an image
            img = Image.open(io.BytesIO(response.content)) # Re-open after verify
        except Exception as img_e:
             print(f"Invalid image content received. First 200 bytes: {response.content[:200]}")
             return None

        width, height = img.size
        
        # Filter small images (icons, logos)
        # Relaxed logic to allow banners that might be short in height
        if width < 250 or height < 150:
            print(f"Skipping small image ({width}x{height})")
            return None
            
        # Crop bottom part (watermark)
        # Only crop if image is reasonably tall to avoid destroying it
        # Increased crop pixels to ensure logo removal
        
        # Standard Codelist watermark area seems to be around 60-80px
        if height > 400:
             crop_pixels = 85
        elif height > 300: 
             crop_pixels = 70
        else:
             # Smaller crop for smaller images
             crop_pixels = 45
             
        if height > (crop_pixels + 50): # Ensure we have enough image left
            new_height = height - crop_pixels
            img = img.crop((0, 0, width, new_height))
            print(f"Cropped {crop_pixels}px from bottom. New size: {width}x{new_height}")
        
        # Save to work_dir
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)
            
        filename = f"cover_{int(time.time())}.jpg"
        save_path = os.path.join(work_dir, filename)
        
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        img.save(save_path, "JPEG", quality=90)
        return save_path
        
    except Exception as e:
        print(f"Failed to process image: {e}")
        return None

def extract_metadata_from_codelist(url, work_dir=None):
    print(f"Scraping metadata from {url}...")
    
    metadata = {
        'title': None,
        'image_url': None,
        'image_path': None,
        'demo_url': None,
        'upload_ee_url': None
    }
    
    # Use a session to persist cookies/clearance
    session = requests.Session()
    
    try:
        response = session.get(url, impersonate="chrome")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Extract Title
        title_tag = soup.find('h1', class_='entry-title')
        if title_tag:
            metadata['title'] = title_tag.get_text(strip=True)
            
        # 1b. Try to get og:image from Codelist first (often the main post image)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            metadata['image_url'] = img_url # Set URL immediately as fallback
            if work_dir:
                 print(f"Found og:image: {img_url}, processing...")
                 local_path = process_and_save_image(img_url, work_dir, session, referer=url)
                 if local_path:
                     metadata['image_path'] = local_path
            
        # Collect images from codelist.cc as fallback
        codelist_images = []
        for img in soup.find_all('img', src=True):
            src = img['src'].strip()
            # Clean up URL if it has spaces or newlines
            if src:
                codelist_images.append(src)
            
        # 2. Extract upload.ee link
        matches = re.findall(r'(https?://www\.upload\.ee/files/[^\s"<]+)', response.text)
        if matches:
            metadata['upload_ee_url'] = matches[0]
        else:
             for a in soup.find_all('a', href=True):
                if 'upload.ee' in a['href']:
                    metadata['upload_ee_url'] = a['href']
                    break

        # 3. Extract CodeCanyon link to find image
        codecanyon_url = None
        for a in soup.find_all('a', href=True):
            if 'codecanyon.net/item' in a['href']:
                codecanyon_url = a['href']
                break
        
        if codecanyon_url:
            print(f"Found CodeCanyon URL: {codecanyon_url}")
            # Ensure domain is codecanyon.net
            if 'www.lolinez.com' in codecanyon_url:
                 # Extract the real URL after the query parameter if possible
                 parts = codecanyon_url.split('?')
                 if len(parts) > 1 and 'codecanyon.net' in parts[-1]:
                     codecanyon_url = parts[-1]
                 else:
                     codecanyon_url = codecanyon_url.replace('www.lolinez.com', 'codecanyon.net')
            
            metadata['demo_url'] = codecanyon_url
            
            # Scrape CodeCanyon for image
            try:
                cc_response = requests.get(codecanyon_url, impersonate="chrome")
                cc_soup = BeautifulSoup(cc_response.text, 'html.parser')
                
                # Try finding the main preview image
                # Often it's in a meta tag or specific img class
                # Example: <img ... class="item-header__image" ... src="...">
                # Or og:image
                
                og_image = cc_soup.find('meta', property='og:image')
                if og_image:
                    metadata['image_url'] = og_image['content']
                else:
                    # Fallback to looking for img tags with specific patterns
                    # The user gave an example: https://market-resized.envatousercontent.com/...
                    for img in cc_soup.find_all('img', src=True):
                         if 'envatousercontent.com' in img['src'] and 'preview' in img['src'] or 'banner' in img['src']:
                             metadata['image_url'] = img['src']
                             break
                             
                # If we found an image on CodeCanyon, process it locally to crop it if needed
                if metadata['image_url'] and work_dir:
                     print(f"Found CodeCanyon image: {metadata['image_url']}, processing...")
                     local_path = process_and_save_image(metadata['image_url'], work_dir, session=None, referer=codecanyon_url)
                     if local_path:
                         metadata['image_path'] = local_path
            except Exception as e:
                print(f"Error scraping CodeCanyon: {e}")

        # Fallback to codelist image if still no image
        if not metadata['image_url'] and not metadata['image_path']:
            print("Trying fallback to Codelist images...")
            for img_src in codelist_images:
                
                # Handle relative URLs
                if img_src.startswith('/'):
                    img_src = "https://codelist.cc" + img_src
                
                # Clean URL: remove any accidental concatenation or whitespace
                img_src = img_src.split()[0]  # Take first part if spaces exist
                img_src = img_src.strip()

                # Look for the main post image, usually ends with .jpg or .png and is not a small icon
                # Codelist usually puts the main image in the post body
                if 'wp-content/uploads' in img_src or '/uploads/posts/' in img_src:
                    if work_dir:
                        local_path = process_and_save_image(img_src, work_dir, session, referer=url)
                        if local_path:
                            metadata['image_path'] = local_path
                            metadata['image_url'] = img_src # Ensure we have the URL too
                            print(f"Using processed Codelist image: {local_path}")
                            break
                    else:
                        metadata['image_url'] = img_src
                        print(f"Using Codelist image: {img_src}")
                        break
                
    except Exception as e:
        print(f"Error scraping codelist: {e}")
        
    return metadata

def clean_files(extract_dir):
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

def add_copyright_files(extract_dir):
    if not os.path.exists(COPYRIGHT_DIR):
        print(f"Copyright directory not found at {COPYRIGHT_DIR}")
        return

    print("Adding copyright files...")
    for filename in os.listdir(COPYRIGHT_DIR):
        src_file = os.path.join(COPYRIGHT_DIR, filename)
        if os.path.isfile(src_file):
            dst_file = os.path.join(extract_dir, filename)
            shutil.copy2(src_file, dst_file)

def repack_to_zip(extract_dir, output_zip_path):
    print(f"Creating {output_zip_path}...")
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, extract_dir)
                zipf.write(file_path, arcname)
    print("Repack complete.")

def process_url(url, work_dir, progress_callback=None, add_copyright=False):
    metadata = None
    
    # Determine if it's a codelist URL
    if "codelist.cc" in url:
        print("Detected codelist.cc URL. Extracting metadata...")
        metadata = extract_metadata_from_codelist(url, work_dir)
        if not metadata or not metadata['upload_ee_url']:
            raise Exception("Could not find upload.ee link on the provided codelist.cc page.")
        print(f"Found upload.ee URL: {metadata['upload_ee_url']}")
        url = metadata['upload_ee_url']
    
    # Process as upload.ee
    zip_path = process_upload_ee_url(url, work_dir, progress_callback, add_copyright)
    
    return zip_path, metadata

def process_upload_ee_url(url, work_dir, progress_callback=None, add_copyright=False):
    download_dir = os.path.join(work_dir, "downloads")
    extract_dir = os.path.join(work_dir, "extracted")
    
    if os.path.exists(download_dir): shutil.rmtree(download_dir)
    if os.path.exists(extract_dir): shutil.rmtree(extract_dir)
    
    os.makedirs(download_dir)
    os.makedirs(extract_dir)
    
    # 1. Get Link
    direct_link = get_direct_link(url)
    if not direct_link:
        raise Exception("Could not find direct download link on page.")
        
    # 2. Download
    filename = direct_link.split('/')[-1]
    rar_path = os.path.join(download_dir, filename)
    if not download_file(direct_link, rar_path, progress_callback=progress_callback):
        raise Exception("Download failed.")
        
    # 3. Extract
    print(f"Extracting {rar_path}...")
    extraction_success = False
    error_msg = ""
    
    # Priority 1: Try unrar first (most reliable for RAR5/proprietary formats)
    if shutil.which('unrar'):
        print("Using unrar...")
        # unrar x -y -p- <file> <dest>
        cmd_unrar = ['unrar', 'x', '-y', '-p-', rar_path, extract_dir]
        res_unrar = subprocess.run(cmd_unrar, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res_unrar.returncode == 0:
            extraction_success = True
            print("Unrar successful.")
        else:
            error_msg = res_unrar.stderr.decode('utf-8', errors='ignore')
            print(f"Unrar failed: {error_msg}")
    
    # Priority 2: Try 7-Zip if unrar failed or is missing
    if not extraction_success:
        seven_zip = setup_tools()
        if seven_zip:
            print(f"Using {seven_zip}...")
            # 7z x <file> -o<dest> -y -p-
            cmd = [seven_zip, 'x', rar_path, f'-o{extract_dir}', '-y', '-p-']
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0:
                extraction_success = True
                print("7-Zip extraction successful.")
            else:
                current_err = res.stderr.decode('utf-8', errors='ignore')
                error_msg += f" | 7-Zip failed: {current_err}"
                print(f"7-Zip extraction failed: {current_err}")
        else:
             error_msg += " | 7-Zip tool missing."
             
    if not extraction_success:
        raise Exception(f"Extraction failed. Ensure 'unrar' or 'p7zip-rar' is installed. Details: {error_msg}")
        
    # 4. Clean
    clean_files(extract_dir)
    
    # 5. Add Copyright Files
    if add_copyright:
        add_copyright_files(extract_dir)
    
    # 6. Repack
    output_name = f"{os.path.splitext(filename)[0]}_cleaned.zip"
    output_path = os.path.join(work_dir, output_name)
    repack_to_zip(extract_dir, output_path)
    
    return output_path

if __name__ == "__main__":
    pass
