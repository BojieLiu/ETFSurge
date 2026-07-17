"""P1: 通达信双轨数据源 — 单元测试。所有外部调用必须 mock。"""

from unittest.mock import patch, MagicMock, AsyncMock
import pandas as pd
import pytest
from datetime import date, datetime

from app.fetchers.tdx_fetcher import TdxFetcher, TdxConfig


class TestTdxConfig:
    """通达信配置测试"""

    def test_default_config(self):
        config = TdxConfig()
        assert config.local_data_root == "E:/tdx_data"
        assert config.pool_size == 3
        assert config.timeout == 10

    def test_custom_config(self):
        config = TdxConfig(
            local_data_root="D:/my_tdx_data",
            pool_size=5,
            timeout=30
        )
        assert config.local_data_root == "D:/my_tdx_data"
        assert config.pool_size == 5
        assert config.timeout == 30


class TestTdxFetcher:
    """通达信双轨数据源测试"""

    @pytest.fixture
    def config(self):
        return TdxConfig(local_data_root="E:/test_tdx_data")

    @pytest.fixture
    def fetcher(self, config):
        return TdxFetcher(config)

    @pytest.fixture
    def mock_tdx_api(self):
        """Mock pytdx API"""
        with patch("pytdx.hq.TdxHq_API") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api
            yield mock_api

    # === 本地 CSV 读取测试 ===

    @pytest.fixture
    def mock_local_csv(self, tmp_path):
        """创建模拟通达信 CSV 文件"""
        csv_dir = tmp_path / "tdx_data"
        csv_dir.mkdir()
        
        # 创建测试 CSV 文件
        csv_content = """日期,开盘,最高,最低,收盘,成交量,成交额
2024-01-02,3.45,3.55,3.40,3.50,1000000,35000000
2024-01-03,3.50,3.58,3.48,3.55,1200000,42600000
2024-01-04,3.55,3.60,3.52,3.58,900000,32220000
"""
        csv_file = csv_dir / "510300_D.csv"
        csv_file.write_text(csv_content, encoding="gbk")
        
        return str(csv_dir)

    def test_read_local_kline_success(self, fetcher, mock_local_csv):
        """成功读取本地 CSV K线"""
        with patch.object(fetcher.config, 'local_data_root', mock_local_csv):
            df = fetcher.read_local_kline("510300", period="D")
            
            assert not df.empty
            assert len(df) == 3
            assert "open" in df.columns
            assert "high" in df.columns
            assert "low" in df.columns
            assert "close" in df.columns
            assert "volume" in df.columns
            assert "turnover" in df.columns

    def test_read_local_kline_file_not_found(self, fetcher, tmp_path):
        """文件不存在返回空 DataFrame"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        with patch.object(fetcher.config, 'local_data_root', str(empty_dir)):
            df = fetcher.read_local_kline("999999", period="D")
            assert df.empty

    def test_read_local_kline_encoding_gbk(self, fetcher, tmp_path):
        """GBK 编码正确解析"""
        csv_dir = tmp_path / "tdx_data"
        csv_dir.mkdir()
        
        # 包含中文列名的 CSV
        csv_content = "日期,开盘,最高,最低,收盘,成交量,成交额\n2024-01-02,3.45,3.55,3.40,3.50,1000000,35000000\n"
        csv_file = csv_dir / "510300_D.csv"
        csv_file.write_text(csv_content, encoding="gbk")
        
        with patch.object(fetcher.config, 'local_data_root', str(csv_dir)):
            df = fetcher.read_local_kline("510300", period="D")
            assert not df.empty
            assert df.iloc[0]["close"] == 3.50

    # === pytdx 远程拉取测试 ===

    @pytest.mark.asyncio
    async def test_get_kline_remote_success(self, fetcher, mock_tdx_api):
        """远程获取 K线成功"""
        # Mock 返回数据
        mock_bars = [
            {"datetime": "2024-01-02", "open": 3.45, "high": 3.55, "low": 3.40, "close": 3.50, "vol": 1000000, "amount": 35000000},
            {"datetime": "2024-01-03", "open": 3.50, "high": 3.58, "low": 3.48, "close": 3.55, "vol": 1200000, "amount": 42600000},
        ]
        mock_tdx_api.get_security_bars.return_value = mock_bars
        
        df = await fetcher.get_kline("510300", period="D", count=2)
        
        assert not df.empty
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume", "turnover"]
        assert df.iloc[0]["close"] == 3.50

    @pytest.mark.asyncio
    async def test_get_kline_remote_empty(self, fetcher, mock_tdx_api):
        """远程返回空数据"""
        mock_tdx_api.get_security_bars.return_value = []
        
        df = await fetcher.get_kline("510300", period="D", count=2)
        assert df.empty

    @pytest.mark.asyncio
    async def test_get_kline_remote_timeout(self, fetcher, mock_tdx_api):
        """远程调用超时返回空 DataFrame"""
        import asyncio
        mock_tdx_api.get_security_bars.side_effect = asyncio.TimeoutError()
        
        df = await fetcher.get_kline("510300", period="D", count=2)
        assert df.empty

    @pytest.mark.asyncio
    async def test_get_realtime_quote_success(self, fetcher, mock_tdx_api):
        """实时行情获取成功"""
        mock_quotes = [{
            "code": "510300",
            "price": 3.50,
            "change": 0.02,
            "change_pct": 0.57,
            "volume": 1000000,
            "turnover": 35000000,
            "bid1": 3.50, "bid1_v": 1000,
            "ask1": 3.51, "ask1_v": 1000,
        }]
        mock_tdx_api.get_security_quotes.return_value = mock_quotes
        
        result = await fetcher.get_realtime_quote(["510300"])
        
        assert len(result) == 1
        assert result[0]["code"] == "510300"
        assert result[0]["price"] == 3.50

    @pytest.mark.asyncio
    async def test_get_kline_batch(self, fetcher, mock_tdx_api):
        """批量获取 K线"""
        mock_bars = [
            {"datetime": "2024-01-02", "open": 3.45, "high": 3.55, "low": 3.40, "close": 3.50, "vol": 1000000, "amount": 35000000},
        ]
        mock_tdx_api.get_security_bars.return_value = mock_bars
        
        symbols = ["510300", "560600", "510500"]
        results = await fetcher.get_kline_batch(symbols, period="D", count=1)
        
        assert len(results) == 3
        for symbol in symbols:
            assert symbol in results
            assert not results[symbol].empty

    # === 市场代码判断测试 ===

    @pytest.mark.parametrize("symbol,expected_market", [
        ("510300", 0),  # SH ETF
        ("560600", 0),  # SH ETF
        ("159915", 1),  # SZ ETF
        ("159915", 1),  # SZ ETF
        ("518880", 0),  # SH 黄金
        ("511090", 0),  # SH 债券
        ("159980", 1),  # SZ 有色
    ])
    def test_get_market(self, fetcher, symbol, expected_market):
        """市场代码判断"""
        assert fetcher._get_market(symbol) == expected_market

    # === 周期映射测试 ===

    @pytest.mark.parametrize("period,expected", [
        ("1m", 0),
        ("5m", 1),
        ("15m", 2),
        ("30m", 3),
        ("60m", 4),
        ("D", 5),
        ("W", 6),
        ("M", 7),
    ])
    def test_period_mapping(self, fetcher, period, expected):
        """周期映射正确"""
        assert fetcher._period_map[period] == expected


class TestTdxFetcherIntegration:
    """集成测试：双轨制优先级"""

    @pytest.mark.asyncio
    async def test_local_csv_priority_over_remote(self):
        """本地 CSV 优先于远程 pytdx"""
        fetcher = TdxFetcher(TdxConfig(local_data_root="E:/test_data"))
        
        with patch.object(fetcher, 'read_local_kline', new_callable=AsyncMock) as mock_local, \
             patch.object(fetcher, 'get_kline', new_callable=AsyncMock) as mock_remote:
            
            mock_local.return_value = pd.DataFrame({"close": [3.50]})
            mock_remote.return_value = pd.DataFrame({"close": [3.55]})
            
            # get_kline 应优先调用本地
            result = await fetcher.get_kline("510300", period="D")
            
            mock_local.assert_called_once()
            mock_remote.assert_not_called()  # 本地有数据，不调用远程
            assert result.iloc[0]["close"] == 3.50

    @pytest.mark.asyncio
    async def test_fallback_to_remote_when_local_empty(self):
        """本地无数据时回退到远程"""
        fetcher = TdxFetcher(TdxConfig())
        
        with patch.object(fetcher, 'read_local_kline', new_callable=AsyncMock) as mock_local, \
             patch.object(fetcher, 'get_kline', new_callable=AsyncMock) as mock_remote:
            
            mock_local.return_value = pd.DataFrame()  # 空
            mock_remote.return_value = pd.DataFrame({"close": [3.55]})
            
            result = await fetcher.get_kline("510300", period="D")
            
            mock_local.assert_called_once()
            mock_remote.assert_called_once()
            assert result.iloc[0]["close"] == 3.55


if __name__ == "__main__":
    pytest.main([__file__, "-v"])