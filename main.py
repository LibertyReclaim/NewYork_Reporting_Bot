from __future__ import annotations

import argparse
import inspect
import re
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional

from playwright.sync_api import sync_playwright

from states.alabama import run_alabama
from states.alaska import run_alaska
from states.arkansas import run_arkansas
from states.california import run_california
from states.colorado import run_colorado
from states.connecticut import run_connecticut
from states.delaware import run_delaware
from states.idaho import run_idaho
from states.illinois import run_illinois
from states.indiana import run_indiana
from states.iowa import run_iowa
from states.kansas import run_kansas
from states.louisiana import run_louisiana
from states.maine import run_maine
from states.maryland import run_maryland
from states.massachusetts import run_massachusetts
from states.michigan import run_michigan
from states.mississippi import run_mississippi
from states.minnesota import run_minnesota
from states.nebraska import run_nebraska
from states.nevada import run_nevada
from states.new_hampshire import run_new_hampshire
from states.new_jersey import run_new_jersey
from states.new_york import run_new_york
from states.north_carolina import run_north_carolina
from states.north_dakota import run_north_dakota
from states.ohio import run_ohio
from states.oklahoma import run_oklahoma
from states.oregon import run_oregon
from states.rhode_island import run_rhode_island
from states.south_carolina import run_south_carolina
from states.south_dakota import run_south_dakota
from states.texas import run_texas
from states.utah import run_utah
from states.virginia import run_virginia
from states.washington import run_washington
from states.west_virginia import run_west_virginia
from states.wyoming import run_wyoming
from utils.excel_reader import (
    get_company_by_name,
    get_filings_for_company_and_states,
    load_workbook_data,
)

# Default root for client NAUPA files (Windows-friendly path handling via pathlib)
DEFAULT_CLIENT_ROOT = Path(r"C:\Users\ricardo.garcia\OneDrive - Andersen\Compliance Bot")

