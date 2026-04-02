from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from playwright.sync_api import Locator, Page, TimeoutError

TARGET_URL = "https://ouf.osc.ny.gov/app/holder-info"
STATE_FOLDER_MAP = {
    "NY": "New York",
    "CT": "Connecticut",
    "CA": "California",
    "FL": "Florida",
}


@dataclass
class FieldErrorContext:
    field_name: str
    selector: str
    value: object


def log_step(message: str) -> None:
    print(f"[NY][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[NY][DEBUG] {message}")


def is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def discover_naupa_txt_file(project_root: str, company_name: str, state_folder_name: str) -> str:
    """Discover a single .txt file under Clients/<company_name>/<state_folder_name>/."""
    client_folder = os.path.join(project_root, "Clients", company_name, state_folder_name)
    log_debug(f"NAUPA discovery | searched_folder={client_folder!r}")

    if not os.path.isdir(client_folder):
        raise FileNotFoundError(f"NAUPA folder not found: {client_folder}")

    files_found = [
        os.path.join(client_folder, name)
        for name in os.listdir(client_folder)
        if os.path.isfile(os.path.join(client_folder, name)) and name.lower().endswith(".txt")
    ]
    log_debug(f"NAUPA discovery | files_found={files_found}")

    if len(files_found) == 0:
        raise FileNotFoundError(f"No .txt NAUPA file found in folder: {client_folder}")
    if len(files_found) > 1:
        raise RuntimeError(f"Multiple .txt NAUPA files found in folder {client_folder}: {files_found}")

    return files_found[0]


def run_with_context(action, ctx: FieldErrorContext) -> None:
    try:
        action()
    except Exception:
        print("\n[NY][ERROR] Automation error details:")
        print(f"  Field: {ctx.field_name}")
        print(f"  Selector strategy: {ctx.selector}")
        print(f"  Value: {ctx.value!r}")
        print("  Traceback:")
        traceback.print_exc()
        raise


def scroll_into_view(locator: Locator) -> None:
    locator.scroll_into_view_if_needed(timeout=10_000)


def wait_for_enabled(locator: Locator, timeout_ms: int = 10_000) -> None:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            disabled_attr = locator.get_attribute("disabled")
            aria_disabled = locator.get_attribute("aria-disabled")
            if disabled_attr is None and (aria_disabled is None or aria_disabled.lower() != "true"):
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise TimeoutError("Element did not become enabled in time")


def first_visible_locator(candidates: Iterable[Tuple[str, Locator]], timeout_ms: int = 3_000) -> Tuple[str, Optional[Locator]]:
    for strategy, candidate in candidates:
        try:
            if candidate.count() > 0:
                candidate.first.wait_for(state="visible", timeout=timeout_ms)
                return strategy, candidate.first
        except Exception:
            continue
    return "", None


def locator_tag_name(locator: Locator) -> str:
    return locator.evaluate("el => (el.tagName || '').toLowerCase()")


def build_text_candidates(page: Page, labels: list[str], names: list[str], ids: list[str]) -> list[Tuple[str, Locator]]:
    candidates: list[Tuple[str, Locator]] = []
    for label in labels:
        candidates.append((f"label exact '{label}'", page.get_by_label(label, exact=True)))
    for label in labels:
        candidates.append((f"label partial '{label}'", page.get_by_label(label, exact=False)))
    for nm in names:
        candidates.append((f"input[name='{nm}']", page.locator(f"input[name='{nm}']")))
        candidates.append((f"textarea[name='{nm}']", page.locator(f"textarea[name='{nm}']")))
    for identifier in ids:
        candidates.append((f"input#{identifier}", page.locator(f"input#{identifier}")))
        candidates.append((f"textarea#{identifier}", page.locator(f"textarea#{identifier}")))
    for label in labels:
        candidates.append(
            (
                f"nearby label '{label}' -> next control",
                page.locator(
                    f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::input or self::textarea or self::select][1]"
                ),
            )
        )
    return candidates


