from __future__ import annotations

import re
import time
from typing import Optional, Tuple

from playwright.sync_api import Locator, Page

TARGET_URL = "https://indianaunclaimed.gov/app/holder-info"


def log_step(message: str) -> None:
    print(f"[IN][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[IN][DEBUG] {message}")


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


def normalize_zip(value) -> str:
    raw = str(value or "").strip()
    digits = "".join(re.findall(r"\d", raw))
    if len(digits) >= 5:
        return digits[:5]
    return raw[:5]


def normalize_in_funds_remitted_via(value) -> str:
    raw = str(value or "").strip()
    normalized = raw.upper()
    if normalized == "WIRE":
        return "Wire"
    if normalized == "CHECK":
        return "Check"
    if normalized == "ACH":
        return "ACH"
    if normalized in {"ONLINE", "ELECTRONIC"}:
        return "Online"
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
        raise RuntimeError(f"[IN] {msg}")

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
        raise RuntimeError(f"[IN] {msg}")

    strategy, locator = found
    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' is disabled/read-only; skipping")
        return False

    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[IN] Dropdown '{label}' value is blank")

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




def safe_select_by_label_within_section(
    page: Page,
    section_heading: str,
    label: str,
    value: str,
    optional: bool = False,
) -> bool:
    value_str = str(value).strip()
    if not value_str:
        if optional:
            log_debug(f"Section '{section_heading}' dropdown '{label}' value is blank (optional); skipping")
            return False
        raise RuntimeError(f"[IN] Section '{section_heading}' dropdown '{label}' value is blank")

    section_heading_match = page.get_by_text(section_heading, exact=False)
    if section_heading_match.count() == 0:
        msg = f"Section not found: {section_heading}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return False
        raise RuntimeError(f"[IN] {msg}")

    section_anchor = section_heading_match.first
    section_container = section_anchor.locator("xpath=ancestor::*[self::section or self::fieldset or self::div][1]")

    candidates = [
        (
            f"section label exact: {section_heading} -> {label}",
            section_container.get_by_label(label, exact=True),
        ),
        (
            f"section label partial: {section_heading} -> {label}",
            section_container.get_by_label(label, exact=False),
        ),
        (
            f"section nearby select: {section_heading} -> {label}",
            section_container.locator(
                f"xpath=.//*[contains(normalize-space(.), '{label}')][1]/following::*[self::select][1]"
            ),
        ),
    ]

    strategy, locator = first_visible_locator(candidates)
    if not locator:
        msg = f"Dropdown not found in section '{section_heading}': {label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return False
        raise RuntimeError(f"[IN] {msg}")

    if is_disabled_or_readonly(locator):
        log_debug(f"Dropdown '{label}' in section '{section_heading}' is disabled/read-only; skipping")
        return False

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

    log_debug(
        f"Dropdown '{label}' in section '{section_heading}' did not match option for value={value_str!r}; leaving for manual review"
    )
    return False


def safe_check_radio(page: Page, group_label: str, yes_value: bool, optional: bool = False) -> None:
    target_text = "Yes" if yes_value else "No"
    question = page.get_by_text(group_label, exact=False)
    if question.count() == 0:
        msg = f"Radio group not found: {group_label}"
        if optional:
            log_debug(msg + " (optional; skipping)")
            return
        raise RuntimeError(f"[IN] {msg}")

    q = question.first
    container = q.locator("xpath=ancestor::*[self::div or self::form][1]")

    scoped_label = container.get_by_text(target_text, exact=True)
    if scoped_label.count() > 0 and scoped_label.first.is_visible():
        try:
            scoped_label.first.scroll_into_view_if_needed(timeout=10_000)
            scoped_label.first.click(timeout=10_000)
            log_debug(f"Radio '{group_label}' set to {target_text} via container label")
            return
        except Exception:
            pass

    rel_label = q.locator(f"xpath=following::label[normalize-space(.)='{target_text}'][1]")
    if rel_label.count() > 0 and rel_label.first.is_visible():
        try:
            rel_label.first.scroll_into_view_if_needed(timeout=10_000)
            rel_label.first.click(timeout=10_000)
            log_debug(f"Radio '{group_label}' set to {target_text} via following label")
            return
        except Exception:
            pass

    msg = f"Could not set radio '{group_label}' to {target_text}"
    if optional:
        log_debug(msg + " (optional; skipping)")
        return
    raise RuntimeError(f"[IN] {msg}")


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking NEXT ({step_name})")
    candidates = [
        ("role partial", page.get_by_role("button", name="NEXT", exact=False)),
        ("role next", page.get_by_role("button", name="Next", exact=False)),
        ("button text", page.locator("button:has-text('NEXT'), button:has-text('Next')")),
    ]
    strategy, locator = first_visible_locator(candidates, timeout_ms=8_000)
    if not locator:
        raise RuntimeError("[IN] Could not find NEXT button")
    log_debug(f"NEXT strategy={strategy}")
    locator.scroll_into_view_if_needed(timeout=10_000)
    locator.click(timeout=15_000)


