import json
import os
from pathlib import Path

WORKDIR = Path(os.environ.get("AFE_WORKDIR", "/work"))
LOGDIR = Path(os.environ.get("AFE_LOG_DIR", "/logs/verifier"))
PROTOCOL = WORKDIR / "input/protocol.json"
SUBMISSION = WORKDIR / "output/submission.json"
RESULT = LOGDIR / "afe_result.json"
REWARD = LOGDIR / "reward.json"

def write_result(result):
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    REWARD.write_text(json.dumps({"reward": 1 if result.get("status") == "evaluated" and result.get("score") == 100 else 0}, indent=2), encoding="utf-8")

def fail(code, message):
    write_result({"status":"invalid_submission","score":0,"error":{"code":code,"message":message}})

def main():
    try:
        protocol=json.loads(PROTOCOL.read_text(encoding="utf-8-sig"))
        submission=json.loads(SUBMISSION.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        fail("missing_output", str(exc)); return
    except Exception as exc:
        fail("invalid_json", str(exc)); return
    actions=submission.get("actions")
    report=submission.get("report")
    if not isinstance(actions,list) or not isinstance(report,dict):
        fail("invalid_submission", "actions and report are required"); return
    containers={"stock":{"volume":protocol["stock"]["volume_ul"],"solute":protocol["stock"]["volume_ul"]*protocol["stock"]["concentration_um"]},"diluent":{"volume":protocol["diluent"]["volume_ul"],"solute":0.0}}
    targets=protocol["targets"]
    target_names=[t["name"] for t in targets]
    target_by_name={t["name"]:t for t in targets}
    for t in targets: containers[t["name"]]={"volume":0.0,"solute":0.0}
    simulation=protocol["simulation"]
    failure_by_id={item["action_id"]:item["reason"] for item in simulation["failure_schedule"]}
    failed_ids=set(); used_tips={}; incoming={name:[] for name in target_names}; mix_cycles={name:0 for name in target_names}; last_mix={name:-1 for name in target_names}; source_uses={name:[] for name in target_names}; measurements={}; events=[]; penalties=[]; hard_error=None; measure_index=0
    for index,action in enumerate(actions):
        kind=action.get("type")
        if kind=="transfer":
            source,dest=action.get("source"),action.get("dest")
            try: volume=float(action["volume_ul"])
            except Exception: hard_error=f"action {index} has invalid volume"; break
            if source not in containers or dest not in containers or source==dest or volume<=0: hard_error=f"action {index} has invalid containers or volume"; break
            pipette=protocol["pipettes"].get(action.get("pipette"))
            if pipette is None or volume<pipette["min_ul"] or volume>pipette["max_ul"]: hard_error=f"action {index} violates pipette range"; break
            tip_id=action.get("tip_id")
            if not isinstance(tip_id,str) or not tip_id: hard_error=f"action {index} has no tip_id"; break
            previous=used_tips.get(tip_id)
            if previous is not None and previous!=source: penalties.append("cross_source_tip_reuse")
            used_tips[tip_id]=source
            action_id=action.get("action_id",f"action-{index}")
            if action_id in failure_by_id and not action.get("retry_of"):
                failed_ids.add(action_id); events.append({"action_id":action_id,"status":"failed","reason":failure_by_id[action_id]}); continue
            if action.get("retry_of") and action["retry_of"] not in failed_ids: penalties.append("invalid_retry_reference")
            if containers[source]["volume"]+1e-6<volume: hard_error=f"action {index} aspirates more than available volume"; break
            concentration=containers[source]["solute"]/containers[source]["volume"] if containers[source]["volume"] else 0.0
            containers[source]["volume"]-=volume; containers[source]["solute"]-=volume*concentration
            containers[dest]["volume"]+=volume; containers[dest]["solute"]+=volume*concentration
            if dest in incoming: incoming[dest].append((index,source,volume))
            if source in source_uses: source_uses[source].append(index)
        elif kind=="mix":
            dest=action.get("dest")
            if dest not in target_by_name: hard_error=f"action {index} mixes invalid target"; break
            try: volume=float(action["volume_ul"]); cycles=int(action["cycles"])
            except Exception: hard_error=f"action {index} has invalid mix"; break
            if volume<=0 or volume>containers[dest]["volume"]+1e-6: hard_error=f"action {index} mixes more than current volume"; break
            mix_cycles[dest]+=max(cycles,0); last_mix[dest]=index
        elif kind=="measure":
            target=action.get("target")
            if target not in target_by_name: hard_error=f"action {index} measures invalid target"; break
            pattern=simulation["measurement_error_pattern_ul"]
            observed=containers[target]["volume"]+pattern[measure_index%len(pattern)]
            measurements[target]={"measurement_id":action.get("measurement_id",f"measurement-{measure_index}"),"measured_volume_ul":observed}
            measure_index+=1
        else:
            hard_error=f"action {index} has unsupported type"; break
    if hard_error: fail("invalid_action",hard_error); return
    if len(failed_ids)!=len(simulation["failure_schedule"]): penalties.append("failure_not_exercised")
    report_samples={item.get("name"):item for item in report.get("samples",[]) if isinstance(item,dict)}
    report_events={(item.get("action_id"),item.get("status")):item for item in report.get("events",[]) if isinstance(item,dict)}
    quality_flags=set(report.get("quality_flags",[]))
    if "measurement_uncertainty" not in quality_flags: penalties.append("missing_measurement_quality_flag")
    if failed_ids and ("retry_performed" not in quality_flags or not any((aid,"failed") in report_events for aid in failed_ids)): penalties.append("missing_failure_record")
    if "no_cross_source_tip_reuse" not in quality_flags or "cross_source_tip_reuse" in penalties: penalties.append("contamination_control")
    metrics={}
    for target in targets:
        name=target["name"]; volume=containers[name]["volume"]; concentration=containers[name]["solute"]/volume if volume else 0.0
        volume_error=abs(volume-target["final_volume_ul"]); concentration_error=abs(concentration-target["concentration_um"])/target["concentration_um"]
        metrics[name]={"final_volume_ul":round(volume,6),"volume_error_ul":round(volume_error,6),"concentration_um":round(concentration,6),"concentration_error_fraction":round(concentration_error,6)}
        if volume_error>protocol["transfer_tolerance_ul"]: penalties.append("final_volume")
        if concentration_error>protocol["concentration_tolerance_fraction"]: penalties.append("target_concentration")
        if mix_cycles[name]<protocol["min_mix_cycles"] or last_mix[name]<=max([x[0] for x in incoming[name]],default=-1): penalties.append("mixing")
        expected=sorted([target["sample_source"],"diluent"]); actual=sorted([x[1] for x in incoming[name]])
        if len(incoming[name])!=2 or actual!=expected or any(abs(x[2]-500.0)>protocol["transfer_tolerance_ul"] for x in incoming[name]): penalties.append("protocol_transfer")
        if source_uses[name] and last_mix[name] < source_uses[name][0]: pass
        elif source_uses[name]: penalties.append("sample_used_before_mixing")
        item=report_samples.get(name); measured=measurements.get(name)
        if item is None or measured is None: penalties.append("missing_quality_record"); continue
        if abs(float(item.get("measured_volume_ul",999999))-measured["measured_volume_ul"])>0.01: penalties.append("wrong_measurement_record")
        if abs(float(item.get("volume_error_ul",999999))-(measured["measured_volume_ul"]-target["final_volume_ul"]))>0.01: penalties.append("wrong_volume_error_record")
        if abs(float(item.get("estimated_concentration_um",999999))-concentration)>target["concentration_um"]*protocol["concentration_tolerance_fraction"]: penalties.append("wrong_concentration_record")
        claimed_error=abs(float(item.get("estimated_concentration_um",0))-target["concentration_um"])/target["concentration_um"]
        if abs(float(item.get("concentration_error_fraction",999999))-claimed_error)>0.0001: penalties.append("wrong_concentration_error_record")
    score=max(0,100-20*len(penalties)); write_result({"status":"evaluated","score":score,"raw":{"metrics":metrics,"events":events,"penalties":penalties,"action_count":len(actions)}})

if __name__=="__main__": main()
