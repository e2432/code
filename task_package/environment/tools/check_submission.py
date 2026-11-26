import json
import sys
from pathlib import Path

def main():
    if len(sys.argv)!=3: raise SystemExit("usage: check_submission.py PROTOCOL SUBMISSION")
    protocol=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")); submission=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    if not isinstance(submission.get("actions"),list) or not isinstance(submission.get("report"),dict): raise SystemExit("actions and report must be present")
    known={"stock","diluent","blank","standard"}|{t["name"] for t in protocol["targets"]}
    for index,action in enumerate(submission["actions"]):
        kind=action.get("type")
        if kind=="transfer":
            if action.get("source") not in known or action.get("dest") not in known: raise SystemExit(f"action {index}: unknown container")
            volume=float(action.get("volume_ul",-1)); pipette=protocol["pipettes"].get(action.get("pipette"))
            if action.get("pipette") != "p1000" or not (protocol["pipettes"]["p1000"]["min_ul"]<=volume<=protocol["pipettes"]["p1000"]["max_ul"]): raise SystemExit(f"action {index}: p1000 is required")
        elif kind=="mix":
            if action.get("dest") not in known or int(action.get("cycles",0))<protocol["min_mix_cycles"]: raise SystemExit(f"action {index}: invalid mix")
        elif kind=="measure":
            if action.get("target") not in known: raise SystemExit(f"action {index}: invalid measurement target")
        elif kind=="calibrate":
            if action.get("pipette") not in protocol["pipettes"]: raise SystemExit(f"action {index}: invalid calibration pipette")
        elif kind in {"pause", "finish"}:
            pass
        else: raise SystemExit(f"action {index}: unsupported type")
    names={item.get("name") for item in submission["report"].get("samples",[]) if isinstance(item,dict)}
    expected={t["name"] for t in protocol["targets"]}
    if names!=expected or not isinstance(submission["report"].get("standard"),dict) or not isinstance(submission["report"].get("blank"),dict): raise SystemExit("report must cover target tubes, standard, and blank")
    if any(len(item.get("measurements_ul", [])) < protocol["required_measurement_repeats"] for item in submission["report"]["samples"]): raise SystemExit("each target requires three measurements")
    if len(submission["report"]["standard"].get("measurements_ul", [])) < protocol["required_measurement_repeats"]: raise SystemExit("standard requires three measurements")
    if len(submission["report"]["blank"].get("measurements_ul", [])) < protocol["required_measurement_repeats"]: raise SystemExit("blank requires three measurements")
    print(f"basic validation passed for {len(submission['actions'])} actions")
if __name__=="__main__": main()
