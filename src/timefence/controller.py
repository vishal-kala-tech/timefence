import logging
import time
from pathlib import Path

from .config import load_config
from .policy import day_policy, allowed_now
from .resources import roblox, youtube
from .usage import get_usage, add_usage

MODULES = {"roblox": roblox, "youtube": youtube}


def run(app_dir: Path):
    cfg_path = app_dir / "config/rules.json"
    state = app_dir / "state"
    last_revision = None

    while True:
        try:
            cfg = load_config(cfg_path)
            interval = int(cfg.get("check_interval_seconds", 15))

            if cfg.get("revision") != last_revision:
                logging.info("Loaded config revision %s", cfg.get("revision"))
                last_revision = cfg.get("revision")

            for name, res in cfg["resources"].items():
                if not res.get("enabled") or name not in MODULES:
                    continue

                mod = MODULES[name]
                policy = day_policy(res)
                active = mod.is_active(res)
                limit = int(policy.get("daily_limit_minutes", 0)) * 60
                used = get_usage(state, name)
                limit_label = f"{limit}s" if limit else "none"

                if active and (not allowed_now(policy) or (limit and used >= limit)):
                    logging.warning("Blocking %s: schedule/limit usage=%ss limit=%s", name, used, limit_label)
                    mod.enforce(res)
                elif active:
                    total = add_usage(state, name, interval)
                    logging.info("%s active usage=%ss limit=%s", name, total, limit_label)

        except Exception:
            logging.exception("Controller cycle failed")
        time.sleep(locals().get("interval", 15))
