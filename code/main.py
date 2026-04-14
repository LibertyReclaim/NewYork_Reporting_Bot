from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from excel_loader import load_and_merge_records
from path_utils import build_naupa_path, clean_blank
from state_registry import get_runner


def resolve_project_root() -> Path:
    # This script is run from code/: `cd code && py main.py`
    return Path(__file__).resolve().parent.parent


def process_records() -> None:
    project_root = resolve_project_root()
    records = load_and_merge_records(project_root)

    if not records:
        print("[MAIN] No rows found in merged workbook data.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        processed = False
        for row in records:
            state_code = clean_blank(row.get("state_code") or row.get("state"), default="").upper()
            holder_id = clean_blank(row.get("holder_id"), default="")
            company_name = clean_blank(row.get("company_name") or row.get("holder_name"), default="UNKNOWN_COMPANY")
            report_year = clean_blank(row.get("report_year") or row.get("year"), default="UNKNOWN_YEAR")

            runner = get_runner(state_code)
            if runner is None:
                print(f"[MAIN] Skipping holder_id={holder_id!r}: unsupported state_code={state_code!r}")
                continue

            naupa_path = build_naupa_path(
                project_root=project_root,
                company_name=company_name,
                state_code=state_code,
                report_year=report_year,
            )

            print(f"[MAIN] Processing holder_id={holder_id!r} state={state_code!r}")
            print(f"[MAIN] Expected NAUPA path: {naupa_path}")

            result = runner(context, row, naupa_path)
            print(f"[MAIN] Runner result: {result}")
            processed = True

            # Base system currently supports NY only; run one filing at a time.
            break

        if not processed:
            print("[MAIN] No supported records were found (currently NY only).")
            context.close()
            browser.close()
            return

        input("[MAIN] Browser is open for preview/signature review. Press Enter to close browser...")
        context.close()
        browser.close()


if __name__ == "__main__":
    process_records()
