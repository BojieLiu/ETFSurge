"""ChatSessionRecord model — LLM 多轮对话会话持久化（round53 §9 阶段 2）。

24h TTL 落盘（启动时加载到内存作 L1 缓存，读取时惰性过期）。
契约: api-contracts/analysis/llm-chat-session.md
"""

from sqlalchemy import Column, DateTime, String, Text, func

from ..database import Base


class ChatSessionRecord(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String(40), primary_key=True)
    # [{role, content, ts}] JSON 序列化（阶段 2: 消息压缩 JSON 存储）
    messages_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
