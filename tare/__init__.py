"""
tare — 给 Agent Harness 装上因果测功机

Usage:
    tare audit                     # 静默审计当前 WorkBuddy harness
    tare audit --trace-dir <path>  # 指定 trace 目录
    tare report --format md        # 生成报告
"""

__version__ = "0.1.0"
__all__ = ["audit", "rules", "adapters"]
