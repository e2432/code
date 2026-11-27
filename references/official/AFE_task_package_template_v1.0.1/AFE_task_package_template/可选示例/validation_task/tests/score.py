"""Read a service-collected snapshot, never an agent-uploaded query history."""
import json
import math
from pathlib import Path
from afe_contract import write_result


class InvalidSubmission(ValueError):
    pass


def evaluate(submission, snapshot):
    state = json.loads(Path(snapshot).read_text())
    records = state["queries"]
    if state.get("frozen") is not True or state["budget"] != 3 or len(records) > 3:
        raise ValueError("服务记录未正确封存或预算状态不一致")
    try:
        selected = json.loads(Path(submission).read_text())["query_id"]
    except (FileNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise InvalidSubmission("submission.json 必须包含实际查询 ID") from exc
    record = next((x for x in records if x["query_id"] == selected), None)
    if record is None:
        raise InvalidSubmission("所选 ID 不属于本次服务查询")
    value = record["value"]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("服务记录中的数值无效")
    score = 100 if value >= 0.8 else min(99.99999999999999, max(0, 100 * value / 0.8))
    return {"status": "evaluated", "score": score,
            "raw": {"value": value, "queries_used": len(records)}, "target_exceeded": value > 0.8}


def main():
    try:
        result = evaluate("/work/output/submission.json", "/validation_snapshot/session.json")
    except InvalidSubmission as exc:
        result = {"status": "invalid_submission", "score": 0,
                  "error": {"code": "invalid_output", "message": str(exc)}}
    except Exception as exc:
        result = {"status": "evaluation_error", "score": None,
                  "error": {"code": "service_snapshot_error", "message": str(exc)}}
    write_result(result, supports_over_target=True)


if __name__ == "__main__":
    main()
