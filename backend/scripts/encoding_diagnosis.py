"""
encoding_diagnosis.py — 数据库编码诊断。

直接从 DB 读取 portfolio_designs 表中的 design_text 字段，
检查中文是否正确存储（而不是 mojibake/乱码）。

用法：
    cd backend && python scripts/encoding_diagnosis.py
"""
import asyncio
import sys
import os

# Add backend/ to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def diagnose():
    """读取 DB 中的设计文本并诊断编码问题。"""
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.db")
    db_path = os.path.normpath(db_path)

    if not os.path.exists(db_path):
        print(f"[DIAG] DB 文件不存在: {db_path}")
        print("[DIAG] 跳过编码诊断（可能是首次运行）")
        return

    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            # 检查表是否存在
            cur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_designs'"
            )
            row = await cur.fetchone()
            if not row:
                print("[DIAG] portfolio_designs 表不存在，跳过编码诊断")
                return

            # 获取最近 3 条记录
            cur = await db.execute(
                "SELECT id, design_text, strategy_label FROM portfolio_designs "
                "ORDER BY id DESC LIMIT 3"
            )
            rows = await cur.fetchall()

            if not rows:
                print("[DIAG] portfolio_designs 表为空，跳过编码诊断")
                return

            print(f"[DIAG] 读取到 {len(rows)} 条设计记录:")
            print()

            for row_id, design_text, strategy_label in rows:
                print(f"--- Design ID={row_id} ---")

                # 检查 strategy_label
                print(f"  strategy_label: {strategy_label!r}")
                if strategy_label:
                    has_garbled = any(ord(c) > 0xFFFD or c == '\ufffd' for c in strategy_label)
                    print(f"  乱码判定: {'⚠️ 可能乱码' if has_garbled else '✅ 正常'}")

                # 检查 design_text
                if design_text:
                    text_len = len(design_text)
                    # 统计常见中文字符数
                    cjk_count = sum(1 for c in design_text if '\u4e00' <= c <= '\u9fff')
                    replacement_count = design_text.count('\ufffd')

                    print(f"  design_text 长度: {text_len} 字符")
                    print(f"  中文字符数: {cjk_count}")
                    print(f"  替换字符 \\ufffd 数量: {replacement_count}")

                    if replacement_count > 0:
                        print(f"  ⚠️ 乱码: 发现 {replacement_count} 个替换字符(\\ufffd)")
                    elif cjk_count > 0:
                        print(f"  ✅ 正常: 包含 {cjk_count} 个中文字符")
                    else:
                        print(f"  ⚠️ 无中文: design_text 中没有中文字符")

                    # 显示开头 100 字符
                    preview = design_text[:100]
                    print(f"  预览: {preview!r}")
                else:
                    print(f"  design_text: (空)")

                print()

        print("[DIAG] 诊断完成")

    except Exception as e:
        print(f"[DIAG] 诊断失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    asyncio.run(diagnose())


if __name__ == "__main__":
    main()
