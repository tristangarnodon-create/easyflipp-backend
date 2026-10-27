import json
import re
from typing import Tuple, List, Optional
import httpx
from models import ListingItem

CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

class AIEngine:
    def __init__(self, api_key: str = "", model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key.strip()
        self.model_name = model_name

    def set_api_key(self, api_key: str):
        self.api_key = api_key.strip()

    async def _call_gemini(self, prompt: str) -> str:
        if not self.api_key:
            return ""

        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        # Try active model first, then candidates if 404
        models_to_try = [self.model_name] + [m for m in CANDIDATE_MODELS if m != self.model_name]

        async with httpx.AsyncClient(timeout=25.0) as client:
            for m in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
                try:
                    r = await client.post(url, headers=headers, json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        self.model_name = m  # stick with working model
                        return data["candidates"][0]["content"]["parts"][0]["text"]
                    elif r.status_code in (404, 400):
                        continue
                    else:
                        print(f"[AIEngine] Gemini status {r.status_code} on {m}: {r.text[:150]}")
                        break
                except Exception as ex:
                    print(f"[AIEngine] Network error calling Gemini ({m}): {ex}")
                    break

        return ""

    async def evaluate_listing(self, listing: ListingItem, criteria: str) -> Tuple[bool, str, bool, str]:
        if not criteria.strip():
            return False, "Aucun critère défini pour cette recherche.", False, ""

        if not self.api_key:
            return False, "Clé API Gemini non configurée dans l'application.", False, ""

        prompt = f"""Tu es un analyste expert en PC Flipping (achat / revente de composants et ordinateurs d'occasion pour réaliser une marge financière).
Vérifie avec la plus grande rigueur si l'annonce suivante respecte ABSOLUMENT TOUS les critères imposés par l'utilisateur.

CRITÈRES EXIGÉS PAR L'UTILISATEUR:
"{criteria}"

DÉTAILS DE L'ANNONCE:
- Titre: {listing.title}
- Prix: {listing.price} €
- Plateforme: {listing.platform}
- État / Condition: {listing.condition}
- Vendeur: {listing.seller_name} (Note: {listing.seller_rating or 'N/A'})
- Description: {listing.description}

RÈGLES D'ÉVALUATION:
1. L'annonce doit respecter 100% des critères sans exception.
2. Si un critère obligatoire manque ou est contredit, matches doit être false.
3. AFFAIRE EN OR / ACHAT IMMÉDIAT ("is_urgent_deal"):
   Indique true UNIQUEMENT si l'annonce est une affaire tellement exceptionnelle (prix anormalement bas, sous-cote flagrante, opportunité rare) qu'il faut l'acheter sur-le-champ sous peine qu'elle soit vendue dans l'heure.
   Si ce n'est pas le cas, indique false.
4. Sois concis et objectif dans ton explication.

Réponds UNIQUEMENT en JSON sous ce format strict:
{{
  "matches": true,
  "reason": "Explication courte en français justifiant pourquoi l'annonce respecte ou non tous les critères.",
  "is_urgent_deal": true,
  "urgency_reason": "Pourquoi l'acheter sur-le-champ (ex: 40% sous la cote, risque de vente sous 1h)."
}}
"""
        response_text = await self._call_gemini(prompt)
        if not response_text:
            return False, "Impossible de joindre l'IA Gemini (vérifiez la clé ou le quota).", False, ""

        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            data = json.loads(cleaned)
            matches = bool(data.get("matches", False))
            reason = str(data.get("reason", ""))
            is_urgent = bool(data.get("is_urgent_deal", False))
            urgency_reason = str(data.get("urgency_reason", ""))
            return matches, reason, is_urgent, urgency_reason
        except Exception as e:
            print(f"[AIEngine] Error parsing JSON evaluation: {e}, raw: {response_text}")
            return False, "Erreur de format de réponse IA.", False, ""

    async def select_best_deal(self, listings: List[ListingItem], criteria: str) -> Tuple[Optional[str], str]:
        if not listings:
            return None, ""
        if len(listings) == 1:
            return listings[0].id, "Seule annonce actuellement validée pour cette recherche."

        if not self.api_key:
            # Fallback heuristic: lowest price
            sorted_items = sorted(listings, key=lambda x: x.price)
            return sorted_items[0].id, f"Meilleur prix ({sorted_items[0].price} €)."

        candidates_summary = []
        for item in listings:
            candidates_summary.append({
                "id": item.id,
                "title": item.title,
                "price": f"{item.price} €",
                "platform": item.platform,
                "condition": item.condition,
                "desc": item.description[:120]
            })

        prompt = f"""Tu es un arbitre expert en PC Flipping.
Toutes les annonces suivantes respectent les critères exigés par l'utilisateur:
"{criteria}"

Parmi cette liste d'annonces valides, détermine laquelle est LA MEILLEURE AFFAIRE ABSOLUE (Coup de cœur ultime), en prenant en compte:
- Le prix le plus avantageux par rapport au matériel
- Le potentiel de revente / marge bénéficiaire
- L'état général et la complétude

LISTE DES ANNONCES:
{json.dumps(candidates_summary, ensure_ascii=False, indent=2)}

Réponds UNIQUEMENT en JSON sous ce format strict:
{{
  "best_id": "<l'identifiant exact de l'annonce retenue>",
  "reason": "Explication courte et percutante de pourquoi c'est le coup de cœur ultime."
}}
"""
        response_text = await self._call_gemini(prompt)
        if not response_text:
            sorted_items = sorted(listings, key=lambda x: x.price)
            return sorted_items[0].id, f"Meilleur prix ({sorted_items[0].price} €)."

        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            data = json.loads(cleaned)
            best_id = data.get("best_id")
            reason = str(data.get("reason", "Coup de cœur ultime sélectionné par l'IA."))
            valid_ids = {item.id for item in listings}
            if best_id in valid_ids:
                return best_id, reason
        except Exception as e:
            print(f"[AIEngine] Error picking best deal: {e}")

        # Fallback to lowest price
        best = sorted(listings, key=lambda x: x.price)[0]
        return best.id, f"Meilleur prix relevé ({best.price} €)."
