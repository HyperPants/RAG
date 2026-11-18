import logging
from pathlib import Path

from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config():
    load_dotenv(ROOT / ".env")
    with (ROOT / "config.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def configure_logging():
    path = ROOT / "logs" / "app.log"
    path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
