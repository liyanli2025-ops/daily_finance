"""
经验记忆服务 — AI 投资分析经验库

核心功能：
1. 从 prediction_accuracy 表提取历史回测数据
2. 分析维度准确率：大盘方向 / 板块推荐 / 个股建议
3. 挖掘"常见误判模式"（某种市场状态下连续判断错误）
4. 从 signal_tracker 获取技术信号胜率
5. 生成结构化经验文本，注入到早报+晚报 prompt

设计原则：
- 经验文本控制在 300-400 字，约 200-250 tokens，避免浪费
- 数据不足（< 5 次回测）时返回空字符串，不生成无意义内容
- 发现"薄弱环节"（准确率 < 40%）时给出具体警示
"""
from datetime import date, timedelta
from typing import Dict, List, Optional


class LessonsMemoryService:
    """AI 分析经验记忆服务"""

    def __init__(self):
        self._session_maker = None

    def set_db(self, session_maker):
        """设置数据库会话"""
        self._session_maker = session_maker

    async def get_lessons_memory_text(self, days: int = 30) -> str:
        """
        生成经验记忆文本，可直接注入到 prompt 中。

        内容包括：
        - 各维度历史准确率（大盘/板块/个股）
        - 近期趋势（是否在进步还是退步）
        - 薄弱环节预警（准确率低的维度）
        - 常见误判模式（从 lessons_learned 字段中提取）

        Returns:
            格式化的经验文本，数据不足时返回空字符串
        """
        if not self._session_maker:
            return ""

        try:
            stats = await self._get_accuracy_stats(days)
            if not stats or stats.get("total", 0) < 5:
                return ""

            patterns = await self._get_error_patterns(days)
            recent_trend = await self._get_recent_trend()

            return self._format_lessons_text(stats, patterns, recent_trend)

        except Exception as e:
            print(f"[LessonsMemory] 生成经验文本失败（不影响报告生成）: {e}")
            return ""

    async def _get_accuracy_stats(self, days: int) -> Dict:
        """从 prediction_accuracy 表获取各维度准确率汇总"""
        from ..models.database import PredictionAccuracyModel
        from sqlalchemy import select, func, Integer

        cutoff = date.today() - timedelta(days=days)

        async with self._session_maker() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.avg(PredictionAccuracyModel.overall_accuracy).label("avg_overall"),
                    func.avg(PredictionAccuracyModel.sector_accuracy).label("avg_sector"),
                    func.avg(PredictionAccuracyModel.stock_accuracy).label("avg_stock"),
                    func.sum(
                        PredictionAccuracyModel.market_direction_hit.cast(Integer)
                    ).label("direction_hits"),
                ).where(PredictionAccuracyModel.report_date >= cutoff)
            )
            row = result.one_or_none()

        if row is None or (row[0] or 0) == 0:
            return {}

        total = row[0]
        direction_hits = row[4] or 0

        return {
            "total": total,
            "avg_overall": round(row[1] or 0, 2),
            "direction_rate": round(direction_hits / total, 2),
            "direction_hits": int(direction_hits),
            "sector_rate": round(row[2] or 0, 2),
            "stock_rate": round(row[3] or 0, 2),
        }

    async def _get_error_patterns(self, days: int) -> List[str]:
        """
        从 lessons_learned 字段中提取高频误判模式。
        找出最近 days 天内"大盘方向判断失误"且有实际变动的记录，
        汇总成简短的规律描述。
        """
        from ..models.database import PredictionAccuracyModel
        from sqlalchemy import select

        cutoff = date.today() - timedelta(days=days)
        patterns = []

        async with self._session_maker() as session:
            # 查询失误记录（大盘方向未命中）
            result = await session.execute(
                select(
                    PredictionAccuracyModel.lessons_learned,
                    PredictionAccuracyModel.evaluation,
                    PredictionAccuracyModel.report_date,
                ).where(
                    PredictionAccuracyModel.report_date >= cutoff,
                    PredictionAccuracyModel.market_direction_hit == False,  # noqa: E712
                ).order_by(PredictionAccuracyModel.report_date.desc()).limit(10)
            )
            rows = result.fetchall()

        # 统计"预测看多但实际下跌"vs"预测看空但实际上涨"的次数
        bullish_miss = 0  # 预测看多但跌了
        bearish_miss = 0  # 预测看空但涨了

        for row in rows:
            evaluation = row[1] or {}
            if isinstance(evaluation, dict):
                direction_info = evaluation.get("market_direction", {})
                predicted = direction_info.get("predicted", "")
                actual_change_str = direction_info.get("actual_change", "0%")
                try:
                    actual_change = float(actual_change_str.replace("%", "").replace("+", ""))
                    if predicted == "bullish" and actual_change < 0:
                        bullish_miss += 1
                    elif predicted == "bearish" and actual_change > 0:
                        bearish_miss += 1
                except (ValueError, AttributeError):
                    pass

        total_misses = len(rows)
        if total_misses >= 3:
            if bullish_miss > bearish_miss and bullish_miss >= 2:
                patterns.append(
                    f"近{days}天内有{bullish_miss}次在看多时市场实际下跌，"
                    "存在偏多偏见，遇到看多信号时需多一层验证"
                )
            elif bearish_miss > bullish_miss and bearish_miss >= 2:
                patterns.append(
                    f"近{days}天内有{bearish_miss}次在看空时市场实际上涨，"
                    "存在偏空偏见，遇到看空信号时需多一层验证"
                )

        return patterns

    async def _get_recent_trend(self) -> str:
        """
        判断最近 10 天 vs 前 10 天的准确率变化趋势。

        Returns:
            "improving" / "declining" / "stable" / "unknown"
        """
        from ..models.database import PredictionAccuracyModel
        from sqlalchemy import select, func

        today = date.today()
        recent_cutoff = today - timedelta(days=10)
        prev_cutoff = today - timedelta(days=20)

        async with self._session_maker() as session:
            # 最近 10 天
            r1 = await session.execute(
                select(func.avg(PredictionAccuracyModel.overall_accuracy)).where(
                    PredictionAccuracyModel.report_date >= recent_cutoff
                )
            )
            recent_avg = r1.scalar() or 0

            # 前 10 天
            r2 = await session.execute(
                select(func.avg(PredictionAccuracyModel.overall_accuracy)).where(
                    PredictionAccuracyModel.report_date >= prev_cutoff,
                    PredictionAccuracyModel.report_date < recent_cutoff,
                )
            )
            prev_avg = r2.scalar() or 0

        if recent_avg == 0 or prev_avg == 0:
            return "unknown"

        diff = recent_avg - prev_avg
        if diff > 0.05:
            return "improving"
        elif diff < -0.05:
            return "declining"
        else:
            return "stable"

    def _format_lessons_text(
        self, stats: Dict, patterns: List[str], trend: str
    ) -> str:
        """将统计数据和误判模式格式化为 prompt 可用的文本"""

        total = stats["total"]
        overall = stats["avg_overall"]
        direction = stats["direction_rate"]
        direction_hits = stats["direction_hits"]
        sector = stats["sector_rate"]
        stock = stats["stock_rate"]

        # 趋势描述
        trend_desc = {
            "improving": "📈 近期准确率在提升，状态良好",
            "declining": "📉 近期准确率有所下滑，需更谨慎",
            "stable": "➡️ 近期准确率基本稳定",
            "unknown": "",
        }.get(trend, "")

        # 薄弱环节识别
        weak_points = []
        if direction < 0.45:
            weak_points.append(f"大盘方向判断（命中率仅{direction*100:.0f}%，是最大薄弱点）")
        if sector < 0.40:
            weak_points.append(f"板块推荐（命中率仅{sector*100:.0f}%，需谨慎推荐板块）")
        if stock < 0.40:
            weak_points.append(f"个股建议（命中率仅{stock*100:.0f}%，个股判断需更保守）")

        # 优势领域
        strengths = []
        if direction >= 0.70:
            strengths.append(f"大盘方向判断（命中率{direction*100:.0f}%，是相对可信的判断）")
        if sector >= 0.65:
            strengths.append(f"板块推荐（命中率{sector*100:.0f}%，板块方向判断较可靠）")
        if stock >= 0.65:
            strengths.append(f"个股建议（命中率{stock*100:.0f}%，个股判断相对准确）")

        lines = [
            f"\n### 🧠 历史分析经验库（过去{30}天，共{total}次回测）\n",
        ]

        if trend_desc:
            lines.append(f"> {trend_desc}\n")

        lines.append("**各维度历史命中率：**")
        lines.append(
            f"- 综合准确率：**{overall*100:.0f}%** "
            f"（{'优秀' if overall >= 0.7 else '良好' if overall >= 0.6 else '一般' if overall >= 0.5 else '需提升'}）"
        )
        lines.append(
            f"- 大盘方向：{direction*100:.0f}%（{total}次中命中{direction_hits}次）"
        )
        lines.append(f"- 板块推荐：{sector*100:.0f}%")
        lines.append(f"- 个股建议：{stock*100:.0f}%")

        if strengths:
            lines.append("\n**📌 可信优势（这些判断历史上更准，可以更有把握）：**")
            for s in strengths:
                lines.append(f"- {s}")

        if weak_points:
            lines.append("\n**⚠️ 历史薄弱环节（这些判断历史上容易出错，今日需额外谨慎）：**")
            for w in weak_points:
                lines.append(f"- {w}")

        if patterns:
            lines.append("\n**🔄 已识别的误判模式（请主动规避）：**")
            for p in patterns:
                lines.append(f"- {p}")

        lines.append(
            "\n> 📎 以上是系统基于真实回测数据自动生成的经验总结。"
            "请在今日分析中主动参考这些历史规律，尤其注意薄弱环节和误判模式。\n"
        )

        return "\n".join(lines)


# 单例
_lessons_memory_instance: "Optional[LessonsMemoryService]" = None


def get_lessons_memory_service() -> LessonsMemoryService:
    """获取经验记忆服务实例"""
    global _lessons_memory_instance
    if _lessons_memory_instance is None:
        _lessons_memory_instance = LessonsMemoryService()
    return _lessons_memory_instance
