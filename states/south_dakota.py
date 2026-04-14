from __future__ import annotations

from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://southdakota.findyourunclaimedproperty.com/app/holder-info"


def log_step(message: str) -> None:
    print(f"[SD][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[SD][DEBUG] {message}")


def normalize_number(value, default: str = "") -> str:
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
    disabled = locator.get_attribute("disabled") is not None or (locator.get_attribute("aria-disabled") or "").lower() == "true"
    readonly = locator.get_attribute("readonly") is not None or (locator.get_attribute("aria-readonly") or "").lower() == "true"
    return disabled or readonly


def safe_fill_by_label(page: Page, label: str, value: str, optional: bool = False) -> None:
    found = get_field_locator(page, label, kind="input")
    if not found:
        if optional:
            log_debug(f"Field not found (optional): {label}")
            return
        raise RuntimeError(f"[SD] Field not found: {label}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Field '{label}' is disabled/read-only; skipping")
        return

    text = str(value).strip()
    if optional and not text:
        log_debug(f"{label} is blank (optional); skipping")
        return

    log_debug(f"Filling {label}: {text!r} via {strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.fill(text, timeout=10_000)


def safe_select_by_label(page: Page, label: str, value: str, optional: bool = False) -> bool:
    found = get_field_locator(page, label, kind="select")
    if not found:
        if optional:
            log_debug(f"Dropdown not found (optional): {label}")
            return False
        raise RuntimeError(f"[SD] Dropdown not found: {label}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' is disabled/read-only; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[SD] Dropdown '{label}' value is blank")

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

    locator.click(timeout=10_000)
    option_text = page.get_by_text(value_str, exact=True)
    if option_text.count() > 0 and option_text.first.is_visible():
        option_text.first.click(timeout=10_000)
        return True

    options = locator.locator("option")
    for i in range(options.count()):
        opt = options.nth(i)
        opt_label = (opt.inner_text() or "").strip()
        opt_value = (opt.get_attribute("value") or "").strip()
        if opt_label == value_str:
            locator.select_option(value=opt_value or opt_label, timeout=10_000)
            return True

    log_debug(f"Dropdown '{label}' did not match option for value={value_str!r}; skipping")
    return False


def safe_check_radio(page: Page, group_label: str, yes_value: bool, optional: bool = False) -> None:
    target = "Yes" if yes_value else "No"
    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        if optional:
            log_debug(f"Radio group not found (optional): {group_label}")
            return
        raise RuntimeError(f"[SD] Radio group not found: {group_label}")

    q = question.first
    rel = q.locator(f"xpath=following::label[normalize-space(.)='{target}'][1]")
    if rel.count() > 0 and rel.first.is_visible():
        rel.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target}")
        return

    container = q.locator("xpath=ancestor::*[self::div or self::form][1]").get_by_text(target, exact=True)
    if container.count() > 0 and container.first.is_visible():
        container.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target}")
        return

    if optional:
        log_debug(f"Could not set radio '{group_label}' to {target} (optional)")
        return
    raise RuntimeError(f"[SD] Could not set radio '{group_label}' to {target}")


def safe_select_date_triplet(page: Page, label: str, month: str, day: str, year: str, optional: bool = False) -> None:
    anchor = page.get_by_text(label, exact=False)
    if anchor.count() == 0:
        if optional:
            log_debug(f"Date label not found (optional): {label}")
            return
        raise RuntimeError(f"[SD] Date label not found: {label}")

    base = anchor.first
    month_select = base.locator("xpath=following::select[1]")
    day_select = base.locator("xpath=following::select[2]")
    year_select = base.locator("xpath=following::select[3]")
    if month_select.count() == 0 or day_select.count() == 0 or year_select.count() == 0:
        if optional:
            log_debug(f"Date dropdowns not found (optional): {label}")
            return
        raise RuntimeError(f"[SD] Date dropdowns not found for: {label}")

    log_debug(f"Filling {label}: {month}/{day}/{year}")
    for part_label, select_locator, value in [
        ("month", month_select, month),
        ("day", day_select, day),
        ("year", year_select, year),
    ]:
        try:
            select_locator.first.select_option(value=str(value), timeout=10_000)
            continue
        except Exception:
            pass
        try:
            select_locator.first.select_option(label=str(value), timeout=10_000)
            continue
        except Exception:
            pass

        options = select_locator.first.locator("option")
        selected = False
        for i in range(options.count()):
            opt = options.nth(i)
            opt_label = (opt.inner_text() or "").strip()
            opt_value = (opt.get_attribute("value") or "").strip()
            if opt_label == str(value) or opt_value == str(value):
                select_locator.first.select_option(value=opt_value or opt_label, timeout=10_000)
                selected = True
                break
        if not selected and not optional:
            raise RuntimeError(f"[SD] Could not select {label} {part_label}={value}")


def click_next(page: Page) -> None:
    log_step("Clicking NEXT")
    try:
        page.get_by_role("button", name="NEXT", exact=False).first.click(timeout=15_000)
    except Exception:
        page.locator("button:has-text('NEXT')").first.click(timeout=15_000)


def run_south_dakota(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Primary Holder Info
    safe_fill_by_label(page, "Holder Name", str(company_data.get("company_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder Contact", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone No.", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Email", str(company_data.get("email", "")).strip())
    safe_fill_by_label(page, "Email Confirmation", str(company_data.get("email_confirmation", "")).strip(), optional=True)
    safe_fill_by_label(page, "Address 1", str(company_data.get("address_1", "")).strip())
    safe_fill_by_label(page, "City", str(company_data.get("city", "")).strip())
    safe_fill_by_label(page, "Postal Code", str(company_data.get("zip", "")).strip(), optional=True)
    safe_select_by_label(page, "State", str(company_data.get("state", "")).strip(), optional=True)

    safe_select_date_triplet(page, "Date of Incorporation", "1", "1", "2025", optional=True)
    safe_select_date_triplet(page, "Date of Dissolution", "1", "1", "2025", optional=True)
    safe_fill_by_label(page, "Primary Business Activity", "Finance", optional=True)
    safe_check_radio(page, "First time filing", True, optional=True)
    safe_select_by_label(page, "Payment Method", "Wire", optional=False)

    # Report info
    safe_select_by_label(page, "Report Type", "Annual Report")
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)
    safe_check_radio(page, "This is a Negative Report", False, optional=True)
    safe_fill_by_label(page, "Total Amount of Cash Reported", normalize_number(filing_data.get("total_dollar_amount_remitted"), default=""), optional=True)
    safe_fill_by_label(page, "Total Number of Shares Reported", "0", optional=True)
    safe_fill_by_label(page, "Total Number of Safe Deposit Boxes Reported", "0", optional=True)

    click_next(page)
    print("SD reached_upload_step")
    return {"status": "reached_upload_step"}
