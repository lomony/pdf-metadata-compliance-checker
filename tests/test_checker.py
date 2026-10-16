"""Checks for the generic PDF compliance rules."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from pathlib import Path

from pypdf import PdfWriter

from pdfcheck.checker import check_pdf, load_rules
from pdfcheck.samples import write_samples
from pdfcheck.server import make_server

ROOT = Path(__file__).resolve().parents[1]


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rules(ROOT / "rules.json")

    def test_shipped_rules_match_builtin_shape(self) -> None:
        builtin = load_rules(None)
        self.assertEqual(set(self.rules), set(builtin))
        self.assertEqual(self.rules["required_metadata"], ["Title", "Author", "Subject"])
        self.assertIn("Public", self.rules["classification"]["allowed_values"])

    def test_compliant_sample_passes(self) -> None:
        path = self._samples() / "project-overview.pdf"
        result = check_pdf(path, self.rules)
        self.assertTrue(result.passed, result.to_dict())
        self.assertTrue(any(item.rule == "pdfa" and item.status == "pass" for item in result.findings))

    def test_mixed_sample_reports_specific_failures(self) -> None:
        path = self._samples() / "quarterly-update.pdf"
        result = check_pdf(path, self.rules)
        self.assertFalse(result.passed)
        failed = {(item.rule, item.message) for item in result.findings if item.status == "fail"}
        rules = {rule for rule, _message in failed}
        self.assertIn("metadata", rules)
        self.assertIn("classification", rules)
        self.assertIn("pdfa", rules)
        self.assertTrue(any(item.rule == "file_name" and item.status == "pass" for item in result.findings))
        self.assertTrue(any("Secret" in item.message for item in result.findings))

    def test_keywords_can_satisfy_classification(self) -> None:
        path = self._write(
            {
                "/Title": "Notes",
                "/Author": "Documentation Team",
                "/Subject": "Notes",
                "/Keywords": "handbook, Public",
            }
        )
        result = check_pdf(path, self.rules)
        classification = next(item for item in result.findings if item.rule == "classification")
        self.assertEqual(classification.status, "pass")
        self.assertIn("keywords", classification.message)

    def test_custom_rules_can_turn_checks_off(self) -> None:
        rules = json.loads(json.dumps(self.rules))
        rules["pdfa"]["enabled"] = False
        rules["classification"]["enabled"] = False
        rules["required_metadata"] = ["Title"]
        rules["file_name"]["pattern"] = r".+\.pdf"
        path = self._samples() / "quarterly-update.pdf"
        result = check_pdf(path, rules)
        self.assertTrue(result.passed, result.to_dict())

    def test_bad_file_name_fails_even_when_metadata_is_complete(self) -> None:
        source = self._samples() / "project-overview.pdf"
        renamed = source.with_name("Draft Notes!.pdf")
        result = check_pdf(source, self.rules, display_name=renamed.name)
        file_name = next(item for item in result.findings if item.rule == "file_name")
        self.assertEqual(file_name.status, "fail")

    def test_unreadable_bytes_fail(self) -> None:
        path = self._samples().parent / "not-a-pdf.pdf"
        path.write_bytes(b"this is not a pdf")
        result = check_pdf(path, self.rules)
        self.assertFalse(result.passed)
        self.assertTrue(any(item.rule == "metadata" and item.status == "fail" for item in result.findings))

    def test_server_checks_an_uploaded_pdf(self) -> None:
        server = make_server(self.rules, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/rules") as response:
                body = json.loads(response.read().decode())
            self.assertIn("classification", body)
            pdf = (self._samples() / "project-overview.pdf").read_bytes()
            request = urllib.request.Request(
                f"http://{host}:{port}/api/check",
                data=pdf,
                headers={"X-Filename": "project-overview.pdf", "Content-Type": "application/pdf"},
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode())
            self.assertTrue(payload["passed"])
        finally:
            server.shutdown()
            server.server_close()

    def _samples(self) -> Path:
        directory = Path(self.id().replace(".", "_"))
        # Keep generated files under the system temp via unittest's default tmp? Use a local folder.
        folder = ROOT / "reports" / "test-samples"
        write_samples(folder)
        return folder

    def _write(self, metadata: dict[str, str]) -> Path:
        folder = ROOT / "reports" / "test-samples"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "keyword-sample.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata(metadata)
        with path.open("wb") as handle:
            writer.write(handle)
        return path


if __name__ == "__main__":
    unittest.main()
