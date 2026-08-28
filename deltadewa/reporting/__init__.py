"""Reporting package for DeltaDewa."""

from deltadewa.reporting.audit import PortfolioChangeTracker, PortfolioLogger
from deltadewa.reporting.console import ConsoleReporter
from deltadewa.reporting.program_report import (
    HTML_STYLE,
    CostSection,
    IpsComplianceRow,
    IpsComplianceSection,
    ProgramReport,
    ProtectionSection,
    build_cost_section,
    build_ips_compliance,
    build_program_report,
    build_protection_section,
    expired_legs_caveat,
    render_html,
    render_html_body,
    render_markdown,
)

__all__ = [
    "HTML_STYLE",
    "ConsoleReporter",
    "CostSection",
    "IpsComplianceRow",
    "IpsComplianceSection",
    "PortfolioChangeTracker",
    "PortfolioLogger",
    "ProgramReport",
    "ProtectionSection",
    "build_cost_section",
    "build_ips_compliance",
    "build_program_report",
    "build_protection_section",
    "expired_legs_caveat",
    "render_html",
    "render_html_body",
    "render_markdown",
]
