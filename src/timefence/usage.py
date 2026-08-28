import json
from datetime import date
from pathlib import Path

def _path(state_dir, resource): return state_dir/resource/f"{date.today().isoformat()}.json"
def get_usage(state_dir, resource):
    p=_path(state_dir,resource)
    if not p.exists(): return 0
    return int(json.loads(p.read_text()).get("usage_seconds",0))
def add_usage(state_dir, resource, seconds):
    p=_path(state_dir,resource); p.parent.mkdir(parents=True,exist_ok=True)
    total=get_usage(state_dir,resource)+seconds; tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"usage_seconds":total},indent=2)); tmp.replace(p); return total
