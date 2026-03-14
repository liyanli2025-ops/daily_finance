"""
自选股服务
统一管理配置文件自选股和数据库自选股
提供行业映射、去重等功能
"""
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime


@dataclass
class WatchlistStock:
    """自选股数据结构"""
    code: str
    name: str
    market: str  # "A" 或 "HK"
    sector: Optional[str] = None  # 所属行业
    source: str = "config"  # "config" 或 "database"


# 股票行业映射表（常见股票）
# 后续可以扩展为从 AKShare 动态获取
STOCK_SECTOR_MAP = {
    # 白酒
    "600519": "白酒", "000858": "白酒", "000568": "白酒", "002304": "白酒",
    "603369": "白酒", "000596": "白酒", "603198": "白酒", "000799": "白酒",
    
    # 新能源/锂电
    "300750": "新能源", "002594": "新能源", "300014": "新能源", "002460": "新能源",
    "300274": "新能源", "002812": "新能源", "300124": "新能源", "688005": "新能源",
    "601012": "新能源", "600438": "新能源",
    
    # 光伏
    "601012": "光伏", "002459": "光伏", "688599": "光伏", "601877": "光伏",
    "600732": "光伏", "688223": "光伏",
    
    # 半导体/芯片
    "688981": "半导体", "002371": "半导体", "603501": "半导体", "688008": "半导体",
    "688012": "半导体", "603986": "半导体", "002049": "半导体", "688036": "半导体",
    
    # 消费电子
    "002475": "消费电子", "002241": "消费电子", "603160": "消费电子",
    
    # 医药/医疗
    "000538": "医药", "600276": "医药", "002007": "医药", "300015": "医药",
    "600196": "医药", "000963": "医药", "300122": "医药", "002821": "医药",
    
    # 银行
    "601398": "银行", "601288": "银行", "601939": "银行", "601328": "银行",
    "600036": "银行", "000001": "银行", "601166": "银行", "600000": "银行",
    
    # 保险
    "601318": "保险", "601628": "保险", "601601": "保险", "600061": "保险",
    
    # 证券
    "600030": "证券", "601211": "证券", "000776": "证券", "601688": "证券",
    "600958": "证券",
    
    # 地产
    "001979": "地产", "000002": "地产", "600048": "地产", "600383": "地产",
    "000069": "地产", "600340": "地产",
    
    # 互联网/科技
    "00700": "互联网", "09988": "互联网", "09618": "互联网", "03690": "互联网",
    "01024": "互联网", "09999": "互联网", "02018": "互联网",
    
    # 汽车
    "600104": "汽车", "000625": "汽车", "601238": "汽车", "002594": "汽车",
    "01211": "汽车", "09868": "汽车", "02015": "汽车",
    
    # 家电
    "000651": "家电", "000333": "家电", "002032": "家电", "600690": "家电",
    
    # 食品饮料
    "600887": "食品饮料", "000895": "食品饮料", "603288": "食品饮料",
    "002557": "食品饮料", "600597": "食品饮料",
    
    # 军工
    "600893": "军工", "000768": "军工", "600760": "军工", "002179": "军工",
    "600118": "军工", "000738": "军工",
    
    # 煤炭
    "601088": "煤炭", "600188": "煤炭", "601898": "煤炭", "000983": "煤炭",
    
    # 钢铁
    "600019": "钢铁", "000709": "钢铁", "600010": "钢铁", "000898": "钢铁",
    
    # 石油化工
    "600028": "石油化工", "601857": "石油化工", "600938": "石油化工",
    
    # 电力
    "600900": "电力", "600886": "电力", "601991": "电力", "003816": "电力",
    
    # AI/软件
    "688111": "AI软件", "300033": "AI软件", "300454": "AI软件", "002230": "AI软件",
    "688561": "AI软件", "300496": "AI软件",
}

