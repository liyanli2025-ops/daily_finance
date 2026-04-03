"""
自动化回测服务 — 预测准确度追踪

核心功能：
1. 从早报中提取结构化预测数据（大盘方向、推荐板块、自选股建议）
2. 盘后获取实际收盘数据，逐项对比计算准确率
3. 保存回测结果到数据库，并生成摘要文本注入到晚报 prompt

工作流：
- 晚报生成前（15:30）自动执行 evaluate_morning_predictions()
- 读取今日早报 → 提取预测 → 获取实际收盘 → 逐项对比 → 保存结果
- 晚报 prompt 中注入回测摘要

预测提取策略：
- 从 report.core_opinions 提取操作建议
- 从 report.analysis 提取大盘方向（trend: bullish/bearish/neutral）
- 从 JSON 结构化数据中提取 hot_sectors、risk_sectors、watchlist_analysis
"""
import asyncio
import json
import re
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple


class BacktestService:
    """预测准确度自动回测"""
    
    def __init__(self):
        self._session_maker = None
    
    def set_db(self, session_maker):
        """设置数据库会话"""
        self._session_maker = session_maker
    
    async def evaluate_morning_predictions(self, morning_report) -> Optional[Dict]:
        """
        对比早报预测 vs 实际收盘
        
        评测维度：
        1. 大盘方向（看多/看空/中性）→ 实际涨跌对比
        2. 推荐板块 → 实际涨幅排名
        3. 自选股建议 → 实际涨跌对比
        4. 仓位建议是否合理
        
        Args:
            morning_report: 今日早报 Report 对象
            
        Returns:
            回测结果字典，None 表示无法回测
        """
        if morning_report is None:
            print("[Backtest] 无今日早报，跳过回测")
            return None
        
        print(f"[Backtest] 开始回测早报: {morning_report.title}")
        
        # Step 1: 从早报中提取预测数据
        predictions = self._extract_predictions(morning_report)
        if not predictions:
            print("[Backtest] 无法从早报中提取预测数据")
            return None
        
        print(f"[Backtest] 提取到预测: 大盘方向={predictions.get('market_direction', 'N/A')}, "
              f"看好板块={predictions.get('hot_sectors', [])}, "
              f"自选股建议={len(predictions.get('stock_actions', []))}条")
        
        # Step 2: 获取实际收盘数据
        actuals = await self._get_actual_market_data()
        if not actuals:
            print("[Backtest] 获取实际收盘数据失败")
            return None
        
        # Step 3: 逐项对比
        evaluation = self._compare_predictions_vs_actuals(predictions, actuals)
        
        # Step 4: 保存到数据库
        await self._save_evaluation(morning_report, predictions, actuals, evaluation)
        
        print(f"[Backtest] 回测完成: 综合准确率 {evaluation['overall_accuracy']*100:.0f}%")
        
        return evaluation
    
    def _extract_predictions(self, report) -> Dict:
        """
        从早报中提取结构化预测数据
        
        提取策略：
        1. 从 report.analysis 提取大盘方向（trend）
        2. 从 report.content 中用正则提取具体预测
        3. 从 core_opinions 提取操作建议
        """
        predictions = {
            "market_direction": "neutral",  # bullish/bearish/neutral
            "hot_sectors": [],              # 推荐的板块
            "risk_sectors": [],             # 建议回避的板块
            "stock_actions": [],            # 自选股操作建议 [{code, name, action, target_price}]
            "position_advice": "",          # 仓位建议
            "core_opinions": [],            # 核心操作建议
        }
        
        # 从 analysis 中提取
        if report.analysis:
            analysis = report.analysis
            if hasattr(analysis, 'trend'):
                trend_str = str(analysis.trend.value) if hasattr(analysis.trend, 'value') else str(analysis.trend)
                predictions["market_direction"] = trend_str
            
            if hasattr(analysis, 'opportunities'):
                predictions["hot_sectors"] = analysis.opportunities or []
            if hasattr(analysis, 'risks'):
                predictions["risk_sectors"] = analysis.risks or []
        
        # 从 core_opinions 中提取
        if report.core_opinions:
            predictions["core_opinions"] = report.core_opinions
            
            # 从 opinions 中提取操作建议关键词
            for opinion in report.core_opinions:
                opinion_lower = opinion.lower()
                if any(kw in opinion_lower for kw in ["看多", "加仓", "买入", "bullish"]):
                    if predictions["market_direction"] == "neutral":
                        predictions["market_direction"] = "bullish"
                elif any(kw in opinion_lower for kw in ["看空", "减仓", "卖出", "bearish"]):
                    if predictions["market_direction"] == "neutral":
                        predictions["market_direction"] = "bearish"
        
        # 从 content 中提取仓位建议
        content = report.content or ""
        position_match = re.search(r'(?:总仓位建议|仓位建议)[：:]\s*(.+?)(?:\n|$)', content)
        if position_match:
            predictions["position_advice"] = position_match.group(1).strip()
        
        # 从 content 中提取自选股建议
        stock_patterns = [
            r'(\d{6})[）)]\s*[：:]\s*(买入|卖出|持有|加仓|减仓|观望|清仓)',
            r'(?:建议|操作)[：:]\s*(买入|卖出|持有|加仓|减仓|观望|清仓)',
        ]
        for pattern in stock_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                if len(match.groups()) >= 2:
                    predictions["stock_actions"].append({
                        "code": match.group(1),
                        "action": match.group(2),
                    })
        
        # 从 content 中提取热门板块关键词
        sector_pattern = r'(?:看好|关注|推荐|布局)\s*[：:]?\s*([\u4e00-\u9fa5]{2,6}(?:板块|行业|赛道|概念))'
        sector_matches = re.finditer(sector_pattern, content)
        for match in sector_matches:
            sector = match.group(1)
            if sector not in predictions["hot_sectors"]:
                predictions["hot_sectors"].append(sector)
        
        return predictions
    
    async def _get_actual_market_data(self) -> Dict:
        """
        获取今日实际收盘数据
        
        Returns:
            {
                "sh_index_change": 0.83,  # 上证涨跌幅
                "sz_index_change": 1.25,
                "cyb_index_change": 1.5,
                "top_sectors": ["半导体", "新能源"],  # 涨幅前5板块
                "bottom_sectors": ["地产", "银行"],     # 跌幅前5板块
                "stock_prices": {"600519": {"price": 1800, "change": 2.3}, ...}
            }
        """
        import akshare as ak
        
        actuals = {
            "sh_index_change": 0,
            "sz_index_change": 0,
            "cyb_index_change": 0,
            "top_sectors": [],
            "bottom_sectors": [],
            "stock_prices": {},
            "up_count": 0,
            "down_count": 0,
        }
        
        try:
            loop = asyncio.get_event_loop()
            
            # 获取主要指数
            try:
                df = await loop.run_in_executor(None, ak.stock_zh_index_spot_em)
                if df is not None and not df.empty:
                    index_map = {
                        "000001": "sh_index_change",
                        "399001": "sz_index_change",
                        "399006": "cyb_index_change",
                    }
                    for code, key in index_map.items():
                        row = df[df['代码'] == code]
                        if not row.empty:
                            actuals[key] = float(row.iloc[0]['涨跌幅'])
            except Exception as e:
                print(f"[Backtest] 获取指数失败: {e}")
            
            await asyncio.sleep(1)
            
            # 获取板块排行
            try:
                df = await loop.run_in_executor(None, ak.stock_board_industry_name_em)
                if df is not None and not df.empty:
                    df_sorted = df.sort_values('涨跌幅', ascending=False)
                    actuals["top_sectors"] = df_sorted.head(5)['板块名称'].tolist()
                    actuals["bottom_sectors"] = df_sorted.tail(5)['板块名称'].tolist()
            except Exception as e:
                print(f"[Backtest] 获取板块排行失败: {e}")
            
            await asyncio.sleep(1)
            
            # 获取全A股涨跌统计
            try:
                df = await loop.run_in_executor(None, ak.stock_zh_a_spot_em)
                if df is not None and not df.empty:
                    actuals["up_count"] = len(df[df['涨跌幅'] > 0])
                    actuals["down_count"] = len(df[df['涨跌幅'] < 0])
                    
                    # 缓存所有股票价格
                    for _, row in df.iterrows():
                        code = str(row['代码'])
                        actuals["stock_prices"][code] = {
                            "price": float(row['最新价']),
                            "change": float(row['涨跌幅']),
                        }
            except Exception as e:
                print(f"[Backtest] 获取全A股数据失败: {e}")
            
        except Exception as e:
            print(f"[Backtest] 获取实际数据异常: {e}")
        
        return actuals
    
    def _compare_predictions_vs_actuals(self, predictions: Dict, actuals: Dict) -> Dict:
        """
        逐项对比预测 vs 实际
        
        Returns:
            {
                "overall_accuracy": 0.67,
                "market_direction": {"predicted": "bullish", "actual": "+0.83%", "hit": True},
                "sector_hits": [...],
                "stock_hits": [...],
                "lessons": "..."
            }
        """
        evaluation = {
            "overall_accuracy": 0,
            "market_direction": {},
            "sector_hits": [],
            "stock_hits": [],
            "position_evaluation": "",
            "score_breakdown": {},
            "lessons": "",
        }
        
        scores = []
        
        # 1. 大盘方向评估
        predicted_direction = predictions.get("market_direction", "neutral")
        sh_change = actuals.get("sh_index_change", 0)
        
        actual_direction = "bullish" if sh_change > 0.3 else "bearish" if sh_change < -0.3 else "neutral"
        direction_hit = (predicted_direction == actual_direction) or \
                       (predicted_direction == "bullish" and sh_change > 0) or \
                       (predicted_direction == "bearish" and sh_change < 0)
        
        evaluation["market_direction"] = {
            "predicted": predicted_direction,
            "actual_change": f"{sh_change:+.2f}%",
            "actual_direction": actual_direction,
            "hit": direction_hit,
        }
        scores.append(1.0 if direction_hit else 0.0)
        
        # 2. 板块推荐评估
        hot_sectors = predictions.get("hot_sectors", [])
        actual_top = actuals.get("top_sectors", [])
        
        if hot_sectors and actual_top:
            hits = 0
            for sector in hot_sectors:
                # 模糊匹配（板块名称可能不完全一致）
                for actual_sector in actual_top:
                    if sector in actual_sector or actual_sector in sector:
                        hits += 1
                        evaluation["sector_hits"].append({
                            "predicted": sector,
                            "actual_rank": actual_top.index(actual_sector) + 1,
                            "hit": True
                        })
                        break
                else:
                    evaluation["sector_hits"].append({
                        "predicted": sector,
                        "actual_rank": "未进前5",
                        "hit": False
                    })
            
            sector_accuracy = hits / len(hot_sectors) if hot_sectors else 0
            scores.append(sector_accuracy)
        
        # 3. 自选股建议评估
        stock_actions = predictions.get("stock_actions", [])
        stock_prices = actuals.get("stock_prices", {})
        
        if stock_actions and stock_prices:
            stock_hits = 0
            for action_info in stock_actions:
                code = action_info.get("code", "")
                action = action_info.get("action", "")
                
                if code in stock_prices:
                    actual_change = stock_prices[code]["change"]
                    
                    # 判断建议是否正确
                    hit = False
                    if action in ["买入", "加仓"] and actual_change > 0:
                        hit = True
                    elif action in ["卖出", "减仓", "清仓"] and actual_change < 0:
                        hit = True
                    elif action in ["持有", "观望"]:
                        hit = abs(actual_change) < 3  # 波动不大就算对
                    
                    evaluation["stock_hits"].append({
                        "code": code,
                        "action": action,
                        "actual_change": f"{actual_change:+.2f}%",
                        "hit": hit,
                    })
                    if hit:
                        stock_hits += 1
            
            if stock_actions:
                stock_accuracy = stock_hits / len(stock_actions)
                scores.append(stock_accuracy)
        
        # 4. 仓位建议评估
        up_count = actuals.get("up_count", 0)
        down_count = actuals.get("down_count", 0)
        total = up_count + down_count
        up_ratio = up_count / total if total > 0 else 0.5
        
        position_advice = predictions.get("position_advice", "")
        if "高仓位" in position_advice or "8成" in position_advice or "9成" in position_advice:
            position_correct = up_ratio > 0.6  # 高仓位 → 市场应该是普涨
        elif "低仓位" in position_advice or "3成" in position_advice or "2成" in position_advice:
            position_correct = up_ratio < 0.4  # 低仓位 → 市场应该是普跌
        else:
            position_correct = 0.4 <= up_ratio <= 0.6  # 中等仓位 → 市场应该是震荡
        
        evaluation["position_evaluation"] = f"建议: {position_advice}, 实际上涨比例: {up_ratio*100:.0f}%, {'合理' if position_correct else '偏差'}"
        
        # 计算综合准确率
        if scores:
            evaluation["overall_accuracy"] = round(sum(scores) / len(scores), 2)
        
        # 生成经验教训
        evaluation["lessons"] = self._generate_lessons(evaluation)
        
        return evaluation
    
    def _generate_lessons(self, evaluation: Dict) -> str:
        """根据回测结果生成经验教训"""
        lessons = []
        
        direction = evaluation.get("market_direction", {})
        if direction.get("hit"):
            lessons.append(f"大盘方向判断正确（预测{direction.get('predicted', '?')}，"
                          f"实际{direction.get('actual_change', '?')}）")
        else:
            lessons.append(f"大盘方向判断失误（预测{direction.get('predicted', '?')}，"
                          f"实际{direction.get('actual_change', '?')}），"
                          f"需要反思判断依据")
        
        sector_hits = evaluation.get("sector_hits", [])
        hit_count = sum(1 for s in sector_hits if s.get("hit"))
        if sector_hits:
            lessons.append(f"板块推荐命中{hit_count}/{len(sector_hits)}个")
        
        stock_hits = evaluation.get("stock_hits", [])
        stock_hit_count = sum(1 for s in stock_hits if s.get("hit"))
        if stock_hits:
            lessons.append(f"个股建议命中{stock_hit_count}/{len(stock_hits)}个")
        
        return "；".join(lessons)
    
    async def _save_evaluation(self, report, predictions: Dict, actuals: Dict, evaluation: Dict):
        """保存回测结果到数据库"""
        from ..models.database import PredictionAccuracyModel
        
        if not self._session_maker:
            return
        
        async with self._session_maker() as session:
            record = PredictionAccuracyModel(
                id=str(uuid.uuid4()),
                report_id=report.id,
                report_date=report.report_date,
                market_direction_hit=evaluation.get("market_direction", {}).get("hit", False),
                sector_accuracy=len([s for s in evaluation.get("sector_hits", []) if s.get("hit")]) / 
                               max(len(evaluation.get("sector_hits", [])), 1),
                stock_accuracy=len([s for s in evaluation.get("stock_hits", []) if s.get("hit")]) / 
                              max(len(evaluation.get("stock_hits", [])), 1),
                overall_accuracy=evaluation.get("overall_accuracy", 0),
                predictions=predictions,
                actuals={k: v for k, v in actuals.items() if k != "stock_prices"},  # 不存全量价格
                evaluation=evaluation,
                lessons_learned=evaluation.get("lessons", ""),
                created_at=datetime.now(),
            )
            session.add(record)
            await session.commit()
        
        print(f"[Backtest] 回测结果已保存到数据库")
    
    async def get_recent_accuracy(self, days: int = 30) -> Dict:
        """
        获取最近N天的回测准确率汇总
        
        Returns:
            {
                "avg_accuracy": 0.65,
                "direction_hit_rate": 0.7,
                "sector_hit_rate": 0.6,
                "stock_hit_rate": 0.55,
                "total_evaluations": 20,
                "trend": "improving"  # 准确率趋势
            }
        """
        from ..models.database import PredictionAccuracyModel
        from sqlalchemy import select, func
        
        if not self._session_maker:
            return {}
        
        cutoff_date = date.today() - timedelta(days=days)
        
        async with self._session_maker() as session:
            result = await session.execute(
                select(
                    func.count().label('total'),
                    func.avg(PredictionAccuracyModel.overall_accuracy).label('avg_accuracy'),
                    func.avg(PredictionAccuracyModel.sector_accuracy).label('avg_sector'),
                    func.avg(PredictionAccuracyModel.stock_accuracy).label('avg_stock'),
                    func.sum(PredictionAccuracyModel.market_direction_hit.cast(Integer)).label('direction_hits'),
                ).where(
                    PredictionAccuracyModel.report_date >= cutoff_date
                )
            )
            
            row = result.one_or_none()
        
        if row is None or row[0] == 0:
            return {}
        
        total = row[0]
        direction_hits = row[4] or 0
        
        return {
            "avg_accuracy": round(row[1] or 0, 2),
            "direction_hit_rate": round(direction_hits / total, 2) if total > 0 else 0,
            "sector_hit_rate": round(row[2] or 0, 2),
            "stock_hit_rate": round(row[3] or 0, 2),
            "total_evaluations": total,
        }
    
    async def get_backtest_summary_text(self) -> str:
        """
        生成回测摘要文本，可直接注入到晚报 prompt
        
        Returns:
            格式化的回测摘要
        """
        summary = await self.get_recent_accuracy()
        
        if not summary or summary.get("total_evaluations", 0) == 0:
            return ""
        
        total = summary["total_evaluations"]
        avg = summary["avg_accuracy"]
        
        text = f"""
### 📈 早报预测准确度追踪（最近30天，共{total}次回测）

| 维度 | 准确率 | 评价 |
|------|--------|------|
| **综合准确率** | **{avg*100:.0f}%** | {'优秀' if avg >= 0.7 else '良好' if avg >= 0.6 else '一般' if avg >= 0.5 else '需改进'} |
| 大盘方向命中 | {summary['direction_hit_rate']*100:.0f}% | {summary['total_evaluations']}次中命中{int(summary['direction_hit_rate']*total)}次 |
| 板块推荐命中 | {summary['sector_hit_rate']*100:.0f}% | - |
| 个股建议命中 | {summary['stock_hit_rate']*100:.0f}% | - |

> ⚠️ 请在晚报中坦诚评价今日预测表现，对了说为什么对，错了分析哪里错了。
"""
        return text


# 需要导入 Integer 用于 cast
from sqlalchemy import Integer

# 单例实例
_backtest_instance: Optional[BacktestService] = None


def get_backtest_service() -> BacktestService:
    """获取回测服务实例"""
    global _backtest_instance
    if _backtest_instance is None:
        _backtest_instance = BacktestService()
    return _backtest_instance
