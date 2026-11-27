"""Synthetic interface example. Replace the measurement/mapping for your science."""
import csv
import math
from pathlib import Path
from afe_contract import write_result


class InvalidSubmission(ValueError):
    pass


def evaluate(submission, targets):
    # Load evaluation materials separately: their absence is not an agent error.
    with Path(targets).open(encoding="utf-8") as stream:
        truth = {row["sample_id"]: float(row["target"]) for row in csv.DictReader(stream)}
    if not truth or not all(math.isfinite(x) for x in truth.values()):
        raise ValueError("合成评价材料无效")
    if not Path(submission).is_file():
        raise InvalidSubmission("缺少 /work/output/predictions.csv")
    try:
        with Path(submission).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["sample_id", "prediction"]:
                raise InvalidSubmission("列名必须是 sample_id,prediction")
            predictions = {}
            for row in reader:
                key, value = row["sample_id"], float(row["prediction"])
                if None in row or key in predictions or not math.isfinite(value):
                    raise InvalidSubmission("行格式错误、ID 重复或数值不是有限数")
                predictions[key] = value
    except (UnicodeError, csv.Error, KeyError, TypeError, ValueError) as exc:
        raise InvalidSubmission(str(exc)) from exc
    if predictions.keys() != truth.keys():
        raise InvalidSubmission("提交 ID 与输入不一致")
    mae = sum(abs(predictions[k] - truth[k]) for k in truth) / len(truth)
    # Author owns the mapping. Only a genuinely achieved target receives 100.
    achieved = mae <= 6
    score = 100 if achieved else min(99.99999999999999, max(0.0, 100 * (20 - mae) / 14))
    return {"status": "evaluated", "score": score, "raw": {"mae": mae}, "target_exceeded": mae < 6}


def main():
    try:
        result = evaluate("/work/output/predictions.csv", Path(__file__).with_name("targets.csv"))
    except InvalidSubmission as exc:
        result = {"status": "invalid_submission", "score": 0,
                  "error": {"code": "invalid_output", "message": str(exc)}}
    except Exception as exc:
        result = {"status": "evaluation_error", "score": None,
                  "error": {"code": "verifier_failed", "message": str(exc)}}
    write_result(result, supports_over_target=True)


if __name__ == "__main__":
    main()
