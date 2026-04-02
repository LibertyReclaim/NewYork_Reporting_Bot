from __future__ import annotations

import time

TARGET_URL = "https://southcarolina.findyourunclaimedproperty.com/app/holder-info"


def log_step(message: str) -> None:
    print(f"[SC][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[SC][DEBUG] {message}")


def normalize_number(value, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("$", "")
    return text if text else default


def safe_fill(page, label: str, value: str, optional: bool = False) -> None:
    locator = page.get_by_label(label, exact=False)
    if locator.count() == 0:
        if optional:
            log_debug(f"Field not found: {label} (optional; skipping)")
            return
        raise RuntimeError(f"[SC] Field not found: {label}")

    field = locator.first
    disabled = field.get_attribute("disabled") is not None or (field.get_attribute("aria-disabled") or "").lower() == "true"
    readonly = field.get_attribute("readonly") is not None or (field.get_attribute("aria-readonly") or "").lower() == "true"
    if disabled or readonly:
        log_debug(f"Field '{label}' is disabled/read-only; skipping")
        return

    text = str(value).strip()
    if optional and not text:
        log_debug(f"{label} is blank (optional); skipping")
        return

    log_debug(f"Filling {label}: {text!r}")
    field.scroll_into_view_if_needed(timeout=10_000)
    field.fill(text, timeout=10_000)


def run_south_carolina(context, company_data: dict, filing_data: dict) -> dict:
    page = context.new_page()

    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.get_by_label("Holder Name", exact=False).first.wait_for(state="visible", timeout=30_000)

    # Primary Holder Info
    safe_fill(page, "Holder Name", str(company_data.get("holder_name", "")).strip())
    safe_fill(page, "Holder Tax ID", str(company_data.get("holder_tax_id", "")).strip())
    safe_fill(page, "Contact Person", str(company_data.get("contact_name", "")).strip())
    safe_fill(page, "Contact Phone Number", str(company_data.get("contact_phone", "")).strip())
    safe_fill(page, "Phone Extension", str(company_data.get("phone_extension", "")).strip(), optional=True)

    email = str(company_data.get("email", "")).strip()
    safe_fill(page, "Email", email)
    safe_fill(page, "Email Confirmation", email)

    # Report Info
    page.get_by_label("Report Type", exact=False).first.select_option(label="Annual Report")
    page.get_by_label("Report Year", exact=False).first.select_option(label="2025")

    try:
        page.get_by_text("This is a Negative Report", exact=False).first.locator("xpath=following::label[normalize-space(.)='No'][1]").click()
    except Exception:
        page.get_by_label("No", exact=False).first.click()

    remitted = normalize_number(filing_data.get("total_dollar_amount_remitted"), default="")
    log_debug(f"Filling Total Dollar Amount Remitted: {remitted!r}")
    safe_fill(page, "Total Dollar Amount Remitted", remitted)

    # Required exact fallback chain for Funds Remitted Via
    log_debug("Selecting Funds Remitted Via: 'Wire'")
    try:
        page.get_by_label("Funds Remitted Via").select_option(label="Wire")
    except Exception:
        try:
            page.locator("select").first.select_option(label="Wire")
        except Exception:
            page.get_by_role("combobox").first.select_option(label="Wire")

    # NEXT fallback chain
    log_step("Clicking NEXT (after SC holder info)")
    try:
        page.get_by_role("button", name="NEXT").click()
    except Exception:
        page.locator("button:has-text('NEXT')").first.click()

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

    log_step("Reached South Carolina upload step.")
    return {"status": "reached_upload_step"}
