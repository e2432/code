import json
import sys
from pathlib import Path

def step_matches(step, action):
    if not isinstance(step, dict) or step.get("type") != action.get("type"):
        return False
    for field, expected in step.items():
        if field == "id" or field == "type":
            continue
        actual = action.get(field)
        if field == "volume_ul":
            try:
                if abs(float(actual) - float(expected)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        elif actual != expected:
            return False
    return True

def main():
    if len(sys.argv)!=3: raise SystemExit("usage: check_submission.py PROTOCOL SUBMISSION")
    protocol=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")); submission=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    if not isinstance(submission.get("actions"),list) or not isinstance(submission.get("report"),dict): raise SystemExit("actions and report must be present")
    known={"stock","diluent","blank","standard"}|{t["name"] for t in protocol["targets"]}
    steps={step.get("id"):step for step in protocol.get("steps",[]) if step.get("id")}
    for index,action in enumerate(submission["actions"]):
        kind=action.get("type")
        if kind=="transfer":
            if action.get("step_id") not in steps or not step_matches(steps[action.get("step_id")], action): raise SystemExit(f"action {index}: invalid step_id")
            if action.get("source") not in known or action.get("dest") not in known: raise SystemExit(f"action {index}: unknown container")
            volume=float(action.get("volume_ul",-1)); pipette=protocol["pipettes"].get(action.get("pipette"))
            if action.get("pipette") != "p1000" or not (protocol["pipettes"]["p1000"]["min_ul"]<=volume<=protocol["pipettes"]["p1000"]["max_ul"]): raise SystemExit(f"action {index}: p1000 is required")
        elif kind=="mix":
            if action.get("dest") not in {t["name"] for t in protocol["targets"]} or int(action.get("cycles",0))<protocol["min_mix_cycles"]: raise SystemExit(f"action {index}: invalid mix")
        elif kind=="measure":
            if action.get("target") not in known: raise SystemExit(f"action {index}: invalid measurement target")
        elif kind=="calibrate":
            if action.get("pipette") not in protocol["pipettes"]: raise SystemExit(f"action {index}: invalid calibration pipette")
            spec=protocol.get("calibration",{}).get(action.get("pipette"))
            if spec and float(action.get("reference_volume_ul",-1)) != float(spec["reference_volume_ul"]): raise SystemExit(f"action {index}: invalid calibration reference")
        elif kind in {"observe", "move"}:
            # These actions are used by the simulation to expose visual and
            # motion-layer failures.  They do not change liquid state.
            if not action.get("action_id") or action.get("step_id") not in steps or not step_matches(steps[action.get("step_id")], action):
                raise SystemExit(f"action {index}: observe/move requires a valid step_id and action_id")
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
