"""python -m is not used; run: uv run python eval/sysops_decide/runner.py"""

from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("runner.py")), run_name="__main__")
