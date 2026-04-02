from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from playwright.sync_api import Locator, Page, TimeoutError

TARGET_URL = "https://ctbiglist.gov/app/holder-info"


@dataclass
class FieldErrorContext:
    field_name: str
    selector: str
    value: object


def log_step(message: str) -> None:
    print(f"[CT][STEP] {message}")


def log_debug(message: str) -> None:
    print(f"[CT][DEBUG] {message}")


def is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def run_with_context(action, ctx: FieldErrorContext) -> None:
    try:
        action()
    except Exception:
        print("\n[CT][ERROR] Automation error details:")
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


def discover_naupa_txt_file(project_root: str, company_name: str) -> str:
    client_folder = os.path.join(project_root, "Clients", company_name, "Connecticut")
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


def fill_text_input(page: Page, field_name: str, value: str, labels: list[str], names: list[str], ids: list[str] | None = None) -> None:
    if is_blank(value):
        log_step(f"Skipping text field '{field_name}' because value is blank")
        return

    candidates: list[Tuple[str, Locator]] = []
    for label in labels:
        candidates.append((f"label exact '{label}'", page.get_by_label(label, exact=True)))
        candidates.append((f"label partial '{label}'", page.get_by_label(label, exact=False)))
    for nm in names:
        candidates.append((f"input[name='{nm}']", page.locator(f"input[name='{nm}']")))
        candidates.append((f"textarea[name='{nm}']", page.locator(f"textarea[name='{nm}']")))
    for idv in ids or []:
        candidates.append((f"input#{idv}", page.locator(f"input#{idv}")))
        candidates.append((f"textarea#{idv}", page.locator(f"textarea#{idv}")))
    for label in labels:
        candidates.append(
            (
                f"nearby label '{label}' -> next control",
                page.locator(f"xpath=//*[contains(normalize-space(.), '{label}')][1]/following::*[self::input or self::textarea][1]"),
            )
        )

    strategy, locator = first_visible_locator(candidates)
    if not locator:
        raise RuntimeError(f"Could not locate text input for field '{field_name}'")

    ctx = FieldErrorContext(field_name=field_name, selector=strategy, value=value)

    def action() -> None:
        tag = locator_tag_name(locator)
        if tag not in {"input", "textarea"}:
            raise RuntimeError(f"Matched non-text element for {field_name}: {tag}")
        locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(locator)
        wait_for_enabled(locator)
        log_debug(f"Text field '{field_name}' | strategy={strategy} | value={value!r}")
        locator.fill(str(value), timeout=10_000)

    run_with_context(action, ctx)


def fill_total_dollar_amount_remitted(page: Page, raw_value: object) -> None:
    field_name = "total_dollar_amount_remitted"
    if is_blank(raw_value):
        log_step("Skipping text field 'total_dollar_amount_remitted' because value is blank")
        return

    raw_str = str(raw_value)
    normalized_value = raw_str.strip().replace(",", "").replace("$", "")
    log_debug(
        f"CT total_dollar_amount_remitted | raw_value={raw_str!r} | normalized_value={normalized_value!r}"
    )

    candidates: list[Tuple[str, Locator]] = [
        (
            "Strategy A - get_by_label('Total Dollar Amount Remitted')",
            page.get_by_label("Total Dollar Amount Remitted", exact=False),
        ),
        (
            "Strategy B - get_by_text(...).following::input[1]",
            page.get_by_text("Total Dollar Amount Remitted", exact=False).locator("xpath=following::input[1]"),
        ),
        (
            "Strategy C - nearest input fallback",
            page.locator(
                "xpath=//*[contains(normalize-space(.), 'Total Dollar Amount Remitted')][1]/following::*[self::input][1]"
            ),
        ),
    ]

    selected_strategy = ""
    selected_locator: Optional[Locator] = None
    for strategy_name, locator in candidates:
        count = 0
        try:
            count = locator.count()
        except Exception:
            count = 0
        log_debug(f"CT total_dollar_amount_remitted | {strategy_name} | matches={count}")
        if count <= 0:
            continue
        try:
            locator.first.wait_for(state="visible", timeout=4_000)
            selected_locator = locator.first
            selected_strategy = strategy_name
            break
        except Exception:
            continue

    if not selected_locator:
        raise RuntimeError("CT: could not find Total Dollar Amount Remitted field")

    ctx = FieldErrorContext(field_name=field_name, selector=selected_strategy, value=normalized_value)

    def action() -> None:
        tag = locator_tag_name(selected_locator)
        if tag not in {"input", "textarea"}:
            raise RuntimeError(f"Matched non-text element for {field_name}: {tag}")
        selected_locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(selected_locator)
        wait_for_enabled(selected_locator)
        selected_locator.fill(normalized_value, timeout=10_000)
        log_debug(f"CT total_dollar_amount_remitted | succeeded_with={selected_strategy}")

    run_with_context(action, ctx)


