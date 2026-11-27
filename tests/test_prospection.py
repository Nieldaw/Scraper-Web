"""Page /prospection : brouillons d'e-mails à relire et à marquer comme envoyés à la main."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape

import httpx
import pytest

from immo_ne_collector.main import app
from immo_ne_collector.models import EmailDraft, EmailDraftStatus, Property
from immo_ne_collector.services import prospection

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def _draft(
    status: str, text: str = "Bonjour,\n\nVotre bien m'intéresse.\nCordialement"
) -> EmailDraft:
    prop = Property(
        id=uuid.uuid4(), title="Villa à Bevaix", city="Bevaix", postal_code="2022",
        price_chf=Decimal("1250000"), first_seen_at=NOW, last_seen_at=NOW,
    )  # fmt: skip
    return EmailDraft(
        id=uuid.uuid4(), property_id=prop.id, generated_text=text, status=status,
        created_at=NOW, sent_at=NOW if status == "sent" else None, property=prop,
    )  # fmt: skip


def test_transitions_autorisees():
    t = prospection.ALLOWED_TRANSITIONS
    assert t["draft"] == {"validated", "sent"}
    assert t["validated"] == {"draft", "sent"}
    assert t["sent"] == set()  # un brouillon envoyé est figé


def test_statuts_enum_et_libelles_coherents():
    assert {s.value for s in EmailDraftStatus} == set(prospection.STATUS_LABELS)


@pytest.fixture
def client(monkeypatch):
    drafts = [_draft("draft"), _draft("validated"), _draft("sent")]
    calls: list[tuple] = []

    async def fake_list(_s, status="all"):
        return [d for d in drafts if status in ("all", d.status)]

    async def fake_counts(_s):
        return {"all": 3, "draft": 1, "validated": 1, "sent": 1}

    async def fake_set(_s, draft_id, new_status):
        calls.append((draft_id, new_status))
        if draft_id == MISSING:
            return None
        if new_status == "validated" and draft_id == SENT_ID:
            raise prospection.InvalidTransition("sent → validated")
        return drafts[0]

    monkeypatch.setattr(prospection, "list_drafts", fake_list)
    monkeypatch.setattr(prospection, "count_by_status", fake_counts)
    monkeypatch.setattr(prospection, "set_draft_status", fake_set)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return http, calls


MISSING = uuid.uuid4()
SENT_ID = uuid.uuid4()


async def test_liste_affiche_texte_bien_et_boutons_selon_le_statut(client):
    http, _ = client
    html = unescape((await http.get("/prospection")).text)
    assert "Villa à Bevaix" in html and "2022 Bevaix" in html and "CHF 1'250'000" in html
    assert "Votre bien m'intéresse." in html
    # brouillon : Valider + Marquer comme envoyé ; validé : Remettre en brouillon + envoyé ; envoyé : rien
    assert html.count("Marquer comme envoyé") == 2
    assert html.count(">Valider<") == 1
    assert html.count("Remettre en brouillon") == 1
    assert 'href="/prospection"' in html


async def test_texte_du_brouillon_est_echappe(client, monkeypatch):
    http, _ = client

    async def fake_list(_s, status="all"):
        return [_draft("draft", "<script>alert(1)</script>")]

    monkeypatch.setattr(prospection, "list_drafts", fake_list)
    html = (await http.get("/prospection")).text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


async def test_filtre_par_statut(client):
    http, _ = client
    html = (await http.get("/prospection?status=sent")).text
    assert html.count('class="draft ') == 1 and "draft-sent" in html
    assert (await http.get("/prospection?status=nimportequoi")).status_code == 422


async def test_marquer_comme_envoye_redirige_vers_la_meme_vue(client):
    http, calls = client
    did = uuid.uuid4()
    resp = await http.post(
        f"/prospection/{did}/status", data={"status": "sent", "back": "validated"}
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/prospection?status=validated"
    assert calls == [(did, "sent")]


async def test_statut_inconnu_ou_interdit(client):
    http, _ = client
    assert (
        await http.post(f"/prospection/{MISSING}/status", data={"status": "sent"})
    ).status_code == 404
    assert (
        await http.post(f"/prospection/{SENT_ID}/status", data={"status": "validated"})
    ).status_code == 409


async def test_redirection_ignore_une_valeur_back_arbitraire(client):
    http, _ = client
    resp = await http.post(
        f"/prospection/{uuid.uuid4()}/status", data={"status": "sent", "back": "https://evil.test"}
    )
    assert resp.headers["location"] == "/prospection?status=all"


@pytest.mark.db
async def test_cycle_complet_en_base():
    from immo_ne_collector.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        prop = Property(title="Maison", city="Sion", first_seen_at=NOW, last_seen_at=NOW)
        session.add(prop)
        await session.flush()
        draft = EmailDraft(property_id=prop.id, generated_text="Bonjour")
        session.add(draft)
        await session.commit()
        assert draft.status == "draft"

        listed = await prospection.list_drafts(session)
        assert [d.property.city for d in listed] == ["Sion"]
        assert (await prospection.count_by_status(session)) == {
            "draft": 1, "validated": 0, "sent": 0, "all": 1,
        }  # fmt: skip

        await prospection.set_draft_status(session, draft.id, "validated")
        sent = await prospection.set_draft_status(session, draft.id, "sent")
        assert sent.status == "sent" and sent.sent_at is not None
        with pytest.raises(prospection.InvalidTransition):
            await prospection.set_draft_status(session, draft.id, "draft")
        assert await prospection.set_draft_status(session, uuid.uuid4(), "sent") is None

        # le brouillon disparaît avec son bien (ON DELETE CASCADE)
        await session.delete(prop)
        await session.commit()
        assert await prospection.list_drafts(session) == []
