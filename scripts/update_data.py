"""데이터 수집 → data/series.parquet 저장 (GitHub Actions / 로컬용).

실행: python scripts/update_data.py
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetch import fetch_all, PARQUET, DATA_DIR  # noqa: E402


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    df = fetch_all()
    df.to_parquet(PARQUET)
    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": int(len(df)),
        "last_month": str(df.index[-1].date()),
        "columns": list(df.columns),
    }
    with open(os.path.join(DATA_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"saved {len(df)} rows (~{df.index[-1].date()}) -> {PARQUET}")


if __name__ == "__main__":
    main()
