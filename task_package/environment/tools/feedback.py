import argparse
import hashlib
import json
import os
import random
from pathlib import Path


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


def scheduled_failure(schedule, key, attempt_number):
    for item in schedule:
        if item.get("attempt") == attempt_number and item.get("step_id") == key.get("id"):
            return item.get("reason")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--instance-id", default="default")
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8-sig"))
    action = json.loads(Path(args.action).read_text(encoding="utf-8-sig"))
    state_path = Path(args.state)
    forced_instance_id = os.environ.get("AFE_INSTANCE_ID")
    instance_id = forced_instance_id or args.instance_id
    instance = next((item for item in protocol.get("instances", []) if item.get("id") == instance_id), None)
    if instance is None:
        raise SystemExit(f"unknown instance_id: {instance_id}")
    simulation = dict(protocol["simulation"])
    simulation["seed"] = instance.get("seed", simulation["seed"])
    simulation["failure_schedule"] = instance.get("failure_schedule", simulation["failure_schedule"])
    step_definitions = {step.get("id"): step for step in protocol.get("steps", []) if step.get("id")}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    else:
        stock_volume = instance.get("stock_volume_ul", protocol["stock"]["volume_ul"])
        state = {
            "containers": {
                "stock": {"volume": stock_volume, "solute": stock_volume * protocol["stock"]["concentration_um"]},
                "diluent": {"volume": protocol["diluent"]["volume_ul"], "solute": 0.0},
                "blank": {"volume": protocol["blank"]["volume_ul"], "solute": 0.0},
                "standard": {"volume": protocol["standard"]["volume_ul"], "solute": protocol["standard"]["volume_ul"] * protocol["standard"]["concentration_um"]},
            },
            "step": 0,
            "failed_ids": [],
            "failed_semantics": {},
            "attempt_counts": {},
            "used_tips": {},
            "transfer_occurrences": {},
            "calibration": {},
            "instance_id": instance_id,
        }
        for target in protocol["targets"]:
            state["containers"][target["name"]] = {"volume": 0.0, "solute": 0.0}
    kind = action.get("type")
    action_id = action.get("action_id", f"action-{state['step']}")
    key = semantic_key(action)
    key_text = json.dumps(key, sort_keys=True, ensure_ascii=False)
    retry_of = action.get("retry_of")
    feedback = {"step": state["step"], "status": "ok"}
    failed_semantics = state.setdefault("failed_semantics", {})
    if retry_of and (retry_of not in state.get("failed_ids", []) or failed_semantics.get(retry_of) != key):
        feedback.update({"status": "failed", "reason": "invalid_retry_reference"})
    else:
        attempt_number = None
        scheduled_reason = None
        if kind in {"transfer", "observe", "move"}:
            if step_definitions.get(key.get("id")) is None or not step_matches(step_definitions[key.get("id")], key):
                feedback.update({"status": "failed", "reason": "invalid_step_id"})
                state["step"] += 1
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(feedback, ensure_ascii=False, indent=2))
                return
            attempt_number = state.setdefault("attempt_counts", {}).get(key_text, 0) + 1
            state["attempt_counts"][key_text] = attempt_number
            scheduled_reason = scheduled_failure(simulation["failure_schedule"], key, attempt_number)
        if scheduled_reason and not retry_of:
            state.setdefault("failed_ids", []).append(action_id)
            failed_semantics[action_id] = key
            feedback.update({"status": "failed", "reason": scheduled_reason, "retry_required": True, "semantic_step": key, "attempt": attempt_number})
        elif kind in {"observe", "move"}:
            feedback.update({"operation": kind, "semantic_step": key, "attempt": attempt_number})
        elif kind == "calibrate":
            pipette = action.get("pipette")
            spec = protocol.get("calibration", {}).get(pipette)
            if spec is None:
                feedback.update({"status": "failed", "reason": "unknown_calibration_pipette"})
            else:
                measured = float(action.get("measured_volume_ul", 0.0))
                error = abs(measured - spec["reference_volume_ul"])
                state["calibration"][pipette] = {"error_ul": error}
                feedback.update({"pipette": pipette, "calibration_error_ul": error, "status": "ok" if error <= spec["tolerance_ul"] else "failed"})
        elif kind == "transfer":
            source, dest = action.get("source"), action.get("dest")
            volume = float(action.get("volume_ul", 0.0))
            tip_id = action.get("tip_id")
            if source not in state["containers"] or dest not in state["containers"] or source == dest or not tip_id:
                feedback.update({"status": "failed", "reason": "invalid_transfer"})
            else:
                previous_source = state.setdefault("used_tips", {}).get(tip_id)
                carryover_volume = 0.0
                carryover_solute = 0.0
                if previous_source is not None and previous_source != source:
                    previous = state["containers"][previous_source]
                    previous_concentration = previous["solute"] / previous["volume"] if previous["volume"] else 0.0
                    carryover_volume = float(protocol["carryover_volume_ul"])
                    carryover_solute = carryover_volume * previous_concentration
                    feedback.update({"contamination_risk": True, "carryover_volume_ul": carryover_volume})
                route_key = f"{source}->{dest}"
                route_occurrence = state.setdefault("transfer_occurrences", {}).get(route_key, 0)
                state["transfer_occurrences"][route_key] = route_occurrence + 1
                realized = volume + float(simulation.get("transfer_systematic_bias_ul", 0.0))
                realized += clipped_error(simulation["seed"], simulation, "transfer", source, dest, route_occurrence)
                if state["containers"][source]["volume"] + 1e-6 < realized:
                    feedback.update({"status": "failed", "reason": "insufficient_source_volume", "retry_required": True, "semantic_step": key})
                else:
                    concentration = state["containers"][source]["solute"] / state["containers"][source]["volume"] if state["containers"][source]["volume"] else 0.0
                    state["containers"][source]["volume"] -= realized
                    state["containers"][source]["solute"] -= realized * concentration
                    state["containers"][dest]["volume"] += realized + carryover_volume
                    state["containers"][dest]["solute"] += realized * concentration + carryover_solute
                    state["used_tips"][tip_id] = source
                    feedback.update({"realized_volume_ul": realized, "semantic_step": key})
        elif kind == "measure":
            target = action.get("target")
            if target not in state["containers"]:
                feedback.update({"status": "failed", "reason": "invalid_measure_target"})
            else:
                repeat_index = state.setdefault("measurement_counts", {}).get(target, 0)
                error = clipped_error(simulation["seed"], simulation, "measurement", target, repeat_index)
                observed = state["containers"][target]["volume"] + error
                state["measurement_counts"][target] = repeat_index + 1
                feedback.update({"target": target, "measured_volume_ul": observed, "measurement_error_ul": error})
        elif kind == "mix":
            dest = action.get("dest")
            volume = float(action.get("volume_ul", 0.0))
            if dest not in {item["name"] for item in protocol["targets"]} or volume <= 0 or volume > state["containers"][dest]["volume"] + protocol["transfer_tolerance_ul"]:
                feedback.update({"status": "failed", "reason": "invalid_mix"})
            else:
                feedback.update({"mixed_target": dest, "mix_quality": min(1.0, float(action.get("cycles", 0)) / 5.0)})
        elif kind == "pause":
            state["status"] = "paused"
            feedback.update({"status": "paused", "reason": action.get("reason"), "last_safe_checkpoint": action.get("last_safe_checkpoint")})
        elif kind == "finish":
            state["status"] = "completed"
            feedback.update({"status": "completed"})
        else:
            feedback.update({"status": "invalid", "reason": "unsupported_action"})
    state["step"] += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(feedback, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
