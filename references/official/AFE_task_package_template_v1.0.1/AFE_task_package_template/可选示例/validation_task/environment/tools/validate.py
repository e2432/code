import argparse
import json
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--candidate-id", required=True)
args = parser.parse_args()
request = urllib.request.Request("http://validation:8000/validate",
    data=json.dumps({"candidate_id": args.candidate_id}).encode(),
    headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode())
    raise SystemExit(1)
