import json
import math
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
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    reward = {"reward": 1 if result.get("status") == "evaluated" and result.get("score") == 100 else 0}
    REWARD.write_text(json.dumps(reward, indent=2))


def fail(code, message):
    write_result({"status": "invalid_submission", "score": 0, "error": {"code": code, "message": message}})


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
    if not isinstance(actions, list):
        fail("invalid_actions", "actions must be a JSON array")
        return

    containers = {
        "stock": {"volume": protocol["stock"]["volume_ul"], "solute": protocol["stock"]["volume_ul"] * protocol["stock"]["concentration_um"]},
        "diluent": {"volume": protocol["diluent"]["volume_ul"], "solute": 0.0},
    }
    for target in protocol["targets"]:
        containers[target["name"]] = {"volume": 0.0, "solute": 0.0}

    target_names = [t["name"] for t in protocol["targets"]]
    target_by_name = {t["name"]: t for t in protocol["targets"]}
    source_usage = {}
    used_tips = {}
    mix_cycles = {name: 0 for name in target_names}
    action_indices = {name: [] for name in target_names}
    mix_indices = {name: [] for name in target_names}
    penalties = []
    hard_error = None

    for index, action in enumerate(actions):
        kind = action.get("type")
        if kind == "transfer":
            source = action.get("source")
            dest = action.get("dest")
            try:
                volume = float(action["volume_ul"])
            except Exception:
                hard_error = f"action {index} has invalid volume"
                break
            if source not in containers or dest not in containers or source == dest or volume <= 0:
                hard_error = f"action {index} has invalid source, destination, or volume"
                break
            pipette = protocol["pipettes"].get(action.get("pipette"))
            if pipette is None or volume < pipette["min_ul"] or volume > pipette["max_ul"]:
                hard_error = f"action {index} violates pipette range"
                break
            if containers[source]["volume"] + 1e-6 < volume:
                hard_error = f"action {index} aspirates more than available volume"
                break
            tip_id = action.get("tip_id")
            if not isinstance(tip_id, str) or not tip_id:
                hard_error = f"action {index} has no tip_id"
                break
            previous_source = used_tips.get(tip_id)
            if previous_source is not None and previous_source != source:
                penalties.append("cross_source_tip_reuse")
            used_tips[tip_id] = source
            concentration = containers[source]["solute"] / containers[source]["volume"] if containers[source]["volume"] else 0.0
            containers[source]["volume"] -= volume
            containers[source]["solute"] -= volume * concentration
            containers[dest]["volume"] += volume
            containers[dest]["solute"] += volume * concentration
            source_usage[source] = source_usage.get(source, 0.0) + volume
            if dest in action_indices:
                action_indices[dest].append((index, source, volume))
        elif kind == "mix":
            dest = action.get("dest")
            if dest not in target_by_name:
                hard_error = f"action {index} mixes an invalid target"
                break
            try:
                volume = float(action["volume_ul"])
                cycles = int(action["cycles"])
            except Exception:
                hard_error = f"action {index} has invalid mixing parameters"
                break
            if volume <= 0 or volume > containers[dest]["volume"] + 1e-6:
                hard_error = f"action {index} mixes more than current volume"
                break
            mix_cycles[dest] += max(cycles, 0)
            mix_indices[dest].append(index)
        else:
            hard_error = f"action {index} has unsupported type"
            break

    if hard_error:
        fail("invalid_action", hard_error)
        return

    scores = {}
    for target in protocol["targets"]:
        name = target["name"]
        volume_error = abs(containers[name]["volume"] - target["final_volume_ul"])
        concentration = containers[name]["solute"] / containers[name]["volume"] if containers[name]["volume"] else 0.0
        concentration_error = abs(concentration - target["concentration_um"]) / target["concentration_um"]
        scores[f"{name}_volume_error_ul"] = round(volume_error, 6)
        scores[f"{name}_concentration_um"] = round(concentration, 6)
        scores[f"{name}_concentration_error_fraction"] = round(concentration_error, 6)
        if volume_error > protocol["transfer_tolerance_ul"]:
            penalties.append("final_volume")
        if concentration_error > protocol["concentration_tolerance_fraction"]:
            penalties.append("target_concentration")
        if mix_cycles[name] < protocol["min_mix_cycles"]:
            penalties.append("insufficient_mixing")
        expected_source = target["sample_source"]
        incoming = action_indices[name]
        if len(incoming) != 2:
            penalties.append("wrong_transfer_count")
        else:
            incoming_sources = sorted(item[1] for item in incoming)
            expected_sources = sorted([expected_source, "diluent"])
            if incoming_sources != expected_sources:
                penalties.append("wrong_sample_source")
            if any(abs(item[2] - 500.0) > protocol["transfer_tolerance_ul"] for item in incoming):
                penalties.append("wrong_transfer_volume")
        use_indices = [index for index, action in enumerate(actions) if action.get("type") == "transfer" and action.get("source") == name]
        if use_indices and not any(mix_index < use_indices[0] for mix_index in mix_indices[name]):
            penalties.append("sample_used_before_mixing")

    for name, volume in source_usage.items():
        if name in ("stock", "diluent") and volume > protocol[name]["volume_ul"] + 1e-6:
            penalties.append("source_overdraw")

    total_penalties = len(penalties)
    score = 100 if total_penalties == 0 else max(0, 100 - 20 * total_penalties)
    result = {"status": "evaluated", "score": score, "raw": {"metrics": scores, "penalties": penalties, "action_count": len(actions)}}
    write_result(result)


if __name__ == "__main__":
    main()


