"""Single check facade used by the CLI, Web page, and edit precondition."""
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from . import xlsx_contract, xlsx_schema
from .xlsx_schema import RULES_PATH


@dataclass(frozen=True)
class Finding:
    severity: str
    rule_id: str
    sheet: str
    cell: str
    value: str
    message: str
    impact: str


@dataclass(frozen=True)
class CheckResult:
    target: str
    generated_at: str
    findings: tuple

    @property
    def error_count(self):
        return sum(item.severity == "error" for item in self.findings)

    @property
    def warning_count(self):
        return sum(item.severity == "warning" for item in self.findings)

    @property
    def info_count(self):
        return sum(item.severity == "info" for item in self.findings)


def _rules():
    with RULES_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _severity(value):
    return str(value).lower()


def check_file(xlsx_path):
    rules = _rules()
    impacts = rules.get("contract_rules", {})
    items = []
    for item in xlsx_schema.check_xlsx(xlsx_path):
        items.append(Finding(_severity(item.severity), item.rule_id, "-", "-", "", item.message, "workbook schema"))
    for item in xlsx_contract.check_file(str(xlsx_path)):
        spec = impacts[item.rule_id]
        items.append(Finding(_severity(item.severity), item.rule_id, item.sheet, item.cell, item.value, item.message, spec.get("impact", "generator contract")))
    unique = {(item.severity, item.rule_id, item.sheet, item.cell, item.message): item for item in items}
    ordered = tuple(sorted(unique.values(), key=lambda item: (item.severity, item.rule_id, item.sheet, item.cell, item.message)))
    return CheckResult(str(xlsx_path), datetime.now(timezone.utc).isoformat(), ordered)


def check_target(target):
    return check_file(target.xlsx)