def fill_text_input(page: Page, field_name: str, value: str, labels: Iterable[str], names: Iterable[str], ids: Iterable[str] | None = None) -> None:
    if is_blank(value):
        log_step(f"Skipping text field '{field_name}' because value is blank")
        return

    strategy, locator = first_visible_locator(build_text_candidates(page, list(labels), list(names), list(ids or [])))
    if not locator:
        raise RuntimeError(f"Could not locate text input for field '{field_name}'")

    ctx = FieldErrorContext(field_name=field_name, selector=strategy or "no-match", value=value)

    def action() -> None:
        tag_name = locator_tag_name(locator)
        if tag_name not in {"input", "textarea"}:
            raise TypeError(f"Matched element tag '{tag_name}' is not a text input")
        locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(locator)
        wait_for_enabled(locator, timeout_ms=10_000)
        log_debug(f"Text field '{field_name}' | strategy={strategy} | value={value!r}")
        locator.click(timeout=10_000)
        locator.fill(str(value), timeout=10_000)

    run_with_context(action, ctx)


def fill_email_confirmation(page: Page, value: str) -> None:
    field_name = "email_confirmation"
    if is_blank(value):
        log_step("Skipping text field 'email_confirmation' because value is blank")
        return

    candidates: list[Tuple[str, Locator]] = [
        ("get_by_label exact 'Email Address Confirmation'", page.get_by_label("Email Address Confirmation", exact=True)),
        ("get_by_label partial 'Email Address Confirmation'", page.get_by_label("Email Address Confirmation", exact=False)),
        ("get_by_label partial '*Email Address Confirmation'", page.get_by_label("*Email Address Confirmation", exact=False)),
        ("input[name*='confirm' i]", page.locator("input[name*='confirm' i]")),
        ("input[id*='confirm' i]", page.locator("input[id*='confirm' i]")),
        (
            "nearby label 'Email Address Confirmation' -> next input",
            page.locator(
                "xpath=//*[contains(normalize-space(.), 'Email Address Confirmation')][1]/following::*[self::input or self::textarea or self::select][1]"
            ),
        ),
    ]

    strategy, locator = first_visible_locator(candidates, timeout_ms=4_000)
    if not locator:
        raise RuntimeError("Could not locate text input for field 'email_confirmation'")

    ctx = FieldErrorContext(field_name=field_name, selector=strategy or "no-match", value=value)

    def action() -> None:
        locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(locator)
        wait_for_enabled(locator, timeout_ms=10_000)
        locator.fill(str(value), timeout=10_000)

    run_with_context(action, ctx)


def fill_total_dollar_amount_remitted(page: Page, value: str) -> None:
    field_name = "total_dollar_amount_remitted"
    if is_blank(value):
        log_step("Skipping text field 'total_dollar_amount_remitted' because value is blank")
        return

    candidates: list[Tuple[str, Locator]] = [
        ("get_by_label('Total Dollar Amount Remitted')", page.get_by_label("Total Dollar Amount Remitted", exact=True)),
        ("get_by_label('*Total Dollar Amount Remitted')", page.get_by_label("*Total Dollar Amount Remitted", exact=False)),
        (
            "get_by_text('Total Dollar Amount Remitted').locator(xpath=following::input[1])",
            page.get_by_text("Total Dollar Amount Remitted", exact=False).locator("xpath=following::input[1]"),
        ),
        ("locator(input[name*='amount' i]).first", page.locator("input[name*='amount' i]").first),
        ("locator(input[id*='amount' i]).first", page.locator("input[id*='amount' i]").first),
        (
            "nearby label 'Total Dollar Amount Remitted' -> next input",
            page.locator("xpath=//*[contains(normalize-space(.), 'Total Dollar Amount Remitted')][1]/following::*[self::input][1]"),
        ),
    ]

    selected_locator: Optional[Locator] = None
    selected_strategy = ""
    for strategy, loc in candidates:
        try:
            count = loc.count()
            log_debug(f"total_dollar_amount_remitted attempt | strategy={strategy} | count={count}")
            if count == 0:
                continue
            loc.first.wait_for(state="visible", timeout=3_000)
            loc.first.scroll_into_view_if_needed(timeout=5_000)
            selected_locator = loc.first
            selected_strategy = strategy
            break
        except Exception:
            continue

    if not selected_locator:
        raise RuntimeError("Could not locate text input for field 'total_dollar_amount_remitted'")

    ctx = FieldErrorContext(field_name=field_name, selector=selected_strategy, value=value)

    def action() -> None:
        selected_locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(selected_locator)
        wait_for_enabled(selected_locator, timeout_ms=10_000)
        selected_locator.fill(str(value), timeout=10_000)

    run_with_context(action, ctx)


