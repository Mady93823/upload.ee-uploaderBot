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

def search_codelist(query):
    """
    Search codelist.cc for a query and return the first result URL.
    Uses DLE search endpoint (POST).
    """
    search_url = "https://codelist.cc/index.php?do=search"
    params = {
        "subaction": "search",
        "story": query
    }
    
    try:
        # Use POST for DLE search
        r = requests.post(search_url, data=params, impersonate="chrome120", timeout=30)
        if r.status_code != 200:
            return None
        
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 1. Look for articles with the new structure
        # <h3 class="post__title"> <a href="...">Title</a> </h3>
        
        results = []
        
        # Method A: Standard Search Results
        for article in soup.find_all('article'):
            title_h3 = article.find('h3', class_='post__title')
            if title_h3:
                a_tag = title_h3.find('a', href=True)
                if a_tag:
                    results.append((a_tag.get_text(strip=True), a_tag['href']))
        
        # Method B: Fallback (older themes or different views)
        if not results:
            for h2 in soup.find_all('h2', class_='post-titleEntry'):
                a_tag = h2.find('a', href=True)
                if a_tag:
                    results.append((a_tag.get_text(strip=True), a_tag['href']))
        
        # Filter results for relevance
        # If we have results, check if they actually contain the query keywords
        # This prevents returning "Latest Posts" when search yields nothing
        
        query_words = query.lower().split()
        # Use first few meaningful words for strict checking
        # e.g. "Wowy - Multi-language" -> check for "wowy"
        key_word = query_words[0] if query_words else ""
        
        for title, url in results:
            if key_word in title.lower():
                return url
                
        # If no strict match, but we have results and the query was long, 
        # maybe return the first one if it shares *some* words?
        # For now, let's be strict to avoid bad matches.
        
        return None

    except Exception as e:
        print(f"Search error: {e}")
        return None

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
        # Do NOT set User-Agent manually when using impersonate, it causes conflicts/blocks
        headers = {
            "Referer": referer if referer else "https://codelist.cc/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin"
        }

        print(f"Downloading image using curl_cffi impersonate...")
        
        # Retry with different impersonations if first attempt fails
        impersonations = ["chrome", "chrome120", "safari15_3", "okhttp"]
        
        success = False
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
                        # Verify we actually have content
                        if response.content and len(response.content) > 0:
                            success = True
                            break # Success!
                        else:
                            print("Got empty body despite 200 OK, retrying...")
                    else:
                        print(f"Got {content_type} instead of image, retrying...")
                else:
                    print(f"Status code {response.status_code}, retrying...")
                
            except Exception as e:
                print(f"Attempt failed: {e}")
                time.sleep(1)
        
        if not success:
            print("Python download attempts failed. Trying fallback to system curl...")
            try:
                # Fallback to system curl
                if not os.path.exists(work_dir):
                    os.makedirs(work_dir)
                
                filename = f"cover_{int(time.time())}.jpg"
                save_path = os.path.join(work_dir, filename)
                
                cmd = [
                    "curl", "-L",
                    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "-H", f"Referer: {referer if referer else 'https://codelist.cc/'}",
                    "--connect-timeout", "15",
                    "--max-time", "30",
                    "--output", save_path,
                    img_url
                ]
                
                print(f"Running curl: {' '.join(cmd)}")
                subprocess.run(cmd, check=True, capture_output=True)
                
                if os.path.exists(save_path) and os.path.getsize(save_path) > 1000:
                    print("Curl download successful!")
                    # Verify it's an image
                    try:
                        img = Image.open(save_path)
                        img.verify() # Check integrity
                        img = Image.open(save_path) # Reopen for processing
                        
                        # Use this image for the rest of processing
                        success = True
                    except Exception as e:
                        print(f"Curl downloaded file is not a valid image: {e}")
                        os.remove(save_path)
                        return None
                else:
                    print("Curl failed or file too small.")
                    return None
                    
            except Exception as e:
                print(f"Curl fallback failed: {e}")
                return None

        if not success:
             print("All download attempts failed.")
             return None
             
        if 'img' not in locals():
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
        # Increased crop pixels to ensure logo removal (Aggressive mode)
        
        # Standard Codelist watermark area seems to be around 60-80px but can be larger
        if height > 500:
            crop_pixels = 110
        elif height > 400:
            crop_pixels = 90
        elif height >= 300: 
            crop_pixels = 70
        else:
            # Smaller crop for smaller images
            crop_pixels = 65
             
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
        'upload_ee_url': None,
        'krakenfiles_url': None,
        'workupload_url': None,
        'pixeldrain_url': None,
        'description': None
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
            
        # 1a. Extract Description
        # Heuristic: Text before "Demo:"
        full_text = soup.get_text(separator=' ', strip=True)
        if "Demo:" in full_text:
             parts = full_text.split("Demo:")
             if len(parts) > 0:
                 raw_desc = parts[0].strip()
                 # Remove metadata (usually ends with "views")
                 if "views" in raw_desc:
                     raw_desc = raw_desc.split("views")[-1].strip()
                 # Clean up any "By admin..." artifacts if "views" wasn't found or didn't catch it
                 elif "By admin" in raw_desc:
                     raw_desc = raw_desc.split("By admin")[-1].strip()
                     
                 # Take the last logical chunk if it's too long
                 if len(raw_desc) > 1000:
                     raw_desc = raw_desc[-1000:]
                 
                 metadata['description'] = raw_desc

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

        # 2b. Extract Krakenfiles link
        matches_kf = re.findall(r'(https?://krakenfiles\.com/view/[^\s"<]+)', response.text)
        if matches_kf:
            metadata['krakenfiles_url'] = matches_kf[0]
        else:
             for a in soup.find_all('a', href=True):
                if 'krakenfiles.com' in a['href']:
                    metadata['krakenfiles_url'] = a['href']
                    break

        # 2c. Extract Workupload link
        matches_wu = re.findall(r'(https?://workupload\.com/file/[^\s"<]+)', response.text)
        if matches_wu:
            metadata['workupload_url'] = matches_wu[0]
        else:
             for a in soup.find_all('a', href=True):
                if 'workupload.com/file/' in a['href']:
                    metadata['workupload_url'] = a['href']
                    break
                    
        # 2d. Extract Pixeldrain link
        matches_pd = re.findall(r'(https?://pixeldrain\.com/u/[^\s"<]+)', response.text)
        if matches_pd:
            metadata['pixeldrain_url'] = matches_pd[0]
        else:
             for a in soup.find_all('a', href=True):
                if 'pixeldrain.com/u/' in a['href']:
                    metadata['pixeldrain_url'] = a['href']
                    break

        # 3. Extract Demo link (Generic)
        # Look for "Demo:" text and the following link
        demo_url = None
        
        # Method A: Specific CodeCanyon check (Legacy, but robust for CC)
        for a in soup.find_all('a', href=True):
            if 'codecanyon.net/item' in a['href']:
                demo_url = a['href']
                break
        
        # Method B: Generic "Demo:" finder if not found
        if not demo_url:
            # Look for text node containing "Demo:"
            # We search in the entry-content to avoid sidebar noise
            content_div = soup.find('div', class_='entry-content') or soup
            
            # 1. Search for "Demo:" text node
            demo_text_node = content_div.find(string=lambda t: 'Demo:' in t if t else False)
            if demo_text_node:
                # Check siblings for the first link
                # Sometimes it's immediate sibling, sometimes separated by whitespace
                
                # Check next element (<a> tag)
                next_el = demo_text_node.next_element
                while next_el and next_el.name != 'a':
                    next_el = next_el.next_element
                    # Safety break if we go too far
                    if next_el and next_el.name in ['br', 'div', 'p']:
                        break
                
                if next_el and next_el.name == 'a' and next_el.get('href'):
                    demo_url = next_el.get('href')
                
                # If that failed, check parent's links (e.g. <span>Demo: <a...></span>)
                if not demo_url and demo_text_node.parent:
                    for a in demo_text_node.parent.find_all('a', href=True):
                        demo_url = a.get('href')
                        break

        if demo_url:
            print(f"Found Demo URL: {demo_url}")
            # Ensure domain is codecanyon.net if it's a lolinez wrapper
            if 'www.lolinez.com' in demo_url:
                 # Extract the real URL after the query parameter if possible
                 parts = demo_url.split('?')
                 if len(parts) > 1:
                     # It might be codecanyon or ANY other site now
                     demo_url = parts[-1]
            
            metadata['demo_url'] = demo_url
            
            # Scrape CodeCanyon for image ONLY if it is actually CodeCanyon
            if 'codecanyon.net' in demo_url:
                codecanyon_url = demo_url # Alias for CC scraping
                try:
                # Add headers for CodeCanyon
                # ... existing CodeCanyon scraping logic ...
                    cc_headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9"
                    }
                    cc_response = requests.get(codecanyon_url, impersonate="chrome120", headers=cc_headers)
                    cc_soup = BeautifulSoup(cc_response.text, 'html.parser')
            
                    candidates = []

                    # 1. Open Graph Image (Most reliable)
                    og_image = cc_soup.find('meta', property='og:image')
                    if og_image:
                        candidates.append(og_image['content'])

                    # 2. Look for specific Envato image classes
                    header_img = cc_soup.find('img', class_='item-header__image')
                    if header_img and header_img.get('src'):
                         candidates.append(header_img['src'])
                    
                    # 3. Scan all images for envatousercontent
                    for img in cc_soup.find_all('img', src=True):
                         src = img['src']
                         if 'envatousercontent.com' in src:
                             # Exclude obviously small icons if possible by name
                             if 'avatar' not in src and 'icon' not in src:
                                candidates.append(src)
                    
                    # Remove duplicates while preserving order
                    unique_candidates = []
                    for c in candidates:
                        if c not in unique_candidates:
                            unique_candidates.append(c)
                    
                    candidates = unique_candidates
                    print(f"Found {len(candidates)} image candidates on CodeCanyon.")
                    
                    # Try candidates
                    for img_url in candidates:
                         if work_dir:
                             print(f"Processing candidate: {img_url}")
                             local_path = process_and_save_image(img_url, work_dir, session=None, referer=codecanyon_url)
                             if local_path:
                                 metadata['image_path'] = local_path
                                 metadata['image_url'] = img_url
                                 print(f"Success with CodeCanyon image: {local_path}")
                                 break
                         else:
                             metadata['image_url'] = img_url
                             break

                except Exception as e:
                    print(f"Error scraping CodeCanyon: {e}")

        # Fallback to codelist image if we don't have a valid processed image
        if not metadata['image_path']:
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

