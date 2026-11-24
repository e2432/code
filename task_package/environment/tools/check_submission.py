import json
import sys
from pathlib import Path

def main():
    if len(sys.argv)!=3: raise SystemExit("usage: check_submission.py PROTOCOL SUBMISSION")
    protocol=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")); submission=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    if not isinstance(submission.get("actions"),list) or not isinstance(submission.get("report"),dict): raise SystemExit("actions and report must be present")
    known={"stock","diluent"}|{t["name"] for t in protocol["targets"]}
    for index,action in enumerate(submission["actions"]):
        kind=action.get("type")
        if kind=="transfer":
            if action.get("source") not in known or action.get("dest") not in known: raise SystemExit(f"action {index}: unknown container")
            volume=float(action.get("volume_ul",-1)); pipette=protocol["pipettes"].get(action.get("pipette"))
            if pipette is None or not (pipette["min_ul"]<=volume<=pipette["max_ul"]): raise SystemExit(f"action {index}: invalid pipette volume")
        elif kind=="mix":
            if action.get("dest") not in known or int(action.get("cycles",0))<protocol["min_mix_cycles"]: raise SystemExit(f"action {index}: invalid mix")
        elif kind=="measure":
            if action.get("target") not in known: raise SystemExit(f"action {index}: invalid measurement target")
        else: raise SystemExit(f"action {index}: unsupported type")
    names={item.get("name") for item in submission["report"].get("samples",[]) if isinstance(item,dict)}
    expected={t["name"] for t in protocol["targets"]}
    if names!=expected: raise SystemExit("report.samples must cover all target tubes")
    print(f"basic validation passed for {len(submission['actions'])} actions")
if __name__=="__main__": main()
