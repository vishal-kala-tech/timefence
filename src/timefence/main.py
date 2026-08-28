import logging, os
from pathlib import Path
from .controller import run

def main():
    app=Path(os.environ.get("TIME_FENCE_HOME", Path.home()/"Library/Application Support/TimeFence"))
    logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s")
    run(app)
if __name__ == "__main__": main()