def select_dropdown(page: Page, field_name: str, value: str, labels: Iterable[str] | None = None, names: Iterable[str] | None = None, ids: Iterable[str] | None = None) -> None:
    if is_blank(value):
        log_step(f"Skipping dropdown field '{field_name}' because value is blank")
        return

    label_values = list(labels or [])
    name_values = list(names or [])
    id_values = list(ids or [])

    candidates: list[Tuple[str, Locator]] = []
    for label in label_values:
        candidates.append((f"get_by_label exact '{label}'", page.get_by_label(label, exact=True)))
    for label in label_values:
        candidates.append((f"get_by_label partial '{label}'", page.get_by_label(label, exact=False)))
    for nm in name_values:
        candidates.append((f"select[name='{nm}']", page.locator(f"select[name='{nm}']")))
    for identifier in id_values:
        candidates.append((f"select#{identifier}", page.locator(f"select#{identifier}")))
    for label in label_values:
        candidates.append((f"nearby label '{label}' -> following select", page.locator(f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::select][1]")))

    strategy, locator = first_visible_locator(candidates)
    if not locator:
        raise RuntimeError(f"Could not locate dropdown for field '{field_name}'")

    ctx = FieldErrorContext(field_name=field_name, selector=strategy or "no-match", value=value)

    def action() -> None:
        locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(locator)
        wait_for_enabled(locator, timeout_ms=10_000)
        try:
            locator.select_option(label=str(value), timeout=10_000)
            return
        except Exception:
            locator.select_option(value=str(value), timeout=10_000)

    run_with_context(action, ctx)


def select_yes_no(page: Page, field_name: str, value: str, labels: Iterable[str], names: Iterable[str]) -> None:
    if is_blank(value):
        log_step(f"Skipping radio field '{field_name}' because value is blank")
        return

    normalized = str(value).strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        target_text = "Yes"
    elif normalized in {"no", "n", "false", "0"}:
        target_text = "No"
    else:
        raise ValueError(f"Field '{field_name}' expects Yes/No value, got: {value!r}")

    ctx = FieldErrorContext(field_name=field_name, selector=f"radio->{target_text}", value=value)

    def action() -> None:
        for question_text in list(labels):
            question = page.get_by_text(question_text, exact=False).first
            if page.get_by_text(question_text, exact=False).count() == 0:
                continue

            container = question.locator("xpath=ancestor::*[self::div or self::form][1]")
            scoped_label = container.get_by_text(target_text, exact=True)
            if scoped_label.count() > 0:
                for i in range(scoped_label.count()):
                    candidate_label = scoped_label.nth(i)
                    if candidate_label.is_visible():
                        scroll_into_view(candidate_label)
                        candidate_label.click(timeout=10_000)
                        return

            rel_label = question.locator(f"xpath=following::label[normalize-space(.)='{target_text}'][1]")
            if rel_label.count() > 0 and rel_label.first.is_visible():
                scroll_into_view(rel_label.first)
                rel_label.first.click(timeout=10_000)
                return

        raise RuntimeError(f"Could not locate radio group for field: {field_name}")

    run_with_context(action, ctx)


def upload_txt_file(page: Page, field_name: str, file_path: str) -> None:
    if is_blank(file_path):
        raise ValueError("upload_txt_file_path is blank")

    normalized = os.path.abspath(os.path.expanduser(str(file_path)))
    if not os.path.isfile(normalized):
        raise FileNotFoundError(f"TXT file not found: {normalized}")

    ctx = FieldErrorContext(field_name=field_name, selector="hidden-file-input", value=normalized)

    def action() -> None:
        log_debug(f"Upload field '{field_name}' | resolved_file_path={normalized!r}")
        log_debug(f"Upload field '{field_name}' | os.path.exists={os.path.exists(normalized)}")

        # Optional scroll to upload area for stability.
        try:
            upload_area = page.locator("input[type='file'], button:has-text('Add Document')").first
            if upload_area.count() > 0:
                scroll_into_view(upload_area)
        except Exception:
            pass

        strategies = [
            ("input[type='file']", page.locator("input[type='file']").first),
            ("input[id*='reportFile']", page.locator("input[id*='reportFile']").first),
            ("input[type='file'][class*='d-none']", page.locator("input[type='file'][class*='d-none']").first),
        ]

        selected_strategy = ""
        selected_input: Optional[Locator] = None
        for strategy_name, locator in strategies:
            try:
                count = page.locator(strategy_name).count()
                log_debug(
                    f"Upload field '{field_name}' | locator_strategy={strategy_name} | matching_count={count}"
                )
                locator.wait_for(state="attached", timeout=15_000)
                selected_input = locator
                selected_strategy = strategy_name
                log_debug(
                    f"Upload field '{field_name}' | locator_strategy={strategy_name} | attached=True"
                )
                break
            except Exception as e:
                log_debug(
                    f"Upload field '{field_name}' | locator_strategy={strategy_name} | attached=False | error={e}"
                )
                continue

        if not selected_input:
            raise RuntimeError("Could not find attached file input element for upload")

        set_ok = False
        try:
            selected_input.set_input_files(normalized, timeout=15_000)
            set_ok = True
            log_debug(
                f"Upload field '{field_name}' | locator_strategy={selected_strategy} | set_input_files_succeeded=True"
            )
        except Exception as first_err:
            log_debug(
                f"Upload field '{field_name}' | locator_strategy={selected_strategy} | set_input_files_succeeded=False | error={first_err}"
            )
            # Single fallback: click Add Document and retry set_input_files immediately.
            add_doc = page.get_by_role("button", name="Add Document", exact=False)
            if add_doc.count() > 0:
                add_doc.first.click(timeout=10_000)
                selected_input.wait_for(state="attached", timeout=10_000)
                selected_input.set_input_files(normalized, timeout=15_000)
                set_ok = True
                log_debug(
                    f"Upload field '{field_name}' | fallback=Add Document click + retry set_input_files | succeeded=True"
                )
            else:
                raise

        files_len_ok = bool(selected_input.evaluate("el => !!(el.files && el.files.length > 0)"))
        log_debug(f"Upload field '{field_name}' | input.files.length>0={files_len_ok}")
        if not files_len_ok:
            raise RuntimeError("File input did not receive file")

        filename = os.path.basename(normalized)
        filename_visible = False
        try:
            filename_text = page.get_by_text(filename, exact=False)
            filename_visible = filename_text.count() > 0 and filename_text.first.is_visible()
        except Exception:
            filename_visible = False
        log_debug(f"Upload field '{field_name}' | filename_text_appeared={filename_visible}")

        next_usable = False
        try:
            next_btn = page.get_by_role("button", name="Next", exact=False)
            next_usable = next_btn.count() > 0 and next_btn.first.is_enabled()
        except Exception:
            next_usable = False
        log_debug(f"Upload field '{field_name}' | next_button_usable={next_usable}")

        if not set_ok:
            raise RuntimeError("set_input_files did not succeed")

    run_with_context(action, ctx)


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking Next ({step_name})")
    strategy, next_button = first_visible_locator(
        [
            ("role button exact", page.get_by_role("button", name="Next", exact=True)),
            ("role button partial", page.get_by_role("button", name="Next", exact=False)),
            ("button text", page.locator("button:has-text('Next')")),
            ("submit value", page.locator("input[type='submit'][value*='Next']")),
        ],
        timeout_ms=8_000,
    )
    if not next_button:
        raise RuntimeError("Could not find Next button")

    log_debug(f"Next button strategy: {strategy}")
    scroll_into_view(next_button)
    wait_for_enabled(next_button, timeout_ms=10_000)
    next_button.click(timeout=15_000)


def wait_for_preview_page(page: Page) -> None:
    log_step("Waiting for preview/signature page")
    preview_markers = [
        page.get_by_text("Electronic Signature", exact=False),
        page.get_by_text("Preview", exact=False),
        page.get_by_text("I certify", exact=False),
        page.get_by_role("heading", name="Electronic Signature", exact=False),
    ]
    deadline = time.time() + 60
    while time.time() < deadline:
        for marker in preview_markers:
            try:
                if marker.count() > 0 and marker.first.is_visible():
                    return
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise TimeoutError("Preview/signature page markers not found within 60 seconds")


def run_new_york(context, company_data: dict, filing_data: dict) -> str:
    """Run the NY workflow in a new tab and stop at preview page."""
    merged = {**company_data, **filing_data}

    # map workbook naming to existing bot field names with auto-discovery fallback
    company_name = str(merged.get("company_name", "")).strip()
    state_code = str(merged.get("state_code", "")).strip().upper()
    state_name_from_row = str(merged.get("state_name", "")).strip()
    resolved_state_folder = state_name_from_row or STATE_FOLDER_MAP.get(state_code, "")
    explicit_naupa = str(merged.get("naupa_file_path", "")).strip()

    log_debug(
        f"NAUPA resolution | company_name={company_name!r} | state_code={state_code!r} | "
        f"resolved_state_folder={resolved_state_folder!r}"
    )

    explicit_exists = bool(explicit_naupa and os.path.exists(explicit_naupa))
    log_debug(
        f"NAUPA resolution | workbook_path_value={explicit_naupa!r} | workbook_path_exists={explicit_exists}"
    )

    if explicit_naupa and explicit_exists:
        merged["upload_txt_file_path"] = explicit_naupa
        log_debug(f"NAUPA resolution | using existing filing_data['naupa_file_path']={explicit_naupa!r}")
    else:
        if explicit_naupa and not explicit_exists:
            print(
                f"[NY][WARN] filing_data['naupa_file_path'] does not exist on disk: {explicit_naupa!r}. "
                "Falling back to Clients folder auto-discovery."
            )

        if not company_name:
            raise RuntimeError("Cannot auto-discover NAUPA file: company_name is blank")
        if not resolved_state_folder:
            raise RuntimeError(
                f"Cannot auto-discover NAUPA file: state_name blank and no mapping for state_code={state_code!r}"
            )

        fallback_search_folder = os.path.join(os.getcwd(), "Clients", company_name, resolved_state_folder)
        log_debug(f"NAUPA resolution | fallback_search_folder={fallback_search_folder!r}")

        discovered = discover_naupa_txt_file(
            project_root=os.getcwd(),
            company_name=company_name,
            state_folder_name=resolved_state_folder,
        )
        merged["upload_txt_file_path"] = discovered
        log_debug(f"NAUPA resolution | final_chosen_file_path={discovered!r}")

    page = context.new_page()
    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)

    text_fields = {
        "holder_name": dict(labels=["Holder Name", "Name of Holder"], names=["holder_name", "holderName"], ids=[]),
        "holder_tax_id": dict(labels=["Holder Tax ID", "FEIN", "Tax ID"], names=["holder_tax_id", "holderTaxId", "tax_id"], ids=[]),
        "holder_id": dict(labels=["Holder ID"], names=["holder_id", "holderId"], ids=[]),
        "contact_name": dict(labels=["Contact Name"], names=["contact_name", "contactName"], ids=[]),
        "contact_phone": dict(labels=["Contact Phone", "Phone"], names=["contact_phone", "contactPhone", "phone"], ids=[]),
        "phone_extension": dict(labels=["Extension", "Phone Extension"], names=["phone_extension", "extension"], ids=[]),
        "previous_business_name": dict(labels=["Previous Business Name"], names=["previous_business_name"], ids=[]),
        "previous_business_fein": dict(labels=["Previous Business FEIN", "Previous Business FEIN/Tax ID"], names=["previous_business_fein"], ids=[]),
        "email": dict(labels=["Email Address", "Email"], names=["email"], ids=[]),
        "address_1": dict(labels=["Address 1", "Address Line 1"], names=["address_1", "address1"], ids=[]),
        "address_2": dict(labels=["Address 2", "Address Line 2"], names=["address_2", "address2"], ids=[]),
        "city": dict(labels=["City"], names=["city"], ids=[]),
        "zip": dict(labels=["ZIP", "Zip Code", "Postal Code"], names=["zip", "zipcode", "postal"], ids=[]),
        "parent_company_fein": dict(labels=["Parent Company FEIN", "Parent FEIN"], names=["parent_company_fein"], ids=[]),
    }

    dropdown_fields = {
        "state": dict(labels=["State"], names=["state"], ids=["state"]),
        "country": dict(labels=["Country"], names=["countryCode"], ids=["countryCode"]),
        "report_type": dict(labels=["Report Type"], names=["report_type"], ids=[]),
        "report_year": dict(labels=["Report Year", "Year"], names=["report_year"], ids=[]),
        "funds_remitted_via": dict(labels=["Funds Remitted Via", "Funds Method", "Method"], names=["funds_remitted_via"], ids=[]),
    }

    yes_no_fields = {
        "business_is_active": dict(labels=["Business is active:"], names=["business_is_active"]),
        "on_behalf_of_another_org": dict(labels=["on behalf of another organization", "report on behalf", "another organization"], names=["on_behalf_of_another_org"]),
        "first_time_filing": dict(labels=["first time this business entity", "first time filing", "unclaimed property report"], names=["first_time_filing"]),
        "foreign_address": dict(labels=["Foreign Address"], names=["foreign_address"]),
        "combined_file": dict(labels=["Combined file"], names=["combined_file"]),
    }

    log_step("Filling text input fields")
    for key, config in text_fields.items():
        fill_text_input(page, key, merged.get(key, ""), config.get("labels", []), config.get("names", []), config.get("ids", []))

    fill_email_confirmation(page, merged.get("email_confirmation", ""))
    fill_total_dollar_amount_remitted(page, merged.get("total_dollar_amount_remitted", ""))

    log_step("Selecting dropdown fields")
    for key, config in dropdown_fields.items():
        select_dropdown(page, key, merged.get(key, ""), config.get("labels", []), config.get("names", []), config.get("ids", []))

    log_step("Selecting Yes/No radio fields")
    for key, config in yes_no_fields.items():
        select_yes_no(page, key, merged.get(key, ""), config.get("labels", []), config.get("names", []))

    click_next(page, "after holder info")

    log_step("Uploading TXT file")
    upload_txt_file(page, "upload_txt_file_path", merged.get("upload_txt_file_path", ""))

    click_next(page, "after file upload")

    wait_for_preview_page(page)
    print("[NY] Reached preview page. Review, sign, and submit manually.")
    return "reached preview"
