import requests
from bs4 import BeautifulSoup
import os

url = "https://www.upload.ee/files/18774607/foodscan-26nulled.rar.html"

def get_direct_link(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch page: {response.status_code}")
        return None
    
    soup = BeautifulSoup(response.text, 'html.parser')
    # Usually upload.ee has a direct link or a button. 
    # Let's look for the download link.
    # It often looks like <a href="...">Download</a> or similar.
    
    # Debug: print all links
    for a in soup.find_all('a', href=True):
        if 'download' in a.text.lower() or 'files' in a['href']:
             # checking for typical direct link structure
             pass

    # Looking for the specific download button/link structure for upload.ee
    # It seems to be often in an element with id="d_l" or similar, or just the first big link.
    # Let's try to find a link that ends with .rar and is not the current url.
    
    # Specific for upload.ee: The download link is often in a specific container.
    # Let's dump the hrefs found to analyze.
    links = [a['href'] for a in soup.find_all('a', href=True)]
    return links

links = get_direct_link(url)
print("Links found:")
for l in links:
    print(l)
