from pathlib import Path

APP_TITLE = "EZMount"
KOFI_URL = "https://ko-fi.com/username"
STARTUP_PREFIX = "EZMount_"

def parse_remotes_from_conf(conf_text: str):
    remotes = []
    for line in conf_text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]") and len(s) > 2:
            name = s[1:-1].strip()
            if name and name not in remotes:
                remotes.append(name)
    return remotes

def conf_basename(path):
    try:
        return Path(path).name
    except Exception:
        return "(none)"
