"""Génération des brouillons d'e-mails : prompts, enchaînement des 2 skills, script (sans réseau)."""

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from immo_ne_collector.models import EmailDraft, Property
from immo_ne_collector.services import email_generation as eg

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def _prop(**over):
    base = dict(
        id="p1", title="Villa 5 pièces", property_type="maison", postal_code="2022", city="Bevaix",
        price_chf=Decimal("1250000"), rooms=Decimal("5"), living_area_m2=Decimal("160"),
        raw_data={"agency": "Immo Test SA"}, sitn_owner_name="Jean Dupont",
        listings=[SimpleNamespace(description="Belle villa avec jardin.")],
    )  # fmt: skip
    base.update(over)
    return SimpleNamespace(**base)


def test_les_deux_skills_commencent_par_les_phrases_demandees():
    assert eg.SKILL_REDACTION.startswith(
        "Tu es un agent immobilier. Rédige un email de contact professionnel pour ce bien."
    )
    assert eg.SKILL_HUMANIZE.startswith("Humanise ce texte pour qu'il ne ressemble pas à une IA.")


def test_brief_contient_les_donnees_publiques_et_jamais_le_proprietaire():
    brief = eg.build_property_brief(_prop(), "Claire Martin", "Immo Martin")
    assert brief.startswith("<annonce>") and "</annonce>" in brief
    for expected in ("Villa 5 pièces", "2022 Bevaix", "CHF 1'250'000", "Pièces : 5",
                     "160 m²", "Immo Test SA", "Belle villa avec jardin.", "Nom : Claire Martin"):  # fmt: skip
        assert expected in brief
    assert "Jean Dupont" not in brief and "propriétaire" not in brief.lower()


def test_brief_sans_expediteur_et_description_tronquee():
    brief = eg.build_property_brief(
        _prop(listings=[SimpleNamespace(description="x" * 5000)], price_chf=None)
    )
    assert "Expéditeur :\n(non fourni)" in brief
    assert (
        "x" * eg.MAX_DESCRIPTION_CHARS in brief
        and "x" * (eg.MAX_DESCRIPTION_CHARS + 1) not in brief
    )
    assert "Prix affiché" not in brief


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _resp(text="", stop="end_turn", i=10, o=5):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        content=[block] if text else [], stop_reason=stop,
        usage=SimpleNamespace(input_tokens=i, output_tokens=o),
    )  # fmt: skip


def _client(*replies):
    messages = FakeMessages(replies)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


async def test_generate_enchaine_redaction_puis_humanisation():
    client, messages = _client(
        _resp("Objet : A\n\nBrouillon IA"), _resp("Objet : A\n\nTexte humain")
    )
    gen = eg.EmailGenerator(client=client, sender_name="Claire")
    assert await gen.generate(_prop()) == "Objet : A\n\nTexte humain"
    first, second = messages.calls
    assert first["system"] == eg.SKILL_REDACTION and second["system"] == eg.SKILL_HUMANIZE
    assert "<annonce>" in first["messages"][0]["content"]
    assert (
        second["messages"][0]["content"] == "Objet : A\n\nBrouillon IA"
    )  # le 2e skill reçoit le 1er résultat
    for call in (first, second):
        assert call["model"] == "claude-opus-5-5"
        assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
        assert "tools" not in call and "temperature" not in call
    assert (gen.usage.calls, gen.usage.input_tokens, gen.usage.output_tokens) == (2, 20, 10)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (_resp("x", stop="refusal"), "refus"),
        (_resp("x", stop="max_tokens"), "tronquée"),
        (_resp(""), "vide"),
    ],
)
async def test_generate_refuse_les_reponses_inutilisables(reply, message):
    client, _ = _client(reply)
    with pytest.raises(eg.GenerationError, match=message):
        await eg.EmailGenerator(client=client).generate(_prop())


# --- script ----------------------------------------------------------------------------------
SPEC = importlib.util.spec_from_file_location(
    "generate_emails", Path(__file__).resolve().parents[1] / "scripts" / "generate_emails.py"
)
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


def _args(*argv):
    return script.build_parser().parse_args(list(argv))


@pytest.fixture
def stub_db(monkeypatch):
    saved = []

    async def fake_select(_session, **kw):
        fake_select.kw = kw
        return [_prop(), _prop(id="p2", title="Appart")]

    async def fake_save(_session, prop, text):
        saved.append((prop.id, text))

    monkeypatch.setattr(script, "select_properties", fake_select)
    monkeypatch.setattr(script, "save_draft", fake_save)
    monkeypatch.setattr(script, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(script, "get_settings", lambda: SimpleNamespace(anthropic_api_key=None))
    return saved, fake_select


class _NullSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


async def test_dry_run_n_appelle_ni_api_ni_base(stub_db, capsys):
    saved, _ = stub_db
    assert await script.run(_args("--dry-run")) == 0
    assert saved == [] and "2 bien(s) sans brouillon" in capsys.readouterr().out


async def test_sans_cle_api_arret_propre(stub_db, capsys):
    assert await script.run(_args()) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


async def test_limite_invalide(stub_db):
    assert await script.run(_args("--limit", "0")) == 2


async def test_insere_un_brouillon_par_bien_et_continue_apres_un_echec(
    stub_db, monkeypatch, capsys
):
    import anthropic

    saved, fake_select = stub_db
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client, _ = _client(
        _resp("brouillon 1"), _resp("final 1"),  # bien 1 : OK
        _resp("x", stop="refusal"),  # bien 2 : refus → ignoré
    )  # fmt: skip
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: client)
    code = await script.run(_args("--only-new", "--canton", "NE", "--limit", "3"))
    assert code == 0
    assert saved == [("p1", "final 1")]
    assert fake_select.kw == {"limit": 3, "only_new": True, "canton": "NE"}
    out = capsys.readouterr()
    assert "1 brouillon(s) créé(s), 1 échec(s)" in out.out and "refus" in out.err


# --- sélection en base -------------------------------------------------------------------------
@pytest.mark.db
async def test_select_properties_ignore_les_biens_deja_traites():
    from immo_ne_collector.db import AsyncSessionLocal

    def mk(title, status="NEW", canton="NE"):
        return Property(title=title, status=status, first_seen_at=NOW, last_seen_at=NOW,
                        raw_data={"detected_canton": canton})  # fmt: skip

    async with AsyncSessionLocal() as session:
        new, active, done, gone, vd = (
            mk("nouveau"), mk("actif", "ACTIVE"), mk("deja"), mk("parti", "INACTIVE"), mk("vaud", canton="VD"),
        )  # fmt: skip
        session.add_all([new, active, done, gone, vd])
        await session.flush()
        session.add(EmailDraft(property_id=done.id, generated_text="x"))
        await session.commit()

        titles = lambda rows: {p.title for p in rows}  # noqa: E731
        assert titles(await eg.select_properties(session, limit=10)) == {"nouveau", "actif", "vaud"}
        assert titles(await eg.select_properties(session, limit=10, only_new=True)) == {
            "nouveau",
            "vaud",
        }
        assert titles(await eg.select_properties(session, limit=10, canton="ne")) == {
            "nouveau",
            "actif",
        }
        assert len(await eg.select_properties(session, limit=1)) == 1

        saved = await eg.save_draft(session, new, "Objet : x")
        assert saved.status == "draft"
        assert "nouveau" not in titles(await eg.select_properties(session, limit=10))
