"""
round19 P3 存量迁移（2026-08-12）: 按当前价补录历史持仓 avg_cost。

背景: 阶段 1 修复前 add_etf/update_etf 不落库 avg_cost——已存在持仓多数为 NULL。
口径（用户已确认）: portfolio_etfs 中 avg_cost 为 NULL 且 is_active 的持仓，
用 market_data_hub 实时价/最近收盘价写 avg_cost（拿不到价保持 NULL 并列出清单，
不伪造）；shares_held 保持 NULL（继续按目标权重估算份额）。

用法: python scripts/backfill_avg_cost.py [--dry-run]
输出: 补录条数 / 保持 NULL 清单 / 迁移前后 avg_cost 非空率。
"""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(dry_run: bool = False) -> int:
    from app.database import init_db, async_session
    from app.models.portfolio import PortfolioETF
    from app.services.market_data_hub import market_data_hub
    from sqlalchemy import select

    await init_db()
    updated = 0
    skipped = []
    before_count = 0
    total_count = 0
    async with async_session() as session:
        rows = list((await session.execute(
            select(PortfolioETF).where(PortfolioETF.is_active == True)  # noqa: E712
        )).scalars().all())
        total_count = len(rows)
        before_count = sum(1 for e in rows if e.avg_cost is not None)
        for e in rows:
            if e.avg_cost is not None:
                continue
            rt = await market_data_hub.get_asset_realtime(e.symbol, e.asset_type)
            price = (rt or {}).get("price") if rt else None
            if not price:
                skipped.append(e.symbol)
                continue
            if not dry_run:
                e.avg_cost = float(price)
                updated += 1
            else:
                updated += 1
        if not dry_run:
            await session.commit()
    after_count = before_count + updated if not dry_run else before_count
    print(f"[backfill_avg_cost] total={total_count} 已有成本={before_count} "
          f"{'将补录' if dry_run else '补录'}={updated} 保持NULL={len(skipped)}")
    if skipped:
        print(f"  保持 NULL（实时价不可用，不伪造）: {skipped}")
    print(f"  avg_cost 非空率: {before_count}/{total_count} → "
          f"{after_count}/{total_count}（{'dry-run 未写库' if dry_run else '已写库'}）")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按当前价补录历史持仓 avg_cost")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.dry_run)))