def process_workupload_url(url, work_dir, progress_callback=None, add_copyright=False):
    print(f"Processing Workupload URL: {url}")
    download_dir = os.path.join(work_dir, "downloads")
    
    if os.path.exists(download_dir): shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    try:
        session = requests.Session()
        # 1. Get Page to set cookies
        resp = session.get(url, impersonate="chrome120")
        resp.raise_for_status()
        
        file_id = url.split('/file/')[-1]
        download_url = f"https://workupload.com/start/{file_id}"
        
        print(f"Download URL: {download_url}")
        
        # 2. Download
        filename = "download.rar"
        
        dl_resp = session.get(download_url, stream=True, impersonate="chrome120")
        dl_resp.raise_for_status()
        
        cd = dl_resp.headers.get('content-disposition')
        if cd:
            if 'filename="' in cd:
                filename = cd.split('filename="')[1].split('"')[0]
            elif 'filename=' in cd:
                filename = cd.split('filename=')[1].split(';')[0]
                
        save_path = os.path.join(download_dir, filename)
        
        total_size = int(dl_resp.headers.get('content-length', 0))
        downloaded_size = 0
        
        with open(save_path, 'wb') as f:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded_size, total_size)
                        
        print(f"Downloaded to {save_path}")
        return process_archive(save_path, work_dir, add_copyright)

    except Exception as e:
        print(f"Workupload processing failed: {e}")
        return None

