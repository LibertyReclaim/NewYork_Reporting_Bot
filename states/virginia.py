from __future__ import annotations

import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://vamoneysearch.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[VA][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[VA][DEBUG] {message}")


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def normalize_number(value, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("$", "")
    return text if text else default


def normalize_va_funds(value) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    if upper == "ACH":
        return "ACH"
    if upper == "CHECK":
        return "Check"
    if upper == "WIRE":
        return "Wire"
    return raw


def first_visible_locator(candidates: list[Tuple[str, Locator]], timeout_ms: int = 4_000) -> Tuple[str, Optional[Locator]]:
    for strategy, candidate in candidates:
        try:
            if candidate.count() > 0:
                candidate.first.wait_for(state="visible", timeout=timeout_ms)
                return strategy, candidate.first
        except Exception:
            continue
    return "", None


def get_field_locator(page: Page, label: str, kind: str = "input") -> Optional[Tuple[str, Locator]]:
    if kind == "select":
        candidates = [
            (f"label exact: {label}", page.get_by_label(label, exact=True)),
            (f"label partial: {label}", page.get_by_label(label, exact=False)),
            (
                f"nearby select: {label}",
                page.locator(f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::select][1]"),
            ),
        ]
    else:
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
        return None
    return strategy, locator


def is_disabled_or_readonly(locator: Locator) -> bool:
    disabled_attr = locator.get_attribute("disabled")
    aria_disabled = (locator.get_attribute("aria-disabled") or "").lower()
    readonly_attr = locator.get_attribute("readonly")
    aria_readonly = (locator.get_attribute("aria-readonly") or "").lower()
    return disabled_attr is not None or aria_disabled == "true" or readonly_attr is not None or aria_readonly == "true"


def safe_fill_by_label(page: Page, label: str, value: str, optional: bool = False) -> None:
    found = get_field_locator(page, label, kind="input")
    if not found:
        msg = f"Field not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[VA] {msg}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Field '{label}' is disabled/read-only; skipping")
        return

    value_str = str(value).strip()
    if optional and not value_str:
        log_debug(f"{label} is blank (optional); skipping")
        return

    log_debug(f"Filling {label}: {value_str!r} via {strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.fill(value_str, timeout=10_000)


def safe_select_by_label(page: Page, label: str, value: str, optional: bool = False) -> bool:
    found = get_field_locator(page, label, kind="select")
    if not found:
        msg = f"Dropdown not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return False
        raise RuntimeError(f"[VA] {msg}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' is disabled/read-only; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[VA] Dropdown '{label}' value is blank")

    log_debug(f"Selecting {label}: {value_str!r} via {strategy}")
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

    log_debug(f"Dropdown '{label}' did not match option for value={value_str!r}; leaving for manual review")
    return False


def safe_check_radio(page: Page, group_label: str, yes_value: bool, optional: bool = False) -> None:
    target_text = "Yes" if yes_value else "No"
    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        msg = f"Radio group not found: {group_label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[VA] {msg}")

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

    msg = f"Could not set radio '{group_label}' to {target_text}"
    if optional:
        log_debug(msg + " (optional; skipping)")
        return
    raise RuntimeError(f"[VA] {msg}")


def safe_select_date_part(locator: Locator, target_value: str, field_name: str) -> None:
    target = str(target_value).strip()
    log_debug(f"Due-diligence {field_name} target: {target!r}")

    try:
        locator.select_option(value=target, timeout=10_000)
        return
    except Exception:
        pass

    try:
        locator.select_option(label=target, timeout=10_000)
        return
    except Exception:
        pass

    options = locator.locator("option")
    entries: list[tuple[str, str]] = []
    available_labels: list[str] = []
    for i in range(options.count()):
        opt = options.nth(i)
        label = (opt.inner_text() or "").strip()
        value = (opt.get_attribute("value") or "").strip()
        entries.append((label, value))
        if label:
            available_labels.append(label)

    log_debug(f"Due-diligence {field_name} available options: {available_labels}")

    normalized_target = target.lower().strip()

    month_aliases = {normalized_target}
    if field_name == "month":
        if normalized_target in {"1", "01", "january", "jan"}:
            month_aliases.update({"1", "01", "january", "jan"})

    for label, value in entries:
        normalized_label = label.lower().strip()
        normalized_value = value.lower().strip()

        if field_name == "month":
            if normalized_label in month_aliases or normalized_value in month_aliases:
                locator.select_option(value=value or label, timeout=10_000)
                log_debug(f"Due-diligence month selected by fallback: {label or value!r}")
                return
        else:
            if normalized_label == normalized_target or normalized_value == normalized_target:
                locator.select_option(value=value or label, timeout=10_000)
                log_debug(f"Due-diligence {field_name} selected by fallback: {label or value!r}")
                return

        if field_name in {"day", "month"} and normalized_target in {"01", "1"}:
            if normalized_label in {"01", "1"} or normalized_value in {"01", "1"}:
                locator.select_option(value=value or label, timeout=10_000)
                log_debug(f"Due-diligence {field_name} selected by fallback: {label or value!r}")
                return

    raise RuntimeError(f"[VA] Could not select Due-diligence {field_name} for target={target!r}")


