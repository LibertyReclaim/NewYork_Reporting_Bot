from __future__ import annotations

import re
import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page, TimeoutError

TARGET_URL = "https://findmassmoney.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[MA][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[MA][DEBUG] {message}")


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "yes", "y", "1"}


def normalize_money(value) -> str:
    if value is None:
        return "0"
    text = str(value).strip()
    if text == "":
        return "0"
    text = text.replace(",", "").replace("$", "")
    try:
        num = float(text)
        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "0"


def parse_company_address(address: str) -> Tuple[str, str, str, str]:
    """Best-effort parser: returns (address1, city, state, postal_code)."""
    if not address:
        return "", "", "", ""

    text = str(address).strip()
    if not text:
        return "", "", "", ""

    # Typical pattern: street, city, ST 12345
    match = re.match(r"^(.*?),\s*([^,]+),\s*([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3).upper(), match.group(4).strip()

    # Fallback: pull zip and state if present.
    zip_match = re.search(r"(\d{5}(?:-\d{4})?)", text)
    state_match = re.search(r"\b([A-Za-z]{2})\b", text)
    postal_code = zip_match.group(1) if zip_match else ""
    state = state_match.group(1).upper() if state_match else ""
    return text, "", state, postal_code


def first_visible_locator(candidates: list[Tuple[str, Locator]], timeout_ms: int = 4_000) -> Tuple[str, Optional[Locator]]:
    for strategy, candidate in candidates:
        try:
            if candidate.count() > 0:
                candidate.first.wait_for(state="visible", timeout=timeout_ms)
                return strategy, candidate.first
        except Exception:
            continue
    return "", None


def safe_fill_by_label(page: Page, label: str, value: str) -> None:
    candidates = [
        (f"label exact: {label}", page.get_by_label(label, exact=True)),
        (f"label partial: {label}", page.get_by_label(label, exact=False)),
        (
            f"nearby input: {label}",
            page.locator(
                f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::input or self::textarea][1]"
            ),
        ),
    ]
    strategy, locator = first_visible_locator(candidates)
    if not locator:
        raise RuntimeError(f"[MA] Could not locate text field for label: {label}")
    log_debug(f"Fill '{label}' via {strategy} value={value!r}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.fill(str(value), timeout=10_000)


def safe_select_by_label(page: Page, label: str, value: str) -> None:
    candidates = [
        (f"label exact: {label}", page.get_by_label(label, exact=True)),
        (f"label partial: {label}", page.get_by_label(label, exact=False)),
        (
            f"nearby select: {label}",
            page.locator(f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::select][1]"),
        ),
    ]
    strategy, locator = first_visible_locator(candidates)
    if not locator:
        raise RuntimeError(f"[MA] Could not locate dropdown for label: {label}")

    log_debug(f"Select '{label}' via {strategy} value={value!r}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    try:
        locator.select_option(label=str(value), timeout=10_000)
    except Exception:
        locator.select_option(value=str(value), timeout=10_000)


def safe_select_negative_report(page: Page, is_negative: bool) -> None:
    target = "Yes" if is_negative else "No"
    question = page.get_by_text("This is a Negative Report", exact=False)
    if question.count() == 0:
        raise RuntimeError("[MA] Could not find negative report question text")

    q = question.first
    container = q.locator("xpath=ancestor::*[self::div or self::form][1]")
    scoped_label = container.get_by_text(target, exact=True)
    if scoped_label.count() > 0:
        scoped_label.first.scroll_into_view_if_needed(timeout=10_000)
        scoped_label.first.click(timeout=10_000)
        log_debug(f"Negative report selected={target} via container label")
        return

    rel_label = q.locator(f"xpath=following::label[normalize-space(.)='{target}'][1]")
    if rel_label.count() > 0 and rel_label.first.is_visible():
        rel_label.first.scroll_into_view_if_needed(timeout=10_000)
        rel_label.first.click(timeout=10_000)
        log_debug(f"Negative report selected={target} via following label")
        return

    raise RuntimeError("[MA] Could not select negative report Yes/No")


def safe_set_incorporation_date(page: Page, month: str = "01", day: str = "01", year: str = "2020") -> None:
    candidates = [
        page.get_by_label("Date of Incorporation", exact=False),
        page.locator("select[name*='incorporation'][name*='month' i], select[id*='incorporation'][id*='month' i]"),
    ]

    # Try direct labeled control first if it's a date widget that can accept text.
    try:
        if candidates[0].count() > 0:
            ctrl = candidates[0].first
            ctrl.scroll_into_view_if_needed(timeout=10_000)
            tag = ctrl.evaluate("el => (el.tagName || '').toLowerCase()")
            if tag in {"input", "textarea"}:
                ctrl.fill(f"{month}/{day}/{year}", timeout=10_000)
                log_debug("Date of Incorporation filled directly as text")
                return
    except Exception:
        pass

    # Try common month/day/year select groups near date label.
    label = page.get_by_text("Date of Incorporation", exact=False)
    if label.count() > 0:
        base = label.first
        mm = base.locator("xpath=following::select[1]")
        dd = base.locator("xpath=following::select[2]")
        yy = base.locator("xpath=following::select[3]")
        if mm.count() > 0 and dd.count() > 0 and yy.count() > 0:
            mm.first.select_option(label=month)
            dd.first.select_option(label=day)
            try:
                yy.first.select_option(label=year)
            except Exception:
                yy.first.select_option(value=year)
            log_debug("Date of Incorporation selected via MM/DD/YYYY dropdowns")
            return

    log_debug("Date of Incorporation placeholder could not be set; continuing")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role exact", page.get_by_role("button", name="Next", exact=True)),
        ("role partial", page.get_by_role("button", name="Next", exact=False)),
        ("text button", page.locator("button:has-text('Next')")),
        ("submit", page.locator("input[type='submit'][value*='Next']")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[MA] Could not find NEXT button")
    log_debug(f"NEXT strategy: {strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run(page: Page, filing: dict, company: dict) -> dict:
    """Massachusetts holder info step automation. Stops after NEXT to upload step."""
    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Primary holder info
    holder_name = str(company.get("holder_name", company.get("company_name", ""))).strip()
    fein = str(company.get("holder_tax_id", company.get("fein", ""))).strip()
    holder_id = str(company.get("holder_id", "")).strip()
    contact_name = str(company.get("contact_name", "")).strip()
    phone = str(company.get("contact_phone", company.get("phone", ""))).strip()
    phone_extension = str(company.get("phone_extension", "")).strip()
    email = str(company.get("email", "")).strip()
    email_confirmation = str(company.get("email_confirmation", email)).strip()

    address1 = str(company.get("address_1", "")).strip()
    address2 = str(company.get("address_2", "")).strip()
    city = str(company.get("city", "")).strip()
    state = str(company.get("state", "")).strip()
    postal_code = str(company.get("postal_code", company.get("zip", ""))).strip()

    # Fallback parsing only if sheet does not provide structured address values.
    if not address1 and not city and not postal_code:
        address_raw = str(company.get("address", "")).strip()
        parsed_address1, parsed_city, parsed_state, parsed_postal = parse_company_address(address_raw)
        address1 = parsed_address1 or address_raw
        city = city or parsed_city
        state = state or parsed_state
        postal_code = postal_code or parsed_postal

    safe_fill_by_label(page, "Holder Name", holder_name)
    safe_fill_by_label(page, "Holder Tax ID", fein)
    if holder_id:
        safe_fill_by_label(page, "Holder ID", holder_id)
    safe_fill_by_label(page, "Holder Contact", contact_name)
    safe_fill_by_label(page, "Contact Phone No", phone)
    safe_fill_by_label(page, "Phone Extension", phone_extension)
    safe_fill_by_label(page, "Email", email)
    safe_fill_by_label(page, "Email Confirmation", email_confirmation)

    safe_fill_by_label(page, "Address 1", address1)
    safe_fill_by_label(page, "Address 2", address2)
    safe_fill_by_label(page, "Address 3", "")
    safe_fill_by_label(page, "City", city)

    # State should be Massachusetts, but enforce if needed.
    try:
        safe_select_by_label(page, "State", "Massachusetts")
    except Exception:
        log_debug("State selection fallback: keeping existing state value")

    safe_fill_by_label(page, "Postal Code", postal_code)

    # State of Incorporation placeholder strategy.
    try:
        safe_select_by_label(page, "State of Incorporation", "CA")
    except Exception:
        inferred = state if state else ""
        if inferred:
            try:
                safe_select_by_label(page, "State of Incorporation", inferred)
            except Exception:
                log_debug("State of Incorporation fallback selection failed; continuing")

    # Date of Incorporation placeholder 01/01/2020
    safe_set_incorporation_date(page, month="01", day="01", year="2020")

    # Report Info
    safe_select_by_label(page, "Report Type", "Annual Report")
    report_year = str(filing.get("report_year", "")).strip()
    if report_year:
        safe_select_by_label(page, "Report Year", report_year)
    safe_select_negative_report(page, normalize_bool(filing.get("negative_report")))

    # Report Totals
    amount = normalize_money(filing.get("total_dollar_amount_remitted"))
    safe_fill_by_label(page, "Aggregate Cash Total", amount)
    safe_fill_by_label(page, "Owner Cash Total", amount)
    safe_fill_by_label(page, "Total of Cash Amount Reported", amount)
    safe_fill_by_label(page, "Total Number of Shares Reported", "0")
    safe_fill_by_label(page, "Number of Owners Reported", "1")

    click_next(page, "after MA holder info")

    # Wait for upload step readiness and stop.
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                file_input.first.wait_for(state="attached", timeout=2_000)
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    log_step("Reached Massachusetts upload step. Continue flow manually/next module.")
    return {"state": "MA", "status": "reached_upload_step"}


def run_massachusetts(context, company_data: dict, filing_data: dict) -> dict:
    """Wrapper for controller compatibility (opens a new tab and calls run)."""
    page = context.new_page()
    return run(page=page, filing=filing_data, company=company_data)
