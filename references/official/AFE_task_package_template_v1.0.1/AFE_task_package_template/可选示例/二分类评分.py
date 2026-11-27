"""插入作者实际评价逻辑中；goal_verified 必须来自本题的实际检验。"""
from afe_contract import write_result


def report_binary_result(goal_verified):
    write_result({"status": "evaluated", "score": 100 if goal_verified else 0},
                 supports_over_target=False)
