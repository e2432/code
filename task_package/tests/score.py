import json
import os
import random
import statistics
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
    if result.get("status") in {"pending_review", "evaluation_error"}:
        if REWARD.exists():
            REWARD.unlink()
    else:
        REWARD.write_text(json.dumps({"reward": int(result.get("status") == "evaluated" and result.get("score") == 100)}, indent=2), encoding="utf-8")


def fail(code, message):
    write_result({"status": "invalid_submission", "score": 0, "error": {"code": code, "message": message}})


def measurement_error(rng, simulation):
    if simulation.get("measurement_error_distribution", "normal") == "normal":
        sd = simulation.get("measurement_error_sd_ul", 1.0)
        clip = simulation.get("measurement_error_clip_sd", 3.0) * sd
        return max(-clip, min(clip, rng.gauss(0.0, sd)))
    span = simulation.get("measurement_error_range_ul", 1.0)
    return rng.uniform(-span, span)


def main():
    try:
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8-sig"))
        submission = json.loads(SUBMISSION.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        fail("missing_output", str(exc))
        return
    except Exception as exc:
        fail("invalid_json", str(exc))
        return

    actions = submission.get("actions")
    report = submission.get("report")
    if not isinstance(actions, list) or not isinstance(report, dict):
        fail("invalid_submission", "actions and report are required")
        return

    instance_id = submission.get("instance_id", "default")
    instance = next((item for item in protocol.get("instances", []) if item.get("id") == instance_id), None)
    if instance is None:
        fail("unknown_instance", f"unknown instance_id: {instance_id}")
        return

    simulation = dict(protocol["simulation"])
    simulation["seed"] = instance.get("seed", simulation["seed"])
    simulation["failure_schedule"] = instance.get("failure_schedule", simulation["failure_schedule"])
    failure_by_id = {item["action_id"]: item["reason"] for item in simulation["failure_schedule"]}
    rng = random.Random(simulation["seed"])
    stock_volume = instance.get("stock_volume_ul", protocol["stock"]["volume_ul"])
    containers = {
        "stock": {"volume": stock_volume, "solute": stock_volume * protocol["stock"]["concentration_um"]},
        "diluent": {"volume": protocol["diluent"]["volume_ul"], "solute": 0.0},
        "blank": {"volume": protocol["blank"]["volume_ul"], "solute": 0.0},
        "standard": {"volume": protocol["standard"]["volume_ul"], "solute": protocol["standard"]["volume_ul"] * protocol["standard"]["concentration_um"]},
    }
    targets = protocol["targets"]
    names = [target["name"] for target in targets]
    target_by_name = {target["name"]: target for target in targets}
    for target in targets:
        containers[target["name"]] = {"volume": 0.0, "solute": 0.0}

    used_tips = {}
    incoming = {name: [] for name in names}
    mix_quality = {name: 0.0 for name in names}
    last_mix = {name: -1 for name in names}
    source_uses = {name: [] for name in names}
    measurements = {}
    events = []
    contamination = []
    penalties = []
    failed_ids = set()
    calibration = {}
    finished = False
    paused = False
    hard_error = None
    measure_index = 0

    for index, action in enumerate(actions):
        kind = action.get("type")
        action_id = action.get("action_id", f"action-{index}")
        if kind == "calibrate":
            pipette = action.get("pipette")
            spec = protocol["calibration"].get(pipette)
            if spec is None:
                penalties.append("unknown_calibration_pipette")
                continue
            measured = float(action.get("measured_volume_ul", 0.0))
            error = abs(measured - spec["reference_volume_ul"])
            calibration[pipette] = {"reference_volume_ul": spec["reference_volume_ul"], "measured_volume_ul": measured, "error_ul": error}
            if error > spec["tolerance_ul"]:
                penalties.append("calibration")
            continue
        if kind in {"observe", "move"}:
            if action_id in failure_by_id and not action.get("retry_of"):
                failed_ids.add(action_id)
                events.append({"action_id": action_id, "status": "failed", "reason": failure_by_id[action_id]})
            elif action.get("retry_of") and action["retry_of"] not in failed_ids:
                penalties.append("invalid_retry_reference")
            continue
        if kind == "transfer":
            source, dest = action.get("source"), action.get("dest")
            try:
                volume = float(action["volume_ul"])
            except Exception:
                hard_error = f"action {index} has invalid volume"
                break
            if source not in containers or dest not in containers or source == dest or volume <= 0:
                hard_error = f"action {index} has invalid containers or volume"
                break
            if action.get("pipette") != "p1000":
                hard_error = f"action {index} must use p1000"
                break
            spec = protocol["pipettes"]["p1000"]
            if volume < spec["min_ul"] or volume > spec["max_ul"]:
                hard_error = f"action {index} violates p1000 range"
                break
            tip_id = action.get("tip_id")
            previous_source = used_tips.get(tip_id)
            if previous_source is not None and previous_source != source:
                contamination.append({"action_index": index, "tip_id": tip_id, "previous_source": previous_source, "source": source, "carryover_volume_ul": protocol["carryover_volume_ul"]})
                penalties.append("contamination")
            used_tips[tip_id] = source
            if action_id in failure_by_id and not action.get("retry_of"):
                failed_ids.add(action_id)
                events.append({"action_id": action_id, "status": "failed", "reason": failure_by_id[action_id]})
                continue
            if action.get("retry_of") and action["retry_of"] not in failed_ids:
                penalties.append("invalid_retry_reference")
            if containers[source]["volume"] + 1e-6 < volume:
                events.append({"action_id": action_id, "status": "failed", "reason": "insufficient_source_volume"})
                penalties.append("insufficient_volume")
                continue
            concentration = containers[source]["solute"] / containers[source]["volume"] if containers[source]["volume"] else 0.0
            containers[source]["volume"] -= volume
            containers[source]["solute"] -= volume * concentration
            containers[dest]["volume"] += volume
            containers[dest]["solute"] += volume * concentration
            if dest in incoming:
                incoming[dest].append((index, source, volume))
            if source in source_uses:
                source_uses[source].append(index)
            continue
        if kind == "mix":
            dest = action.get("dest")
            cycles = int(action.get("cycles", 0))
            volume = float(action.get("volume_ul", 0.0))
            if dest not in target_by_name or volume <= 0 or volume > containers[dest]["volume"] + 1e-6:
                hard_error = f"action {index} has invalid mix"
                break
            mix_quality[dest] = min(1.0, max(mix_quality[dest], cycles / 5.0))
            last_mix[dest] = index
            if cycles < protocol["min_mix_cycles"]:
                penalties.append("insufficient_mixing")
            continue
        if kind == "measure":
            target = action.get("target")
            if target not in containers:
                hard_error = f"action {index} has invalid measure target"
                break
            error = measurement_error(rng, simulation)
            observed = containers[target]["volume"] + error
            measurements.setdefault(target, []).append({"measurement_id": action.get("measurement_id", f"m-{measure_index}"), "measured_volume_ul": observed, "error_ul": error})
            measure_index += 1
            continue
        if kind == "pause":
            paused = True
            events.append({"status": "paused", "reason": action.get("reason"), "last_safe_checkpoint": action.get("last_safe_checkpoint")})
            continue
        if kind == "finish":
            finished = True
            continue
        hard_error = f"action {index} has unsupported type"
        break

    if hard_error:
        fail("invalid_action", hard_error)
        return
    for name in names:
        if len(measurements.get(name, [])) < protocol["required_measurement_repeats"]:
            penalties.append("repeat_measurement")
        if mix_quality[name] < protocol["mix_quality_minimum"]:
            penalties.append("mix_quality")
        if source_uses[name] and last_mix[name] < source_uses[name][0]:
            pass
        elif source_uses[name]:
            penalties.append("sample_used_before_mixing")
        expected_sources = sorted([target_by_name[name]["sample_source"], "diluent"])
        actual_sources = sorted(item[1] for item in incoming[name])
        if len(incoming[name]) != 2 or actual_sources != expected_sources:
            penalties.append("protocol_transfer")
    if len(measurements.get("blank", [])) < protocol["required_measurement_repeats"]:
        penalties.append("blank_control")
    if len(measurements.get("standard", [])) < protocol["required_measurement_repeats"]:
        penalties.append("standard_control")
    if "p1000" not in calibration:
        penalties.append("missing_calibration")
    if failed_ids and not any(event.get("action_id") in failed_ids and event.get("status") == "failed" for event in events):
        penalties.append("failure_record")
    if not finished:
        penalties.append("missing_finish")
    if paused:
        penalties.append("unresolved_pause")
    run_state = None
    try:
        progress = json.loads((WORKDIR / "output/progress.json").read_text(encoding="utf-8-sig"))
        run_state = json.loads((WORKDIR / "output/run_state.json").read_text(encoding="utf-8-sig"))
        if run_state.get("status") != "completed":
            penalties.append("run_state_not_completed")
        if any(step.get("status") != "completed" for step in progress.get("steps", [])):
            penalties.append("progress_incomplete")
    except FileNotFoundError:
        penalties.append("missing_state_artifacts")
    except Exception:
        penalties.append("invalid_state_artifacts")
    if paused and run_state and run_state.get("status") == "paused":
        write_result({"status": "pending_review", "score": None, "raw": {"events": events, "penalties": penalties, "action_count": len(actions)}, "notes": "Agent paused after an unrecoverable simulation state and saved a checkpoint."})
        return
    report_samples = {item.get("name"): item for item in report.get("samples", []) if isinstance(item, dict)}
    metrics = {}
    concentration_errors = []
    volume_errors = []
    quality_penalties = []
    for target in targets:
        name = target["name"]
        values = [item["measured_volume_ul"] for item in measurements.get(name, [])]
        mean = statistics.mean(values) if values else 0.0
        sd = statistics.pstdev(values) if len(values) > 1 else 0.0
        true_concentration = containers[name]["solute"] / containers[name]["volume"] if containers[name]["volume"] else 0.0
        estimated_concentration = containers[name]["solute"] / mean if mean else 0.0
        concentration_error = abs(estimated_concentration - target["concentration_um"]) / target["concentration_um"]
        volume_error = mean - target["final_volume_ul"]
        concentration_errors.append(concentration_error)
        volume_errors.append(abs(volume_error))
        metrics[name] = {"measurements_ul": [round(value, 6) for value in values], "mean_volume_ul": round(mean, 6), "volume_error_ul": round(volume_error, 6), "volume_sd_ul": round(sd, 6), "estimated_concentration_um": round(estimated_concentration, 6), "concentration_error_fraction": round(concentration_error, 6), "true_concentration_um": round(true_concentration, 6)}
        if concentration_error > protocol["concentration_tolerance_fraction"]:
            penalties.append("target_concentration")
        if abs(volume_error) > protocol["transfer_tolerance_ul"]:
            penalties.append("volume_auxiliary")
        item = report_samples.get(name)
        if item is None:
            quality_penalties.append("missing_quality_record")
            continue
        if abs(float(item.get("mean_volume_ul", 999999)) - mean) > 0.01 or abs(float(item.get("volume_error_ul", 999999)) - volume_error) > 0.01 or abs(float(item.get("estimated_concentration_um", 999999)) - estimated_concentration) > 0.01 or abs(float(item.get("concentration_error_fraction", 999999)) - concentration_error) > 0.0001:
            quality_penalties.append("quality_record")
    if not isinstance(report.get("standard"), dict):
        quality_penalties.append("standard_report")
    if not isinstance(report.get("blank"), dict):
        quality_penalties.append("blank_report")
    penalties.extend(quality_penalties)
    primary_error = statistics.mean(concentration_errors) if concentration_errors else 1.0
    primary_score = max(0.0, 100.0 * (1.0 - primary_error / protocol["concentration_tolerance_fraction"]))
    mean_volume_error = statistics.mean(volume_errors) if volume_errors else protocol["transfer_tolerance_ul"]
    volume_score = max(0.0, 100.0 * (1.0 - mean_volume_error / protocol["transfer_tolerance_ul"]))
    quality_score = max(0.0, 100.0 - 20.0 * len(set(penalties)))
    score = round(0.8 * primary_score + 0.1 * volume_score + 0.1 * quality_score, 4)
    if len(set(penalties)) == 0:
        score = 100.0
    write_result({"status": "evaluated", "score": score, "raw": {"metrics": metrics, "events": events, "contamination": contamination, "calibration": calibration, "penalties": sorted(set(penalties)), "primary_concentration_score": round(primary_score, 4), "volume_auxiliary_score": round(volume_score, 4), "quality_score": round(quality_score, 4), "action_count": len(actions), "instance_id": instance_id}})


if __name__ == "__main__":
    main()
