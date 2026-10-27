import json
import re
import urllib.parse
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from models import ListingItem

class LeboncoinScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="safari15_5")
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
        }

    def fetch_listings(self, search_url: str, search_id: str) -> List[ListingItem]:
        # Ensure sort=time is present so latest items arrive first
        parsed = urllib.parse.urlparse(search_url)
        params = urllib.parse.parse_qs(parsed.query)
        params["sort"] = ["time"]
        new_query = urllib.parse.urlencode(params, doseq=True)
        target_url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment
        ))

        try:
            r = self.session.get(target_url, headers=self.headers, timeout=15)
            if r.status_code != 200:
                print(f"[LeboncoinScraper] Status {r.status_code} on {target_url}")
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            items: List[ListingItem] = []

            # 1. First attempt: parse __NEXT_DATA__
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                try:
                    data = json.loads(next_data.string)
                    props = data.get("props", {}).get("pageProps", {})
                    ads = props.get("searchData", {}).get("ads", [])
                    for ad in ads:
                        list_id = str(ad.get("list_id", ""))
                        if not list_id:
                            continue

                        raw_price = ad.get("price")
                        price = 0.0
                        if isinstance(raw_price, list) and raw_price:
                            price = float(raw_price[0])
                        elif isinstance(raw_price, (int, float)):
                            price = float(raw_price)

                        subject = ad.get("subject", "Annonce Leboncoin")
                        url = ad.get("url") or f"https://www.leboncoin.fr/ad/ordinateurs/{list_id}"
                        
                        img_urls = ad.get("images", {}).get("urls", [])
                        loc = ad.get("location", {}).get("city", "")
                        owner = ad.get("owner", {}).get("name", "")
                        pub_date = ad.get("first_publication_date", "")
                        desc = ad.get("body", "")

                        items.append(ListingItem(
                            id=f"lbc_{list_id}",
                            search_id=search_id,
                            platform="leboncoin",
                            title=subject,
                            price=price,
                            currency="EUR",
                            url=url,
                            image_urls=img_urls,
                            location=loc,
                            seller_name=owner,
                            published_at=pub_date,
                            description=desc
                        ))
                    if items:
                        return items
                except Exception as ex:
                    print(f"[LeboncoinScraper] Error parsing NEXT_DATA: {ex}")

            # 2. Fallback: Parse ad links in HTML DOM
            ad_links = soup.select("a[href*='/ad/']")
            seen_ids = set()
            for a in ad_links:
                href = a.get("href", "")
                id_match = re.search(r'/ad/[^/]+/(\d+)', href)
                if not id_match:
                    continue
                list_id = id_match.group(1)
                if list_id in seen_ids:
                    continue
                seen_ids.add(list_id)

                full_url = href if href.startswith("http") else f"https://www.leboncoin.fr{href}"
                card_text = a.text.strip()
                
                # Extract price
                price = 0.0
                price_match = re.search(r'(\d+[\d\s]*)\s*€', card_text)
                if price_match:
                    try:
                        price = float(price_match.group(1).replace(" ", ""))
                    except ValueError:
                        pass

                img_tag = a.find("img")
                img_urls = [img_tag.get("src")] if img_tag and img_tag.get("src") else []

                items.append(ListingItem(
                    id=f"lbc_{list_id}",
                    search_id=search_id,
                    platform="leboncoin",
                    title=card_text[:80],
                    price=price,
                    currency="EUR",
                    url=full_url,
                    image_urls=img_urls,
                    description=card_text[:200]
                ))

            return items
        except Exception as e:
            print(f"[LeboncoinScraper] Error fetching {search_url}: {e}")
            return []
