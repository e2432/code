import hashlib
import json
import math
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

SCIENCE_GATE_PENALTIES = {
    "target_concentration", "contamination",
    "protocol_transfer", "mix_quality", "missing_calibration", "unresolved_failure",
    "insufficient_volume", "required_action_missing", "unresolved_pause", "calibration",
    "calibration_reference", "sample_used_before_mixing", "volume_auxiliary",
    "insufficient_mixing", "nonpositive_realized_volume", "pause_without_evidence",
}
RECORD_GATE_PENALTIES = {
    "repeat_measurement", "blank_control", "standard_control", "quality_record",
    "missing_quality_record", "standard_report", "blank_report", "missing_finish",
    "missing_state_artifacts", "invalid_state_artifacts", "run_state_not_completed",
    "progress_incomplete", "invalid_retry_reference", "failure_record",
    "duplicate_action_id", "actions_after_pause", "duplicate_pause", "unknown_calibration_pipette",
    "missing_events_artifact", "invalid_events_artifact", "progress_instance_mismatch", "run_state_instance_mismatch",
    "progress_schema", "calibration_order",
}


def write_result(result):
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("status") in {"pending_review", "evaluation_error"}:
        if REWARD.exists():
            REWARD.unlink()
    else:
        REWARD.write_text(
            json.dumps({"reward": int(result.get("status") == "evaluated" and result.get("score") == 100)}, indent=2),
            encoding="utf-8",
        )


def fail(code, message):
    write_result({
        "status": "invalid_submission",
        "score": 0,
        "error": {"code": code, "message": message},
    })


def keyed_rng(seed, *parts):
    key = "|".join([str(seed), *[str(part) for part in parts]])
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def clipped_error(seed, simulation, kind, *parts):
    distribution = simulation.get(f"{kind}_error_distribution", "normal")
    if distribution == "normal":
        sd = float(simulation.get(f"{kind}_error_sd_ul", 0.0))
        clip_sd = float(simulation.get(f"{kind}_error_clip_sd", 3.0))
        error = keyed_rng(seed, kind, *parts).gauss(0.0, sd)
        return max(-clip_sd * sd, min(clip_sd * sd, error))
    span = float(simulation.get(f"{kind}_error_range_ul", 0.0))
    return keyed_rng(seed, kind, *parts).uniform(-span, span)


def close(a, b, tolerance):
    try:
        return math.isfinite(float(a)) and abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def list_matches(reported, actual, tolerance=1e-3):
    if not isinstance(reported, list) or len(reported) != len(actual):
        return False
    return all(close(r, a, tolerance) for r, a in zip(reported, actual))


def semantic_key(action):
    kind = action.get("type")
    if kind == "transfer":
        try:
            volume = round(float(action.get("volume_ul")), 9)
        except (TypeError, ValueError):
            volume = action.get("volume_ul")
        return {"id": action.get("step_id"), "type": kind, "source": action.get("source"), "dest": action.get("dest"), "volume_ul": volume}
    if kind in {"observe", "move"}:
        return {"id": action.get("step_id"), "type": kind, "target": action.get("target") or action.get("dest") or action.get("object")}
    return {"type": kind}


