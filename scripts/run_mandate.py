import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.services.mandates import run_mandate_and_export


async def _run() -> int:
    mandate, result, export_result = await run_mandate_and_export(output_dir=ROOT / "data" / "exports")
    criteria = result.criteria

    print(f"Mandate ID: {mandate.id}")
    print(
        "Criteria: "
        f"cities={criteria.cities}, "
        f"property_types={criteria.property_types}, "
        f"price=[{criteria.min_price_chf}, {criteria.max_price_chf}], "
        f"rooms=[{criteria.min_rooms}, {criteria.max_rooms}], "
        f"living_area=[{criteria.min_living_area_m2}, {criteria.max_living_area_m2}], "
        f"only_active={criteria.only_active}"
    )
    print(f"Matched properties: {len(result.matches)}")
    print(f"CSV path: {export_result.path}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
