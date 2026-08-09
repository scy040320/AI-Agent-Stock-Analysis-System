import os
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, SystemMessage
from tools import fetch_stock_data

class PerformanceTracker:
    def __init__(self):
        self.start_time = 0
        self.end_time = 0
    def start(self):
        self.start_time = time.time()
    def stop(self) -> float:
        self.end_time = time.time()
        return round(self.end_time - self.start_time, 2)

tracker = PerformanceTracker()

# 1. 意图路由器（分诊台：判断用户是个股分析还是大盘宏观）
def intent_router(state: MessagesState) -> str:
    user_msg = state["messages"][-1].content
    # 若包含数字（股票代码）或明确的个股分析关键词，走个股支路；否则走宏观大盘支路
    if any(char.isdigit() for char in user_msg) or any(k in user_msg for k in ["股票", "个股", "分析", "茅台", "恒通", "涨跌"]):
        return "individual_stock"
    else:
        return "macro_trend"

# 2. 宏观大盘分析节点
def macro_analyst_node(state: MessagesState, llm) -> Dict[str, Any]:
    print("▶️ [支路 B] 宏观分析师正在撰写大盘与经济研报...")
    sys_msg = SystemMessage(content="你是首席宏观策略分析师 Chen。请针对用户关于大盘、宏观经济或整体市场走势的提问，撰写一份结构清晰、有深度的宏观研报，末尾署名 '宏观策略分析师 Chen'。")
    response = llm.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}

# 3. 个股数据分析节点
def data_analyst_node(state: MessagesState, analyst_engine) -> Dict[str, Any]:
    print("▶️ [支路 A] 数据分析师响应中...")
    prompt = "你是一位严谨的数据分析师。请调用工具获取最新行情与基本面，并输出精简摘要。"
    messages = [SystemMessage(content=prompt)] + state["messages"]
    try:
        response = analyst_engine.invoke({"messages": messages})
        return {"messages": [response["messages"][-1]]}
    except Exception as e:
        return {"messages": [HumanMessage(content=f"数据获取异常: {str(e)}")]}

# 4. 数据校验节点
def result_validation_node(state: MessagesState) -> Dict[str, Any]:
    last_message = state["messages"][-1].content
    if "错误" in last_message or "未找到" in last_message:
        validation_note = SystemMessage(content="[校验提示]: 数据提取存在异常，请投资经理注意风险提示。")
    else:
        validation_note = SystemMessage(content="[校验提示]: 原始数据校验通过。")
    return {"messages": [validation_note]}

# 5. 投资经理个股研报节点
def investment_manager_node(state: MessagesState, llm) -> Dict[str, Any]:
    analyst_report = state["messages"][-2].content if len(state["messages"]) >= 2 else state["messages"][-1].content
    validation_status = state["messages"][-1].content
    
    sys_msg = SystemMessage(content=(
        "你是首席投资经理 Chen。你现在需要对用户刚才查询的具体 A 股标的撰写《个股深度投资策略研报》。\n"
        "【严格指令】：\n"
        "1. 你的分析必须紧紧围绕数据分析师提供的个股行情与业务属性展开，绝不能写成脱离个股的宏观经济论文。\n"
        "2. 研报必须包含：个股近期走势解读、基本面风险评估、以及针对该股票的具体操作建议。\n"
        "3. 请在研报末尾署名 '投资经理 Chen'。"
    ))
    user_msg = HumanMessage(content=f"数据摘要：\n{analyst_report}\n\n校验状态：\n{validation_status}\n\n请输出最终个股研报。")
    response = llm.invoke([sys_msg, user_msg])
    return {"messages": [response]}

# 6. 动态编译带有条件路由和 HITL 中断的图
def get_user_app(api_key: str):
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        temperature=0.1
    )
    tools_list = [fetch_stock_data]
    analyst_engine = create_react_agent(llm, tools_list)

    workflow = StateGraph(MessagesState)
    
    # 注册节点
    workflow.add_node("Data_Analyst", lambda s: data_analyst_node(s, analyst_engine))
    workflow.add_node("Validator", result_validation_node)
    workflow.add_node("Investment_Manager", lambda s: investment_manager_node(s, llm))
    workflow.add_node("Macro_Analyst", lambda s: macro_analyst_node(s, llm))
    
    # 【条件路由】：从 START 触发 intent_router
    workflow.add_conditional_edges(
        START,
        intent_router,
        {
            "individual_stock": "Data_Analyst",
            "macro_trend": "Macro_Analyst"
        }
    )
    
    # 个股支路
    workflow.add_edge("Data_Analyst", "Validator")
    workflow.add_edge("Validator", "Investment_Manager")
    workflow.add_edge("Investment_Manager", END)
    
    # 宏观支路
    workflow.add_edge("Macro_Analyst", END)
    
    import sqlite3
    conn = sqlite3.connect("agent_memory.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    
    # 仅对个股支路的投资经理前设置拦截（HITL）
    return workflow.compile(
        checkpointer=memory,
        interrupt_before=["Investment_Manager"]
    )