from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.services.population_cache import preprocess_population_cache


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess local population GeoTIFF into MySQL cache tables.")
    parser.add_argument("--stride", type=int, default=520, help="Sampling stride in raster pixels. Smaller is more accurate but slower.")
    parser.add_argument("--max-samples", type=int, default=7000, help="Max heatmap samples stored in database.")
    parser.add_argument("--reset", action="store_true", help="Clear existing population cache for 2025 before preprocessing.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = preprocess_population_cache(
            db,
            stride_pixels=args.stride,
            max_samples=args.max_samples,
            reset=args.reset,
        )
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
