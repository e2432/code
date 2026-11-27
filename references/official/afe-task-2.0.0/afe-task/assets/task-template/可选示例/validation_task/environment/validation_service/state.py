"""Tiny Linux-only state store for the synthetic service example."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path


@contextmanager
def locked_state(directory="/state"):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "session.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "session.json"
        state = json.loads(path.read_text()) if path.exists() else {"budget": 3, "queries": [], "frozen": False}
        try:
            yield state
            temporary = root / "session.json.tmp"
            temporary.write_text(json.dumps(state, allow_nan=False))
            temporary.replace(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def query(state, candidate_id, values):
    if state["frozen"]:
        return 409, {"error": "session_closed"}
    if not isinstance(candidate_id, str) or candidate_id not in values:
        return 400, {"error": "invalid_candidate"}
    for record in state["queries"]:
        if record["candidate_id"] == candidate_id:
            return 200, dict(record, remaining=state["budget"] - len(state["queries"]))
    if len(state["queries"]) >= state["budget"]:
        return 429, {"error": "budget_exhausted"}
    record = {"query_id": "q" + str(len(state["queries"]) + 1),
              "candidate_id": candidate_id, "value": values[candidate_id]}
    state["queries"].append(record)
    return 200, dict(record, remaining=state["budget"] - len(state["queries"]))
