import json
import os
import random
import statistics
from pathlib import Path

WORKDIR=Path(os.environ.get("AFE_WORKDIR","/work"))
LOGDIR=Path(os.environ.get("AFE_LOG_DIR","/logs/verifier"))
PROTOCOL=WORKDIR/"input/protocol.json"
SUBMISSION=WORKDIR/"output/submission.json"
RESULT=LOGDIR/"afe_result.json"
REWARD=LOGDIR/"reward.json"

def write_result(result):
    RESULT.parent.mkdir(parents=True,exist_ok=True)
    RESULT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    if result.get("status") in {"pending_review","evaluation_error"}:
        if REWARD.exists(): REWARD.unlink()
    else:
        REWARD.write_text(json.dumps({"reward":1 if result.get("status")=="evaluated" and result.get("score")==100 else 0},indent=2),encoding="utf-8")

def fail(code,message):
    write_result({"status":"invalid_submission","score":0,"error":{"code":code,"message":message}})

def main():
    try:
        protocol=json.loads(PROTOCOL.read_text(encoding="utf-8-sig")); submission=json.loads(SUBMISSION.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        fail("missing_output",str(exc)); return
    except Exception as exc:
        fail("invalid_json",str(exc)); return
    actions=submission.get("actions"); report=submission.get("report");
    if not isinstance(actions,list) or not isinstance(report,dict): fail("invalid_submission","actions and report are required"); return
    instance_id=submission.get("instance_id","default")
    instance=next((item for item in protocol.get("instances",[]) if item.get("id")==instance_id),None)
    if instance is None: fail("unknown_instance",f"unknown instance_id: {instance_id}"); return
    sim=dict(protocol["simulation"])
    sim["seed"]=instance.get("seed",sim["seed"])
    sim["failure_schedule"]=instance.get("failure_schedule",sim["failure_schedule"])
    stock_volume=instance.get("stock_volume_ul",protocol["stock"]["volume_ul"])
    containers={"stock":{"volume":stock_volume,"solute":stock_volume*protocol["stock"]["concentration_um"]},"diluent":{"volume":protocol["diluent"]["volume_ul"],"solute":0.0},"blank":{"volume":protocol["blank"]["volume_ul"],"solute":0.0}}
    targets=protocol["targets"]; names=[t["name"] for t in targets]; target_by_name={t["name"]:t for t in targets}
    for t in targets: containers[t["name"]]={"volume":0.0,"solute":0.0}
    failure_by_id={x["action_id"]:x["reason"] for x in sim["failure_schedule"]}; rng=random.Random(sim["seed"])
    used_tips={}; incoming={n:[] for n in names}; mix_quality={n:0.0 for n in names}; last_mix={n:-1 for n in names}; source_uses={n:[] for n in names}; measurements={}; events=[]; contamination=[]; penalties=[]; failed_ids=set(); calibration={}; finished=False; paused=False; measure_count=0; hard_error=None
    for index,action in enumerate(actions):
        kind=action.get("type")
        if kind=="calibrate":
            pipette=action.get("pipette"); spec=protocol["calibration"].get(pipette)
            if spec is None: penalties.append("unknown_calibration_pipette"); continue
            measured=float(action.get("measured_volume_ul",0)); error=abs(measured-spec["reference_volume_ul"])
            calibration[pipette]={"reference_volume_ul":spec["reference_volume_ul"],"measured_volume_ul":measured,"error_ul":error}
            if error>spec["tolerance_ul"]: penalties.append("calibration")
        elif kind=="transfer":
            source,dest=action.get("source"),action.get("dest")
            try: volume=float(action["volume_ul"])
            except Exception: hard_error=f"action {index} invalid volume"; break
            if source not in containers or dest not in containers or source==dest or volume<=0: hard_error=f"action {index} invalid containers"; break
            pipette=protocol["pipettes"].get(action.get("pipette"))
            if pipette is None or not pipette["min_ul"]<=volume<=pipette["max_ul"]: hard_error=f"action {index} invalid pipette"; break
            tip=action.get("tip_id"); previous=used_tips.get(tip)
            if previous is not None and previous!=source:
                contamination.append({"action_index":index,"tip_id":tip,"previous_source":previous,"source":source,"carryover_volume_ul":protocol["carryover_volume_ul"]})
                penalties.append("contamination")
                containers[dest]["solute"]+=containers[previous]["solute"]/containers[previous]["volume"]*protocol["carryover_volume_ul"] if containers[previous]["volume"] else 0.0
            used_tips[tip]=source; aid=action.get("action_id",f"action-{index}")
            if aid in failure_by_id and not action.get("retry_of"):
                failed_ids.add(aid); events.append({"action_id":aid,"status":"failed","reason":failure_by_id[aid]}); continue
            if action.get("retry_of") and action["retry_of"] not in failed_ids: penalties.append("invalid_retry_reference")
            if containers[source]["volume"]+1e-6<volume:
                events.append({"action_id":aid,"status":"failed","reason":"insufficient_source_volume"}); penalties.append("insufficient_volume"); continue
            concentration=containers[source]["solute"]/containers[source]["volume"] if containers[source]["volume"] else 0.0
            containers[source]["volume"]-=volume; containers[source]["solute"]-=volume*concentration; containers[dest]["volume"]+=volume; containers[dest]["solute"]+=volume*concentration
            if dest in incoming: incoming[dest].append((index,source,volume))
            if source in source_uses: source_uses[source].append(index)
        elif kind=="mix":
            dest=action.get("dest"); cycles=int(action.get("cycles",0)); volume=float(action.get("volume_ul",0))
            if dest not in target_by_name or volume<=0 or volume>containers[dest]["volume"]+1e-6: hard_error=f"action {index} invalid mix"; break
            mix_quality[dest]=min(1.0,max(mix_quality[dest],cycles/5.0)); last_mix[dest]=index
            if cycles<protocol["min_mix_cycles"]: penalties.append("insufficient_mixing")
        elif kind=="measure":
            target=action.get("target")
            if target not in containers: hard_error=f"action {index} invalid measure target"; break
            error=rng.uniform(-sim["measurement_error_range_ul"],sim["measurement_error_range_ul"]); observed=containers[target]["volume"]+error
            measurements.setdefault(target,[]).append({"measurement_id":action.get("measurement_id",f"m-{measure_count}"),"measured_volume_ul":observed,"error_ul":error}); measure_count+=1
        elif kind=="pause":
            paused=True; events.append({"status":"paused","reason":action.get("reason"),"last_safe_checkpoint":action.get("last_safe_checkpoint")})
        elif kind=="finish": finished=True
        else: hard_error=f"action {index} unsupported type"; break
    if hard_error: fail("invalid_action",hard_error); return
    for n in names:
        if measurements.get(n) is None or len(measurements[n])<protocol["required_measurement_repeats"]: penalties.append("repeat_measurement")
        if mix_quality[n]<protocol["mix_quality_minimum"]: penalties.append("mix_quality")
        if source_uses[n] and last_mix[n] < source_uses[n][0]: pass
        elif source_uses[n]: penalties.append("sample_used_before_mixing")
        incoming_sources=sorted(x[1] for x in incoming[n]); expected=sorted([target_by_name[n]["sample_source"],"diluent"])
        if len(incoming[n])!=2 or incoming_sources!=expected: penalties.append("protocol_transfer")
    if len(measurements.get("blank",[]))<protocol["required_measurement_repeats"]: penalties.append("blank_control")
    if "p1000" not in calibration: penalties.append("missing_calibration")
    if failed_ids and not any(e.get("action_id") in failed_ids and e.get("status")=="failed" for e in events): penalties.append("failure_record")
    if not finished: penalties.append("missing_finish")
    if paused: penalties.append("unresolved_pause")
    run_state=None
    try:
        progress=json.loads((WORKDIR/"output/progress.json").read_text(encoding="utf-8-sig"))
        run_state=json.loads((WORKDIR/"output/run_state.json").read_text(encoding="utf-8-sig"))
        if run_state.get("status")!="completed": penalties.append("run_state_not_completed")
        if any(step.get("status")!="completed" for step in progress.get("steps",[])): penalties.append("progress_incomplete")
    except FileNotFoundError:
        penalties.append("missing_state_artifacts")
    except Exception:
        penalties.append("invalid_state_artifacts")
    if paused and run_state and run_state.get("status")=="paused":
        write_result({"status":"pending_review","score":None,"raw":{"events":events,"penalties":penalties,"action_count":len(actions)},"notes":"Agent paused after an unrecoverable simulation state and saved a checkpoint."})
        return
    report_samples={x.get("name"):x for x in report.get("samples",[]) if isinstance(x,dict)}; metrics={}
    for t in targets:
        n=t["name"]; values=[x["measured_volume_ul"] for x in measurements.get(n,[])]; mean=statistics.mean(values) if values else 0.0; sd=statistics.pstdev(values) if len(values)>1 else 0.0; volume_error=mean-t["final_volume_ul"]; est=containers[n]["solute"]/mean if mean else 0.0; conc_err=abs(est-t["concentration_um"])/t["concentration_um"]
        metrics[n]={"measurements_ul":[round(x,6) for x in values],"mean_volume_ul":round(mean,6),"volume_error_ul":round(volume_error,6),"volume_sd_ul":round(sd,6),"estimated_concentration_um":round(est,6),"concentration_error_fraction":round(conc_err,6)}
        if abs(volume_error)>protocol["transfer_tolerance_ul"]: penalties.append("final_volume")
        if conc_err>protocol["concentration_tolerance_fraction"]: penalties.append("target_concentration")
        item=report_samples.get(n)
        if item is None: penalties.append("missing_quality_record"); continue
        if abs(float(item.get("mean_volume_ul",999999))-mean)>0.01 or abs(float(item.get("volume_error_ul",999999))-volume_error)>0.01 or abs(float(item.get("estimated_concentration_um",999999))-est)>0.01 or abs(float(item.get("concentration_error_fraction",999999))-conc_err)>0.0001: penalties.append("quality_record")
    if not isinstance(report.get("blank"),dict): penalties.append("blank_report")
    score=max(0,100-20*len(penalties)); write_result({"status":"evaluated","score":score,"raw":{"metrics":metrics,"events":events,"contamination":contamination,"calibration":calibration,"penalties":penalties,"action_count":len(actions)}})

if __name__=="__main__": main()
