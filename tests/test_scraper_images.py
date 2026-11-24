import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper
from immo_ne_collector.scrapers.image_utils import extract_card_image_url
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper

BASE = "https://www.example.ch/fr/"


def _card(html: str):
    return BeautifulSoup(f"<article>{html}</article>", "html.parser").article


def test_prefers_src_and_resolves_relative_urls():
    assert (
        extract_card_image_url(_card('<img src="/img/a.jpg">'), BASE)
        == "https://www.example.ch/img/a.jpg"
    )


def test_lazy_loaded_and_srcset():
    card = _card('<img src="data:image/gif;base64,AAAA" data-src="https://cdn.example/b.jpg">')
    assert extract_card_image_url(card, BASE) == "https://cdn.example/b.jpg"
    card = _card('<img srcset="https://cdn.example/c.jpg 1x, https://cdn.example/c2.jpg 2x">')
    assert extract_card_image_url(card, BASE) == "https://cdn.example/c.jpg"


def test_skips_placeholders_and_invalid_schemes():
    card = _card(
        '<img src="/assets/logo.png"><img src="javascript:x"><img src="https://cdn.example/d.jpg">'
    )
    assert extract_card_image_url(card, BASE) == "https://cdn.example/d.jpg"
    assert extract_card_image_url(_card("<p>pas d'image</p>"), BASE) is None


async def _collect_with_images(scraper_cls, fixture: str, article_class: str, tmp_path):
    html = Path(f"tests/fixtures/html/{fixture}").read_text(encoding="utf-8")
    # injecte une image après chaque ouverture de carte
    with_img = re.sub(
        rf'(<article class="{article_class}"[^>]*>)',
        r'\1<img src="/photos/x.jpg">',
        html,
    )
    path = tmp_path / fixture
    path.write_text(with_img, encoding="utf-8")
    return (
        await scraper_cls(html_path=path, source="t", base_url="https://test.local").collect(),
        await scraper_cls(
            html_path=Path(f"tests/fixtures/html/{fixture}"),
            source="t",
            base_url="https://test.local",
        ).collect(),
    )


@pytest.mark.parametrize(
    ("scraper_cls", "fixture", "article_class"),
    [
        (AnibisCachedHtmlScraper, "anibis_sample_listing_page.html", "anibis-card"),
        (LookmoveCachedHtmlScraper, "lookmove_sample_listing_page.html", "lookmove-card"),
    ],
)
async def test_scrapers_store_image_url_in_raw_data(scraper_cls, fixture, article_class, tmp_path):
    with_img, without_img = await _collect_with_images(
        scraper_cls, fixture, article_class, tmp_path
    )
    assert with_img and all(
        item.raw_data["image_url"] == "https://test.local/photos/x.jpg" for item in with_img
    )
    assert without_img and all(item.raw_data["image_url"] is None for item in without_img)
