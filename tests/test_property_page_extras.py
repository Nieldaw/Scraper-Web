from immo_ne_collector.services.amenities import extract_amenities
from immo_ne_collector.services.images import extract_image_urls
from immo_ne_collector.services.property_queries import sitn_status_label


def test_amenities_from_description():
    tags = extract_amenities(
        "Appartement rénové", "Grand balcon, ascenseur, cave et place de parc. Vue sur le lac."
    )
    assert tags == ["Balcon", "Ascenseur", "Place de parc", "Cave", "Vue lac", "Rénové"]
    assert extract_amenities(None, "") == []
    assert "Balcon" not in extract_amenities("Les balconnets de la région")


def test_gallery_urls_deduplicated_and_validated():
    raw = {
        "image_url": "https://a/1.jpg",
        "images": ["https://a/1.jpg", {"url": "https://a/2.jpg"}, "javascript:alert(1)", 3],
    }
    assert extract_image_urls(raw) == ["https://a/1.jpg", "https://a/2.jpg"]
    assert extract_image_urls(None) == []


def test_sitn_labels_in_french():
    assert sitn_status_label("NOT_ELIGIBLE_MISSING_ADDRESS") == "Adresse incomplète"
    assert sitn_status_label("INCONNU") == "INCONNU"
    assert sitn_status_label(None) == "–"
