from __future__ import annotations

import argparse
import time
import traceback
from typing import Dict, List

from playwright.sync_api import sync_playwright

from states.california import run_california
from states.connecticut import run_connecticut
from states.delaware import run_delaware
from states.illinois import run_illinois
from states.indiana import run_indiana
from states.maryland import run_maryland
from states.massachusetts import run_massachusetts
from states.michigan import run_michigan
from states.new_jersey import run_new_jersey
from states.new_york import run_new_york
from states.ohio import run_ohio
from states.texas import run_texas
from states.virginia import run_virginia
from utils.excel_reader import (
    get_company_by_name,
    get_filings_for_company_and_states,
    load_workbook_data,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-state holder reporting bot controller")
    parser.add_argument("--workbook", required=True, help="Path to master filing workbook")
    parser.add_argument("--company", required=True, help="Company name (Companies.company_name)")
    parser.add_argument("--states", nargs="+", required=True, help="State codes, e.g. NY CT or NY,CT,CA")
    return parser.parse_args()


def parse_state_codes(raw_values: List[str]) -> List[str]:
    parsed: List[str] = []
    for raw in raw_values:
        parsed.extend([s.strip().upper() for s in str(raw).split(",") if s.strip()])
    return parsed


def print_summary(summary: Dict[str, str]) -> None:
    print("\n========== FINAL SUMMARY ==========")
    for state_code, result in summary.items():
        print(f"- {state_code}: {result}")


def main() -> None:
    args = parse_args()
    requested_states = parse_state_codes(args.states)

    print(f"[MAIN] Loading workbook: {args.workbook}")
    companies_rows, filings_rows, _state_requirements_rows = load_workbook_data(args.workbook)

    print(f"[MAIN] Looking up company by name: {args.company!r}")
    company_data = get_company_by_name(companies_rows, args.company)
    if not company_data:
        raise RuntimeError(f"Company not found in Companies sheet: {args.company!r}")

    # Workbook compatibility aliases (supports holder_* structure and legacy keys).
    company_data = dict(company_data)
    if not company_data.get("company_name"):
        company_data["company_name"] = company_data.get("holder_name", "")
    if not company_data.get("fein"):
        company_data["fein"] = company_data.get("holder_tax_id", "")
    if not company_data.get("phone"):
        company_data["phone"] = company_data.get("contact_phone", "")
    if not company_data.get("address"):
        parts = [
            company_data.get("address_1", ""),
            company_data.get("address_2", ""),
            company_data.get("city", ""),
            company_data.get("state", ""),
        ]
        company_data["address"] = ", ".join([p for p in parts if p]).strip(", ")

    company_id = company_data.get("company_id", "")
    if not company_id:
        raise RuntimeError("Matched company row is missing company_id")

    print(f"[MAIN] Finding filings for company_id={company_id!r} and states={requested_states}")
    matching_filings = get_filings_for_company_and_states(filings_rows, company_id, requested_states)

    filings_by_state: Dict[str, dict] = {}
    for row in matching_filings:
        state = str(row.get("state_code", "")).strip().upper()
        if state and state not in filings_by_state:
            filings_by_state[state] = row

    summary: Dict[str, str] = {}

    with sync_playwright() as p:
        print("[MAIN] Launching Chromium in headed mode")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        for state_code in requested_states:
            filing_data = filings_by_state.get(state_code)
            if not filing_data:
                msg = "no matching filing row"
                print(f"[MAIN] {state_code}: {msg}")
                summary[state_code] = msg
                continue

            try:
                print(f"[MAIN] Dispatching state: {state_code}")

                if state_code == "NY":
                    # Filing data overrides company data when keys overlap.
                    result = run_new_york(context=context, company_data=company_data, filing_data=filing_data)
                    summary[state_code] = str(result)
                elif state_code == "CT":
                    result = run_connecticut(context=context, company_data=company_data, filing_data=filing_data)
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "MA":
                    result = run_massachusetts(context=context, company_data=company_data, filing_data=filing_data)
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "NJ":
                    result = run_new_jersey(context=context, company_data=company_data, filing_data=filing_data)
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "CA":
                    result = run_california(context=context, company_data=company_data, filing_data=filing_data)
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "TX":
                    result = run_texas(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "IL":
                    result = run_illinois(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "OH":
                    result = run_ohio(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "MI":
                    result = run_michigan(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "IN":
                    result = run_indiana(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "VA":
                    result = run_virginia(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "MD":
                    result = run_maryland(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                elif state_code == "DE":
                    result = run_delaware(
                        context=context,
                        company_data=company_data,
                        filing_data=filing_data,
                    )
                    summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
                else:
                    msg = "not implemented"
                    print(f"[MAIN] {state_code}: {msg}")
                    summary[state_code] = msg

            except Exception as exc:
                print(f"[MAIN][ERROR] {state_code} failed: {exc}")
                traceback.print_exc()
                summary[state_code] = f"failed - {exc}"
                continue

        print_summary(summary)
        print("\n[MAIN] Browser/tabs remain open for manual preview review. Press Ctrl+C to exit.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user.")
    except Exception:
        print("\n[MAIN][FATAL] Script terminated due to an error.")
        traceback.print_exc()
        raise
