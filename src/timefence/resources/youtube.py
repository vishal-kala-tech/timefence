import subprocess
ACTIVE_SCRIPT='''tell application "System Events" to set cf to (exists process "Google Chrome") and frontmost of process "Google Chrome"\nif cf then\n tell application "Google Chrome"\n  if (count of windows) > 0 then\n   set u to URL of active tab of front window\n   if u contains "youtube.com/" or u contains "youtu.be/" then return "YES"\n  end if\n end tell\nend if\nreturn "NO"'''
CLOSE_SCRIPT='''tell application "Google Chrome"\nrepeat with w in windows\n set tc to {}\n repeat with t in tabs of w\n  set u to URL of t\n  if u contains "youtube.com/" or u contains "youtu.be/" then set end of tc to t\n end repeat\n repeat with t in tc\n  close t\n end repeat\nend repeat\nend tell'''
def is_active(resource):
    r=subprocess.run(["osascript","-e",ACTIVE_SCRIPT],capture_output=True,text=True); return r.stdout.strip()=="YES"
def enforce(resource): subprocess.run(["osascript","-e",CLOSE_SCRIPT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