def safe_fill_due_diligence_date(page: Page, mm: str, dd: str, yyyy: str) -> None:
    log_debug("Filling Due-diligence Date")

    month_select = page.locator("#dueDiligenceDate-month")
    day_select = page.locator("#dueDiligenceDate-day")
    year_select = page.locator("#dueDiligenceDate-year")

    if month_select.count() == 0 or day_select.count() == 0 or year_select.count() == 0:
        raise RuntimeError("[VA] Due-diligence date dropdowns not found by expected IDs")

    month = month_select.first
    day = day_select.first
    year = year_select.first

    if is_disabled_or_readonly(month) or is_disabled_or_readonly(day) or is_disabled_or_readonly(year):
        raise RuntimeError("[VA] One or more Due-diligence date dropdowns are disabled/read-only")

    month.scroll_into_view_if_needed(timeout=10_000)
    safe_select_date_part(month, mm, "month")

    day.scroll_into_view_if_needed(timeout=10_000)
    safe_select_date_part(day, dd, "day")

    year.scroll_into_view_if_needed(timeout=10_000)
    safe_select_date_part(year, yyyy, "year")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role partial", page.get_by_role("button", name="NEXT", exact=False)),
        ("role next", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('NEXT'), button:has-text('Next')")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[VA] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run_virginia(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # HOLDER INFO
    log_debug("Filling Holder Name")
    safe_fill_by_label(page, "Holder Name", str(company_data.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("fein", company_data.get("holder_tax_id", ""))).strip())

    log_debug("Holder ID should remain blank for Virginia; skipping")

    safe_fill_by_label(page, "Contact Name", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company_data.get("phone", company_data.get("contact_phone", ""))).strip())
    safe_fill_by_label(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)

    email = str(company_data.get("email", "")).strip()
    safe_fill_by_label(page, "Email Address", email)
    safe_fill_by_label(page, "Email Address Confirmation", email)

    # REPORT INFO
    log_debug("Selecting Report Type")
    safe_select_by_label(page, "Report Type", "Annual Report", optional=False)
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=False)

    negative_report = normalize_bool(filing_data.get("negative_report"))
    log_debug(f"Negative Report: {'Yes' if negative_report else 'No'}")
    safe_check_radio(page, "This is a Negative Report", negative_report, optional=True)

    if negative_report:
        log_debug("Negative Report is Yes; skipping Due-diligence Date, Total Dollar Amount Remitted, and Funds Remitted Via")
    else:
        mm = str(filing_data.get("due_diligence_month", "")).strip() or "01"
        dd = str(filing_data.get("due_diligence_day", "")).strip() or "01"
        yyyy = str(filing_data.get("due_diligence_year", "")).strip() or "2026"
        safe_fill_due_diligence_date(page, mm, dd, yyyy)

        total_dollar_amount_remitted = filing_data.get("total_dollar_amount_remitted")
        total_remitted = filing_data.get("total_remitted")
        total_payment_amount = filing_data.get("total_payment_amount")
        total_cash_reported = filing_data.get("total_cash_reported")
        log_debug(
            "Raw Total Dollar Amount Remitted candidates: "
            f"total_dollar_amount_remitted={total_dollar_amount_remitted!r}, "
            f"total_remitted={total_remitted!r}, "
            f"total_payment_amount={total_payment_amount!r}, "
            f"total_cash_reported={total_cash_reported!r}"
        )

        amount = (
            total_dollar_amount_remitted
            or total_remitted
            or total_payment_amount
            or total_cash_reported
            or ""
        )
        amount_normalized = normalize_number(amount, default="")
        log_debug(f"Filling Total Dollar Amount Remitted: {amount_normalized!r}")
        safe_fill_by_label(
            page,
            "Total Dollar Amount Remitted",
            amount_normalized,
            optional=False,
        )

        log_debug("Selecting Funds Remitted Via")
        safe_select_by_label(
            page,
            "Funds Remitted Via",
            normalize_va_funds(filing_data.get("funds_remitted_via")),
            optional=False,
        )

    click_next(page, "after VA holder info")

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

    log_step("Reached Virginia upload step.")
    return {"status": "reached_upload_step"}
