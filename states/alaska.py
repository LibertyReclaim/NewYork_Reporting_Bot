from __future__ import annotations

from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://unclaimedproperty.alaska.gov/app/holder-info"


def log_debug(message: str) -> None:
    print(f"[AK][DEBUG] {message}")


def log_step(message: str) -> None:
    print(f"[AK][STEP] {message}")


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


def safe_select_by_label(page: Page, label: str, value: str, optional: bool = False) -> bool:
    found = get_field_locator(page, label, kind="select")
    if not found:
        if optional:
            return False
        raise RuntimeError(f"[AK] Dropdown not found: {label}")

    _, locator = found
    if is_disabled_or_readonly(locator):
        return False

    try:
        locator.select_option(label=value, timeout=10_000)
        return True
    except Exception:
        pass

    try:
        locator.select_option(value=value, timeout=10_000)
        return True
    except Exception:
        pass

    locator.click(timeout=10_000)
    option_text = page.get_by_text(value, exact=True)
    if option_text.count() > 0 and option_text.first.is_visible():
        option_text.first.click(timeout=10_000)
        return True

    options = locator.locator("option")
    for i in range(options.count()):
        opt = options.nth(i)
        label_text = (opt.inner_text() or "").strip()
        value_text = (opt.get_attribute("value") or "").strip()
        if label_text == value:
            locator.select_option(value=value_text or label_text, timeout=10_000)
            return True

    return False


def safe_fill_by_label(page: Page, label: str, value: str, optional: bool = False) -> None:
    found = get_field_locator(page, label, kind="input")
    if not found:
        if optional:
            return
        raise RuntimeError(f"[AK] Field not found: {label}")

    _, locator = found
    if is_disabled_or_readonly(locator):
        return

    text = str(value).strip()
    if optional and not text:
        return

    log_debug(f"Filling {label}: {text!r}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.fill(text, timeout=10_000)


def select_funds_remitted_via_ach(page: Page) -> None:
    log_debug("Selecting Funds Remitted Via: 'ACH / Electronic'")

    # 1) Primary path: exact label
    if safe_select_by_label(page, "Funds Remitted Via", "ACH / Electronic", optional=True):
        return

    # 2) Fail-safe partial label
    if safe_select_by_label(page, "Funds Remitted", "ACH / Electronic", optional=True):
        return

    # 3) Fail-safe combobox fallback
    combobox = page.get_by_role("combobox")
    if combobox.count() > 0:
        cb = combobox.first
        cb.scroll_into_view_if_needed(timeout=10_000)
        try:
            cb.select_option(label="ACH / Electronic", timeout=10_000)
            return
        except Exception:
            pass

        cb.click(timeout=10_000)
        option_text = page.get_by_text("ACH / Electronic", exact=True)
        if option_text.count() > 0 and option_text.first.is_visible():
            option_text.first.click(timeout=10_000)
            return

    raise RuntimeError("[AK] Could not set Funds Remitted Via to 'ACH / Electronic'")


def click_next(page: Page) -> None:
    log_step("Clicking NEXT")
    try:
        page.get_by_role("button", name="NEXT", exact=False).first.click(timeout=15_000)
    except Exception:
        page.locator("button:has-text('NEXT')").first.click(timeout=15_000)


def run_alaska(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)

    safe_fill_by_label(page, "Holder Name", str(company_data.get("company_name", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip(), optional=True)
    safe_fill_by_label(page, "Contact Name", str(company_data.get("contact_name", "")).strip(), optional=True)
    safe_fill_by_label(page, "Contact Phone Number", str(company_data.get("contact_phone", "")).strip(), optional=True)
    safe_fill_by_label(page, "Email Address", str(company_data.get("email", "")).strip(), optional=True)
    safe_fill_by_label(page, "Email Address Confirmation", str(company_data.get("email", "")).strip(), optional=True)
    safe_fill_by_label(
        page,
        "Total Dollar Amount Remitted",
        str(filing_data.get("total_dollar_amount_remitted", "")).strip(),
        optional=True,
    )

    select_funds_remitted_via_ach(page)
    click_next(page)
    return {"status": "reached_upload_step"}
