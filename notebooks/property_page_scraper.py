import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_pricing_analytics.scraping.booking import *  # noqa: F403
from tourism_pricing_analytics.scraping.booking import main


if __name__ == "__main__":
    main()
