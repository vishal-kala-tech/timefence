import subprocess


def is_active(resource):
    process_pattern = resource.get("process_pattern", "Roblox")

    result = subprocess.run(
        ["pgrep", "-f", process_pattern],
        stdout=subprocess.DEVNULL,
    )

    return result.returncode == 0


def enforce(resource):
    process_pattern = resource.get("process_pattern", "Roblox")

    subprocess.run(
        ["pkill", "-9", "-f", process_pattern],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
