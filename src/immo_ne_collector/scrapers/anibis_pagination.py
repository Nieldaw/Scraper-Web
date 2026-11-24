"""Pagination Anibis : détecte s'il existe une page suivante (bouton « Go to next page »).

Anibis pagine avec des boutons (pas de lien href) : la page suivante s'obtient par `?page=N+1`,
mais seulement tant que le bouton « page suivante » est présent et actif.
"""

import random

from bs4 import BeautifulSoup


def anibis_has_next_page(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    for button in soup.select("nav[aria-label*='pagination'] button, a[rel='next']"):
        label = (button.get("aria-label") or "").lower()
        if button.name == "a" or "next page" in label or "page suivante" in label:
            return not (button.has_attr("disabled") or "Mui-disabled" in (button.get("class") or []))
    return False


def jittered_delay(base_seconds: float) -> float:
    """Délai aléatoire entre 0,75× et 1,75× la base (0 si base <= 0)."""
    if base_seconds <= 0:
        return 0.0
    return base_seconds * random.uniform(0.75, 1.75)
