from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "sample" / "raw_html"
SAVED_DOM_DIR = ROOT / "saved_dom"
