import argparse, json, random
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--protocol",required=True); parser.add_argument("--state",required=True); parser.add_argument("--action",required=True); parser.add_argument("--instance-id",default="default"); args=parser.parse_args()
    protocol=json.loads(Path(args.protocol).read_text(encoding="utf-8-sig")); action=json.loads(Path(args.action).read_text(encoding="utf-8-sig")); state_path=Path(args.state)
    instance=next((item for item in protocol.get("instances",[]) if item.get("id")==args.instance_id),None)
    if instance is None: raise SystemExit(f"unknown instance_id: {args.instance_id}")
    seed=instance.get("seed",protocol["simulation"]["seed"]); failure_schedule=instance.get("failure_schedule",protocol["simulation"]["failure_schedule"])
    if state_path.exists(): state=json.loads(state_path.read_text(encoding="utf-8-sig"))
    else:
        stock_volume=instance.get("stock_volume_ul",protocol["stock"]["volume_ul"])
        state={"containers":{"stock":{"volume":stock_volume,"solute":stock_volume*protocol["stock"]["concentration_um"]},"diluent":{"volume":protocol["diluent"]["volume_ul"],"solute":0.0},"blank":{"volume":protocol["blank"]["volume_ul"],"solute":0.0},"standard":{"volume":protocol["standard"]["volume_ul"],"solute":protocol["standard"]["volume_ul"]*protocol["standard"]["concentration_um"]}},"step":0,"failed_ids":[],"measure_index":0,"used_tips":{},"calibration":{},"instance_id":args.instance_id}
        for target in protocol["targets"]: state["containers"][target["name"]]={"volume":0.0,"solute":0.0}
    kind=action.get("type"); feedback={"step":state["step"],"status":"ok"}
    if kind in {"observe", "move"}:
        aid=action.get("action_id",f"action-{state['step']}"); failures={x["action_id"]:x["reason"] for x in failure_schedule}
        if aid in failures and not action.get("retry_of"):
            state["failed_ids"].append(aid); feedback.update({"status":"failed","reason":failures[aid],"retry_required":True})
        elif action.get("retry_of") and action["retry_of"] not in state.get("failed_ids",[]):
            feedback.update({"status":"failed","reason":"invalid_retry_reference"})
        else:
            feedback.update({"status":"ok","operation":kind})
    elif kind=="calibrate":
        pipette=action.get("pipette"); spec=protocol.get("calibration",{}).get(pipette)
        if spec is None: feedback.update({"status":"failed","reason":"unknown_calibration_pipette"})
        else:
            measured=float(action.get("measured_volume_ul",0)); error=abs(measured-spec["reference_volume_ul"]); state["calibration"][pipette]={"error_ul":error}; feedback.update({"pipette":pipette,"calibration_error_ul":error,"status":"ok" if error<=spec["tolerance_ul"] else "failed"})
    elif kind=="transfer":
        aid=action.get("action_id",f"action-{state['step']}"); failures={x["action_id"]:x["reason"] for x in failure_schedule}
        if aid in failures and not action.get("retry_of"):
            state["failed_ids"].append(aid); feedback.update({"status":"failed","reason":failures[aid],"retry_required":True})
        else:
            source,dest=action["source"],action["dest"]; volume=float(action["volume_ul"]); tip_id=action.get("tip_id")
            previous_source=state.setdefault("used_tips",{}).get(tip_id)
            if previous_source is not None and previous_source!=source:
                feedback.update({"status":"failed","reason":"cross_source_tip_reuse","contamination_risk":True})
            elif state["containers"][source]["volume"]+1e-6<volume:
                feedback.update({"status":"failed","reason":"insufficient_source_volume","retry_required":True})
            else:
                state["used_tips"][tip_id]=source; c=state["containers"][source]["solute"]/state["containers"][source]["volume"] if state["containers"][source]["volume"] else 0.0
                state["containers"][source]["volume"]-=volume; state["containers"][source]["solute"]-=volume*c; state["containers"][dest]["volume"]+=volume; state["containers"][dest]["solute"]+=volume*c; feedback["realized_volume_ul"]=volume
    elif kind=="measure":
        target=action["target"]; rng=random.Random(seed); sd=protocol["simulation"].get("measurement_error_sd_ul",1.0); clip=protocol["simulation"].get("measurement_error_clip_sd",3.0)*sd; [rng.gauss(0.0,sd) for _ in range(state["measure_index"])]
        error=max(-clip,min(clip,rng.gauss(0.0,sd))); observed=state["containers"][target]["volume"]+error; state["measure_index"]+=1; feedback.update({"target":target,"measured_volume_ul":observed,"measurement_error_ul":error})
    elif kind=="mix": feedback.update({"mixed_target":action["dest"],"mix_quality":min(1.0,float(action.get("cycles",0))/5.0)})
    else: feedback.update({"status":"invalid","reason":"unsupported_action"})
    state["step"]+=1; state_path.parent.mkdir(parents=True,exist_ok=True); state_path.write_text(json.dumps(state,indent=2),encoding="utf-8"); print(json.dumps(feedback,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
