"""Retired keyword scoring. Historical database rows remain for audit only.

Legacy scoring inferred predictions from commentary, treated missing prices as zero,
and scored 'watch' as correct when abs(return)<3%. This is not investment performance.
A replacement requires forecasts committed before the observation window, explicit
instrument/horizon/trigger/invalidation, and timestamped outcomes. Not implemented yet.
"""
from typing import Dict, Optional


class BacktestService:
    def __init__(self):
        self._session_maker = None

    def set_db(self, session_maker):
        self._session_maker = session_maker

    async def evaluate_morning_predictions(self, morning_report) -> Optional[Dict]:
        print('[Backtest] 旧关键词评分已停用：尚无经过验证的预测准确率，不请求行情、不写入评分')
        return None

    async def get_recent_accuracy(self, days: int = 30) -> Dict:
        return {}

    async def get_backtest_summary_text(self) -> str:
        return ''


_backtest_instance: Optional[BacktestService] = None


def get_backtest_service() -> BacktestService:
    global _backtest_instance
    if _backtest_instance is None:
        _backtest_instance = BacktestService()
    return _backtest_instance
