# -*- coding: utf-8 -*-
"""积分抽奖量化占卜 —— 命令行入口。

    python run.py                         用内置样例数据出报告（不用 Token，不联网）
    python run.py --live                  连真实麦当劳 MCP（需环境变量 MCD_MCP_TOKEN）
    python run.py --json                  输出 JSON，方便给网页或脚本用
    python run.py --tools                 列出 MCP 服务端有哪些工具（排查用）

报告全程只读：不会替你抽奖，也不会替你下单。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import date, datetime

from mcd_quant import engine, live, report, sample
from mcd_quant.client import McpError


def _inner_list(raw):
    """MCP 响应的外层是 {"success":..,"data":[..]}，这里把数组掏出来。"""
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return raw["data"]
    if isinstance(raw, list):
        return raw
    return []


def _prizes_of(raw) -> list[dict]:
    if isinstance(raw, dict):
        d = raw.get("data")
        if isinstance(d, dict):
            return [p for p in (d.get("prizes") or []) if isinstance(p, dict)]
    return []


def _snapshot_dict(snap: report.Snapshot) -> dict:
    """给 JSON 输出用。dataclasses.asdict 拿不到 @property，这里补全统计字段。"""
    d = dataclasses.asdict(snap)
    v = snap.verdict
    d["verdict"].update({
        "prize_count": len(v.rows),
        "win": v.win,
        "lose": v.lose,
        "unknown": v.unknown,
        "best_yuan": v.best_yuan,
        "draws_affordable": v.draws_affordable,
    })
    return d


def build(source: str, token: str, day: str) -> report.Snapshot:
    """收集数据 → 算 → 拼成一份可以渲染的报告。"""
    errors: dict = {}

    if source == "live":
        raw, errors = live.fetch(token)
        lottery = engine.lottery_from_raw(raw.get("lottery"))
        redeem = engine.redeem_items(_inner_list(raw.get("mall")))
        account = engine.account_from_raw(raw.get("account"))
        campaigns = live.campaigns_today(raw.get("campaigns"), day)
        prizes = _prizes_of(raw.get("prizes"))
    else:
        lottery = engine.lottery_from_raw(sample.LOTTERY)
        redeem = engine.redeem_items(sample.MALL)
        account = engine.account_from_raw(sample.ACCOUNT)
        campaigns = list(sample.CAMPAIGNS_TODAY)
        prizes = list(sample.MY_PRIZES)

    if lottery is None or lottery.cost_points <= 0:
        raise McpError("没拿到可用的抽奖活动信息，无法继续。")

    verdict = engine.evaluate(lottery, redeem, account.get("available", 0.0))
    if verdict is None:
        raise McpError("积分商城没有可用的兑换数据，算不出「1 积分值多少钱」。")

    advice = engine.compare(verdict)
    mood = engine.mood(verdict, advice, account, campaigns)

    return report.Snapshot(
        day=day,
        source=source,
        lottery=lottery,
        verdict=verdict,
        advice=advice,
        mood=mood,
        account=account,
        campaigns=campaigns,
        my_prizes=prizes,
        redeem=redeem,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        errors=errors,
    )


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="run.py",
        description="积分抽奖量化占卜：算清 1 积分值多少钱、抽一次亏不亏、该抽还是该换。",
    )
    parser.add_argument("--live", action="store_true", help="连真实麦当劳 MCP（需 MCD_MCP_TOKEN）")
    parser.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""), help="MCP Token，默认读环境变量")
    parser.add_argument("--date", default=date.today().isoformat(), help="报告日期 YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--tools", action="store_true", help="列出服务端有哪些 MCP 工具")
    args = parser.parse_args(argv)

    try:
        if args.tools:
            for tool in live.list_tools(args.token):
                print(f"- {tool.get('name')}: {(tool.get('description') or '')[:60]}")
            return 0

        snap = build("live" if args.live else "sample", args.token, args.date)

        if args.json:
            print(json.dumps(_snapshot_dict(snap), ensure_ascii=False, indent=2))
        else:
            print(report.render(snap))
        return 0
    except McpError as exc:
        print(f"[出错] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