def select_holder_info_state(page: Page, state_value: str) -> bool:
    target = str(state_value).strip()
    log_debug(f"Selecting Holder Info State directly: {target!r}")
    if not target:
        log_debug("Holder Info State value is blank; skipping")
        return False

    state_labels = page.locator("label", has_text="State")
    total_state_labels = state_labels.count()
    all_selects = page.locator("select")
    total_selects = all_selects.count()
    log_debug(f"Total State labels found: {total_state_labels}")
    log_debug(f"Total select elements found: {total_selects}")

    report_info_heading = page.get_by_text("Report Info", exact=False)
    if report_info_heading.count() == 0:
        raise RuntimeError("[IN] Could not find Report Info heading for Holder Info State scoping")

    holder_state_label = report_info_heading.first.locator(
        "xpath=preceding::label[contains(normalize-space(.), 'State')][1]"
    )
    if holder_state_label.count() == 0:
        raise RuntimeError("[IN] Could not find Holder Info State label before Report Info section")

    holder_state_label = holder_state_label.first
    holder_state_select = holder_state_label.locator("xpath=following::select[1]")
    if holder_state_select.count() == 0:
        raise RuntimeError("[IN] Could not find Holder Info State select from scoped label")

    holder_state_select = holder_state_select.first
    if is_disabled_or_readonly(holder_state_select):
        log_debug("Holder Info State dropdown is disabled/read-only; skipping")
        return False

    select_index = int(
        holder_state_select.evaluate(
            "el => document.evaluate('count(preceding::select)', el, null, XPathResult.NUMBER_TYPE, null).numberValue"
        )
    )
    log_debug(f"Using Holder Info state select index: {select_index}")

    holder_state_select.scroll_into_view_if_needed(timeout=10_000)

    try:
        holder_state_select.select_option(label=target, timeout=10_000)
        log_debug(f"Holder Info State selected by visible text: {target!r}")
        return True
    except Exception:
        pass

    options = holder_state_select.locator("option")
    option_map: dict[str, str] = {}
    ordered_labels: list[str] = []
    for i in range(options.count()):
        opt = options.nth(i)
        opt_label = (opt.inner_text() or "").strip()
        opt_value = (opt.get_attribute("value") or "").strip()
        if opt_label:
            ordered_labels.append(opt_label)
            option_map[opt_label.lower()] = opt_value

    log_debug(f"Holder Info State direct options: {ordered_labels}")

    fallback_value = option_map.get(target.lower(), "")
    if fallback_value:
        try:
            holder_state_select.select_option(value=fallback_value, timeout=10_000)
            log_debug(f"Holder Info State selected by value fallback: {target!r} -> {fallback_value!r}")
            return True
        except Exception:
            pass

    return False