# 行业关键词映射（用于新闻搜索）
SECTOR_KEYWORDS = {
    "白酒": ["白酒", "酱酒", "浓香型", "清香型", "茅台", "五粮液"],
    "新能源": ["新能源", "锂电池", "动力电池", "储能", "电动车", "充电桩"],
    "光伏": ["光伏", "太阳能", "组件", "硅片", "逆变器"],
    "半导体": ["半导体", "芯片", "晶圆", "封测", "光刻", "国产替代"],
    "消费电子": ["消费电子", "智能手机", "穿戴设备", "TWS", "平板电脑"],
    "医药": ["医药", "创新药", "仿制药", "CXO", "生物制药", "医疗器械"],
    "银行": ["银行", "信贷", "存款", "LPR", "净息差"],
    "保险": ["保险", "寿险", "财险", "保费", "偿付能力"],
    "证券": ["券商", "证券", "投行", "经纪", "两融"],
    "地产": ["地产", "房地产", "楼市", "房企", "土拍", "限购"],
    "互联网": ["互联网", "电商", "社交", "游戏", "广告", "云计算"],
    "汽车": ["汽车", "整车", "智能驾驶", "自动驾驶", "车规级"],
    "家电": ["家电", "空调", "冰箱", "洗衣机", "小家电"],
    "食品饮料": ["食品", "饮料", "乳制品", "调味品", "零食"],
    "军工": ["军工", "国防", "航空", "航天", "导弹", "舰船"],
    "煤炭": ["煤炭", "动力煤", "焦煤", "煤价"],
    "钢铁": ["钢铁", "钢材", "螺纹钢", "热卷"],
    "石油化工": ["石油", "原油", "天然气", "炼化", "化工"],
    "电力": ["电力", "火电", "水电", "核电", "发电量"],
    "AI软件": ["AI", "人工智能", "大模型", "GPT", "软件", "AIGC"],
}


