"""Export a data-only plan for an application or simulator; never controls hardware."""
import argparse
import json
from pathlib import Path

from expressive_arm.trajectory import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expression")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = load(args.expression)
    plan = {
        "expression": args.expression,
        "time_unit": "seconds",
        "body_unit": "calibrated_degrees",
        "gripper_unit": "opening_percent",
        "frames": [{"t": row["t"], "target": row["action"]} for row in rows],
    }
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(rows)} targets to {args.output}; no hardware connected.")


if __name__ == "__main__":
    main()
