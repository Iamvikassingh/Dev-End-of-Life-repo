"""Source registry — maps canonical products to lifecycle discovery sources."""
import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "lifecycle_data", "source_registry.json"
)

# Normalize service name → canonical product slug used in source_registry.json
_ALIASES: dict = {
    "lambda":           "aws-lambda",
    "aws_lambda":       "aws-lambda",
    "aws-lambda":       "aws-lambda",
    "awslambda":        "aws-lambda",
    "eks":              "amazon-eks",
    "amazon-eks":       "amazon-eks",
    "amazon_eks":       "amazon-eks",
    "amazoneks":        "amazon-eks",
    "ubuntu":           "ubuntu",
    "ubuntu lts":       "ubuntu",
    "ubuntu_lts":       "ubuntu",
    "ec2_ubuntu":       "ubuntu",
}


def normalize_product(product: str) -> str:
    """Return canonical product slug, e.g. 'Lambda' → 'aws-lambda'."""
    key = product.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    return _ALIASES.get(key, product.lower())


def load_source_registry() -> dict:
    path = os.environ.get("LIFECYCLE_REGISTRY_PATH", _REGISTRY_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug("Lifecycle source registry not found at %s", path)
        return {"version": 1, "defaults": {}, "products": {}}
    except Exception as exc:
        logger.warning("Lifecycle source registry load error: %s", exc)
        return {"version": 1, "defaults": {}, "products": {}}


def get_sources_for_product(product: str) -> List[dict]:
    """Return sources for product sorted by priority (ascending). Empty if none."""
    canonical = normalize_product(product)
    registry = load_source_registry()
    cfg = registry.get("products", {}).get(canonical)
    if not cfg:
        return []
    return sorted(cfg.get("sources", []), key=lambda s: s.get("priority", 99))
