"""
tare.cli — 命令行入口

    tare audit [--trace-dir PATH] [--format text|md|json] [-o FILE]
    tare info  [--trace-dir PATH]
"""
import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .adapters import get_adapter
from .audit import audit
from .report import RENDERERS

DEFAULT_TRACE_DIR = "~/.workbuddy-ai/traces"


def _load(adapter_name: str, trace_dir: str):
    ad = get_adapter(adapter_name, trace_dir)
    idents = ad.discover()
    traces = []
    for i in idents:
        try:
            traces.append(ad.load(i))
        except Exception as e:
            print(f"  ! 跳过 {Path(i).name}: {e}", file=sys.stderr)
    return ad, traces


def cmd_audit(args):
    trace_dir = os.path.expanduser(args.trace_dir)
    if not Path(trace_dir).exists():
        print(f"错误：trace 目录不存在: {trace_dir}", file=sys.stderr)
        print("提示：用 --trace-dir 指定，或 --adapter generic 接入自有数据。",
              file=sys.stderr)
        return 2

    ad, traces = _load(args.adapter, trace_dir)
    if not traces:
        print(f"错误：{trace_dir} 下未找到可解析的 trace。", file=sys.stderr)
        return 2

    result = audit(traces, home=ad.home())
    out = RENDERERS[args.format](result, color=sys.stdout.isatty()) \
        if args.format == "text" else RENDERERS[args.format](result)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"报告已写入: {args.output}")
    else:
        print(out)
    return 0


def cmd_info(args):
    trace_dir = os.path.expanduser(args.trace_dir)
    ad, traces = _load(args.adapter, trace_dir)
    print(f"适配器      : {ad.name}")
    print(f"trace 目录  : {trace_dir}")
    print(f"harness 根  : {ad.home()}")
    print(f"trace 数    : {len(traces)}")
    if traces:
        tot_in = sum(t.input_tokens for t in traces)
        tot_ca = sum(t.cached_tokens for t in traces)
        models = {t.model for t in traces if t.model}
        print(f"模型        : {', '.join(sorted(models)) or '—'}")
        print(f"总 input    : {tot_in:,}")
        print(f"总 cached   : {tot_ca:,}  ({tot_ca/tot_in*100:.1f}%)" if tot_in else "")
        sizes = [(len(t.system_prompt), t.id) for t in traces]
        sizes.sort(reverse=True)
        print(f"最大 system : {sizes[0][0]:,} chars ({sizes[0][1]})")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="tare",
        description="tare — 给 Agent Harness 装上因果测功机",
    )
    p.add_argument("--version", action="version", version=f"tare {__version__}")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("audit", help="静默审计 harness")
    a.add_argument("--trace-dir", default=DEFAULT_TRACE_DIR,
                   help=f"trace 目录（默认 {DEFAULT_TRACE_DIR}）")
    a.add_argument("--adapter", default="workbuddy",
                   choices=["workbuddy", "generic"], help="适配器")
    a.add_argument("--format", default="text", choices=list(RENDERERS),
                   help="输出格式")
    a.add_argument("-o", "--output", help="写入文件而非 stdout")
    a.set_defaults(func=cmd_audit)

    i = sub.add_parser("info", help="查看 trace 数据概览")
    i.add_argument("--trace-dir", default=DEFAULT_TRACE_DIR)
    i.add_argument("--adapter", default="workbuddy",
                   choices=["workbuddy", "generic"])
    i.set_defaults(func=cmd_info)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