class WatchlistService:
    """自选股服务"""
    
    def __init__(self):
        self._config_stocks: List[WatchlistStock] = []
        self._db_stocks: List[WatchlistStock] = []
        self._merged_stocks: List[WatchlistStock] = []
        self._sectors: Set[str] = set()
    
    def load_from_config(self, watchlist_config: str) -> List[WatchlistStock]:
        """
        从配置字符串加载自选股
        
        Args:
            watchlist_config: 格式 "代码:名称:市场,代码:名称:市场"
        """
        self._config_stocks = []
        
        if not watchlist_config or not watchlist_config.strip():
            return self._config_stocks
        
        for item in watchlist_config.split(","):
            item = item.strip()
            if ":" in item:
                parts = item.split(":")
                if len(parts) >= 2:
                    code = parts[0].strip()
                    name = parts[1].strip()
                    market = parts[2].strip() if len(parts) > 2 else "A"
                    sector = self._get_stock_sector(code)
                    
                    self._config_stocks.append(WatchlistStock(
                        code=code,
                        name=name,
                        market=market,
                        sector=sector,
                        source="config"
                    ))
        
        self._update_merged()
        return self._config_stocks
    
    def load_from_database(self, db_stocks: List[Dict]) -> List[WatchlistStock]:
        """
        从数据库加载自选股
        
        Args:
            db_stocks: 数据库查询结果列表 [{"code": "xxx", "name": "xxx", "market": "A"}, ...]
        """
        self._db_stocks = []
        
        for stock in db_stocks:
            code = stock.get("code", "")
            sector = self._get_stock_sector(code)
            
            self._db_stocks.append(WatchlistStock(
                code=code,
                name=stock.get("name", ""),
                market=stock.get("market", "A"),
                sector=sector,
                source="database"
            ))
        
        self._update_merged()
        return self._db_stocks
    
    def _update_merged(self):
        """更新合并后的自选股列表"""
        seen_codes = set()
        self._merged_stocks = []
        self._sectors = set()
        
        # 配置文件的优先（用户主动设置的）
        for stock in self._config_stocks:
            if stock.code not in seen_codes:
                seen_codes.add(stock.code)
                self._merged_stocks.append(stock)
                if stock.sector:
                    self._sectors.add(stock.sector)
        
        # 数据库的补充
        for stock in self._db_stocks:
            if stock.code not in seen_codes:
                seen_codes.add(stock.code)
                self._merged_stocks.append(stock)
                if stock.sector:
                    self._sectors.add(stock.sector)
    
    def _get_stock_sector(self, code: str) -> Optional[str]:
        """根据股票代码获取所属行业"""
        return STOCK_SECTOR_MAP.get(code)
    
    def get_all_stocks(self) -> List[WatchlistStock]:
        """获取所有自选股（合并去重后）"""
        return self._merged_stocks
    
    def get_unique_sectors(self) -> List[str]:
        """获取自选股覆盖的所有行业（去重）"""
        return list(self._sectors)
    
    def get_sector_keywords(self, sector: str) -> List[str]:
        """获取行业搜索关键词"""
        return SECTOR_KEYWORDS.get(sector, [sector])
    
    def get_stocks_by_sector(self, sector: str) -> List[WatchlistStock]:
        """获取指定行业的所有自选股"""
        return [s for s in self._merged_stocks if s.sector == sector]
    
    def get_search_keywords(self) -> Dict[str, List[str]]:
        """
        获取新闻搜索关键词
        
        Returns:
            {
                "stocks": ["贵州茅台", "600519", ...],  # 个股关键词
                "sectors": ["白酒", "新能源", ...]  # 行业关键词
            }
        """
        stock_keywords = []
        for stock in self._merged_stocks:
            stock_keywords.append(stock.name)
            stock_keywords.append(stock.code)
        
        sector_keywords = []
        for sector in self._sectors:
            sector_keywords.extend(self.get_sector_keywords(sector))
        
        return {
            "stocks": list(set(stock_keywords)),
            "sectors": list(set(sector_keywords))
        }
    
    def format_for_prompt(self) -> str:
        """格式化为 AI 分析用的提示文本"""
        if not self._merged_stocks:
            return ""
        
        lines = ["### 📌 用户自选股（请特别关注）", "", "用户正在追踪以下股票，请在分析中重点关注：", ""]
        
        # 按行业分组
        by_sector: Dict[str, List[WatchlistStock]] = {}
        no_sector = []
        
        for stock in self._merged_stocks:
            if stock.sector:
                if stock.sector not in by_sector:
                    by_sector[stock.sector] = []
                by_sector[stock.sector].append(stock)
            else:
                no_sector.append(stock)
        
        # 输出有行业的
        for sector, stocks in by_sector.items():
            lines.append(f"**{sector}板块**：")
            for s in stocks:
                market_name = "A股" if s.market == "A" else "港股"
                lines.append(f"- {s.name}（{s.code}，{market_name}）")
            lines.append("")
        
        # 输出无行业的
        if no_sector:
            lines.append("**其他**：")
            for s in no_sector:
                market_name = "A股" if s.market == "A" else "港股"
                lines.append(f"- {s.name}（{s.code}，{market_name}）")
            lines.append("")
        
        lines.append("请在「模块5:自选股专属分析」中对这些股票进行详细分析。")
        
        return "\n".join(lines)
    
    def format_analysis_prompt(self) -> str:
        """格式化为自选股分析模块的提示文本"""
        if not self._merged_stocks:
            return "（用户暂未设置自选股，可跳过此模块，或提醒用户可以在配置中添加关注的股票）"
        
        lines = []
        
        for stock in self._merged_stocks:
            lines.append(f"""
#### {stock.name}（{stock.code}）

请分析：
1. **今日/本周表现**：结合市场数据，分析该股近期走势
2. **技术面信号**：是否有买入/卖出信号
3. **消息面**：是否有相关新闻影响
4. **操作建议**：买入/持有/减仓/观望，给出具体理由
5. **关键价位**：支撑位和阻力位""")
        
        return "\n".join(lines)


# 单例实例
_watchlist_service: Optional[WatchlistService] = None


def get_watchlist_service() -> WatchlistService:
    """获取自选股服务实例"""
    global _watchlist_service
    if _watchlist_service is None:
        _watchlist_service = WatchlistService()
    return _watchlist_service


def reset_watchlist_service():
    """重置自选股服务（配置变更后调用）"""
    global _watchlist_service
    _watchlist_service = None
