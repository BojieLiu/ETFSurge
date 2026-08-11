"""
TDD: ETFClassifier - Shenwan industry + concept board classification.

All external calls (akshare) must be mocked.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestETFClassifier:
    """ETFClassifier: industry/concept inference from ETF name/tracked_index."""

    @pytest.fixture
    def classifier(self):
        from app.services.etf_classifier import ETFClassifier
        return ETFClassifier()

    def test_classify_by_name_core_index(self, classifier):
        """名称含"沪深300"应归 core 行业为宽基指数"""
        result = classifier._classify_by_name("沪深300ETF", "")
        assert result is not None
        assert result["industry"] == "宽基指数"
        assert "沪深300" in result["concepts"]

    def test_classify_by_name_semiconductor(self, classifier):
        """名称含"半导体"应归电子行业"""
        result = classifier._classify_by_name("半导体ETF", "")
        assert result is not None
        assert result["industry"] == "电子"
        assert "半导体" in result["concepts"]

    def test_classify_by_name_new_energy(self, classifier):
        """round14 P2-U: 名称含"新能源"应归「新能源」行业（旧「电力设备」概念粗映射已改）"""
        result = classifier._classify_by_name("新能源汽车ETF", "")
        assert result is not None
        assert result["industry"] == "新能源"
        assert "新能源" in result["concepts"]

    def test_classify_carbon_neutral_new_energy(self, classifier):
        """round14 P2-U: 碳中和 → 新能源；医疗器械/科创创新药保持医药生物"""
        r1 = classifier._classify_by_name("碳中和ETF", "")
        assert r1["industry"] == "新能源"
        r2 = classifier._classify_by_name("科创新能源ETF", "")
        assert r2["industry"] == "新能源"
        r3 = classifier._classify_by_name("医疗器械ETF", "")
        assert r3["industry"] == "医药生物"
        r4 = classifier._classify_by_name("科创创新药ETF", "科创创新药指数")
        assert r4["industry"] == "医药生物"

    def test_classify_new_energy_via_tracked_index(self, classifier):
        """round14 P2-U: tracked_index 走 _INDEX_RULES（589960 等无 tracked_index 走 name）"""
        r = classifier._classify_by_name("科创新能源ETF", "科创新能源指数")
        assert r["industry"] == "新能源"

    def test_classify_by_name_medical(self, classifier):
        """名称含"医药"应归医药生物行业"""
        result = classifier._classify_by_name("医药ETF", "中证医药卫生指数")
        assert result is not None
        assert result["industry"] == "医药生物"

    def test_classify_by_tracked_index(self, classifier):
        """跟踪指数名含"半导体"应优先于名称中的兜底信息"""
        result = classifier._classify_by_name("科技ETF", "中华半导体芯片指数")
        assert result is not None
        assert "半导体" in result["concepts"]
        assert result["industry"] == "电子"

    def test_classify_unknown(self, classifier):
        """无法识别时应返回 unknown"""
        result = classifier._classify_by_name("XZY创新ETF", "")
        assert result is not None
        assert result["industry"] == "unknown"
        assert result["confidence"] < 0.5

    def test_classify_gold_etf(self, classifier):
        """名称含"黄金"应归防御类商品"""
        result = classifier._classify_by_name("黄金ETF", "")
        assert result is not None
        assert result["industry"] == "商品"
        assert "黄金" in result["concepts"]

    def test_classify_bond_etf(self, classifier):
        """名称含"国债"应归固收类"""
        result = classifier._classify_by_name("30年国债ETF", "")
        assert result is not None
        assert result["industry"] == "固收"
        assert "国债" in result["concepts"]

    def test_classify_brokerage(self, classifier):
        """名称含"证券"或"券商"应归非银金融"""
        result = classifier._classify_by_name("券商ETF", "")
        assert result is not None
        assert result["industry"] == "非银金融"

    def test_classify_military(self, classifier):
        """名称含"军工"应归国防军工"""
        result = classifier._classify_by_name("军工ETF", "中证军工指数")
        assert result is not None
        assert result["industry"] == "国防军工"

    def test_classify_hong_kong(self, classifier):
        """名称含"恒生"应归跨境"""
        result = classifier._classify_by_name("恒生科技ETF", "")
        assert result is not None
        assert result["industry"] == "跨境"
        assert "恒生" in result["concepts"]

    def test_classify_nasdaq(self, classifier):
        """名称含"纳指"应归跨境"""
        result = classifier._classify_by_name("纳指ETF", "纳斯达克100指数")
        assert result is not None
        assert result["industry"] == "跨境"
        assert "纳斯达克" in result["concepts"]

    def test_classify_5g(self, classifier):
        """名称含"5G"应归通信"""
        result = classifier._classify_by_name("5GETF", "")
        assert result is not None
        assert result["industry"] == "通信"

    def test_classify_consumption(self, classifier):
        """名称含"消费"应归食品饮料/消费"""
        result = classifier._classify_by_name("消费ETF", "")
        assert result is not None
        assert result["industry"] == "食品饮料"

    def test_classify_ai(self, classifier):
        """名称含"人工智能"或"AI"应归计算机"""
        result = classifier._classify_by_name("AI人工智能ETF", "")
        assert result is not None
        assert result["industry"] == "计算机"

    def test_classify_cs_index(self, classifier):
        """名称含"中证500"应归宽基指数"""
        result = classifier._classify_by_name("中证500ETF", "中证500指数")
        assert result is not None
        assert result["industry"] == "宽基指数"

    def test_batch_classify(self, classifier):
        """批量分类应返回 {symbol: result}"""
        etfs = [
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300指数"},
            {"symbol": "512480", "name": "半导体ETF", "tracked_index": "中华半导体芯片指数"},
            {"symbol": "518880", "name": "黄金ETF", "tracked_index": ""},
        ]
        results = classifier.batch_classify(etfs)
        assert len(results) == 3
        assert results["510300"]["industry"] == "宽基指数"
        assert results["512480"]["industry"] == "电子"
        assert results["518880"]["industry"] == "商品"
