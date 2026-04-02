from __future__ import annotations

import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://icash.illinoistreasurer.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[IL][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[IL][DEBUG] {message}")


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


def safe_fill_by_label(page: Page, label: str, value: str, optional: bool = False) -> None:
    found = get_field_locator(page, label, kind="input")
    if not found:
        msg = f"Field not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[IL] {msg}")

    strategy, locator = found
    disabled_attr = locator.get_attribute("disabled")
    aria_disabled = (locator.get_attribute("aria-disabled") or "").lower()
    if disabled_attr is not None or aria_disabled == "true":
        log_debug(f"Field '{label}' is disabled; skipping")
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
        raise RuntimeError(f"[IL] {msg}")

    strategy, locator = found
    disabled_attr = locator.get_attribute("disabled")
    aria_disabled = (locator.get_attribute("aria-disabled") or "").lower()
    if disabled_attr is not None or aria_disabled == "true":
        log_debug(f"Dropdown '{label}' is disabled; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[IL] Dropdown '{label}' value is blank")

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
        raise RuntimeError(f"[IL] {msg}")

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
    raise RuntimeError(f"[IL] {msg}")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role partial", page.get_by_role("button", name="NEXT", exact=False)),
        ("role next", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('NEXT'), button:has-text('Next')")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[IL] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run_illinois(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # PRIMARY HOLDER INFO
    safe_fill_by_label(page, "Holder Name", str(company_data.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder ID", str(company_data.get("holder_id", "")).strip(), optional=True)

    safe_fill_by_label(page, "Holder Address 1", str(company_data.get("address_1", "")).strip())
    safe_fill_by_label(page, "Holder Address 2", str(company_data.get("address_2", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder Address 3", str(company_data.get("address_3", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder City", str(company_data.get("city", "")).strip())
    safe_select_by_label(page, "Holder State", str(company_data.get("state", "")).strip(), optional=True)
    safe_fill_by_label(page, "Holder Zip", str(company_data.get("zip_code", "")).strip())

    safe_fill_by_label(page, "Holder Contact", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone No.", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)

    email = str(company_data.get("email", "")).strip()
    email_confirmation = str(company_data.get("email_confirmation", "")).strip() or email
    safe_fill_by_label(page, "Email", email)
    safe_fill_by_label(page, "Email Confirmation", email_confirmation)

    # REPORT INFO
    safe_select_by_label(page, "Report Type", str(filing_data.get("report_type", "")).strip(), optional=True)
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)

    negative_report = normalize_bool(filing_data.get("negative_report"))
    safe_check_radio(page, "This is a Negative Report", negative_report, optional=True)

    if negative_report:
        log_debug("Skipping Reported Amount and Amount To Be Remitted because Negative Report is Yes")
    else:
        safe_fill_by_label(
            page,
            "Reported Amount",
            normalize_number(filing_data.get("reported_amount"), default=""),
            optional=True,
        )
        safe_fill_by_label(
            page,
            "Amount To Be Remitted",
            normalize_number(filing_data.get("amount_to_be_remitted"), default=""),
            optional=True,
        )

    # STATISTICS
    safe_fill_by_label(
        page,
        "Number of Employees",
        normalize_number(filing_data.get("number_of_employees"), default=""),
        optional=True,
    )
    safe_fill_by_label(
        page,
        "Annual Sales/Premiums",
        normalize_number(filing_data.get("annual_sales_premiums"), default=""),
        optional=True,
    )
    safe_fill_by_label(
        page,
        "Total Assets",
        normalize_number(filing_data.get("total_assets"), default=""),
        optional=True,
    )

    click_next(page, "after IL holder info")

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

    log_step("Reached Illinois upload step.")
    return {"status": "reached_upload_step"}
