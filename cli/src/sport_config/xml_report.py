"""The XML report shared by -c and the Web export button."""
from pathlib import Path
from xml.etree import ElementTree as ET


REPORT_NAME = "sport-config-check-report.xml"


def _tree(result):
    root = ET.Element("sport-config-report", {"target": str(result.target), "generated-at": result.generated_at})
    ET.SubElement(root, "summary", {"error": str(result.error_count), "warning": str(result.warning_count), "info": str(result.info_count)})
    findings = ET.SubElement(root, "findings")
    for finding in result.findings:
        item = ET.SubElement(findings, "finding", {"severity": finding.severity, "rule-id": finding.rule_id, "sheet": finding.sheet, "cell": finding.cell})
        ET.SubElement(item, "value").text = finding.value
        ET.SubElement(item, "message").text = finding.message
        ET.SubElement(item, "impact").text = finding.impact
    return ET.ElementTree(root)


def write_report(result, directory):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise RuntimeError("report directory does not exist: {}".format(directory))
    report = directory / REPORT_NAME
    temporary = directory / (REPORT_NAME + ".tmp")
    _tree(result).write(str(temporary), encoding="utf-8", xml_declaration=True)
    temporary.replace(report)
    return report


def report_bytes(result):
    from io import BytesIO
    output = BytesIO()
    _tree(result).write(output, encoding="utf-8", xml_declaration=True)
    return output.getvalue()
