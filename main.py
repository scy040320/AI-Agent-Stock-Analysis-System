import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import HumanMessage, SystemMessage
from tools import fetch_stock_data

# 1. 加载环境变量与大模型
load_dotenv()
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    temperature=0.1 
)

# 2. 预先构建 [节点 A] 所需的工具代理引擎
tools = [fetch_stock_data]
analyst_engine = create_react_agent(llm, tools)

# 3. 定义图节点函数 (Node A: 数据分析师)
def data_analyst_node(state: MessagesState):
    print("\n▶️ [系统日志] 正在执行节点 A: 数据分析师开始抓取和清洗数据...")
    
    # 赋予当前节点专属的人设
    prompt = "你是一位严谨的数据分析师。请调用工具获取数据，并输出客观、清晰的对比摘要。"
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    # 触发工具调用循环
    response = analyst_engine.invoke({"messages": messages})
    
    # 核心架构技巧：我们只把分析师的“最终结论”传递给下一个节点，
    # 屏蔽掉中间繁杂的工具调用日志，实现节点间的解耦。
    final_summary = response["messages"][-1]
    return {"messages": [final_summary]}

# 4. 定义图节点函数 (Node B: 投资经理)
def investment_manager_node(state: MessagesState):
    print("▶️ [系统日志] 正在执行节点 B: 投资经理正在进行深度推理与研报撰写...\n")
    
    # 提取上一个节点 (分析师) 传过来的数据
    analyst_report = state["messages"][-1].content
    
    # 赋予投资经理专属人设，不给它任何工具，只让它专心推理
    sys_msg = SystemMessage(content="你是首席投资经理 Sun。请根据分析师提供的数据，结合当前的宏观科技环境，撰写一份结构清晰、具备深度的投资策略报告。请在报告末尾署名 '投资经理 Chen'。")
    user_msg = HumanMessage(content=f"这是分析师整理好的客观数据：\n{analyst_report}\n\n请给出最终的研报。")
    
    # 直接调用大模型进行纯文本推理
    response = llm.invoke([sys_msg, user_msg])
    return {"messages": [response]}

# 5. 编排过程式流水线 (Procedural Pipeline)
# 严格的单向数据流，拒绝复杂的有限状态机(FSM)嵌套
workflow = StateGraph(MessagesState)

# 注册节点
workflow.add_node("Data_Analyst", data_analyst_node)
workflow.add_node("Investment_Manager", investment_manager_node)

# 定义执行顺序：START -> 分析师 -> 经理 -> END
workflow.add_edge(START, "Data_Analyst")
workflow.add_edge("Data_Analyst", "Investment_Manager")
workflow.add_edge("Investment_Manager", END)

# 编译成可执行的程序
app = workflow.compile()

if __name__ == "__main__":
    print("🚀 启动多智能体量化投研流水线...")
    
    # 用户的初始指令
    user_input = "请帮我查询苹果公司(AAPL)和特斯拉(TSLA)最近的股价表现，并对比市盈率。"
    
    # 触发流水线
    final_state = app.invoke({"messages": [HumanMessage(content=user_input)]})
    
    print("================ 最终投资研报 ================\n")
    # 打印状态机里的最后一条消息（即经理的产出）
    print(final_state["messages"][-1].content)