"""Phase 2.8 G4: 编码 roundtrip 测试。

验证中文文本写入 DB 后读回完全一致（无 mojibake）。
"""

import pytest


@pytest.mark.asyncio
async def test_database_encoding_roundtrip():
    """写入中文字符串，读回后完全一致。"""
    from app.database import async_session
    from app.models.portfolio_design import PortfolioDesign

    test_text = "稳健型方案：低波稳健配置，控制回撤，适合保守型投资者"
    record_id = None

    async with async_session() as db:
        record = PortfolioDesign(
            capital=100000,
            risk_profile="balanced",
            design_text=test_text,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        record_id = record.id

    assert record_id is not None, "Failed to create test record"

    # 重新读取
    async with async_session() as db:
        loaded = await db.get(PortfolioDesign, record_id)
        assert loaded is not None, f"Failed to load record {record_id}"
        assert loaded.design_text == test_text, (
            f"Mojibake detected!\n  wrote: {repr(test_text)}\n  read:  {repr(loaded.design_text)}"
        )

    # Cleanup: 删除测试记录
    async with async_session() as db:
        record = await db.get(PortfolioDesign, record_id)
        if record:
            await db.delete(record)
            await db.commit()