def run_indiana(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # PRIMARY HOLDER INFO
    safe_fill_by_label(page, "Holder Name", str(company_data.get("holder_name", "")).strip())
    safe_fill_by_label(page, "Holder FEIN", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill_by_label(page, "State Tax ID", str(company_data.get("state_tax_id", "")).strip(), optional=True)
    log_debug("Holder ID should remain blank for Indiana; skipping")

    safe_fill_by_label(page, "Contact Name", str(company_data.get("contact_name", "")).strip())
    safe_fill_by_label(page, "Contact Phone Number", str(company_data.get("contact_phone", "")).strip())
    safe_fill_by_label(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)

    email = str(company_data.get("email", "")).strip()
    email_confirmation = str(company_data.get("email_confirmation", "")).strip() or email
    safe_fill_by_label(page, "Email Address", email)
    safe_fill_by_label(page, "Email Address Confirmation", email_confirmation)

    safe_fill_by_label(page, "Address 1", str(company_data.get("address_1", "")).strip())
    safe_fill_by_label(page, "Address 2", str(company_data.get("address_2", "")).strip(), optional=True)
    safe_fill_by_label(page, "Address 3", str(company_data.get("address_3", "")).strip(), optional=True)
    safe_fill_by_label(page, "City", str(company_data.get("city", "")).strip())
    holder_state_value = str(company_data.get("state", "")).strip()
    holder_state_selected = select_holder_info_state(page, holder_state_value)
    if not holder_state_selected:
        log_debug("Holder Info State selection failed; leaving for manual review")

    postal_raw = company_data.get("zip") or company_data.get("zip_code") or ""
    postal_code = normalize_zip(postal_raw)
    log_debug(f"Filling Postal Code (cleaned): {postal_code!r}")
    safe_fill_by_label(page, "Postal Code", postal_code)

    # REPORT INFO
    safe_select_by_label(page, "Report Type", str(filing_data.get("report_type", "")).strip(), optional=True)

    report_year_selected = safe_select_by_label(page, "Report Year", str(filing_data.get("report_year", "")).strip(), optional=True)
    if not report_year_selected:
        log_debug("Report Year dropdown is disabled or unavailable; skipping")

    report_state_value = str(company_data.get("state", "")).strip()
    log_debug(f"Selecting Report Info State: {report_state_value!r}")
    safe_select_by_label_within_section(page, "Report Info", "State", report_state_value, optional=False)

    negative_report = normalize_bool(filing_data.get("negative_report"))
    safe_check_radio(page, "This is a Negative (Zero) Report", negative_report, optional=True)

    safe_check_radio(
        page,
        "Does this report include records that are subject to the HIPAA Privacy Rule",
        normalize_bool(filing_data.get("includes_hipaa_records")),
        optional=True,
    )

    if negative_report:
        log_debug("Negative (Zero) Report is Yes; skipping disabled totals/remittance fields")
    else:
        safe_fill_by_label(page, "Report ID", str(filing_data.get("report_id", "")).strip(), optional=True)
        safe_fill_by_label(
            page,
            "Total Amount of Cash Reported",
            normalize_number(filing_data.get("total_cash_reported"), default=""),
            optional=True,
        )
        safe_fill_by_label(
            page,
            "Total Number of Shares Reported",
            normalize_number(filing_data.get("total_shares_reported"), default=""),
            optional=True,
        )
        safe_fill_by_label(
            page,
            "Total Number of Properties Reported",
            normalize_number(filing_data.get("total_number_of_items_reported"), default=""),
            optional=True,
        )

        sdb_reported = str(filing_data.get("safe_deposit_boxes_reported", "")).strip()
        if not sdb_reported:
            if normalize_bool(filing_data.get("includes_safe_deposit_box")):
                sdb_reported = (
                    normalize_number(filing_data.get("total_number_of_safekeeping_items"), default="").strip() or "1"
                )
            else:
                sdb_reported = "0"
        safe_fill_by_label(page, "Total Number of Safe Deposit Boxes Reported", sdb_reported, optional=True)

        safe_fill_by_label(
            page,
            "Total Dollar Amount Remitted",
            normalize_number(filing_data.get("total_dollar_amount_remitted"), default=""),
            optional=True,
        )

        raw_funds = str(filing_data.get("funds_remitted_via", "")).strip()
        normalized_funds = normalize_in_funds_remitted_via(raw_funds)
        log_debug(f"Raw Funds Remitted Via: {raw_funds!r}")
        log_debug(f"Normalized Indiana Funds Remitted Via: {normalized_funds!r}")

        funds_selected = safe_select_by_label(page, "Funds Remitted Via", normalized_funds, optional=True)
        if not funds_selected and raw_funds and raw_funds != normalized_funds:
            funds_selected = safe_select_by_label(page, "Funds Remitted Via", raw_funds, optional=True)
        if not funds_selected:
            log_debug("Funds Remitted Via value did not match options; leaving for manual review")

    click_next(page, "after IN holder info")

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

    log_step("Reached Indiana upload step.")
    return {"status": "reached_upload_step"}
