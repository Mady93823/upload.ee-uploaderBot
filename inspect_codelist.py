import requests
from bs4 import BeautifulSoup

url = "https://codelist.cc/scripts3/259384-foodscan-v26-qr-code-restaurant-menu-maker-and-contactless-table-ordering-system-with-restaurant-pos-nulled.html"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

try:
    response = requests.get(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Look for upload.ee links
    found = False
    for a in soup.find_all('a', href=True):
        if 'upload.ee' in a['href']:
            print(f"Found upload.ee link: {a['href']}")
            found = True
            
    if not found:
        print("No upload.ee link found directly in hrefs. Checking text content or other attributes...")
        # sometimes links are plain text or hidden
        if 'upload.ee' in response.text:
            print("String 'upload.ee' found in response text.")
            
except Exception as e:
    print(f"Error: {e}")
