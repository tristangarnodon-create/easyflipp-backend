import re
import urllib.parse
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from models import ListingItem

class VintedScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

    def fetch_listings(self, search_url: str, search_id: str) -> List[ListingItem]:
        # Ensure order=newest_first is present
        parsed = urllib.parse.urlparse(search_url)
        params = urllib.parse.parse_qs(parsed.query)
        params["order"] = ["newest_first"]
        new_query = urllib.parse.urlencode(params, doseq=True)
        target_url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment
        ))

        try:
            r = self.session.get(target_url, headers=self.headers, timeout=15)
            if r.status_code != 200:
                print(f"[VintedScraper] Non-200 status code: {r.status_code}")
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            items: List[ListingItem] = []
            seen_item_ids = set()

            # Find all links to /items/
            item_links = soup.select("a[href*='/items/']")
            for link in item_links:
                href = link.get("href", "")
                if not href:
                    continue

                # ID extraction: e.g. /items/10553226078-amd-ryzen...
                id_match = re.search(r'/items/(\d+)', href)
                if not id_match:
                    continue
                item_id = id_match.group(1)
                if item_id in seen_item_ids:
                    continue
                seen_item_ids.add(item_id)

                full_url = href if href.startswith("http") else f"https://www.vinted.fr{href}"
                title = link.get("title") or ""
                
                # Walk up to find card container
                card = link
                for _ in range(5):
                    if card.parent:
                        card = card.parent

                card_text = card.text if card else ""
                
                # Extract price: look for pattern like 140,00 € or 140 €
                price = 0.0
                price_match = re.search(r'(\d+[\d\s]*[,\.]?\d*)\s*€', card_text)
                if price_match:
                    raw_p = price_match.group(1).replace(" ", "").replace(",", ".")
                    try:
                        price = float(raw_p)
                    except ValueError:
                        price = 0.0

                # Extract condition
                condition = ""
                condition_keywords = ["Neuf avec étiquette", "Neuf sans étiquette", "Très bon état", "Bon état", "Satisfaisant"]
                for kw in condition_keywords:
                    if kw.lower() in card_text.lower():
                        condition = kw
                        break

                # Extract image
                image_urls = []
                img_tag = card.find("img")
                if img_tag:
                    src = img_tag.get("src") or img_tag.get("data-src") or ""
                    if src.startswith("http"):
                        image_urls.append(src)

                # If title is empty, infer from href slug
                if not title:
                    slug_match = re.search(r'/items/\d+-([^?]+)', href)
                    if slug_match:
                        title = slug_match.group(1).replace("-", " ").capitalize()
                    else:
                        title = f"Article Vinted #{item_id}"

                items.append(ListingItem(
                    id=f"vinted_{item_id}",
                    search_id=search_id,
                    platform="vinted",
                    title=title.strip(),
                    price=price,
                    currency="EUR",
                    url=full_url,
                    image_urls=image_urls,
                    condition=condition,
                    description=card_text.strip()[:200]
                ))

            return items
        except Exception as e:
            print(f"[VintedScraper] Error fetching {search_url}: {e}")
            return []
