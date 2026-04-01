from __future__ import annotations

import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://unclaimedfunds.nj.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[NJ][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[NJ][DEBUG] {message}")


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def normalize_money(value) -> str:
    if value is None:
        return "0"
    text = str(value).strip().replace(",", "").replace("$", "")
    if text == "":
        return "0"
    try:
        num = float(text)
        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "0"


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
        raise RuntimeError(f"[NJ] Could not locate text field for label: {label}")
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
        raise RuntimeError(f"[NJ] Could not locate dropdown for label: {label}")

    log_debug(f"Select '{label}' via {strategy} value={value!r}")
    locator.scroll_into_view_if_needed(timeout=10_000)

    value_str = str(value).strip()
    if value_str == "":
        return False

    # Try direct selection first.
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

    # Normalized fallback matching.
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


def safe_check_radio(page: Page, group_label: str, target_yes: bool) -> None:
    target_text = "Yes" if target_yes else "No"
    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        raise RuntimeError(f"[NJ] Could not find radio group question: {group_label}")

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

    raise RuntimeError(f"[NJ] Could not set radio '{group_label}' to {target_text}")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role exact", page.get_by_role("button", name="Next", exact=True)),
        ("role partial", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('Next')")),
        ("submit", page.locator("input[type='submit'][value*='Next']")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[NJ] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run(page: Page, filing: dict, company: dict) -> dict:
    """New Jersey holder info automation. Stops after NEXT at upload step."""
    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Primary Holder Information
    safe_fill_by_label(page, "Holder Name", str(company.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Contact Name", str(company.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company.get("phone_extension", "")).strip())

    email = str(company.get("email", "")).strip()
    email_confirmation = str(company.get("email_confirmation", "")).strip() or email
    safe_fill_by_label(page, "Email Address", email)
    safe_fill_by_label(page, "Email Address Confirmation", email_confirmation)

    # Report Information
    safe_select_by_label(page, "Report Type", str(filing.get("report_type", "")).strip())

    report_year = str(filing.get("report_year", "")).strip()
    if report_year:
        year_candidates = [
            page.get_by_label("Report Year", exact=True),
            page.get_by_label("Report Year", exact=False),
            page.locator("select[name*='report'][name*='year' i], select[id*='report'][id*='year' i]"),
        ]
        year_locator: Optional[Locator] = None
        for c in year_candidates:
            try:
                if c.count() > 0:
                    year_locator = c.first
                    break
            except Exception:
                continue

        if year_locator:
            try:
                year_locator.wait_for(state="visible", timeout=5_000)
                disabled_attr = year_locator.get_attribute("disabled")
                aria_disabled = (year_locator.get_attribute("aria-disabled") or "").lower()
                is_disabled = disabled_attr is not None or aria_disabled == "true"
                if is_disabled:
                    log_debug("Report Year is disabled; leaving existing value as-is")
                else:
                    safe_select_by_label(page, "Report Year", report_year)
            except Exception:
                safe_select_by_label(page, "Report Year", report_year)
        else:
            safe_select_by_label(page, "Report Year", report_year)

    safe_check_radio(page, "This is a Negative Report", normalize_bool(filing.get("negative_report")))

    amount = normalize_money(filing.get("total_dollar_amount_remitted"))
    safe_fill_by_label(page, "Total Dollar Amount Remitted", amount)

    payment_type = str(filing.get("funds_remitted_via", "")).strip()
    if payment_type:
        payment_ok = safe_select_by_label(page, "Payment Type", payment_type)
        if not payment_ok:
            log_debug(
                f"Payment Type value {payment_type!r} did not match dropdown options; leaving for manual review"
            )

    click_next(page, "after NJ holder info")

    # Wait for upload step readiness then stop.
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

    log_step("Reached New Jersey upload step.")
    return {"state": "NJ", "status": "reached_upload_step"}


def run_new_jersey(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()
    return run(page=page, filing=filing_data, company=company_data)
