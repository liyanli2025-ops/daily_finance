"""
技术信号追踪与历史胜率统计服务

核心功能：
1. 每日收盘后记录当天触发的技术信号（从 MarketOverview.tech_signal_stocks 提取）
2. 7日后自动评估信号是否命中（查询收盘价，计算7日收益率）
3. 统计各信号类型的历史胜率，注入到 prompt 和 to_prompt_text() 中

工作流：
- 每天15:30 → record_today_signals()  记录今日信号
- 每天15:35 → evaluate_past_signals()  评估7天前的信号
- 报告生成时 → get_signal_win_rates()  获取胜率数据
"""
import asyncio
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession


class SignalTrackerService:
    """技术信号追踪与历史胜率统计"""
    
    def __init__(self):
        self._session_maker = None
    
    def set_db(self, session_maker):
        """设置数据库会话"""
        self._session_maker = session_maker
    
    async def record_today_signals(self, tech_signal_stocks: list):
        """
        记录今日触发的技术信号股
        
        从 MarketOverview.tech_signal_stocks 中提取每只股票的每个信号，
        逐条写入 tech_signal_history 表。
        
        Args:
            tech_signal_stocks: TechSignalStock 列表（来自 market_data_service）
        """
        from ..models.database import TechSignalHistoryModel
        
        if not self._session_maker:
            print("[SignalTracker] 数据库未初始化，跳过记录")
            return
        
        if not tech_signal_stocks:
            print("[SignalTracker] 今日无技术信号股，跳过记录")
            return
        
        today = date.today()
        recorded_count = 0
        
        async with self._session_maker() as session:
            # 检查今天是否已经记录过（避免重复）
            existing = await session.execute(
                select(func.count()).select_from(TechSignalHistoryModel).where(
                    TechSignalHistoryModel.signal_date == today
                )
            )
            if existing.scalar() > 0:
                print(f"[SignalTracker] 今日 {today} 已有记录，跳过")
                return
            
            for stock in tech_signal_stocks:
                # 为每个信号类型创建一条记录
                for signal_type in stock.signals:
                    record = TechSignalHistoryModel(
                        id=str(uuid.uuid4()),
                        signal_date=today,
                        stock_code=stock.code,
                        stock_name=stock.name,
                        signal_type=signal_type,
                        signal_score=stock.signal_score,
                        all_signals=stock.signals,
                        entry_price=stock.price,
                        sector=getattr(stock, 'sector', ''),
                        volume_ratio=getattr(stock, 'volume_ratio', 0),
                        turnover_rate=getattr(stock, 'turnover_rate', 0),
                        is_evaluated=False,
                        created_at=datetime.now(),
                    )
                    session.add(record)
                    recorded_count += 1
            
            await session.commit()
        
        print(f"[SignalTracker] 记录完成: {len(tech_signal_stocks)} 只股票，{recorded_count} 条信号记录")
    
    async def evaluate_past_signals(self, days_back: int = 7):
        """
        评估N天前的信号股是否真的涨了
        
        查找 signal_date = today - days_back 且 is_evaluated = False 的记录，
        获取最新收盘价，计算7日收益率，更新数据库。
        
        Args:
            days_back: 回溯天数（默认7天）
        """
        from ..models.database import TechSignalHistoryModel
        
        if not self._session_maker:
            print("[SignalTracker] 数据库未初始化，跳过评估")
            return
        
        eval_target_date = date.today() - timedelta(days=days_back)
        
        async with self._session_maker() as session:
            # 查找需要评估的记录
            result = await session.execute(
                select(TechSignalHistoryModel).where(
                    and_(
                        TechSignalHistoryModel.signal_date == eval_target_date,
                        TechSignalHistoryModel.is_evaluated == False
                    )
                )
            )
            records = result.scalars().all()
            
            if not records:
                print(f"[SignalTracker] {eval_target_date} 无待评估记录")
                return
            
            print(f"[SignalTracker] 评估 {eval_target_date} 的 {len(records)} 条信号记录...")
            
            # 获取当前股票价格
            stock_codes = list(set(r.stock_code for r in records))
            current_prices = await self._get_current_prices(stock_codes)
            
            evaluated_count = 0
            win_count = 0
            
            for record in records:
                current_price = current_prices.get(record.stock_code)
                if current_price is None or current_price <= 0:
                    continue
                
                # 计算收益率
                return_pct = (current_price - record.entry_price) / record.entry_price * 100
                is_win = return_pct > 0
                
                # 更新记录
                record.eval_date = date.today()
                record.exit_price = current_price
                record.return_pct = round(return_pct, 2)
                record.is_win = is_win
                record.is_evaluated = True
                record.evaluated_at = datetime.now()
                
                evaluated_count += 1
                if is_win:
                    win_count += 1
            
            await session.commit()
        
        win_rate = win_count / evaluated_count * 100 if evaluated_count > 0 else 0
        print(f"[SignalTracker] 评估完成: {evaluated_count} 条，胜率 {win_rate:.1f}%（{win_count}/{evaluated_count}）")
    
    async def get_signal_win_rates(self, min_samples: int = 5) -> Dict[str, Dict]:
        """
        获取各信号类型的历史胜率
        
        Args:
            min_samples: 最少样本数（少于此数不统计，避免小样本偏差）
            
        Returns:
            {
                "MACD金叉": {"win_rate": 0.66, "avg_return": 3.2, "sample_size": 35, "label": "7日胜率66%"},
                "均线多头排列": {"win_rate": 0.60, "avg_return": 2.8, "sample_size": 30, "label": "7日胜率60%"},
                ...
            }
        """
        from ..models.database import TechSignalHistoryModel
        
        if not self._session_maker:
            return {}
        
        async with self._session_maker() as session:
            # 查询已评估的所有记录，按信号类型分组统计
            result = await session.execute(
                select(
                    TechSignalHistoryModel.signal_type,
                    func.count().label('total'),
                    func.sum(
                        # SQLite 中 Boolean 用 0/1 表示
                        TechSignalHistoryModel.is_win.cast(Integer)
                    ).label('wins'),
                    func.avg(TechSignalHistoryModel.return_pct).label('avg_return'),
                ).where(
                    TechSignalHistoryModel.is_evaluated == True
                ).group_by(
                    TechSignalHistoryModel.signal_type
                )
            )
            
            rows = result.all()
        
        win_rates = {}
        for row in rows:
            signal_type = row[0]
            total = row[1]
            wins = row[2] or 0
            avg_return = row[3] or 0
            
            if total >= min_samples:
                rate = wins / total
                win_rates[signal_type] = {
                    "win_rate": round(rate, 2),
                    "avg_return": round(avg_return, 2),
                    "sample_size": total,
                    "label": f"7日胜率{rate*100:.0f}%"
                }
        
        return win_rates
    
    async def get_signal_summary_text(self) -> str:
        """
        生成信号胜率摘要文本，可直接注入到 prompt 中
        
        Returns:
            格式化的胜率文本
        """
        win_rates = await self.get_signal_win_rates()
        
        if not win_rates:
            return ""
        
        lines = ["\n### 📊 技术信号历史胜率（基于真实回测数据）\n"]
        lines.append("| 信号类型 | 7日胜率 | 平均收益 | 样本数 |")
        lines.append("|---------|---------|---------|--------|")
        
        # 按胜率降序排列
        sorted_signals = sorted(win_rates.items(), key=lambda x: x[1]["win_rate"], reverse=True)
        
        for signal_type, data in sorted_signals:
            emoji = "🟢" if data["win_rate"] >= 0.6 else "🟡" if data["win_rate"] >= 0.5 else "🔴"
            lines.append(
                f"| {emoji} {signal_type} | {data['win_rate']*100:.0f}% | "
                f"{data['avg_return']:+.1f}% | {data['sample_size']}次 |"
            )
        
        lines.append("\n> 以上数据基于系统自动回测，每个信号触发后追踪7日收益率。胜率=7日内收益为正的比例。\n")
        
        return "\n".join(lines)
    
    async def _get_current_prices(self, stock_codes: List[str]) -> Dict[str, float]:
        """批量获取股票当前价格"""
        prices = {}
        
        try:
            import akshare as ak
            
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, ak.stock_zh_a_spot_em)
            
            if df is not None and not df.empty:
                for code in stock_codes:
                    row = df[df['代码'] == code]
                    if not row.empty:
                        prices[code] = float(row.iloc[0]['最新价'])
        except Exception as e:
            print(f"[SignalTracker] 获取股票价格失败: {e}")
        
        return prices


# 需要导入 Integer 用于 cast
from sqlalchemy import Integer

# 单例实例
_signal_tracker_instance: Optional[SignalTrackerService] = None


def get_signal_tracker() -> SignalTrackerService:
    """获取信号追踪服务实例"""
    global _signal_tracker_instance
    if _signal_tracker_instance is None:
        _signal_tracker_instance = SignalTrackerService()
    return _signal_tracker_instance
