from __future__ import annotations

from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://unclaimedproperty.colorado.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[CO][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[CO][DEBUG] {message}")


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
        raise RuntimeError(f"[CO] {msg}")

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
        raise RuntimeError(f"[CO] {msg}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' is disabled/read-only; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[CO] Dropdown '{label}' value is blank")

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


def click_text_contains(container: Locator, text_contains: str, optional: bool = False) -> bool:
    option = container.get_by_text(text_contains, exact=False)
    if option.count() > 0 and option.first.is_visible():
        option.first.scroll_into_view_if_needed(timeout=10_000)
        option.first.click(timeout=10_000)
        return True

    if optional:
        log_debug(f"Text not found (optional): {text_contains}")
        return False
    raise RuntimeError(f"[CO] Could not find text containing: {text_contains}")


def safe_check_radio_by_question(page: Page, question_text: str, option_contains: str, optional: bool = False) -> None:
    question = page.get_by_text(question_text, exact=False)
    if question.count() == 0:
        if optional:
            log_debug(f"Radio question not found (optional): {question_text}")
            return
        raise RuntimeError(f"[CO] Radio question not found: {question_text}")

    q = question.first
    rel = q.locator(f"xpath=following::label[contains(normalize-space(.), '{option_contains}')][1]")
    if rel.count() > 0 and rel.first.is_visible():
        rel.first.scroll_into_view_if_needed(timeout=10_000)
        rel.first.click(timeout=10_000)
        log_debug(f"Radio for '{question_text}' set using contains '{option_contains}'")
        return

    container = q.locator("xpath=ancestor::*[self::div or self::form][1]")
    if click_text_contains(container, option_contains, optional=True):
        log_debug(f"Radio for '{question_text}' set using contains '{option_contains}'")
        return

    if optional:
        log_debug(f"Could not set radio (optional): {question_text}")
        return
    raise RuntimeError(f"[CO] Could not set radio for question: {question_text}")


def safe_check_checkbox_contains(page: Page, text_contains: str, optional: bool = False) -> None:
    checkbox_label = page.get_by_text(text_contains, exact=False)
    if checkbox_label.count() == 0:
        if optional:
            log_debug(f"Checkbox label not found (optional): {text_contains}")
            return
        raise RuntimeError(f"[CO] Checkbox label not found: {text_contains}")

    label = checkbox_label.first
    label.scroll_into_view_if_needed(timeout=10_000)
    label.click(timeout=10_000)
    log_debug(f"Checked checkbox containing text: {text_contains}")


def click_next(page: Page) -> None:
    log_step("Clicking NEXT")
    try:
        page.get_by_role("button", name="NEXT", exact=False).first.click(timeout=15_000)
    except Exception:
        page.locator("button:has-text('NEXT')").first.click(timeout=15_000)


def run_colorado(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Holder and contact fields
    safe_fill_by_label(page, "Holder Name", str(company_data.get("company_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder Contact", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone No", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Email", str(company_data.get("email", "")).strip())
    safe_fill_by_label(page, "Email Confirmation", str(company_data.get("email", "")).strip())

    # Dropdowns
    safe_select_by_label(page, "State", "Colorado")
    safe_select_by_label(page, "Report Type", "Annual Report")

    # Certification radios
    safe_check_radio_by_question(
        page,
        "CRS 38-13-501 Notice Requirements",
        "I verify that, to the best of my knowledge, notice requirements have been met",
    )
    safe_check_radio_by_question(
        page,
        "CRS 38-13-402 Content of Report Requirements",
        "I verify that, to the best of my knowledge, that the content of this report",
    )

    # Other fields
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)
    safe_check_radio_by_question(page, "Negative Report", "Yes" if normalize_bool(filing_data.get("negative_report")) else "No", optional=True)

    amount = normalize_number(filing_data.get("total_dollar_amount_remitted"), default="")
    safe_fill_by_label(page, "Reported Amount", amount, optional=True)
    safe_fill_by_label(page, "Amount To Be Remitted", amount, optional=True)

    # Final certification checkbox
    safe_check_checkbox_contains(page, "By submitting this report, I verify that a payment amount")

    click_next(page)
    return {"status": "reached_upload_step"}
