"""
任务记录模型（Z27 任务持久化重构）
Task persistence model — DB as the single source of truth.

Z27 (task-persistence-redesign): 任务生命周期全部落 DB（替代进程内 JSON 文件），
任务完成时 record_id 回写任务行，前端可从任务直达业务记录（设计 / 策略检查）。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from ..database import Base


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # design | check | report
    task_type = Column(String(20), nullable=False, default="design")
    # pending | running | quick_ready | completed | completed_with_errors | failed | cancelled
    status = Column(String(24), nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String(120), nullable=False, default="")
    params_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    # 关联的 DB 业务记录 ID: design → portfolio_designs.id; check → strategy_check_records.id
    record_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """契约字段映射（api-contracts/portfolio/tasks.md §2.3/2.4）。"""
        import json
        return {
            "task_id": self.id,
            "type": self.task_type,
            "status": self.status,
            "progress": int(self.progress or 0),
            "stage": self.stage or "",
            "params": json.loads(str(self.params_json)) if self.params_json else {},
            "result": json.loads(str(self.result_json)) if self.result_json else None,
            "error_message": self.error_message,
            "record_id": self.record_id,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "completed_at": self.completed_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.completed_at else None,
        }
