import argparse, json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--protocol",required=True); parser.add_argument("--state",required=True); parser.add_argument("--action",required=True); args=parser.parse_args()
    protocol=json.loads(Path(args.protocol).read_text(encoding="utf-8-sig")); action=json.loads(Path(args.action).read_text(encoding="utf-8-sig")); state_path=Path(args.state)
    if state_path.exists(): state=json.loads(state_path.read_text(encoding="utf-8-sig"))
    else:
        state={"containers":{"stock":{"volume":protocol["stock"]["volume_ul"],"solute":protocol["stock"]["volume_ul"]*protocol["stock"]["concentration_um"]},"diluent":{"volume":protocol["diluent"]["volume_ul"],"solute":0.0}},"step":0,"failed_ids":[],"measure_index":0}
        for target in protocol["targets"]: state["containers"][target["name"]]={"volume":0.0,"solute":0.0}
    kind=action.get("type"); feedback={"step":state["step"],"status":"ok"}
    if kind=="transfer":
        aid=action.get("action_id",f"action-{state['step']}"); failures={x["action_id"]:x["reason"] for x in protocol["simulation"]["failure_schedule"]}
        if aid in failures and not action.get("retry_of"):
            state["failed_ids"].append(aid); feedback.update({"status":"failed","reason":failures[aid],"retry_required":True})
        else:
            source,dest=action["source"],action["dest"]; volume=float(action["volume_ul"]); c=state["containers"][source]["solute"]/state["containers"][source]["volume"] if state["containers"][source]["volume"] else 0.0
            state["containers"][source]["volume"]-=volume; state["containers"][source]["solute"]-=volume*c; state["containers"][dest]["volume"]+=volume; state["containers"][dest]["solute"]+=volume*c; feedback["realized_volume_ul"]=volume
    elif kind=="measure":
        target=action["target"]; pattern=protocol["simulation"]["measurement_error_pattern_ul"]; observed=state["containers"][target]["volume"]+pattern[state["measure_index"]%len(pattern)]; state["measure_index"]+=1; feedback.update({"target":target,"measured_volume_ul":observed,"measurement_error_ul":pattern[(state["measure_index"]-1)%len(pattern)]})
    elif kind=="mix": feedback["mixed_target"]=action["dest"]
    else: feedback.update({"status":"invalid","reason":"unsupported_action"})
    state["step"]+=1; state_path.parent.mkdir(parents=True,exist_ok=True); state_path.write_text(json.dumps(state,indent=2),encoding="utf-8"); print(json.dumps(feedback,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
