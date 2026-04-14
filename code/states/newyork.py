from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext

TARGET_URL = "https://ouf.osc.ny.gov/app/holder-info"


def run(context: BrowserContext, record: dict[str, Any], naupa_path: Path) -> dict[str, str]:
    """
    NY base runner placeholder.
    Intentionally does NOT submit filings; keeps browser open for manual review at preview/signature.
    """
    page = context.new_page()
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)

    print(f"[NY][STEP] Opened NY holder portal: {TARGET_URL}")
    print(f"[NY][DEBUG] holder_id={record.get('holder_id', '')!r}")
    print(f"[NY][DEBUG] NAUPA path={str(naupa_path)!r}")
    print("[NY][STEP] Manual continuation expected. Do NOT submit. Stop at preview/signature page.")

    # Keep browser open so local operator can complete up to preview/signature page.
    page.pause()

    return {"status": "reached_upload_step"}
