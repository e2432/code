import json
from pathlib import Path
from state import locked_state


def export_state(directory="/state", output="/validation_snapshot/session.json"):
    # Same lock waits for accepted writes, then blocks further queries through frozen.
    with locked_state(directory) as state:
        state["frozen"] = True
        snapshot = json.dumps(state, allow_nan=False)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot)


if __name__ == "__main__":
    export_state()