def select_dropdown(page: Page, field_name: str, value: str, labels: list[str], names: list[str], ids: list[str] | None = None) -> None:
    if is_blank(value):
        log_step(f"Skipping dropdown field '{field_name}' because value is blank")
        return

    candidates: list[Tuple[str, Locator]] = []
    for label in labels:
        candidates.append((f"label exact '{label}'", page.get_by_label(label, exact=True)))
        candidates.append((f"label partial '{label}'", page.get_by_label(label, exact=False)))
    for nm in names:
        candidates.append((f"select[name='{nm}']", page.locator(f"select[name='{nm}']")))
    for idv in ids or []:
        candidates.append((f"select#{idv}", page.locator(f"select#{idv}")))

    strategy, locator = first_visible_locator(candidates)
    if not locator:
        raise RuntimeError(f"Could not locate dropdown for field '{field_name}'")

    ctx = FieldErrorContext(field_name=field_name, selector=strategy, value=value)

    def action() -> None:
        locator.wait_for(state="visible", timeout=10_000)
        scroll_into_view(locator)
        wait_for_enabled(locator)
        log_debug(f"Dropdown '{field_name}' | strategy={strategy} | value={value!r}")
        try:
            locator.select_option(label=str(value), timeout=10_000)
        except Exception:
            locator.select_option(value=str(value), timeout=10_000)

    run_with_context(action, ctx)


def select_yes_no(page: Page, field_name: str, value: str, question_texts: list[str]) -> None:
    if is_blank(value):
        log_step(f"Skipping radio field '{field_name}' because value is blank")
        return

    normalized = str(value).strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        target = "Yes"
    elif normalized in {"no", "n", "false", "0"}:
        target = "No"
    else:
        raise ValueError(f"Field '{field_name}' expects Yes/No value, got: {value!r}")

    ctx = FieldErrorContext(field_name=field_name, selector="question-relative-radio", value=value)

    def action() -> None:
        for question_text in question_texts:
            question = page.get_by_text(question_text, exact=False)
            if question.count() == 0:
                continue
            q = question.first
            container = q.locator("xpath=ancestor::*[self::div or self::form][1]")
            scoped_label = container.get_by_text(target, exact=True)
            if scoped_label.count() > 0:
                for i in range(scoped_label.count()):
                    lbl = scoped_label.nth(i)
                    if lbl.is_visible():
                        scroll_into_view(lbl)
                        lbl.click(timeout=10_000)
                        log_debug(f"Radio '{field_name}' selected={target} via container label")
                        return

            rel_label = q.locator(f"xpath=following::label[normalize-space(.)='{target}'][1]")
            if rel_label.count() > 0 and rel_label.first.is_visible():
                scroll_into_view(rel_label.first)
                rel_label.first.click(timeout=10_000)
                log_debug(f"Radio '{field_name}' selected={target} via following label")
                return

        raise RuntimeError(f"Could not locate radio group for field: {field_name}")

    run_with_context(action, ctx)


def upload_txt_file(page: Page, field_name: str, file_path: str) -> None:
    if is_blank(file_path):
        raise ValueError("upload_txt_file_path is blank")

    resolved_file_path = os.path.abspath(os.path.expanduser(str(file_path)))
    if not os.path.isfile(resolved_file_path):
        raise FileNotFoundError(f"TXT file not found: {resolved_file_path}")

    ctx = FieldErrorContext(field_name=field_name, selector="hidden-file-input", value=resolved_file_path)

    def action() -> None:
        log_debug(f"Upload | file={resolved_file_path!r}")
        strategies = [
            ("input[type='file']", page.locator("input[type='file']").first),
            ("input[id*='reportFile']", page.locator("input[id*='reportFile']").first),
            ("input[type='file'][class*='d-none']", page.locator("input[type='file'][class*='d-none']").first),
        ]

        selected: Optional[Locator] = None
        for strategy_name, loc in strategies:
            try:
                loc.wait_for(state="attached", timeout=15_000)
                selected = loc
                log_debug(f"Upload | strategy={strategy_name} | attached=True")
                break
            except Exception as e:
                log_debug(f"Upload | strategy={strategy_name} | attached=False | error={e}")

        if not selected:
            raise RuntimeError("Could not find attached hidden file input")

        selected.set_input_files(resolved_file_path, timeout=15_000)
        files_len_ok = bool(selected.evaluate("el => !!(el.files && el.files.length > 0)"))
        if not files_len_ok:
            raise RuntimeError("File input did not receive file")

        filename = os.path.basename(resolved_file_path)
        filename_visible = False
        try:
            candidate = page.get_by_text(filename, exact=False)
            filename_visible = candidate.count() > 0 and candidate.first.is_visible()
        except Exception:
            pass
        log_debug(f"Upload | files_attached={files_len_ok} | filename_visible={filename_visible}")

    run_with_context(action, ctx)


