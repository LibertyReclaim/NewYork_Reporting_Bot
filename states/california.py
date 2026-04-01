from __future__ import annotations

import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://claimit.ca.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[CA][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[CA][DEBUG] {message}")


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def normalize_number(value, default: str = "0") -> str:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("$", "")
    return text if text else default


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
        raise RuntimeError(f"[CA] Could not locate text field for label: {label}")
    log_debug(f"Fill '{label}' via {strategy} value={value!r}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.fill(str(value), timeout=10_000)


def safe_select_by_label(page: Page, label: str, value: str) -> bool:
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
        raise RuntimeError(f"[CA] Could not locate dropdown for label: {label}")

    value_str = str(value).strip()
    log_debug(f"Select '{label}' via {strategy} value={value_str!r}")
    if not value_str:
        return False

    locator.scroll_into_view_if_needed(timeout=10_000)
    try:
        locator.select_option(label=value_str, timeout=10_000)
        return True
    except Exception:
        pass
    try:
        locator.select_option(value=value_str, timeout=10_000)
        return True
    except Exception:
        pass

    normalized_target = value_str.lower().replace(" ", "")
    options = locator.locator("option")
    for i in range(options.count()):
        opt = options.nth(i)
        opt_label = (opt.inner_text() or "").strip()
        opt_value = (opt.get_attribute("value") or "").strip()
        if opt_label.lower().replace(" ", "") == normalized_target:
            locator.select_option(label=opt_label, timeout=10_000)
            return True
        if opt_value.lower().replace(" ", "") == normalized_target:
            locator.select_option(value=opt_value, timeout=10_000)
            return True
    return False


def get_select_locator_by_label(page: Page, label: str) -> Optional[Locator]:
    candidates = [
        page.get_by_label(label, exact=True),
        page.get_by_label(label, exact=False),
        page.locator(f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::select][1]"),
    ]
    for candidate in candidates:
        try:
            if candidate.count() > 0:
                candidate.first.wait_for(state="visible", timeout=5_000)
                return candidate.first
        except Exception:
            continue
    return None


def safe_check_radio(page: Page, group_label: str, yes_or_no: str) -> None:
    target_text = "Yes" if str(yes_or_no).strip().lower() == "yes" else "No"

    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        raise RuntimeError(f"[CA] Could not find radio group: {group_label}")

    q = question.first
    container = q.locator("xpath=ancestor::*[self::div or self::form][1]")
    scoped_label = container.get_by_text(target_text, exact=True)
    if scoped_label.count() > 0 and scoped_label.first.is_visible():
        scoped_label.first.scroll_into_view_if_needed(timeout=10_000)
        scoped_label.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target_text} via container label")
        return

    rel_label = q.locator(f"xpath=following::label[normalize-space(.)='{target_text}'][1]")
    if rel_label.count() > 0 and rel_label.first.is_visible():
        rel_label.first.scroll_into_view_if_needed(timeout=10_000)
        rel_label.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target_text} via following label")
        return

    raise RuntimeError(f"[CA] Could not set radio '{group_label}' to {target_text}")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role partial", page.get_by_role("button", name="NEXT", exact=False)),
        ("role next", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('NEXT'), button:has-text('Next')")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[CA] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run(page: Page, filing: dict, company: dict) -> dict:
    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # HOLDER INFORMATION
    safe_fill_by_label(page, "Holder Name", str(company.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder ID", "")
    safe_fill_by_label(page, "Contact Name", str(company.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company.get("phone_extension", "")).strip())

    email = str(company.get("email", "")).strip()
    email_confirmation = str(company.get("email_confirmation", "")).strip() or email
    safe_fill_by_label(page, "Email Address", email)
    safe_fill_by_label(page, "Email Address Confirmation", email_confirmation)

    # REPORT INFORMATION
    safe_select_by_label(page, "Report Type", str(filing.get("report_type", "")).strip())
    safe_select_by_label(page, "Submission Type", str(filing.get("submission_type", "")).strip())

    report_year = str(filing.get("report_year", "")).strip()
    if report_year:
        safe_select_by_label(page, "Report Year", report_year)

    fiscal_year_end = str(filing.get("fiscal_year_end", "June")).strip() or "June"
    log_debug(f"Fiscal Year End target value={fiscal_year_end!r}")
    selected = safe_select_by_label(page, "Fiscal Year End", fiscal_year_end)
    if not selected:
        log_debug(f"Fiscal Year End value {fiscal_year_end!r} not found; leaving for manual review")

    negative_report = normalize_bool(filing.get("negative_report"))
    safe_check_radio(page, "This is a Negative Report", "Yes" if negative_report else "No")

    total_cash_reported = normalize_number(
        filing.get("total_cash_reported", filing.get("total_dollar_amount_remitted", "0")), default="0"
    )
    safe_fill_by_label(page, "Total Cash Reported", total_cash_reported)

    payment_type = str(filing.get("funds_remitted_via", "")).strip()
    funds_locator = get_select_locator_by_label(page, "Funds Remitted Via")
    if funds_locator:
        disabled_attr = funds_locator.get_attribute("disabled")
        aria_disabled = (funds_locator.get_attribute("aria-disabled") or "").lower()
        is_disabled = disabled_attr is not None or aria_disabled == "true"
        if is_disabled:
            log_debug("Funds Remitted Via is disabled; skipping field")
        elif payment_type:
            payment_ok = safe_select_by_label(page, "Funds Remitted Via", payment_type)
            if not payment_ok:
                log_debug(f"Funds Remitted Via value {payment_type!r} not found; leaving for manual review")
    else:
        log_debug("Funds Remitted Via select not found; skipping field")

    total_shares_reported = normalize_number(filing.get("total_shares_reported", "0"), default="0")
    safe_fill_by_label(page, "Total Shares Reported", total_shares_reported)

    includes_sdb = normalize_bool(filing.get("includes_safe_deposit_box"))
    safe_check_radio(page, "Includes Safe Deposit Box", "Yes" if includes_sdb else "No")

    click_next(page, "after CA holder info")

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

    log_step("Reached California upload step.")
    return {"status": "reached_upload_step"}


def run_california(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()
    return run(page=page, filing=filing_data, company=company_data)
