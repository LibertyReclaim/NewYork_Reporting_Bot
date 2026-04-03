from __future__ import annotations

from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://unclaimed.oregon.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[OR][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[OR][DEBUG] {message}")


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
        msg = f"Field not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[OR] {msg}")

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
        msg = f"Dropdown not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return False
        raise RuntimeError(f"[OR] {msg}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' is disabled/read-only; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[OR] Dropdown '{label}' value is blank")

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
        label_text = (opt.inner_text() or "").strip()
        value_text = (opt.get_attribute("value") or "").strip()
        if label_text == value_str:
            locator.select_option(value=value_text or label_text, timeout=10_000)
            return True

    log_debug(f"Dropdown '{label}' did not match option for value={value_str!r}; skipping")
    return False


def safe_check_radio(page: Page, group_label: str, yes_value: bool, optional: bool = False) -> None:
    target = "Yes" if yes_value else "No"
    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        msg = f"Radio group not found: {group_label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[OR] {msg}")

    q = question.first
    rel = q.locator(f"xpath=following::label[normalize-space(.)='{target}'][1]")
    if rel.count() > 0 and rel.first.is_visible():
        rel.first.scroll_into_view_if_needed(timeout=10_000)
        rel.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target}")
        return

    container = q.locator("xpath=ancestor::*[self::div or self::form][1]").get_by_text(target, exact=True)
    if container.count() > 0 and container.first.is_visible():
        container.first.scroll_into_view_if_needed(timeout=10_000)
        container.first.click(timeout=10_000)
        log_debug(f"Radio '{group_label}' set to {target}")
        return

    if optional:
        log_debug(f"Could not set radio '{group_label}' to {target} (optional; skipping)")
        return
    raise RuntimeError(f"[OR] Could not set radio '{group_label}' to {target}")


def fill_email_address_confirmation(page: Page, email_value: str) -> None:
    email_text = str(email_value).strip()
    if not email_text:
        raise RuntimeError("[OR] Email value is blank for confirmation field")

    labels_to_try = ["Email Address Confirmation", "Confirmation"]
    for label in labels_to_try:
        found = get_field_locator(page, label, kind="input")
        if not found:
            continue

        strategy, locator = found
        if is_disabled_or_readonly(locator):
            log_debug(f"Field '{label}' is disabled/read-only; skipping")
            return

        log_debug(f"Filling Email Address Confirmation: {email_text!r} via {strategy}")
        locator.scroll_into_view_if_needed(timeout=10_000)
        locator.fill(email_text, timeout=10_000)
        return

    raise RuntimeError("[OR] Field not found: Email Address Confirmation")


def click_next(page: Page) -> None:
    log_step("Clicking NEXT")
    try:
        page.get_by_role("button", name="NEXT", exact=False).first.click(timeout=15_000)
    except Exception:
        page.locator("button:has-text('NEXT')").first.click(timeout=15_000)


def run_oregon(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Primary Holder Info
    safe_fill_by_label(page, "Holder Name", str(company_data.get("company_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder ID", str(company_data.get("holder_id", "")).strip(), optional=True)
    safe_select_by_label(page, "Incorporated States", "Oregon")
    safe_select_by_label(page, "Month", "1", optional=True)
    safe_select_by_label(page, "Day", "1", optional=True)
    safe_select_by_label(page, "Year", "2025", optional=True)
    safe_fill_by_label(page, "NAICS Code Charter", "999999")

    # Address
    safe_fill_by_label(page, "Holder Address 1", str(company_data.get("address_1", "")).strip())
    safe_fill_by_label(page, "Holder Address 2", str(company_data.get("address_2", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder Address 3", str(company_data.get("address_3", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder City", str(company_data.get("city", "")).strip())
    safe_select_by_label(page, "Holder State", "Oregon")
    safe_fill_by_label(page, "Holder Zip", str(company_data.get("zip", "")).strip())

    # Contact
    safe_fill_by_label(page, "Contact Name", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)
    safe_fill_by_label(page, "Email", str(company_data.get("email", "")).strip())
    fill_email_address_confirmation(page, str(company_data.get("email", "")).strip())

    # Report Info
    safe_select_by_label(page, "Report Type", "Annual Report")
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)
    safe_check_radio(page, "This is a Negative Report", normalize_bool(filing_data.get("negative_report")), optional=True)
    safe_fill_by_label(
        page,
        "Total Dollar Amount Remitted",
        normalize_number(filing_data.get("total_dollar_amount_remitted"), default=""),
        optional=True,
    )

    click_next(page)
    return {"status": "reached_upload_step"}
