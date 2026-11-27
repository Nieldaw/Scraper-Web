"""Génère des brouillons d'e-mails de prospection (table email_drafts) avec l'API Anthropic.

Pour chaque bien actif qui n'a pas encore de brouillon :
  1. skill « rédaction »  : e-mail de contact professionnel pour ce bien ;
  2. skill « humanisation » : réécriture pour un ton naturel ;
  3. insertion dans email_drafts (statut « draft »).

Rien n'est envoyé. Relisez les brouillons sur /prospection, envoyez-les vous-même, puis
cliquez sur « Marquer comme envoyé ».

Exemples :
  python3 scripts/generate_emails.py --dry-run
  python3 scripts/generate_emails.py --limit 5 --sender-name "Claire Martin" \
      --sender-agency "Immo Martin"
  python3 scripts/generate_emails.py --only-new --canton NE --limit 20

Clé API : variable ANTHROPIC_API_KEY (ou ligne ANTHROPIC_API_KEY=… dans .env).
Chaque bien coûte deux appels à l'API : gardez --limit bas au début.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.config import get_settings  # noqa: E402
from immo_ne_collector.db import AsyncSessionLocal  # noqa: E402
from immo_ne_collector.services.email_generation import (  # noqa: E402
    DEFAULT_MODEL,
    EmailGenerator,
    GenerationError,
    save_draft,
    select_properties,
)
from immo_ne_collector.services.source_config import ROMANDY_CANTONS  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="nombre maximum de biens (défaut : 10)"
    )
    parser.add_argument(
        "--only-new", action="store_true", help="seulement les biens au statut « nouveau »"
    )
    parser.add_argument("--canton", choices=ROMANDY_CANTONS, help="restreindre à un canton")
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))
    parser.add_argument("--sender-name", default=os.environ.get("EMAIL_SENDER_NAME"))
    parser.add_argument("--sender-agency", default=os.environ.get("EMAIL_SENDER_AGENCY"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="liste les biens concernés sans appeler l'API ni écrire en base",
    )
    return parser


def _api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or get_settings().anthropic_api_key


async def run(args: argparse.Namespace) -> int:
    if not 1 <= args.limit <= 200:
        print("--limit doit être compris entre 1 et 200.", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as session:
        properties = await select_properties(
            session, limit=args.limit, only_new=args.only_new, canton=args.canton
        )
        print(f"{len(properties)} bien(s) sans brouillon.")
        if args.dry_run or not properties:
            for prop in properties:
                print(
                    f"- {prop.title or 'Sans titre'} "
                    f"({prop.postal_code or ''} {prop.city or ''})".rstrip()
                )
            return 0

        key = _api_key()
        if not key:
            print(
                "Clé API manquante : définissez ANTHROPIC_API_KEY "
                "(variable d'environnement ou .env).",
                file=sys.stderr,
            )
            return 2

        import anthropic

        client = anthropic.AsyncAnthropic(api_key=key)
        generator = EmailGenerator(
            client=client,
            model=args.model,
            sender_name=args.sender_name,
            sender_agency=args.sender_agency,
        )
        created = failed = 0
        for prop in properties:
            label = prop.title or str(prop.id)
            try:
                text = await generator.generate(prop)
                await save_draft(session, prop, text)
                created += 1
                print(f"✓ {label}")
            except GenerationError as exc:
                failed += 1
                print(f"✗ {label} : {exc}", file=sys.stderr)
            except anthropic.AuthenticationError:
                print("Clé API refusée (AuthenticationError). Arrêt.", file=sys.stderr)
                return 1
            except (
                anthropic.APIError
            ) as exc:  # réseau, quota, 5xx… : on continue avec le bien suivant
                failed += 1
                print(f"✗ {label} : {type(exc).__name__} — {exc}", file=sys.stderr)

        usage = generator.usage
        print(
            f"\nTerminé : {created} brouillon(s) créé(s), {failed} échec(s). "
            f"{usage.calls} appels, {usage.input_tokens} tokens en entrée, "
            f"{usage.output_tokens} en sortie. À relire sur /prospection."
        )
        return 0 if created or not failed else 1


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
