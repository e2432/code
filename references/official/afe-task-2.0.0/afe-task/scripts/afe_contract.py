#!/usr/bin/env python3
"""AFE 1.0 data checks and result output. Standard library only; no task execution."""
import argparse
import json
import math
from pathlib import Path
import sys

PROTOCOL_VERSION = "1.0"
STATUSES = {"evaluated", "invalid_submission", "pending_review", "evaluation_error"}
DOMAINS = ["生命", "化学", "材料", "物理", "天文", "地球", "能源", "信息", "神经科学", "医学", "数学"]


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return type(value) in (int, float) and (type(value) is int or math.isfinite(value))


def score_ok(value):
    return number(value) and 0 <= value <= 100


def json_text(value):
    # Also rejects non-finite numbers inside open raw/extension fields.
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_result(value, supports_over_target=None):
    errors, warnings = [], []
    if not isinstance(value, dict):
        return ["结果必须是 JSON 对象"], warnings
    try:
        json_text(value)
    except (ValueError, TypeError):
        errors.append("结果必须是合法 JSON，不能包含 NaN/Infinity")
    status = value.get("status")
    if not nonempty(status):
        errors.append("status 必须是非空字符串")
        status = None
    if "score" not in value or not (value["score"] is None or score_ok(value["score"])):
        errors.append("score 必须出现，取有限 0–100 数值或 null；布尔值不是分数")
    if "notes" in value and not isinstance(value["notes"], str):
        errors.append("notes 应为字符串")
    if "raw" in value and not isinstance(value["raw"], dict):
        errors.append("运行结果 raw 应为对象；未提供时省略")
    if "target_exceeded" in value and type(value["target_exceeded"]) is not bool:
        errors.append("target_exceeded 应为布尔值；未判断时省略")
    if "error" in value:
        error = value["error"]
        if not isinstance(error, dict) or not all(nonempty(error.get(k)) for k in ("code", "message")):
            errors.append("error 应包含非空 code、message")
    if status == "evaluated":
        if not score_ok(value.get("score")):
            errors.append("evaluated 必须有有限的 0–100 主分")
        if "error" in value:
            errors.append("evaluated 不使用 error")
    elif status == "invalid_submission":
        if not score_ok(value.get("score")) or value["score"] != 0:
            errors.append("invalid_submission 的 score 为 0")
        if "error" not in value:
            errors.append("invalid_submission 必须给出 error")
    elif status in ("pending_review", "evaluation_error"):
        if value.get("score") is not None:
            errors.append(status + " 的 score 为 null")
        if status == "evaluation_error" and "error" not in value:
            errors.append("evaluation_error 必须给出 error")
        if status == "pending_review" and "error" in value:
            errors.append("pending_review 不使用 error")
    elif nonempty(status):
        warnings.append("扩展状态需说明语义和字段，并由平台接入后用于统计")
    if status in STATUSES - {"evaluated"}:
        if "raw" in value or "target_exceeded" in value:
            errors.append("通用非 evaluated 状态省略 raw/target_exceeded；补充信息可写 notes")
    if value.get("target_exceeded") is True:
        if status != "evaluated" or value.get("score") != 100:
            errors.append("target_exceeded=true 需要 evaluated 且 score=100")
        if supports_over_target is False:
            errors.append("题目声明不支持超目标，不能输出 target_exceeded=true")
        elif supports_over_target is None:
            warnings.append("超目标能力未提供，需与 task.toml 核对")
    return errors, warnings


def validate_reference(value):
    errors = []
    if not isinstance(value, dict):
        return ["info.json 必须为对象"], []
    for key in ("name", "proposed_at", "description"):
        if not nonempty(value.get(key)):
            errors.append(key + " 必须为非空字符串")
    # Date precision is intentionally not forced: year/month/day or a documented unknown.
    sources = value.get("source_urls")
    if not isinstance(sources, list) or not sources or not all(nonempty(x) for x in sources):
        errors.append("source_urls 应为非空资源地址列表")
    if "score" in value and value["score"] is not None and not score_ok(value["score"]):
        errors.append("可选参考 score 应为有限 0–100 数值或 null")
    if "raw" in value and value["raw"] is not None and not isinstance(value["raw"], dict):
        errors.append("可选参考 raw 应为对象或 null")
    if "notes" in value and not isinstance(value["notes"], str):
        errors.append("notes 应为字符串")
    try:
        json_text(value)
    except (ValueError, TypeError):
        errors.append("info.json 不能包含非 JSON 值或非有限数")
    return errors, []


