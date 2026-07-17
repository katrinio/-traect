from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Sequence
from typing import Any

from traect.api.app import main as serve
from traect.app.database import make_engine
from traect.app.weekly_audit import AuditScope, WeeklyAuditReport, audit_weekly_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="traect")
    commands = parser.add_subparsers(dest="command")
    audit_parser = commands.add_parser("audit", help="audit persisted application data")
    audit_targets = audit_parser.add_subparsers(dest="audit_target", required=True)
    weekly = audit_targets.add_parser("weekly-data", help="audit historical weekly reviews")
    weekly.add_argument(
        "--fix-safe",
        action="store_true",
        help="apply only repairs whose intended result is unambiguous",
    )
    weekly.add_argument("--format", choices=("text", "json"), default="text", dest="output_format")
    weekly.add_argument("--workspace-id", type=int)
    weekly.add_argument("--iso-year", type=int)
    weekly.add_argument("--iso-week", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        serve()
        return 0
    if args.command == "audit" and args.audit_target == "weekly-data":
        return _run_weekly_audit(args, parser)
    parser.error("unknown command")
    return 2


def _run_weekly_audit(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if (args.iso_year is None) != (args.iso_week is None):
        parser.error("--iso-year and --iso-week must be provided together")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    database_url = os.environ.get("TRAECT_DATABASE_URL", "sqlite:///traect.db")
    engine = make_engine(database_url)
    try:
        report = audit_weekly_data(
            engine,
            scope=AuditScope(
                workspace_id=args.workspace_id,
                iso_year=args.iso_year,
                iso_week=args.iso_week,
            ),
            fix_safe=args.fix_safe,
        )
    finally:
        engine.dispose()
    if args.output_format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_weekly_audit_report(report))
    if report.repairs_rolled_back:
        return 2
    return 1 if report.unresolved_manual_review else 0


def format_weekly_audit_report(report: WeeklyAuditReport) -> str:
    lines = [
        "Weekly data audit",
        f"Audited at: {report.audited_at.isoformat()}",
        f"Inspected: {report.total_weeks_inspected} weeks, {report.total_states_inspected} states",
        f"Issues: {len(report.issues)}",
    ]
    if report.issue_counts_by_severity:
        severity_counts = ", ".join(f"{key}={value}" for key, value in report.issue_counts_by_severity.items())
        lines.append(f"By severity: {severity_counts}")
    if report.issue_counts_by_code:
        code_counts = ", ".join(f"{key}={value}" for key, value in report.issue_counts_by_code.items())
        lines.append(f"By code: {code_counts}")
    lines.extend(
        [
            (
                f"Repairs: proposed={report.repairs_proposed}, applied={report.repairs_applied}, "
                f"rolled_back={report.repairs_rolled_back}"
            ),
            f"Manual review or fatal: {report.unresolved_manual_review}",
        ]
    )
    if report.issues:
        lines.append("")
        lines.append("Findings:")
        lines.extend(_format_issue(issue.to_dict()) for issue in report.issues)
    if report.repairs:
        lines.append("")
        lines.append("Repair plan/results:")
        lines.extend(_format_repair(repair.to_dict()) for repair in report.repairs)
    return "\n".join(lines)


def _format_issue(issue: dict[str, Any]) -> str:
    location = f"workspace={issue['workspace_id']} week={issue['week_id']}"
    domains = f" domains={issue['domain_ids']}" if issue["domain_ids"] else ""
    weeks = f" related_weeks={issue['related_week_ids']}" if issue["related_week_ids"] else ""
    return f"- [{issue['severity']}] {issue['code']} {location}{domains}{weeks}: {issue['message']}"


def _format_repair(repair: dict[str, Any]) -> str:
    affected = f" affected={repair['affected_ids']}" if repair["affected_ids"] else ""
    message = f" ({repair['message']})" if repair["message"] else ""
    return f"- [{repair['status']}] {repair['kind']} week={repair['week_id']}{affected}{message}"
