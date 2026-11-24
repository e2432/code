import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_submission.py PROTOCOL SUBMISSION")
    protocol = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    submission = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    actions = submission.get("actions")
    if not isinstance(actions, list):
        raise SystemExit("actions must be a list")
    valid_pipettes = protocol["pipettes"]
    known = {"stock", "diluent"} | {t["name"] for t in protocol["targets"]}
    for index, action in enumerate(actions):
        if action.get("type") == "transfer":
            if action.get("source") not in known or action.get("dest") not in known:
                raise SystemExit(f"action {index}: unknown container")
            volume = float(action.get("volume_ul", -1))
            pipette = valid_pipettes.get(action.get("pipette"))
            if pipette is None or not (pipette["min_ul"] <= volume <= pipette["max_ul"]):
                raise SystemExit(f"action {index}: invalid pipette volume")
        elif action.get("type") == "mix":
            if action.get("dest") not in known or int(action.get("cycles", 0)) < protocol["min_mix_cycles"]:
                raise SystemExit(f"action {index}: invalid mix")
        else:
            raise SystemExit(f"action {index}: unsupported type")
    print(f"basic validation passed for {len(actions)} actions")


if __name__ == "__main__":
    main()


