import argparse
import json
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument("--path",required=True)
parser.add_argument("--step",required=True)
parser.add_argument("--status",choices=["pending","running","completed","blocked"],required=True)
parser.add_argument("--evidence")
args=parser.parse_args()
path=Path(args.path)
if path.exists(): data=json.loads(path.read_text(encoding="utf-8-sig"))
else: data={"steps":[]}
steps=data.setdefault("steps",[])
item=next((step for step in steps if step.get("id")==args.step),None)
if item is None:
    item={"id":args.step}; steps.append(item)
item["status"]=args.status
if args.evidence is not None: item["evidence"]=args.evidence
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(item,ensure_ascii=False))
