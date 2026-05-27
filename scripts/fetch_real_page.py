import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.http_fetcher import (
    ScraperHTTPError,
    ScraperTimeoutError,
    fetch_html_to_cache,
)


async def _run(url: str) -> int:
    try:
        result = await fetch_html_to_cache(
            url=url,
            cache_dir=ROOT / "data" / "cache" / "html",
            source="anibis_fetch_test",
        )
    except ScraperHTTPError as exc:
        print(f"HTTP error: {exc.status_code} for {exc.url}")
        return 1
    except ScraperTimeoutError as exc:
        print(f"Timeout error: {exc}")
        return 1
    except Exception as exc:
        print(f"Network or fetch error: {exc}")
        return 1

    print(f"HTTP status: {result.status_code}")
    print(f"Saved file size: {result.size_bytes} bytes")
    print(f"Saved path: {result.file_path}")
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print('Usage: python3 scripts/fetch_real_page.py "URL_A_TESTER"')
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(sys.argv[1])))


if __name__ == "__main__":
    main()
