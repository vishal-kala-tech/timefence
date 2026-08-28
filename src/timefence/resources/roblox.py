import subprocess

def is_active(resource):
    return subprocess.run(["pgrep","-f",resource.get("process_pattern","Roblox")],stdout=subprocess.DEVNULL).returncode == 0

def enforce(resource):
    subprocess.run(["pkill","-9","-f",resource.get("process_pattern","Roblox")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
