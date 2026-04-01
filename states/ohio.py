from __future__ import annotations

import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://unclaimedfunds.ohio.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[OH][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[OH][DEBUG] {message}")


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
        raise RuntimeError(f"[OH] {msg}")

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
        raise RuntimeError(f"[OH] {msg}")

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
        raise RuntimeError(f"[OH] Dropdown '{label}' value is blank")

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


def safe_select_date_triplet(page: Page, label: str, mm: str, dd: str, yyyy: str, optional: bool = False) -> None:
    values = [str(mm).strip(), str(dd).strip(), str(yyyy).strip()]
    if optional and not any(values):
        log_debug(f"Skipping {label} because all date parts are blank")
        return

    anchor = page.get_by_text(label, exact=False)
    if anchor.count() == 0:
        msg = f"Date field label not found: {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[OH] {msg}")

    base = anchor.first
    mm_sel = base.locator("xpath=following::select[1]")
    dd_sel = base.locator("xpath=following::select[2]")
    yy_sel = base.locator("xpath=following::select[3]")

    if mm_sel.count() == 0 or dd_sel.count() == 0 or yy_sel.count() == 0:
        msg = f"Date dropdown triplet not found for {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[OH] {msg}")

    def select_part(sel: Locator, val: str, part_name: str) -> None:
        if not val:
            if optional:
                return
            raise RuntimeError(f"[OH] Missing required {part_name} for {label}")
        sel.first.scroll_into_view_if_needed(timeout=10_000)
        try:
            sel.first.select_option(label=val, timeout=10_000)
            return
        except Exception:
            pass
        try:
            sel.first.select_option(value=val, timeout=10_000)
            return
        except Exception:
            pass
        if val.isdigit():
            alt = str(int(val))
            try:
                sel.first.select_option(label=alt, timeout=10_000)
                return
            except Exception:
                pass
            try:
                sel.first.select_option(value=alt, timeout=10_000)
                return
            except Exception:
                pass
        raise RuntimeError(f"[OH] Could not set {label} {part_name}={val}")

    log_debug(f"Selecting {label}: MM={values[0]!r}, DD={values[1]!r}, YYYY={values[2]!r}")
    select_part(mm_sel, values[0], "MM")
    select_part(dd_sel, values[1], "DD")
    select_part(yy_sel, values[2], "YYYY")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role partial", page.get_by_role("button", name="NEXT", exact=False)),
        ("role next", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('NEXT'), button:has-text('Next')")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[OH] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def run_ohio(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # PRIMARY HOLDER INFO
    safe_fill_by_label(page, "Holder Name", str(company_data.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "Holder ID", str(company_data.get("holder_id", "")).strip(), optional=True)

    safe_fill_by_label(page, "Address 1", str(company_data.get("address_1", "")).strip())
    safe_fill_by_label(page, "Address 2", str(company_data.get("address_2", "")).strip(), optional=True)
    safe_fill_by_label(page, "City", str(company_data.get("city", "")).strip())
    safe_select_by_label(page, "State", str(company_data.get("state", "")).strip(), optional=True)
    safe_fill_by_label(page, "Postal Code", str(company_data.get("zip_code", "")).strip())

    safe_fill_by_label(page, "Contact Name", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)

    email = str(company_data.get("email", "")).strip()
    safe_fill_by_label(page, "Email Address", email)
    safe_fill_by_label(page, "Email Confirmation", email)

    safe_select_by_label(page, "State of Incorporation", str(company_data.get("state_of_incorporation", "")).strip(), optional=True)
    safe_select_date_triplet(
        page,
        "Date of Incorporation",
        str(company_data.get("incorporation_month", "")).strip(),
        str(company_data.get("incorporation_day", "")).strip(),
        str(company_data.get("incorporation_year", "")).strip(),
        optional=True,
    )

    # REPORT INFORMATION
    safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)
    safe_select_by_label(page, "Report Type", str(filing_data.get("report_type", "")).strip(), optional=True)

    safe_fill_by_label(
        page,
        "Total Dollar Amount Remitted",
        normalize_number(filing_data.get("total_dollar_amount_remitted"), default=""),
        optional=True,
    )
    safe_select_by_label(page, "Funds Remitted Via", str(filing_data.get("funds_remitted_via", "")).strip(), optional=True)

    click_next(page, "after OH holder info")

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

    log_step("Reached Ohio upload step.")
    return {"status": "reached_upload_step"}
