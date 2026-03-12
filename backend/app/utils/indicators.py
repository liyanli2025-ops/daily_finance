"""
技术指标计算工具
"""
from typing import List, Optional, Dict, Any
import numpy as np
from dataclasses import dataclass


@dataclass
class OHLCV:
    """K线数据"""
    open: float
    high: float
    low: float
    close: float
    volume: float


class TechnicalIndicators:
    """技术指标计算器"""
    
    @staticmethod
    def sma(prices: List[float], period: int) -> List[Optional[float]]:
        """
        简单移动平均线 (SMA)
        
        Args:
            prices: 价格序列
            period: 周期
            
        Returns:
            SMA 序列（前 period-1 个为 None）
        """
        if len(prices) < period:
            return [None] * len(prices)
        
        result = [None] * (period - 1)
        
        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1:i + 1]
            result.append(sum(window) / period)
        
        return result
    
    @staticmethod
    def ema(prices: List[float], period: int) -> List[Optional[float]]:
        """
        指数移动平均线 (EMA)
        
        Args:
            prices: 价格序列
            period: 周期
            
        Returns:
            EMA 序列
        """
        if len(prices) < period:
            return [None] * len(prices)
        
        multiplier = 2 / (period + 1)
        result = [None] * (period - 1)
        
        # 第一个 EMA 使用 SMA
        result.append(sum(prices[:period]) / period)
        
        # 后续使用 EMA 公式
        for i in range(period, len(prices)):
            ema_value = (prices[i] - result[-1]) * multiplier + result[-1]
            result.append(ema_value)
        
        return result
    
    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, List[Optional[float]]]:
        """
        MACD 指标
        
        Args:
            prices: 价格序列
            fast: 快线周期（默认12）
            slow: 慢线周期（默认26）
            signal: 信号线周期（默认9）
            
        Returns:
            包含 DIF、DEA、Histogram 的字典
        """
        ema_fast = TechnicalIndicators.ema(prices, fast)
        ema_slow = TechnicalIndicators.ema(prices, slow)
        
        # DIF = EMA(fast) - EMA(slow)
        dif = []
        for f, s in zip(ema_fast, ema_slow):
            if f is not None and s is not None:
                dif.append(f - s)
            else:
                dif.append(None)
        
        # DEA = EMA(DIF, signal)
        dif_values = [v for v in dif if v is not None]
        dea_calc = TechnicalIndicators.ema(dif_values, signal) if len(dif_values) >= signal else []
        
        # 对齐 DEA 到原始长度
        dea = [None] * (len(dif) - len(dea_calc)) + dea_calc
        
        # Histogram = (DIF - DEA) * 2
        histogram = []
        for d, e in zip(dif, dea):
            if d is not None and e is not None:
                histogram.append((d - e) * 2)
            else:
                histogram.append(None)
        
        return {
            "dif": dif,
            "dea": dea,
            "histogram": histogram
        }
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """
        相对强弱指数 (RSI)
        
        Args:
            prices: 价格序列
            period: 周期（默认14）
            
        Returns:
            RSI 序列
        """
        if len(prices) < period + 1:
            return [None] * len(prices)
        
        # 计算价格变化
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        result = [None] * period
        
        # 分离上涨和下跌
        gains = [max(0, c) for c in changes]
        losses = [max(0, -c) for c in changes]
        
        # 第一个 RSI 使用简单平均
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))
        
        # 后续使用平滑平均
        for i in range(period, len(changes)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100 - (100 / (1 + rs)))
        
        return result
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict[str, List[Optional[float]]]:
        """
        布林带
        
        Args:
            prices: 价格序列
            period: 周期（默认20）
            std_dev: 标准差倍数（默认2）
            
        Returns:
            包含 upper、middle、lower 的字典
        """
        if len(prices) < period:
            empty = [None] * len(prices)
            return {"upper": empty, "middle": empty, "lower": empty}
        
        middle = TechnicalIndicators.sma(prices, period)
        
        upper = [None] * (period - 1)
        lower = [None] * (period - 1)
        
        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1:i + 1]
            std = np.std(window)
            upper.append(middle[i] + std_dev * std)
            lower.append(middle[i] - std_dev * std)
        
        return {
            "upper": upper,
            "middle": middle,
            "lower": lower
        }
    
    @staticmethod
    def kdj(highs: List[float], lows: List[float], closes: List[float], 
            n: int = 9, m1: int = 3, m2: int = 3) -> Dict[str, List[Optional[float]]]:
        """
        KDJ 指标
        
        Args:
            highs: 最高价序列
            lows: 最低价序列
            closes: 收盘价序列
            n: RSV 周期（默认9）
            m1: K 值平滑周期（默认3）
            m2: D 值平滑周期（默认3）
            
        Returns:
            包含 K、D、J 的字典
        """
        length = len(closes)
        if length < n:
            empty = [None] * length
            return {"k": empty, "d": empty, "j": empty}
        
        # 计算 RSV
        rsv = [None] * (n - 1)
        for i in range(n - 1, length):
            window_high = max(highs[i - n + 1:i + 1])
            window_low = min(lows[i - n + 1:i + 1])
            
            if window_high == window_low:
                rsv.append(50.0)
            else:
                rsv.append((closes[i] - window_low) / (window_high - window_low) * 100)
        
        # 计算 K、D、J
        k_values = [None] * (n - 1)
        d_values = [None] * (n - 1)
        j_values = [None] * (n - 1)
        
        # 初始化
        k_values.append(50.0)
        d_values.append(50.0)
        j_values.append(50.0)
        
        for i in range(n, length):
            k = (2/3) * k_values[-1] + (1/3) * rsv[i]
            d = (2/3) * d_values[-1] + (1/3) * k
            j = 3 * k - 2 * d
            
            k_values.append(k)
            d_values.append(d)
            j_values.append(j)
        
        return {
            "k": k_values,
            "d": d_values,
            "j": j_values
        }
    
    @staticmethod
    def calculate_all(klines: List[OHLCV]) -> Dict[str, Any]:
        """
        计算所有技术指标
        
        Args:
            klines: K线数据列表
            
        Returns:
            所有指标的最新值
        """
        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        
        # 计算各项指标
        ma5 = TechnicalIndicators.sma(closes, 5)
        ma10 = TechnicalIndicators.sma(closes, 10)
        ma20 = TechnicalIndicators.sma(closes, 20)
        ma60 = TechnicalIndicators.sma(closes, 60)
        
        macd = TechnicalIndicators.macd(closes)
        rsi = TechnicalIndicators.rsi(closes)
        boll = TechnicalIndicators.bollinger_bands(closes)
        kdj = TechnicalIndicators.kdj(highs, lows, closes)
        
        # 返回最新值
        return {
            "ma5": ma5[-1] if ma5 else None,
            "ma10": ma10[-1] if ma10 else None,
            "ma20": ma20[-1] if ma20 else None,
            "ma60": ma60[-1] if ma60 else None,
            "macd_dif": macd["dif"][-1] if macd["dif"] else None,
            "macd_dea": macd["dea"][-1] if macd["dea"] else None,
            "macd_histogram": macd["histogram"][-1] if macd["histogram"] else None,
            "rsi_6": TechnicalIndicators.rsi(closes, 6)[-1] if len(closes) > 6 else None,
            "rsi_12": TechnicalIndicators.rsi(closes, 12)[-1] if len(closes) > 12 else None,
            "rsi_24": TechnicalIndicators.rsi(closes, 24)[-1] if len(closes) > 24 else None,
            "boll_upper": boll["upper"][-1] if boll["upper"] else None,
            "boll_middle": boll["middle"][-1] if boll["middle"] else None,
            "boll_lower": boll["lower"][-1] if boll["lower"] else None,
            "kdj_k": kdj["k"][-1] if kdj["k"] else None,
            "kdj_d": kdj["d"][-1] if kdj["d"] else None,
            "kdj_j": kdj["j"][-1] if kdj["j"] else None,
        }
