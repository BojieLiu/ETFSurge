"""round24 R26: 盘后快照持久化模型。

盘后/熔断时数据源变薄（design 570 实测 valid_rate=0%、correlation 空、sector_momentum=[]
、fund_flow=0）。last-good pool / kline cache / ic batch 全内存，重启即丢。
本模型把「最后良好快照」落盘——pool 快照 / sector_momentum / fund_flow——盘后/熔断时
读快照兜底（在 last-good 缓存之上再一层），解决「盘后重启 = 全空 = 静态兜底」。

注意：快照是「降级兜底源」，不是实时源。语义上等价于 round24 R3 的 data_precision
「仅供参考」——UI 应标注 as_of 时间，避免冒充实时。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from ..database import Base


class MarketSnapshot(Base):
    """市场数据快照（T-1 真实数据的 last-good 落盘）。

    kind:
        "pool"            — get_pool 返回的因子矩阵快照（核心字段：symbol/name/
                            pe_ttm/pb/market_cap 等）
        "sector_momentum" — 板块动量快照
        "fund_flow"       — 资金流快照
    payload: JSON 字符串（与对应 service 返回结构一致）。
    as_of:   快照时点（ISO 字符串）。盘后完整数据用 15:30（含盘后成交量），
             15:00-15:30 窗口内用 15:00（盘中最后快照）。
    """

    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(20), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    as_of = Column(String(24), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        import json

        return {
            "id": self.id,
            "kind": self.kind,
            "payload": json.loads(str(self.payload)) if self.payload else None,
            "as_of": self.as_of,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
