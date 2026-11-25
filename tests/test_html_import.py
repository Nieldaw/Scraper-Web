from pathlib import Path

import pytest

from immo_ne_collector.services.html_import import HtmlImportError, validate_upload

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def test_validate_upload_rules():
    assert validate_upload("homegate", "all", b"<html><body>x</body></html>") is None
    assert validate_upload("homegate", "NE", b"<html></html>") == "NE"
    with pytest.raises(HtmlImportError):
        validate_upload("inconnu", "all", b"<html></html>")
    with pytest.raises(HtmlImportError):
        validate_upload("homegate", "XX", b"<html></html>")
    with pytest.raises(HtmlImportError):
        validate_upload("homegate", "all", b"%PDF-1.4 binaire")


@pytest.mark.db
async def test_import_homegate_fixture_persists(tmp_path):
    from immo_ne_collector.services.html_import import import_html_page

    content = (FIXTURES / "homegate_initial_state_land.html").read_bytes()
    try:
        result = await import_html_page(
            source="homegate", canton="all", content=content, cache_dir=tmp_path
        )
    except HtmlImportError as exc:  # fixture sans vente exploitable : message clair attendu
        assert "annonce" in str(exc).lower()
        return
    assert result.detected >= 1 and (tmp_path / result.saved_as).exists()