def process_pixeldrain_url(url, work_dir, progress_callback=None, add_copyright=False):
    print(f"Processing Pixeldrain URL: {url}")
    download_dir = os.path.join(work_dir, "downloads")
    
    if os.path.exists(download_dir): shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    try:
        # https://pixeldrain.com/u/tn5KZgLz -> https://pixeldrain.com/api/file/tn5KZgLz
        file_id = url.split('/u/')[-1]
        download_url = f"https://pixeldrain.com/api/file/{file_id}"
        print(f"Download URL: {download_url}")
        
        session = requests.Session()
        dl_resp = session.get(download_url, stream=True, impersonate="chrome120")
        dl_resp.raise_for_status()
        
        filename = "download.rar"
        cd = dl_resp.headers.get('content-disposition')
        if cd:
            if 'filename="' in cd:
                filename = cd.split('filename="')[1].split('"')[0]
            elif 'filename=' in cd:
                filename = cd.split('filename=')[1].split(';')[0]
                
        save_path = os.path.join(download_dir, filename)
        
        total_size = int(dl_resp.headers.get('content-length', 0))
        downloaded_size = 0
        
        with open(save_path, 'wb') as f:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded_size, total_size)
                        
        print(f"Downloaded to {save_path}")
        return process_archive(save_path, work_dir, add_copyright)

    except Exception as e:
        print(f"Pixeldrain processing failed: {e}")
        return None

