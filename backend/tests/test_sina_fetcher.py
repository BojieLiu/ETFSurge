"""P1: 新浪财经数据源 — 单元测试。所有外部调用必须 mock。"""

from unittest.mock import patch, MagicMock, AsyncMock
import pandas as pd
import pytest
import json
from datetime import date

from app.fetchers.sina_fetcher import SinaFetcher


class TestSinaFetcher:
    """新浪财经数据源测试"""

    @pytest.fixture
    def fetcher(self):
        return SinaFetcher(timeout=10)

    # === 实时行情测试 ===

    @pytest.mark.asyncio
    async def test_get_realtime_success(self, fetcher):
        """实时行情获取成功"""
        mock_response = (
            'var hq_str_sh510300="沪深300ETF,3.500,3.480,3.520,3.450,3.500,'
            '1000000,35000000,0.020,0.57,2024-01-15,15:00:00";\n'
            'var hq_str_sz159915="创业板ETF,2.100,2.080,2.120,2.050,2.100,'
            '500000,10500000,0.030,1.45,2024-01-15,15:00:00";\n'
        )
        
        with patch.object(fetcher.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value.text = mock_response
            mock_get.return_value.encoding = "gbk"
            
            result = await fetcher.get_realtime(["sh510300", "sz159915"])
            
            assert len(result) == 2
            assert result[0]["symbol"] == "510300"
            assert result[0]["name"] == "沪深300ETF"
            assert result[0]["price"] == 3.50
            assert result[0]["change_pct"] == 0.57
            assert result[1]["symbol"] == "159915"
            assert result[1]["name"] == "创业板ETF"

    @pytest.mark.asyncio
    async def test_get_realtime_empty(self, fetcher):
        """空符号列表返回空"""
        result = await fetcher.get_realtime([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_realtime_network_error(self, fetcher):
        """网络错误返回空"""
        with patch.object(fetcher.client, 'get', side_effect=Exception("Network error")):
            result = await fetcher.get_realtime(["510300"])
            assert result == []

    # === 历史 K线测试 ===

    @pytest.mark.asyncio
    async def test_get_kline_success(self, fetcher):
        """历史K线获取成功"""
        mock_data = [
            {"day": "2024-01-02", "open": 3.45, "high": 3.55, "low": 3.40, "close": 3.50, "volume": 1000000},
            {"day": "2024-01-03", "open": 3.50, "high": 3.58, "low": 3.48, "close": 3.55, "volume": 1200000},
        ]
        
        with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            df = await fetcher.get_kline("510300", period="d", count=2, adjust="qfq")
            
            assert not df.empty
            assert len(df) == 2
            assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume"]
            assert df.iloc[0]["close"] == 3.50

    @pytest.mark.asyncio
    async def test_get_kline_different_periods(self, fetcher):
        """不同周期参数"""
        periods = {"5": "5", "15": "15", "30": "30", "60": "60", "d": "d", "w": "w", "m": "m"}
        
        for period, expected in periods.items():
            with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
                mock_get.return_value = [{"day": "2024-01-02", "open": 3.45, "high": 3.55, "low": 3.40, "close": 3.50, "volume": 1000000}]
                
                df = await fetcher.get_kline("510300", period=period, count=1)
                assert not df.empty
                
                # 验证请求参数
                call_args = mock_get.call_args
                assert call_args[1]["params"]["scale"] == expected

    @pytest.mark.asyncio
    async def test_get_kline_adjust_types(self, fetcher):
        """复权类型"""
        adjust_types = {"qfq": "qfq", "hfq": "hfq", "none": "none"}
        
        for adjust, expected in adjust_types.items():
            with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
                mock_get.return_value = []
                
                await fetcher.get_kline("510300", period="d", count=1, adjust=adjust)
                
                call_args = mock_get.call_args
                if adjust != "none":
                    assert call_args[1]["params"]["adjust"] == expected

    # === 历史K线（带复权）===

    @pytest.mark.asyncio
    async def test_get_kline_history_with_adjust(self, fetcher):
        """带复权的历史K线"""
        mock_data = [
            {"日期": "2024-01-02", "开盘": 3.45, "最高": 3.55, "最低": 3.40, "收盘": 3.50, "成交量": 1000000},
        ]
        
        with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            df = await fetcher.get_kline("510300", period="d", count=10, adjust="qfq")
            
            assert not df.empty
            # 验证请求参数包含 adjust
            call_args = fetcher._get_json.call_args
            assert call_args[1]["params"]["adjust"] == "qfq"

    # === 财务报表测试 ===

    @pytest.mark.asyncio
    async def test_get_financial_report_main(self, fetcher):
        """主表财务报表"""
        # Mock HTML 表格
        mock_html = """
        <table>
            <tr><td>报表日期</td><td>2023-12-31</td></tr>
            <tr><td>营业收入(万元)</td><td>1000000</td></tr>
            <tr><td>净利润(万元)</td><td>100000</td></tr>
        </table>
        """
        
        with patch.object(fetcher, '_get_html_tables', new_callable=AsyncMock) as mock_get:
            mock_df = pd.DataFrame({
                "报表日期": ["2023-12-31"],
                "营业收入(万元)": [1000000],
                "净利润(万元)": [100000]
            })
            mock_get.return_value = [mock_df]
            
            result = await fetcher.get_financial_report("510300", report_type="cwzb")
            
            assert not result.empty
            assert "营业收入(万元)" in result.columns

    @pytest.mark.asyncio
    async def test_get_financial_report_types(self, fetcher):
        """不同报表类型"""
        report_types = ["cwzb", "lr", "xjll", "zcfz"]
        
        for rtype in report_types:
            with patch.object(fetcher, '_get_html_tables', new_callable=AsyncMock) as mock_get:
                mock_df = pd.DataFrame({"报表日期": ["2023-12-31"], "数值": [100]})
                mock_get.return_value = [mock_df]
                
                result = await fetcher.get_financial_report("510300", report_type=rtype)
                assert not result.empty
                
                # 验证 URL 参数
                call_args = fetcher._get_html_tables.call_args
                assert rtype in call_args[0][0]

    # === 板块/概念成分股测试 ===

    @pytest.mark.asyncio
    async def test_get_concept_stocks(self, fetcher):
        """概念板块成分股"""
        mock_data = [
            {"代码": "510300", "名称": "沪深300ETF", "最新价": 3.50},
            {"代码": "560600", "名称": "中证A500ETF", "最新价": 3.20},
        ]
        
        with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetcher.get_concept_stocks("bk_gn_123")
            
            assert result == ["510300", "560600"]
            
            call_args = fetcher._get_json.call_args
            assert call_args[1]["params"]["node"] == "bk_gn_123"

    # === 期权链/隐含波动率测试 ===

    @pytest.mark.asyncio
    async def test_get_option_chain(self, fetcher):
        """期权链/隐含波动率"""
        mock_jsonp = """
        IO.XSRV2.CallbackOptionAll([
            {"symbol": "510300", "iv": 0.25, "delta": 0.5, "gamma": 0.02, "theta": -0.05, "vega": 0.1, "rho": 0.01},
            {"symbol": "510300", "iv": 0.30, "delta": 0.3, "gamma": 0.03, "theta": -0.08, "vega": 0.15, "rho": 0.02}
        ]);
        """
        
        with patch.object(fetcher, '_get_jsonp', new_callable=AsyncMock) as mock_get:
            mock_df = pd.DataFrame({
                "symbol": ["510300", "510300"],
                "iv": [0.25, 0.30],
                "delta": [0.5, 0.3],
            })
            mock_get.return_value = mock_df
            
            result = await fetcher.get_option_chain("510300")
            
            assert not result.empty
            assert "iv" in result.columns
            assert "delta" in result.columns

    # === 板块/概念成分股测试 ===

    @pytest.mark.asyncio
    async def test_get_sector_stocks(self, fetcher):
        """板块成分股"""
        mock_data = [
            {"代码": "510300", "名称": "沪深300ETF"},
            {"代码": "560600", "名称": "中证A500ETF"},
        ]
        
        with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetcher.get_sector_stocks("bk_gn_123")
            
            assert result == ["510300", "560600"]

    # === 期权链/希腊值测试 ===

    @pytest.mark.asyncio
    async def test_get_option_chain_greeks(self, fetcher):
        """期权链希腊值"""
        mock_jsonp = """
        IO.XSRV2.CallbackOptionAll([
            {"code": "10002527", "name": "50ETF购3月3.4", "iv": 0.25, "delta": 0.5, "gamma": 0.02, "theta": -0.05, "vega": 0.1, "rho": 0.01},
            {"code": "10002528", "name": "50ETF沽3月3.4", "iv": 0.30, "delta": -0.5, "gamma": 0.03, "theta": -0.08, "vega": 0.15, "rho": 0.02}
        ]);
        """
        
        with patch.object(fetcher, '_get_jsonp', new_callable=AsyncMock) as mock_get:
            mock_df = pd.DataFrame({
                "code": ["10002527", "10002528"],
                "iv": [0.25, 0.30],
                "delta": [0.5, -0.5],
                "gamma": [0.02, 0.03],
                "theta": [-0.05, -0.08],
                "vega": [0.1, 0.15],
                "rho": [0.01, 0.02],
            })
            mock_get.return_value = mock_df
            
            result = await fetcher.get_option_chain("510050")
            
            assert not result.empty
            assert "delta" in result.columns
            assert "gamma" in result.columns
            assert "theta" in result.columns
            assert "vega" in result.columns
            assert "rho" in result.columns

    # === 财务报表测试 ===

    @pytest.mark.asyncio
    async def test_get_financial_report_main(self, fetcher):
        """主表财务报表"""
        mock_html = """
        <table>
            <tr><td>报表日期</td><td>2023-12-31</td></tr>
            <tr><td>营业收入(万元)</td><td>1000000</td></tr>
            <tr><td>净利润(万元)</td><td>100000</td></tr>
        </table>
        """
        
        with patch.object(fetcher, '_get_html_tables', new_callable=AsyncMock) as mock_get:
            mock_df = pd.DataFrame({
                "报表日期": ["2023-12-31"],
                "营业收入(万元)": [1000000],
                "净利润(万元)": [100000]
            })
            mock_get.return_value = [mock_df]
            
            result = await fetcher.get_financial_report("510300", report_type="cwzb")
            
            assert not result.empty
            assert "营业收入(万元)" in result.columns

    # === 板块/概念成分股测试 ===

    @pytest.mark.asyncio
    async def test_get_concept_stocks(self, fetcher):
        """概念板块成分股"""
        mock_data = [
            {"代码": "510300", "名称": "沪深300ETF", "最新价": 3.50},
            {"代码": "560600", "名称": "中证A500ETF", "最新价": 3.20},
        ]
        
        with patch.object(fetcher, '_get_json', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetcher.get_concept_stocks("bk_gn_123")
            
            assert result == ["510300", "560600"]
            
            call_args = fetcher._get_json.call_args
            assert call_args[1]["params"]["node"] == "bk_gn_123"

    # === 期权链/隐含波动率测试 ===

    @pytest.mark.asyncio
    async def test_get_option_chain(self, fetcher):
        """期权链/隐含波动率"""
        mock_jsonp = """
        IO.XSRV2.CallbackOptionAll([
            {"symbol": "510300", "iv": 0.25, "delta": 0.5, "gamma": 0.02, "theta": -0.05, "vega": 0.1, "rho": 0.01},
            {"symbol": "510300", "iv": 0.30, "delta": 0.3, "gamma": 0.03, "theta": -0.08, "vega": 0.15, "rho": 0.02}
        ]);
        """
        
        with patch.object(fetcher, '_get_jsonp', new_callable=AsyncMock) as mock_get:
            mock_df = pd.DataFrame({
                "symbol": ["510300", "510300"],
                "iv": [0.25, 0.30],
                "delta": [0.5, 0.3],
            })
            mock_get.return_value = mock_df
            
            result = await fetcher.get_option_chain("510300")
            
            assert not result.empty
            assert "iv" in result.columns
            assert "delta" in result.columns

    # === 错误处理测试 ===

    @pytest.mark.asyncio
    async def test_timeout_handling(self, fetcher):
        """超时处理"""
        with patch.object(fetcher.client, 'get', side_effect=asyncio.TimeoutError()):
            result = await fetcher.get_realtime(["510300"])
            assert result == []

    @pytest.mark.asyncio
    async def test_http_error_handling(self, fetcher):
        """HTTP错误处理"""
        with patch.object(fetcher.client, 'get', side_effect=Exception("HTTP 500")):
            result = await fetcher.get_realtime(["510300"])
            assert result == []

    @pytest.mark.asyncio
    async def test_json_decode_error(self, fetcher):
        """JSON解析错误处理"""
        with patch.object(fetcher.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value.text = "invalid json"
            result = await fetcher.get_realtime(["510300"])
            assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])