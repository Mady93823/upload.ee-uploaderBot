import requests
from bs4 import BeautifulSoup
import re

url = "https://codelist.cc/scripts3/259384-foodscan-v26-qr-code-restaurant-menu-maker-and-contactless-table-ordering-system-with-restaurant-pos-nulled.html"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, 'html.parser')

# Find all text containing upload.ee
print("Searching text nodes...")
for string in soup.stripped_strings:
    if 'upload.ee' in string:
        print(f"Found in text: {string}")

# Find using regex on the whole html
print("\nSearching regex in raw HTML...")
matches = re.findall(r'(https?://www\.upload\.ee/files/[^\s"<]+)', response.text)
for m in matches:
    print(f"Regex match: {m}")