VALID_STATE_CODES = {
    "AL", "AK", "AR", "AZ", "CA", "CO", "CT", "DE", "GA", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA",
    "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}

STATE_RUNNERS: Dict[str, Callable] = {
    "AL": run_alabama,
    "AK": run_alaska,
    "AR": run_arkansas,
    "CA": run_california,
    "CO": run_colorado,
    "CT": run_connecticut,
    "DE": run_delaware,
    "ID": run_idaho,
    "IL": run_illinois,
    "IN": run_indiana,
    "IA": run_iowa,
    "KS": run_kansas,
    "LA": run_louisiana,
    "MA": run_massachusetts,
    "MD": run_maryland,
    "ME": run_maine,
    "MI": run_michigan,
    "MN": run_minnesota,
    "MS": run_mississippi,
    "NC": run_north_carolina,
    "ND": run_north_dakota,
    "NE": run_nebraska,
    "NH": run_new_hampshire,
    "NJ": run_new_jersey,
    "NV": run_nevada,
    "NY": run_new_york,
    "OH": run_ohio,
    "OK": run_oklahoma,
    "OR": run_oregon,
    "RI": run_rhode_island,
    "SC": run_south_carolina,
    "SD": run_south_dakota,
    "TX": run_texas,
    "UT": run_utah,
    "VA": run_virginia,
    "WA": run_washington,
    "WV": run_west_virginia,
    "WY": run_wyoming,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-state holder reporting bot controller")
    parser.add_argument("--workbook", required=True, help="Path to master filing workbook")
    parser.add_argument("--company", required=True, help="Company name (Companies.company_name)")
    parser.add_argument(
        "--states",
        nargs="+",
        required=False,
        help="Optional override. State codes, e.g. NY CT or NY,CT,CA. If omitted, auto-detected from NAUPA filenames.",
    )
    parser.add_argument(
        "--client-root",
        default=str(DEFAULT_CLIENT_ROOT),
        help="Root folder containing company folders with NAUPA TXT files.",
    )
    return parser.parse_args()


def parse_state_codes(raw_values: Optional[List[str]]) -> List[str]:
    if not raw_values:
        return []
    parsed: List[str] = []
    for raw in raw_values:
        parsed.extend([s.strip().upper() for s in str(raw).split(",") if s.strip()])
    return parsed


def parse_state_code_from_filename(filename: str) -> Optional[str]:
    """Extract a valid 2-letter state code from filename tokens split by separators."""
    stem = Path(filename).stem.upper()
    tokens = [t for t in re.split(r"[\s_\-\.]+", stem) if t]
    for token in tokens:
        if token in VALID_STATE_CODES:
            return token
    return None


def discover_client_naupa_files(client_folder: Path) -> Dict[str, Path]:
    """Discover .txt NAUPA files and map the newest file per state code."""
    if not client_folder.exists() or not client_folder.is_dir():
        raise FileNotFoundError(f"Client folder does not exist: {client_folder}")

    txt_files = [p for p in client_folder.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
    if not txt_files:
        raise FileNotFoundError(f"No .txt NAUPA files found in client folder: {client_folder}")

    mapping: Dict[str, Path] = {}
    for txt_file in txt_files:
        state_code = parse_state_code_from_filename(txt_file.name)
        if not state_code:
            print(f"[MAIN] SKIPPED filename with no state code: {txt_file.name}")
            continue

        if state_code in mapping:
            current = mapping[state_code]
            if txt_file.stat().st_mtime > current.stat().st_mtime:
                print(
                    f"[MAIN] WARNING duplicate state file for {state_code}; choosing newer file: "
                    f"{txt_file.name} over {current.name}"
                )
                mapping[state_code] = txt_file
            else:
                print(
                    f"[MAIN] WARNING duplicate state file for {state_code}; keeping newer file: "
                    f"{current.name}, skipping {txt_file.name}"
                )
        else:
            mapping[state_code] = txt_file

    if not mapping:
        raise FileNotFoundError(f"No valid state-coded .txt files found in client folder: {client_folder}")

    return mapping


def print_summary(summary: Dict[str, str]) -> None:
    print("\n========== FINAL SUMMARY ==========")
    for state_code, result in summary.items():
        print(f"- {state_code}: {result}")


def invoke_state_runner(
    runner: Callable,
    context,
    company_data: dict,
    filing_data: dict,
    naupa_file_path: Path,
    test_mode: bool,
):
    """
    Invoke state runner with backward-compatible signature handling.
    If runner supports extra args, pass naupa_file_path/test_mode explicitly.
    """
    signature = inspect.signature(runner)
    kwargs = {
        "context": context,
        "company_data": company_data,
        "filing_data": filing_data,
    }
    if "naupa_file_path" in signature.parameters:
        kwargs["naupa_file_path"] = str(naupa_file_path)
    if "test_mode" in signature.parameters:
        kwargs["test_mode"] = test_mode
    return runner(**kwargs)


def main() -> None:
    args = parse_args()

    print(f"[MAIN] Loading workbook: {args.workbook}")
    companies_rows, filings_rows, _state_requirements_rows = load_workbook_data(args.workbook)

    print(f"[MAIN] Looking up company by name: {args.company!r}")
    company_data = get_company_by_name(companies_rows, args.company)
    if not company_data:
        raise RuntimeError(f"Company not found in Companies sheet: {args.company!r}")

    # Workbook compatibility aliases
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

    client_root = Path(args.client_root)
    client_folder = client_root / args.company
    print(f"[MAIN] Client folder: {client_folder}")

    naupa_files_by_state = discover_client_naupa_files(client_folder)
    print(f"[MAIN] Found {len(naupa_files_by_state)} NAUPA txt files")

    detected_states = sorted(naupa_files_by_state.keys())
    print(f"[MAIN] Detected states from filenames: {', '.join(detected_states)}")

    manual_override_states = parse_state_codes(args.states)
    if manual_override_states:
        requested_states = [s for s in manual_override_states if s in detected_states]
        missing_manual = sorted(set(manual_override_states) - set(detected_states))
        if missing_manual:
            print(f"[MAIN] Skipped manual states with no matching txt file: {', '.join(missing_manual)}")
        print(f"[MAIN] Using manual --states override: {', '.join(requested_states)}")
    else:
        requested_states = detected_states

    unsupported_detected = sorted([s for s in requested_states if s not in STATE_RUNNERS])
    if unsupported_detected:
        print(f"[MAIN] Skipped unsupported detected states: {', '.join(unsupported_detected)}")

    runnable_states = [s for s in requested_states if s in STATE_RUNNERS]
    if not runnable_states:
        raise RuntimeError("No implemented states available to run after filtering detected/manual states")

    print(f"[MAIN] Implemented states to run: {', '.join(runnable_states)}")

    print(f"[MAIN] Finding filings for company_id={company_id!r} and states={runnable_states}")
    matching_filings = get_filings_for_company_and_states(filings_rows, company_id, runnable_states)

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

        for state_code in runnable_states:
            naupa_path = naupa_files_by_state.get(state_code)
            if not naupa_path:
                print(f"[MAIN] {state_code}: skipped - no NAUPA txt path")
                summary[state_code] = "skipped - no NAUPA txt path"
                continue

            filing_data = filings_by_state.get(state_code)
            if not filing_data:
                print(f"[MAIN] {state_code}: skipped - no matching filing row")
                summary[state_code] = "skipped - no matching filing row"
                continue

            # Inject explicit NAUPA override and test mode markers for state runners.
            filing_data = dict(filing_data)
            filing_data["naupa_file_path"] = str(naupa_path)
            filing_data["upload_txt_file_path"] = str(naupa_path)
            filing_data["test_mode"] = True

            try:
                print(f"[MAIN] Dispatching state: {state_code}")
                print(f"[{state_code}] Using NAUPA file: {naupa_path}")
                runner = STATE_RUNNERS[state_code]
                result = invoke_state_runner(
                    runner=runner,
                    context=context,
                    company_data=company_data,
                    filing_data=filing_data,
                    naupa_file_path=naupa_path,
                    test_mode=True,
                )
                print(f"[{state_code}] TEST MODE: stopping before final submit")
                summary[state_code] = result.get("status", str(result)) if isinstance(result, dict) else str(result)
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
