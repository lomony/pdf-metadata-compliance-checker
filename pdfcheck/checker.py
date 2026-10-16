"""Configurable checks for PDF metadata and file-name compliance."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logging.getLogger("pypdf").setLevel(logging.ERROR)

DEFAULT_RULES: dict[str, Any] = {
    "file_name": {
        "enabled": True,
        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.pdf$",
        "ignore_case": False,
    },
    "required_metadata": ["Title", "Author", "Subject"],
    "classification": {
        "enabled": True,
        "keys": ["Classification", "SecurityClassification"],
        "allowed_values": ["Public", "Internal", "Confidential", "Restricted"],
        "search_keywords": True,
    },
    "pdfa": {
        "enabled": True,
        "accepted_parts": ["1", "2", "3"],
        "accepted_conformance": ["A", "B", "U"],
    },
}

@dataclass
class Finding:
    rule: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "status": self.status, "message": self.message}


@dataclass
class CheckResult:
    file_name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(item.status == "pass" for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file_name,
            "passed": self.passed,
            "findings": [item.to_dict() for item in self.findings],
        }


def load_rules(path: Path | None = None) -> dict[str, Any]:
    """Load a rules file, or return the built-in defaults when path is None."""
    if path is None:
        return json.loads(json.dumps(DEFAULT_RULES))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Rules file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Rules file is not valid JSON: {path} ({exc})") from exc
    if not isinstance(raw, dict):
        raise SystemExit("Rules file must be a JSON object.")
    return _normalize_rules(raw)


def default_rules_path() -> Path | None:
    candidate = Path.cwd() / "rules.json"
    return candidate if candidate.is_file() else None


def check_pdf(path: Path, rules: dict[str, Any], display_name: str | None = None) -> CheckResult:
    """Check one PDF. display_name is the name used for the file-name rule."""
    rules = _normalize_rules(rules)
    file_name = display_name or path.name
    result = CheckResult(file_name=file_name)
    result.findings.append(_check_file_name(file_name, rules["file_name"]))

    reader, read_error = _open_pdf(path)
    if reader is None:
        message = f"The file could not be read ({read_error})."
        for rule in ("metadata", "classification", "pdfa"):
            if _rule_enabled(rules, rule):
                result.findings.append(Finding(rule, "fail", message))
        return result

    values = _metadata_values(reader)
    for field_name in rules["required_metadata"]:
        value = values.get(field_name.lower())
        if value:
            shown = value if len(value) <= 80 else value[:77] + "..."
            result.findings.append(
                Finding("metadata", "pass", f"{field_name} is present ({shown}).")
            )
        else:
            result.findings.append(
                Finding("metadata", "fail", f"Required metadata field {field_name} is missing.")
            )

    if rules["classification"]["enabled"]:
        result.findings.append(_check_classification(values, rules["classification"]))
    if rules["pdfa"]["enabled"]:
        result.findings.append(_check_pdfa(reader, rules["pdfa"]))
    return result


def format_text(results: list[CheckResult]) -> str:
    lines: list[str] = []
    for result in results:
        label = "pass" if result.passed else "fail"
        lines.append(f"{result.file_name}: {label}")
        for item in result.findings:
            lines.append(f"  [{item.status}] {item.rule}: {item.message}")
        lines.append("")
    failed = sum(not result.passed for result in results)
    lines.append(f"{len(results)} file(s) checked, {failed} with failures.")
    return "\n".join(lines).rstrip() + "\n"


def format_json(results: list[CheckResult]) -> str:
    payload = {
        "passed": all(result.passed for result in results),
        "results": [result.to_dict() for result in results],
    }
    return json.dumps(payload, indent=2) + "\n"


def _rule_enabled(rules: dict[str, Any], rule: str) -> bool:
    if rule == "metadata":
        return bool(rules["required_metadata"])
    return bool(rules[rule]["enabled"])


def _normalize_rules(raw: dict[str, Any]) -> dict[str, Any]:
    file_name = raw.get("file_name", DEFAULT_RULES["file_name"])
    if not isinstance(file_name, dict):
        raise SystemExit("file_name must be an object.")
    pattern = str(file_name.get("pattern", DEFAULT_RULES["file_name"]["pattern"]))
    flags = re.IGNORECASE if file_name.get("ignore_case") else 0
    try:
        re.compile(pattern, flags)
    except re.error as exc:
        raise SystemExit(f"file_name.pattern is not a valid regular expression: {exc}") from exc

    required = raw.get("required_metadata", DEFAULT_RULES["required_metadata"])
    if not isinstance(required, list) or not all(isinstance(item, str) and item.strip() for item in required):
        raise SystemExit("required_metadata must be a list of field names.")

    classification = raw.get("classification", DEFAULT_RULES["classification"])
    if not isinstance(classification, dict):
        raise SystemExit("classification must be an object.")
    keys = classification.get("keys", DEFAULT_RULES["classification"]["keys"])
    allowed = classification.get("allowed_values", DEFAULT_RULES["classification"]["allowed_values"])
    if not isinstance(keys, list) or not all(isinstance(item, str) and item.strip() for item in keys):
        raise SystemExit("classification.keys must be a list of metadata names.")
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item.strip() for item in allowed):
        raise SystemExit("classification.allowed_values must be a list of labels.")

    pdfa = raw.get("pdfa", DEFAULT_RULES["pdfa"])
    if not isinstance(pdfa, dict):
        raise SystemExit("pdfa must be an object.")

    return {
        "file_name": {
            "enabled": bool(file_name.get("enabled", True)),
            "pattern": pattern,
            "ignore_case": bool(file_name.get("ignore_case", False)),
        },
        "required_metadata": [item.strip() for item in required],
        "classification": {
            "enabled": bool(classification.get("enabled", True)),
            "keys": [item.strip() for item in keys],
            "allowed_values": [item.strip() for item in allowed],
            "search_keywords": bool(classification.get("search_keywords", True)),
        },
        "pdfa": {
            "enabled": bool(pdfa.get("enabled", True)),
            "accepted_parts": [str(item).strip() for item in pdfa.get("accepted_parts", ["1", "2", "3"])],
            "accepted_conformance": [
                str(item).strip().upper()
                for item in pdfa.get("accepted_conformance", ["A", "B", "U"])
            ],
        },
    }


def _check_file_name(file_name: str, rule: dict[str, Any]) -> Finding:
    if not rule["enabled"]:
        return Finding("file_name", "pass", "File-name check is turned off.")
    flags = re.IGNORECASE if rule["ignore_case"] else 0
    if re.fullmatch(rule["pattern"], file_name, flags):
        return Finding("file_name", "pass", "File name matches the configured pattern.")
    return Finding(
        "file_name",
        "fail",
        "File name does not match the configured pattern. "
        "Use the file name only, without a folder path.",
    )


def _open_pdf(path: Path) -> tuple[PdfReader | None, str]:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            return None, "the file is encrypted"
        # Touch a page so damaged files fail here rather than later.
        len(reader.pages)
        return reader, ""
    except PdfReadError as exc:
        return None, _short_error(exc)
    except Exception as exc:  # noqa: BLE001 - unreadable input should be a finding
        return None, _short_error(exc)


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:180]


def _metadata_values(reader: PdfReader) -> dict[str, str]:
    values: dict[str, str] = {}
    info = reader.metadata or {}
    for key, raw in info.items():
        name = str(key).lstrip("/")
        text = _as_text(raw)
        if name and text:
            values[name.lower()] = text

    xmp = reader.xmp_metadata
    if xmp is not None:
        for name, text in _xmp_values(xmp).items():
            values.setdefault(name.lower(), text)
    return values


def _xmp_values(xmp: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    mapping = {
        "Title": getattr(xmp, "dc_title", None),
        "Author": getattr(xmp, "dc_creator", None),
        "Subject": getattr(xmp, "dc_description", None),
        "Keywords": getattr(xmp, "dc_subject", None),
    }
    for name, raw in mapping.items():
        text = _as_text(raw)
        if text:
            found[name] = text
    custom = getattr(xmp, "custom_properties", None) or {}
    if isinstance(custom, dict):
        for key, raw in custom.items():
            text = _as_text(raw)
            if text:
                found[str(key).lstrip("/")] = text
    return found


def _as_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        parts = [_as_text(value) for value in raw.values()]
        return ", ".join(part for part in parts if part)
    if isinstance(raw, (list, tuple)):
        parts = [_as_text(value) for value in raw]
        return ", ".join(part for part in parts if part)
    text = str(raw).strip()
    return "" if text in {"None", "{}"} else text


def _check_classification(values: dict[str, str], rule: dict[str, Any]) -> Finding:
    allowed = rule["allowed_values"]
    found: list[str] = []
    for key in rule["keys"]:
        value = values.get(key.lower())
        if value:
            found.append(value)
            match = _match_allowed(value, allowed)
            if match:
                return Finding(
                    "classification",
                    "pass",
                    f"Security classification {match} is present in {key}.",
                )
    if rule["search_keywords"]:
        keywords = values.get("keywords", "")
        match = _keyword_match(keywords, allowed)
        if match:
            return Finding(
                "classification",
                "pass",
                f"Security classification {match} is present in keywords.",
            )
    if found:
        shown = ", ".join(found)
        labels = ", ".join(allowed)
        return Finding(
            "classification",
            "fail",
            f"Security classification '{shown}' is not one of the allowed values ({labels}).",
        )
    labels = ", ".join(allowed)
    keys = ", ".join(rule["keys"])
    return Finding(
        "classification",
        "fail",
        f"Security classification is missing. Set {keys} to one of: {labels}.",
    )


def _match_allowed(value: str, allowed: list[str]) -> str | None:
    folded = value.casefold().strip()
    for label in allowed:
        if folded == label.casefold():
            return label
    return None


def _keyword_match(keywords: str, allowed: list[str]) -> str | None:
    if not keywords:
        return None
    for label in allowed:
        pattern = rf"(?i)(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])"
        if re.search(pattern, keywords):
            return label
    return None


def _check_pdfa(reader: PdfReader, rule: dict[str, Any]) -> Finding:
    xmp = reader.xmp_metadata
    part = _as_text(getattr(xmp, "pdfaid_part", None)) if xmp is not None else ""
    conformance = _as_text(getattr(xmp, "pdfaid_conformance", None)) if xmp is not None else ""
    conformance = conformance.upper()
    if not part:
        return Finding(
            "pdfa",
            "fail",
            "PDF/A identification metadata (pdfaid:part) is missing. "
            "This check reads the claim stored in the file; it is not a full PDF/A validator.",
        )
    if part not in rule["accepted_parts"]:
        accepted = ", ".join(rule["accepted_parts"])
        return Finding(
            "pdfa",
            "fail",
            f"PDF/A part {part} is not in the accepted list ({accepted}).",
        )
    accepted_levels = rule["accepted_conformance"]
    if accepted_levels:
        if not conformance:
            return Finding(
                "pdfa",
                "fail",
                "PDF/A part is present, but conformance (pdfaid:conformance) is missing.",
            )
        if conformance not in accepted_levels:
            levels = ", ".join(accepted_levels)
            return Finding(
                "pdfa",
                "fail",
                f"PDF/A conformance {conformance} is not in the accepted list ({levels}).",
            )
    label = f"PDF/A-{part}{conformance}" if conformance else f"PDF/A-{part}"
    return Finding(
        "pdfa",
        "pass",
        f"{label} identification metadata is present. "
        "This check reads the claim stored in the file; it is not a full PDF/A validator.",
    )