def click_next(page: Page, step_name: str) -> None:
    log_step(f"Clicking Next ({step_name})")
    strategy, next_btn = first_visible_locator(
        [
            ("role exact", page.get_by_role("button", name="Next", exact=True)),
            ("role fuzzy", page.get_by_role("button", name="Next", exact=False)),
            ("button text", page.locator("button:has-text('Next')")),
            ("submit value", page.locator("input[type='submit'][value*='Next']")),
        ],
        timeout_ms=8_000,
    )
    if not next_btn:
        raise RuntimeError("Could not find Next button")

    log_debug(f"Next button strategy={strategy}")
    scroll_into_view(next_btn)
    wait_for_enabled(next_btn)
    next_btn.click(timeout=15_000)


def wait_for_preview_page(page: Page) -> None:
    log_step("Waiting for preview page")
    markers = [
        page.get_by_text("Electronic Signature", exact=False),
        page.get_by_text("Preview", exact=False),
        page.get_by_text("I certify", exact=False),
    ]
    deadline = time.time() + 60
    while time.time() < deadline:
        for marker in markers:
            try:
                if marker.count() > 0 and marker.first.is_visible():
                    return
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise TimeoutError("Preview/signature page markers not found within 60 seconds")


def run_connecticut(context, company_data: dict, filing_data: dict) -> dict:
    merged = {**company_data, **filing_data}

    company_name = str(merged.get("company_name", "")).strip()
    explicit_naupa = str(merged.get("naupa_file_path", "")).strip()
    if explicit_naupa and os.path.exists(explicit_naupa):
        merged["upload_txt_file_path"] = explicit_naupa
        log_debug(f"NAUPA resolution | using workbook path {explicit_naupa!r}")
    else:
        if explicit_naupa:
            print(
                f"[CT][WARN] filing_data['naupa_file_path'] does not exist on disk: {explicit_naupa!r}. "
                "Falling back to Clients folder auto-discovery."
            )
        if not company_name:
            raise RuntimeError("Cannot auto-discover NAUPA file: company_name is blank")
        discovered = discover_naupa_txt_file(project_root=os.getcwd(), company_name=company_name)
        merged["upload_txt_file_path"] = discovered
        log_debug(f"NAUPA resolution | discovered file {discovered!r}")

    page = context.new_page()
    log_step(f"Navigating to {TARGET_URL}")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)

    text_fields = {
        "holder_name": dict(labels=["Holder Name"], names=["holder_name", "holderName"]),
        "holder_tax_id": dict(labels=["Holder Tax ID", "Tax ID"], names=["holder_tax_id", "holderTaxId"]),
        "holder_id": dict(labels=["Holder ID"], names=["holder_id", "holderId"]),
        "contact_name": dict(labels=["Contact Name"], names=["contact_name", "contactName"]),
        "contact_phone": dict(labels=["Contact Phone Number", "Contact Phone"], names=["contact_phone", "contactPhone"]),
        "phone_extension": dict(labels=["Phone Extension", "Extension"], names=["phone_extension", "extension"]),
        "email": dict(labels=["Email Address", "Email"], names=["email"]),
        "email_confirmation": dict(labels=["Email Address Confirmation"], names=["email_confirmation", "confirm_email"]),
        "total_dollar_amount_remitted": dict(labels=["Total Dollar Amount Remitted"], names=["total_dollar_amount_remitted", "total_amount"]),
    }

    dropdown_fields = {
        "report_type": dict(labels=["Report Type"], names=["report_type"]),
        "report_year": dict(labels=["Report Year", "Year"], names=["report_year"]),
        "funds_remitted_via": dict(labels=["Funds Remitted Via", "Funds Method"], names=["funds_remitted_via"]),
    }

    log_step("Filling CT text fields")
    for key, cfg in text_fields.items():
        if key == "total_dollar_amount_remitted":
            continue
        fill_text_input(page, key, merged.get(key, ""), cfg.get("labels", []), cfg.get("names", []), cfg.get("ids", []))
    fill_total_dollar_amount_remitted(page, merged.get("total_dollar_amount_remitted", ""))

    log_step("Selecting CT dropdowns")
    for key, cfg in dropdown_fields.items():
        select_dropdown(page, key, merged.get(key, ""), cfg.get("labels", []), cfg.get("names", []), cfg.get("ids", []))

    log_step("Selecting CT radio fields")
    select_yes_no(
        page,
        field_name="negative_report",
        value=merged.get("negative_report", ""),
        question_texts=["This is a Negative Report"],
    )

    click_next(page, "after holder info")

    log_step("Uploading CT TXT file")
    upload_txt_file(page, "upload_txt_file_path", merged.get("upload_txt_file_path", ""))

    click_next(page, "after file upload")

    wait_for_preview_page(page)
    print("[CT] Reached preview page. Review, sign, and submit manually.")
    return {"state": "CT", "status": "reached_preview"}
