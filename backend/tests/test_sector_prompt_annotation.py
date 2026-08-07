"""
O26 (docs/archived/round8-rediagnosis.md §7 §5.1H): 板块技术分析点位口径标注。

现象: 板块分析报告报"指数报收 50118.43 点"，但全文无「板块指数点位」显式标签——
专业读者易误读为成分股或沪深大盘。验收: 报告 prompt 首段含「板块指数（BKxxxx）
点位」表述；技术面注明均线周期。
"""

import inspect
import pytest

from app.routers import analysis as analysis_router


class TestSectorPromptAnnotation:
    def test_sector_prompt_annotates_index_point(self):
        """prompt 首段含「板块指数（BKxxxx，东财板块行情）点位」显式口径。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "板块指数（{sector_code}，东财板块行情）" in src
        assert "点位为" in src
        assert "非成分股均价" in src
        assert "亦非沪深大盘指数" in src

    def test_sector_prompt_notes_ma_period(self):
        """技术面注明均线周期（最近 30 个交易日日线）。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "均线周期为最近 30 个交易日日线" in src

    def test_sector_prompt_keeps_constituents_news(self):
        """成分股/资讯注入保留（O26 只加标注，不删既有注入）。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "成分股：{json.dumps(constituents" in src
        assert "资讯：{json.dumps(news" in src
