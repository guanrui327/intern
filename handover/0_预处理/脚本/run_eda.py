# -*- coding: utf-8 -*-
"""生成两台设备的数据 EDA 概览报告。"""

from src.eda import build_overview_report


def main() -> None:
    report_path = build_overview_report()
    print(f"EDA 报告已生成: {report_path}")


if __name__ == "__main__":
    main()
