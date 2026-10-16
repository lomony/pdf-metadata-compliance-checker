"""Command-line entry point for the PDF Metadata & Compliance Checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdfcheck.checker import check_pdf, default_rules_path, format_json, format_text, load_rules
from pdfcheck.server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdfcheck",
        description="Check PDF metadata, security classification, file names, and PDF/A claims.",
    )
    parser.add_argument("--rules", type=Path, help="Path to a JSON rules file. Defaults to ./rules.json.")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Check one or more PDF files.")
    check.add_argument("pdfs", nargs="+", type=Path, help="PDF files to check.")
    check.add_argument("--json", action="store_true", help="Print a JSON report.")
    check.add_argument("--html", type=Path, help="Write an HTML report to this path.")

    web = sub.add_parser("serve", help="Open a local browser page for checking PDFs.")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    rules_path = args.rules if args.rules is not None else default_rules_path()
    rules = load_rules(rules_path)

    if args.command == "serve":
        serve(rules, host=args.host, port=args.port)
        return 0

    missing = [path for path in args.pdfs if not path.is_file()]
    if missing:
        print("File not found: " + ", ".join(str(path) for path in missing), file=sys.stderr)
        return 2

    results = [check_pdf(path, rules) for path in args.pdfs]
    if args.json:
        sys.stdout.write(format_json(results))
    else:
        sys.stdout.write(format_text(results))
    if args.html:
        args.html.write_text(_html_report(results), encoding="utf-8")
        print(f"Wrote {args.html}")
    return 0 if all(result.passed for result in results) else 1


def _html_report(results: list) -> str:
    rows: list[str] = []
    for result in results:
        state = "pass" if result.passed else "fail"
        items = "".join(
            f"<li class='{item.status}'><strong>{item.status}</strong> "
            f"{_escape(item.rule)}: {_escape(item.message)}</li>"
            for item in result.findings
        )
        rows.append(f"<section><h2 class='{state}'>{_escape(result.file_name)}</h2><ul>{items}</ul></section>")
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>PDF Metadata &amp; Compliance Checker</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 46rem; color: #1c2430; }}
    h1 {{ font-size: 1.6rem; }}
    li {{ margin: 0.35rem 0; }}
    .pass {{ color: #1f7a4d; }}
    .fail {{ color: #a33b32; }}
  </style>
</head>
<body>
  <h1>PDF Metadata &amp; Compliance Checker</h1>
  {body}
</body>
</html>
"""


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    raise SystemExit(main())
