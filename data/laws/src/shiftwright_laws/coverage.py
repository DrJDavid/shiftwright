"""Print the state x rule-type coverage table: `uv run python -m shiftwright_laws.coverage`."""
import json

from shiftwright_contracts.models import LawRuleType

from shiftwright_laws.resolver import LAWS_DIR

ABBR = {"weekly_overtime": "wOT", "daily_overtime": "dOT", "meal_break": "meal", "rest_break": "rest",
        "minor_limits": "minor", "minor_prohibited_roles": "minRole", "min_rest_between_shifts": "clopen",
        "predictive_scheduling": "predict", "reporting_time_pay": "report", "minimum_wage": "wage", "tipped_minimum_wage": "tipW"}


def table() -> str:
    cols = [t.value for t in LawRuleType]
    lines = ["| file | " + " | ".join(ABBR[c] for c in cols) + " | notes |",
             "|---|" + "---|" * (len(cols) + 1)]
    files = [LAWS_DIR / "federal.json", *sorted((LAWS_DIR / "states").glob("*.json")),
             *sorted(p for p in (LAWS_DIR / "cities").glob("*.json") if not p.name.startswith("_"))]
    for p in files:
        doc = json.loads(p.read_text())
        counts = {c: 0 for c in cols}
        for r in doc["rules"]:
            counts[r["type"]] += 1
        cells = [str(counts[c]) if counts[c] else "–" for c in cols]
        lines.append(f"| {p.stem} | " + " | ".join(cells) + f" | {len(doc.get('notes', []))} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table())