def process_krakenfiles_url(url, work_dir, progress_callback=None, add_copyright=False):
    print(f"Processing Krakenfiles URL: {url}")
    download_dir = os.path.join(work_dir, "downloads")
    extract_dir = os.path.join(work_dir, "extracted")
    
    if os.path.exists(download_dir): shutil.rmtree(download_dir)
    if os.path.exists(extract_dir): shutil.rmtree(extract_dir)
    
    os.makedirs(download_dir)
    os.makedirs(extract_dir)

    try:
        try:
            from pykraken.kraken import Kraken
        except ImportError:
            raise Exception("py-kraken module not found. Please run 'pip install py-kraken'")

        k = Kraken()
        # py-kraken logic
        # It seems py-kraken might need 'requests' but we have it.
        # k.get_download_link(url) returns the force-download url
        
        print("Getting download link via py-kraken...")
        download_url = k.get_download_link(url)
        
        if not download_url:
             raise Exception("py-kraken returned None for download link.")
             
        print(f"Download URL: {download_url}")
        
        # Download using our robust downloader
        filename = "download.rar" # Default
        # Try to extract filename from URL if possible or just use default
        
        save_path = os.path.join(download_dir, filename)
        
        # Use our download_file function which handles retries and headers
        # Note: force-download might not need referer, but adding it doesn't hurt
        if not download_file(download_url, save_path, progress_callback=progress_callback):
             raise Exception("Download failed.")
             
        # Check if file is valid (not html error page)
        if os.path.exists(save_path) and os.path.getsize(save_path) < 1000:
             # Read content to check for error
             with open(save_path, 'rb') as f:
                 content = f.read(200)
                 print(f"File too small. Content: {content}")
             raise Exception("Downloaded file is too small (likely error page).")

        return process_archive(save_path, work_dir, add_copyright)

    except Exception as e:
        print(f"Krakenfiles processing failed: {e}")
        return None

def process_archive(rar_path, work_dir, add_copyright=False):
    extract_dir = os.path.join(work_dir, "extracted")
    if not os.path.exists(extract_dir):
        os.makedirs(extract_dir)

    print(f"Extracting {rar_path}...")
    extraction_success = False
    error_msg = ""
    
    # Priority 1: Try unrar
    if shutil.which('unrar'):
        print("Using unrar...")
        cmd_unrar = ['unrar', 'x', '-y', '-p-', rar_path, extract_dir]
        res_unrar = subprocess.run(cmd_unrar, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res_unrar.returncode == 0:
            extraction_success = True
            print("Unrar successful.")
        else:
            error_msg = res_unrar.stderr.decode('utf-8', errors='ignore')
            print(f"Unrar failed: {error_msg}")
    
    # Priority 2: Try 7-Zip
    if not extraction_success:
        seven_zip = setup_tools()
        if seven_zip:
            print(f"Using {seven_zip}...")
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
        
    # Clean
    clean_files(extract_dir)
    
    # Add Copyright Files
    if add_copyright:
        add_copyright_files(extract_dir)
    
    # Repack
    filename = os.path.basename(rar_path)
    output_name = f"{os.path.splitext(filename)[0]}_cleaned.zip"
    output_path = os.path.join(work_dir, output_name)
    repack_to_zip(extract_dir, output_path)
    
    return output_path

def process_url(url, work_dir, progress_callback=None, add_copyright=False):
    metadata = None
    zip_path = None
    
    # Determine if it's a codelist URL
    if "codelist.cc" in url:
        print("Detected codelist.cc URL. Extracting metadata...")
        metadata = extract_metadata_from_codelist(url, work_dir)
        
        # Collect candidates
        candidates = []
        if metadata.get('upload_ee_url'): candidates.append(('upload.ee', metadata['upload_ee_url']))
        if metadata.get('krakenfiles_url'): candidates.append(('krakenfiles', metadata['krakenfiles_url']))
        if metadata.get('workupload_url'): candidates.append(('workupload', metadata['workupload_url']))
        if metadata.get('pixeldrain_url'): candidates.append(('pixeldrain', metadata['pixeldrain_url']))
        
        if not candidates:
             raise Exception("Could not find supported download link (upload.ee, krakenfiles, workupload, pixeldrain) on the provided codelist.cc page.")
             
        for host, link in candidates:
            print(f"Attempting download from {host}: {link}")
            try:
                if host == 'upload.ee':
                    zip_path = process_upload_ee_url(link, work_dir, progress_callback, add_copyright)
                elif host == 'krakenfiles':
                    zip_path = process_krakenfiles_url(link, work_dir, progress_callback, add_copyright)
                elif host == 'workupload':
                    zip_path = process_workupload_url(link, work_dir, progress_callback, add_copyright)
                elif host == 'pixeldrain':
                    zip_path = process_pixeldrain_url(link, work_dir, progress_callback, add_copyright)
                
                if zip_path and os.path.exists(zip_path):
                    print(f"Successfully processed using {host}")
                    break # Success!
                else:
                    print(f"Failed to process with {host} (no file returned)")
            except Exception as e:
                print(f"Error processing with {host}: {e}")
                # Continue to next candidate
    
    else:
        # Direct link provided (assume upload.ee or krakenfiles)
        if "krakenfiles.com" in url:
            zip_path = process_krakenfiles_url(url, work_dir, progress_callback, add_copyright)
        elif "workupload.com" in url:
            zip_path = process_workupload_url(url, work_dir, progress_callback, add_copyright)
        elif "pixeldrain.com" in url:
            zip_path = process_pixeldrain_url(url, work_dir, progress_callback, add_copyright)
        else:
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
        
    # 3. Process Archive
    return process_archive(rar_path, work_dir, add_copyright)

if __name__ == "__main__":
    pass