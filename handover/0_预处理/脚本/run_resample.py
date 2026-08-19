# -*- coding: utf-8 -*-
"""将关键测点重采样为 1 分钟宽表并保存 parquet。"""

from src import config
from src.eda import resample_device


def main() -> None:
    output_dir = config.OUTPUT_DIR / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmj_path = resample_device(
        device="cmj",
        csv_path=config.CMJ_CSV,
        state_points=config.CMJ_STATE_POINTS,
        monitor_points=config.CMJ_MONITOR_POINTS,
        output_dir=output_dir,
    )
    print(f"采煤机宽表: {cmj_path}")

    zzj_path = resample_device(
        device="zzj",
        csv_path=config.ZZJ_CSV,
        state_points=config.ZZJ_STATE_POINTS,
        monitor_points=config.ZZJ_MONITOR_POINTS,
        output_dir=output_dir,
    )
    print(f"转载机宽表: {zzj_path}")


if __name__ == "__main__":
    main()
