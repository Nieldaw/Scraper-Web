"""Brouillons d'e-mails de prospection : lecture et changement de statut.

Aucun envoi n'est fait ici : l'utilisateur envoie lui-même et marque le brouillon comme envoyé.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.models import EmailDraft, EmailDraftStatus

STATUS_LABELS = {
    EmailDraftStatus.DRAFT.value: "Brouillon",
    EmailDraftStatus.VALIDATED.value: "Validé",
    EmailDraftStatus.SENT.value: "Envoyé",
}
STATUS_TABS = (("all", "Tous"), *STATUS_LABELS.items())
# transitions autorisées : brouillon → validé → envoyé (on peut envoyer sans passer par « validé »)
ALLOWED_TRANSITIONS = {
    EmailDraftStatus.DRAFT.value: {"validated", "sent"},
    EmailDraftStatus.VALIDATED.value: {"draft", "sent"},
    EmailDraftStatus.SENT.value: set(),
}


async def list_drafts(session: AsyncSession, status: str = "all") -> list[EmailDraft]:
    query = (
        select(EmailDraft)
        .options(selectinload(EmailDraft.property))
        .order_by(EmailDraft.created_at.desc(), EmailDraft.id)
    )
    if status in STATUS_LABELS:
        query = query.where(EmailDraft.status == status)
    return list((await session.execute(query)).scalars().all())


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(select(EmailDraft.status, func.count()).group_by(EmailDraft.status))
    ).all()
    counts = {key: 0 for key in STATUS_LABELS}
    counts.update({status: n for status, n in rows})
    counts["all"] = sum(counts[key] for key in STATUS_LABELS)
    return counts


class InvalidTransition(ValueError):
    pass


async def set_draft_status(
    session: AsyncSession, draft_id: UUID, new_status: str
) -> EmailDraft | None:
    """Change le statut ; ``None`` si inconnu, ``InvalidTransition`` si le passage est interdit."""
    draft = await session.get(EmailDraft, draft_id)
    if draft is None:
        return None
    if new_status not in ALLOWED_TRANSITIONS.get(draft.status, set()):
        raise InvalidTransition(f"{draft.status} → {new_status}")
    draft.status = new_status
    draft.sent_at = datetime.now(UTC) if new_status == EmailDraftStatus.SENT.value else None
    await session.commit()
    return draft