def step_matches(step, key):
    if not isinstance(step, dict) or step.get("type") != key.get("type"):
        return False
    for field, expected in step.items():
        if field == "type":
            continue
        actual = key.get(field)
        if field == "volume_ul":
            try:
                if abs(float(actual) - float(expected)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        elif actual != expected:
            return False
    return True


def required_step_id(step):
    if isinstance(step, str):
        return step
    if isinstance(step, dict):
        return step.get("id")
    return None


def scheduled_failure(schedule, key, attempt_number):
    for item in schedule:
        if item.get("attempt") == attempt_number and item.get("step_id") == key.get("id"):
            return item.get("reason")
    return None


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

    forced_instance_id = os.environ.get("AFE_INSTANCE_ID")
    submitted_instance_id = submission.get("instance_id")
    instance_id = forced_instance_id or submitted_instance_id or "default"
    if forced_instance_id and submitted_instance_id not in {None, forced_instance_id}:
        fail("instance_mismatch", "submission.instance_id does not match evaluator-pinned AFE_INSTANCE_ID")
        return
    instance = next((item for item in protocol.get("instances", []) if item.get("id") == instance_id), None)
    if instance is None:
        fail("unknown_instance", f"unknown instance_id: {instance_id}")
        return

    simulation = dict(protocol["simulation"])
    simulation["seed"] = instance.get("seed", simulation["seed"])
    simulation["failure_schedule"] = instance.get("failure_schedule", simulation["failure_schedule"])
    required_steps = instance.get("required_steps", [])
    step_definitions = {step.get("id"): step for step in protocol.get("steps", []) if step.get("id")}
    seen_steps = []
    seen_action_ids = set()

    stock_volume = float(instance.get("stock_volume_ul", protocol["stock"]["volume_ul"]))
    containers = {
        "stock": {"volume": stock_volume, "solute": stock_volume * protocol["stock"]["concentration_um"]},
        "diluent": {"volume": float(protocol["diluent"]["volume_ul"]), "solute": 0.0},
        "blank": {"volume": float(protocol["blank"]["volume_ul"]), "solute": 0.0},
        "standard": {
            "volume": float(protocol["standard"]["volume_ul"]),
            "solute": float(protocol["standard"]["volume_ul"]) * protocol["standard"]["concentration_um"],
        },
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
    transfer_occurrences = {}
    measurements = {}
    events = []
    contamination = []
    penalties = []
    failed_ids = set()
    failed_semantics = {}
    retry_refs = set()
    attempt_counts = {}
    calibration = {}
    first_transfer_index = None
    calibration_indices = []
    finished = False
    paused = False
    pause_index = None
    hard_error = None
    action_ids_after_pause = []

    for index, action in enumerate(actions):
        kind = action.get("type")
        action_id = action.get("action_id", f"action-{index}")
        if action_id in seen_action_ids:
            penalties.append("duplicate_action_id")
        seen_action_ids.add(action_id)
        if paused:
            action_ids_after_pause.append(action_id)

        key = semantic_key(action)
        key_text = json.dumps(key, sort_keys=True, ensure_ascii=False)
        retry_of = action.get("retry_of")
        if retry_of:
            if retry_of not in failed_ids or failed_semantics.get(retry_of) != key:
                penalties.append("invalid_retry_reference")
                continue
            retry_refs.add(retry_of)
        if kind in {"transfer", "observe", "move"}:
            definition = step_definitions.get(key.get("id"))
            if definition is None or not step_matches(definition, key):
                hard_error = f"action {index} has missing or mismatched step_id"
                break
            seen_steps.append(key)
            attempt_number = attempt_counts.get(key_text, 0) + 1
            attempt_counts[key_text] = attempt_number
            scheduled_reason = scheduled_failure(simulation["failure_schedule"], key, attempt_number)
        else:
            attempt_number = None
            scheduled_reason = None

        if kind == "calibrate":
            calibration_indices.append(index)
            pipette = action.get("pipette")
            spec = protocol["calibration"].get(pipette)
            if spec is None:
                penalties.append("unknown_calibration_pipette")
                continue
            if not close(action.get("reference_volume_ul"), spec["reference_volume_ul"], 1e-9):
                penalties.append("calibration_reference")
            measured = float(action.get("measured_volume_ul", 0.0))
            error = abs(measured - spec["reference_volume_ul"])
            calibration[pipette] = {
                "reference_volume_ul": spec["reference_volume_ul"],
                "measured_volume_ul": measured,
                "error_ul": error,
            }
            if error > spec["tolerance_ul"]:
                penalties.append("calibration")
            continue

        if kind in {"observe", "move"}:
            if scheduled_reason and not retry_of:
                failed_ids.add(action_id)
                failed_semantics[action_id] = key
                events.append({"action_id": action_id, "status": "failed", "reason": scheduled_reason, "semantic_step": key, "attempt": attempt_number})
                continue
            events.append({"action_id": action_id, "status": "ok", "operation": kind, "retry_of": retry_of, "semantic_step": key, "attempt": attempt_number})
            continue

        if kind == "transfer":
            if first_transfer_index is None:
                first_transfer_index = index
            source, dest = action.get("source"), action.get("dest")
            try:
                requested_volume = float(action["volume_ul"])
            except Exception:
                hard_error = f"action {index} has invalid volume"
                break
            if source not in containers or dest not in containers or source == dest or requested_volume <= 0:
                hard_error = f"action {index} has invalid containers or volume"
                break
            if action.get("pipette") != "p1000":
                hard_error = f"action {index} must use p1000"
                break
            spec = protocol["pipettes"]["p1000"]
            if requested_volume < spec["min_ul"] or requested_volume > spec["max_ul"]:
                hard_error = f"action {index} violates p1000 range"
                break
            if scheduled_reason and not retry_of:
                failed_ids.add(action_id)
                failed_semantics[action_id] = key
                events.append({"action_id": action_id, "status": "failed", "reason": scheduled_reason, "semantic_step": key, "attempt": attempt_number})
                continue
            tip_id = action.get("tip_id")
            if not tip_id:
                hard_error = f"action {index} is missing tip_id"
                break
            previous_source = used_tips.get(tip_id)
            carryover_volume = 0.0
            carryover_solute = 0.0
            if previous_source is not None and previous_source != source:
                previous = containers[previous_source]
                previous_concentration = previous["solute"] / previous["volume"] if previous["volume"] else 0.0
                carryover_volume = float(protocol["carryover_volume_ul"])
                carryover_solute = carryover_volume * previous_concentration
                contamination.append({
                    "action_index": index,
                    "tip_id": tip_id,
                    "previous_source": previous_source,
                    "source": source,
                    "carryover_volume_ul": carryover_volume,
                    "carryover_solute_um_ul": carryover_solute,
                })
                penalties.append("contamination")
            route_key = (source, dest)
            route_occurrence = transfer_occurrences.get(route_key, 0)
            transfer_occurrences[route_key] = route_occurrence + 1
            realized_volume = requested_volume + float(simulation.get("transfer_systematic_bias_ul", 0.0))
            realized_volume += clipped_error(simulation["seed"], simulation, "transfer", source, dest, route_occurrence)
            if realized_volume <= 0:
                events.append({"action_id": action_id, "status": "failed", "reason": "nonpositive_realized_volume", "semantic_step": key, "attempt": attempt_number})
                penalties.append("insufficient_volume")
                continue
            if containers[source]["volume"] + 1e-6 < realized_volume:
                events.append({"action_id": action_id, "status": "failed", "reason": "insufficient_source_volume", "semantic_step": key, "attempt": attempt_number})
                penalties.append("insufficient_volume")
                continue
            concentration = containers[source]["solute"] / containers[source]["volume"] if containers[source]["volume"] else 0.0
            containers[source]["volume"] -= realized_volume
            containers[source]["solute"] -= realized_volume * concentration
            containers[dest]["volume"] += realized_volume + carryover_volume
            containers[dest]["solute"] += realized_volume * concentration + carryover_solute
            used_tips[tip_id] = source
            if dest in incoming:
                incoming[dest].append((index, source, realized_volume))
            if source in source_uses:
                source_uses[source].append(index)
            events.append({"action_id": action_id, "status": "ok", "operation": "transfer", "semantic_step": key, "attempt": attempt_number})
            continue

        if kind == "mix":
            dest = action.get("dest")
            try:
                cycles = int(action.get("cycles", 0))
                volume = float(action.get("volume_ul", 0.0))
            except (TypeError, ValueError):
                hard_error = f"action {index} has invalid mix parameters"
                break
            if dest not in target_by_name:
                hard_error = f"action {index} has invalid mix target"
                break
            if volume <= 0 or volume > containers[dest]["volume"] + protocol["transfer_tolerance_ul"]:
                penalties.append("insufficient_mixing")
                events.append({"action_id": action_id, "status": "invalid", "operation": "mix", "reason": "mix_volume_exceeds_available", "target": dest})
                continue
            mix_quality[dest] = min(1.0, max(mix_quality[dest], cycles / 5.0))
            last_mix[dest] = index
            if cycles < protocol["min_mix_cycles"]:
                penalties.append("insufficient_mixing")
            events.append({"action_id": action_id, "status": "ok", "operation": "mix", "target": dest, "cycles": cycles})
            continue

        if kind == "measure":
            target = action.get("target")
            if target not in containers:
                hard_error = f"action {index} has invalid measure target"
                break
            repeat_index = len(measurements.get(target, []))
            measurement_id = action.get("measurement_id", f"m-{repeat_index}")
            error = clipped_error(simulation["seed"], simulation, "measurement", target, repeat_index)
            observed = containers[target]["volume"] + error
            measurements.setdefault(target, []).append({
                "measurement_id": measurement_id,
                "measured_volume_ul": observed,
                "error_ul": error,
            })
            events.append({"action_id": action_id, "status": "ok", "operation": "measure", "target": target, "repeat_index": repeat_index})
            continue

        if kind == "pause":
            if paused:
                penalties.append("duplicate_pause")
            paused = True
            pause_index = index
            events.append({"status": "paused", "reason": action.get("reason"), "last_safe_checkpoint": action.get("last_safe_checkpoint")})
            continue

        if kind == "finish":
            finished = True
            events.append({"status": "finished", "action_id": action_id})
            continue

        hard_error = f"action {index} has unsupported type"
        break

    if hard_error:
        fail("invalid_action", hard_error)
        return

    if action_ids_after_pause:
        penalties.append("actions_after_pause")
    missing_required = [step for step in required_steps if not any(required_step_id(step) == seen.get("id") for seen in seen_steps)]
    if missing_required:
        penalties.append("required_action_missing")
        events.append({"status": "required_actions_missing", "steps": missing_required})
    if failed_ids and not failed_ids.issubset(retry_refs):
        penalties.append("unresolved_failure")
    if not finished and not paused:
        penalties.append("missing_finish")
    if first_transfer_index is not None and (not calibration_indices or min(calibration_indices) > first_transfer_index):
        penalties.append("calibration_order")
    if paused and instance.get("expected_outcome", "complete") != "pause":
        penalties.append("unresolved_pause")

    run_state = None
    progress = None
    try:
        progress = json.loads((WORKDIR / "output/progress.json").read_text(encoding="utf-8-sig"))
        run_state = json.loads((WORKDIR / "output/run_state.json").read_text(encoding="utf-8-sig"))
        if not paused and run_state.get("status") != "completed":
            penalties.append("run_state_not_completed")
        if progress.get("instance_id") != instance_id:
            penalties.append("progress_instance_mismatch")
        if run_state.get("instance_id") != instance_id:
            penalties.append("run_state_instance_mismatch")
        if not paused:
            expected_progress = protocol.get("progress_steps", [])
            actual_steps = progress.get("steps")
            actual_ids = [step.get("id") for step in actual_steps] if isinstance(actual_steps, list) and all(isinstance(step, dict) for step in actual_steps) else None
            if actual_ids is None or len(actual_ids) != len(expected_progress) or len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(expected_progress):
                penalties.append("progress_schema")
            if not isinstance(actual_steps, list) or any(step.get("status") != "completed" for step in actual_steps):
                penalties.append("progress_incomplete")
    except FileNotFoundError:
        penalties.append("missing_state_artifacts")
    except Exception:
        penalties.append("invalid_state_artifacts")

    events_path = WORKDIR / "output/events.jsonl"
    try:
        event_lines = [line for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        artifact_events = [json.loads(line) for line in event_lines]
        if not event_lines or any(not isinstance(event, dict) for event in artifact_events):
            penalties.append("invalid_events_artifact")
        else:
            for expected in events:
                action_id = expected.get("action_id")
                if action_id and not any(
                    event.get("action_id") == action_id and event.get("status") == expected.get("status")
                    for event in artifact_events
                ):
                    penalties.append("invalid_events_artifact")
                    break
    except FileNotFoundError:
        penalties.append("missing_events_artifact")
    except Exception:
        penalties.append("invalid_events_artifact")

    expected_outcome = instance.get("expected_outcome", "complete")
    expected_pause_step = instance.get("expected_pause_step")
    safe_failure = any(
        event.get("reason") == "insufficient_source_volume"
        and (expected_pause_step is None or step_matches(expected_pause_step, event.get("semantic_step", {})))
        for event in events
    )
    pause_evidence = (
        paused and run_state and run_state.get("status") == "paused" and not hard_error
        and expected_outcome == "pause" and safe_failure
        and any(event.get("status") == "paused" and event.get("reason") and event.get("last_safe_checkpoint") for event in events)
        and not action_ids_after_pause
    )
    safe_pause_evidence = pause_evidence
    if paused and pause_evidence:
        remaining_penalties = [penalty for penalty in penalties if penalty not in {"insufficient_volume", "calibration_order"}]
        if remaining_penalties:
            safe_pause_evidence = False
        else:
            penalties = remaining_penalties
    if paused and safe_pause_evidence:
        write_result({
            "status": "evaluated",
            "score": float(protocol.get("score_caps", {}).get("safe_pause", 50.0)),
            "raw": {"outcome": "safe_pause_expected", "events": events, "penalties": sorted(set(penalties)), "action_count": len(actions), "instance_id": instance_id},
            "notes": "The instance declares an infeasible inventory; the Agent supplied the required failure evidence and safe checkpoint.",
        })
        return
    if paused:
        if not pause_evidence:
            penalties.append("pause_without_evidence" if expected_outcome == "pause" else "unresolved_pause")
        write_result({
            "status": "evaluated",
            "score": 0.0,
            "raw": {"outcome": "failed", "events": events, "penalties": sorted(set(penalties)), "action_count": len(actions), "instance_id": instance_id},
            "notes": "Pause without the predeclared evidence is an evaluated failure, not a pending human review.",
        })
        return

    report_samples = {item.get("name"): item for item in report.get("samples", []) if isinstance(item, dict)}
    metrics = {}
    concentration_errors = []
    volume_errors = []
    quality_penalties = []

    for target in targets:
        name = target["name"]
        records = measurements.get(name, [])
        values = [item["measured_volume_ul"] for item in records]
        if len(records) < protocol["required_measurement_repeats"]:
            penalties.append("repeat_measurement")
        mean = statistics.mean(values) if values else 0.0
        sd = statistics.pstdev(values) if len(values) > 1 else 0.0
        true_volume = containers[name]["volume"]
        true_concentration = containers[name]["solute"] / true_volume if true_volume else 0.0
        estimated_concentration = containers[name]["solute"] / mean if mean else 0.0
        estimated_concentration_error = abs(estimated_concentration - target["concentration_um"]) / target["concentration_um"]
        concentration_error = abs(true_concentration - target["concentration_um"]) / target["concentration_um"]
        measurement_error = mean - true_volume
        volume_error = true_volume - target["final_volume_ul"]
        concentration_errors.append(concentration_error)
        volume_errors.append(abs(volume_error))
        metrics[name] = {
            "measurements_ul": [round(value, 6) for value in values],
            "mean_volume_ul": round(mean, 6),
            "volume_error_ul": round(volume_error, 6),
            "measurement_error_ul": round(measurement_error, 6),
            "volume_sd_ul": round(sd, 6),
            "estimated_concentration_um": round(estimated_concentration, 6),
            "estimated_concentration_error_fraction": round(estimated_concentration_error, 6),
            "concentration_error_fraction": round(concentration_error, 6),
            "true_volume_ul": round(true_volume, 6),
            "target_volume_error_ul": round(true_volume - target["final_volume_ul"], 6),
            "true_concentration_um": round(true_concentration, 6),
        }
        if concentration_error > protocol["concentration_tolerance_fraction"]:
            penalties.append("target_concentration")
        if abs(volume_error) > protocol["transfer_tolerance_ul"]:
            penalties.append("volume_auxiliary")
        item = report_samples.get(name)
        if item is None:
            quality_penalties.append("missing_quality_record")
        else:
            if not list_matches(item.get("measurements_ul"), values):
                quality_penalties.append("quality_record")
            if not close(item.get("mean_volume_ul"), mean, 1e-5) or not close(item.get("volume_error_ul"), volume_error, 1e-5) or not close(item.get("measurement_error_ul"), measurement_error, 1e-5) or not close(item.get("volume_sd_ul"), sd, 1e-5) or not close(item.get("estimated_concentration_um"), estimated_concentration, 1e-5) or not close(item.get("estimated_concentration_error_fraction"), estimated_concentration_error, 1e-6):
                quality_penalties.append("quality_record")
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

    blank_records = measurements.get("blank", [])
    standard_records = measurements.get("standard", [])
    if len(blank_records) < protocol["required_measurement_repeats"]:
        penalties.append("blank_control")
    if len(standard_records) < protocol["required_measurement_repeats"]:
        penalties.append("standard_control")
    if "p1000" not in calibration:
        penalties.append("missing_calibration")

    blank_values = [item["measured_volume_ul"] for item in blank_records]
    blank_mean = statistics.mean(blank_values) if blank_values else 0.0
    blank_sd = statistics.pstdev(blank_values) if len(blank_values) > 1 else 0.0
    standard_values = [item["measured_volume_ul"] for item in standard_records]
    standard_mean = statistics.mean(standard_values) if standard_values else 0.0
    standard_sd = statistics.pstdev(standard_values) if len(standard_values) > 1 else 0.0

    standard_report = report.get("standard")
    if not isinstance(standard_report, dict):
        quality_penalties.append("standard_report")
    else:
        if not list_matches(standard_report.get("measurements_ul"), standard_values):
            quality_penalties.append("standard_report")
        if not close(standard_report.get("mean_volume_ul"), standard_mean, 1e-5) or not close(standard_report.get("volume_sd_ul"), standard_sd, 1e-5):
            quality_penalties.append("standard_report")
    blank_report = report.get("blank")
    if not isinstance(blank_report, dict):
        quality_penalties.append("blank_report")
    else:
        if not list_matches(blank_report.get("measurements_ul"), blank_values):
            quality_penalties.append("blank_report")
        if not close(blank_report.get("mean_volume_ul"), blank_mean, 1e-5) or not close(blank_report.get("volume_sd_ul"), blank_sd, 1e-5):
            quality_penalties.append("blank_report")

    penalties.extend(quality_penalties)
    primary_error = statistics.mean(concentration_errors) if concentration_errors else 1.0
    primary_score = max(0.0, 100.0 * (1.0 - primary_error / protocol["concentration_tolerance_fraction"]))
    mean_volume_error = statistics.mean(volume_errors) if volume_errors else protocol["transfer_tolerance_ul"]
    volume_score = max(0.0, 100.0 * (1.0 - mean_volume_error / protocol["transfer_tolerance_ul"]))
    quality_score = max(0.0, 100.0 - 10.0 * len(set(quality_penalties)))
    base_score = round(0.8 * primary_score + 0.1 * volume_score + 0.1 * quality_score, 4)
    unique_penalties = set(penalties)
    outcome = "completed" if not unique_penalties else "failed"
    if not unique_penalties:
        score = 100.0
    elif unique_penalties & SCIENCE_GATE_PENALTIES:
        score = min(base_score, float(protocol.get("score_caps", {}).get("scientific_gate", 50.0)))
    elif unique_penalties & RECORD_GATE_PENALTIES:
        score = min(base_score, float(protocol.get("score_caps", {}).get("record_gate", 80.0)))
    else:
        # Any unclassified penalty is still a failed record condition.
        score = min(base_score, float(protocol.get("score_caps", {}).get("record_gate", 80.0)))
    write_result({
        "status": "evaluated",
        "score": round(score, 4),
        "raw": {
            "outcome": outcome,
            "metrics": metrics,
            "standard": {
                "measurements_ul": [round(value, 6) for value in standard_values],
                "mean_volume_ul": round(standard_mean, 6),
                "volume_sd_ul": round(standard_sd, 6),
                "assay_status": "not_implemented",
            },
            "blank": {
                "measurements_ul": [round(value, 6) for value in blank_values],
                "mean_volume_ul": round(blank_mean, 6),
                "volume_sd_ul": round(blank_sd, 6),
                "assay_status": "not_implemented",
            },
            "events": events,
            "contamination": contamination,
            "calibration": calibration,
            "penalties": sorted(unique_penalties),
            "primary_concentration_score": round(primary_score, 4),
            "volume_auxiliary_score": round(volume_score, 4),
            "quality_score": round(quality_score, 4),
            "base_score_before_gates": base_score,
            "action_count": len(actions),
            "instance_id": instance_id,
        },
    })


if __name__ == "__main__":
    main()
