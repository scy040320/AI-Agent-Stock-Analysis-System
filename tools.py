import akshare as ak
import requests
from langchain_core.tools import tool

@tool
def fetch_stock_data(ticker: str) -> str:
    """
    用于获取中国 A 股市场指定股票代码的近期行情与基本面数据。
    参数 ticker: 必须是 6 位数的 A 股股票代码，例如 '600519' (贵州茅台), '000001' (平安银行), '300750' (宁德时代)。
    """
    clean_ticker = ticker.strip().split(".")[0]
    
    # 【方案一：尝试通过 AKShare 获取】
    try:
        df = ak.stock_zh_a_hist(symbol=clean_ticker, period="daily", adjust="qfq")
        if df is not None and not df.empty:
            recent_df = df.tail(5)
            result = f"--- 【A股代码: {clean_ticker}】近期行情数据 (来源: AKShare) ---\n"
            for _, row in recent_df.iterrows():
                result += f"- 日期: {row['日期']} | 收盘价: {row['收盘']} 元 | 涨跌幅: {row['涨跌幅']}% | 成交量: {row['成交量']}\n"
            return result
    except Exception as e:
        print(f"AKShare 访问异常，正在尝试备用数据源... 错误: {str(e)}")

    # 【方案二：降级使用新浪财经官方公开 API 接口兜底】
    try:
        # A股代码适配：上证以 1 开头，深证以 0 开头
        market_prefix = "sh" if clean_ticker.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={market_prefix}{clean_ticker}"
        headers = {"Referer": "https://finance.sina.com.cn"}
        
        response = requests.get(url, headers=headers, timeout=5)
        
        # === 修复：拆分条件判断，避免海象运算符语法冲突 ===
        if response.status_code == 200:
            data = response.text
            if data and '="' in data:
                content = data.split('="')[1].split('"')[0]
                fields = content.split(",")
                if len(fields) > 30:
                    name = fields[0]
                    current_price = fields[3]
                    yesterday_close = fields[2]
                    change_pct = (float(current_price) - float(yesterday_close)) / float(yesterday_close) * 100
                    
                    return (f"--- 【A股代码: {clean_ticker}】实时行情 (来源: 新浪财经备用源) ---\n"
                            f"- 股票名称: {name}\n"
                            f"- 当前最新价: {current_price} 元\n"
                            f"- 昨日收盘价: {yesterday_close} 元\n"
                            f"- 涨跌幅估算: {change_pct:.2f}%\n"
                            f"- (注: 备用源成功绕过网络波动，保障投研流程继续)")
        
        return f"错误: 尝试了主用源与备用源均无法获取 A 股代码 {clean_ticker} 的数据，请检查网络或稍后重试。"
        
    except Exception as e2:
        return f"获取 A 股 {ticker} 数据时发生严重错误: {str(e2)}"