def validate_metadata(value):
    errors, warnings = [], []
    if not isinstance(value, dict):
        return ["metadata.afe 必须为表"], warnings
    if value.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("本校验器支持 metadata.afe.protocol_version=1.0")
    if not nonempty(value.get("level")):
        errors.append("level 必须提供；首版填写 L1")
    elif value["level"] != "L1":
        warnings.append("首版只纳入 L1；此等级需另行确认接入范围")
    domains = value.get("domains")
    if not isinstance(domains, list) or not domains or not all(isinstance(x, str) and x in DOMAINS for x in domains):
        errors.append("domains 应为既定 11 科学领域的非空列表")
    elif len(domains) != len(set(domains)):
        errors.append("domains 不应重复")
    if type(value.get("supports_over_target")) is not bool:
        errors.append("supports_over_target 必须为布尔值")
    mapping = value.get("score_mapping")
    if not isinstance(mapping, dict) or not all(nonempty(mapping.get(k)) for k in ("url", "description")):
        errors.append("score_mapping 必须给出 url 和 description")
    if "reference_urls" in value:
        refs = value["reference_urls"]
        if not isinstance(refs, list) or not all(nonempty(x) for x in refs):
            errors.append("reference_urls 应为资源地址列表；无参考时省略或留空列表")
    if "validation" in value:
        val = value["validation"]
        if not isinstance(val, dict) or not all(nonempty(val.get(k)) for k in ("command", "description")):
            errors.append("validation 提供时应有 command 和 description")
    return errors, warnings


def reward_for(value):
    """None means no final numeric reward, not zero scientific achievement."""
    if value["status"] == "evaluated":
        return int(value["score"] == 100)
    if value["status"] == "invalid_submission":
        return 0
    return None


def write_result(value, output_dir="/logs/verifier", supports_over_target=None):
    errors, warnings = validate_result(value, supports_over_target)
    if errors:
        raise ValueError("; ".join(errors))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    # Remove only previous reward outputs, so a pending/error result cannot inherit success.
    for name in ("reward.json", "reward.txt"):
        old = destination / name
        if old.exists():
            old.unlink()
    (destination / "afe_result.json").write_text(json_text(value), encoding="utf-8")
    reward = reward_for(value)
    if reward is not None:
        (destination / "reward.json").write_text(json_text({"reward": reward}), encoding="utf-8")
    return warnings


def collect_result(log_dir, supports_over_target=None, runtime_error=None):
    """Read downloaded verifier logs. This is a platform adapter, not a Harbor plugin."""
    root = Path(log_dir)
    try:
        result = read_json(root / "afe_result.json")
    except (OSError, ValueError):
        return {"disposition": "evaluation_error", "score": None, "reward": None,
                "error": {"code": "missing_or_invalid_result", "message": runtime_error or "没有可读取的 afe_result.json；请核对运行记录。"}}
    errors, warnings = validate_result(result, supports_over_target)
    if errors:
        return {"disposition": "evaluation_error", "score": None, "reward": None,
                "error": {"code": "result_contract_error", "message": "; ".join(errors)}}
    reward = reward_for(result)
    if reward is not None:
        try:
            actual = read_json(root / "reward.json")
            consistent = isinstance(actual, dict) and number(actual.get("reward")) and actual["reward"] == reward
        except (OSError, ValueError):
            consistent = False
        if not consistent:
            return {"disposition": "evaluation_error", "score": None, "reward": None,
                    "error": {"code": "reward_mismatch", "message": "reward.json 缺失或与 AFE 结果不一致。"}, "result": result}
    status = result["status"]
    disposition = "scored" if reward is not None else (status if status in STATUSES else "unmapped_status")
    output = {"disposition": disposition, "score": result["score"] if reward is not None else None,
              "reward": reward, "result": result}
    if warnings:
        output["warnings"] = warnings
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["result", "reference", "metadata", "collect"])
    parser.add_argument("path", help="JSON 文件；collect 模式为已下载的 verifier 日志目录")
    parser.add_argument("--supports-over-target", choices=["true", "false"])
    parser.add_argument("--runtime-error", help="平台已有运行错误，仅在结果缺失时补充诊断")
    parser.add_argument("--output", help="可选的检查/收集结果保存位置，勿放入待审题包")
    args = parser.parse_args()
    support = None if args.supports_over_target is None else args.supports_over_target == "true"
    try:
        if args.mode == "collect":
            report = collect_result(args.path, support, args.runtime_error)
            code = 0 if report["disposition"] == "scored" else 3
        else:
            value = read_json(args.path)
            if args.mode == "result":
                errors, warnings = validate_result(value, support)
            else:
                errors, warnings = (validate_reference if args.mode == "reference" else validate_metadata)(value)
            report = {"valid": not errors, "errors": errors, "warnings": warnings}
            code = 1 if errors else 0
        encoded = json_text(report)
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return code
    except (OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
