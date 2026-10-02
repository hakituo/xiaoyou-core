"""
自我改进系统 — 结构化学习、纠正追踪、核心记忆管理

整合自：
- SKILL.md (self-improvement): 结构化学习日志、晋升工作流、模式检测
- SKILL1.md (memory-manager): MEMORY.md 核心记忆、纠正检测、漂移防护、自动瘦身
- 现有系统: WeightedMemoryManager, AutoHealService, correction.py, JournalService

核心能力：
1. 结构化学习/错误/功能请求日志（.learnings/）
2. 通用纠正检测与记录（扩展 correction.py）
3. 轻量核心记忆（MEMORY.md，每次 session 加载）
4. 学习晋升与模式检测（→ 永久规则）
5. 每日日志（memory/YYYY-MM-DD.md）
6. 记忆漂移防护
"""

from .service import SelfImprovementService, get_self_improvement_service

__all__ = ["SelfImprovementService", "get_self_improvement_service"]
