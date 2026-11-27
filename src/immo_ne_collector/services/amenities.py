"""Tags d'équipements extraits (mots-clés) du titre et de la description d'une annonce."""

import re
import unicodedata

# (libellé affiché, motifs sur texte sans accents, en minuscules)
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Balcon", (r"\bbalcons?\b",)),
    ("Terrasse", (r"\bterrasses?\b",)),
    ("Ascenseur", (r"\bascenseurs?\b", r"\blift\b")),
    ("Garage", (r"\bgarages?\b", r"\bbox ferme\b")),
    ("Place de parc", (r"\bplaces? de parc\b", r"\bplaces? de stationnement\b", r"\bparking\b")),
    ("Cave", (r"\bcaves?\b",)),
    ("Jardin", (r"\bjardins?\b", r"\bpelouse\b")),
    ("Cheminée", (r"\bcheminee\b", r"\bpoele\b")),
    ("Piscine", (r"\bpiscine\b",)),
    ("Buanderie", (r"\bbuanderie\b", r"\bmachine a laver\b")),
    ("Vue lac", (r"\bvue (sur )?(le )?lac\b", r"\bvue lac\b")),
    ("Vue dégagée", (r"\bvue (imprenable|degagee|panoramique)\b", r"\bsans vis-a-vis\b")),
    ("Cuisine agencée", (r"\bcuisine (equipee|agencee|moderne)\b",)),
    ("Rénové", (r"\brenove[e]?s?\b", r"\brenovation\b", r"\bentierement refait\b")),
    ("Calme", (r"\bcalme\b", r"\btranquille\b")),
    ("Mansardé", (r"\bmansarde[e]?s?\b", r"\bcombles?\b")),
    ("Accès PMR", (r"\bpmr\b", r"\bhandicap", r"\bmobilite reduite\b")),
    ("Proche transports", (r"\btransports? publics?\b", r"\bproche (de la )?gare\b")),
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_amenities(*texts: str | None) -> list[str]:
    haystack = _fold(" . ".join(t for t in texts if t))
    if not haystack.strip():
        return []
    return [
        label for label, patterns in _RULES if any(re.search(p, haystack) for p in patterns)
    ]
