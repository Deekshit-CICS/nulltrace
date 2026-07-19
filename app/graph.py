from typing import Annotated, TypedDict, List
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.prebuilt import ToolNode, tools_condition

from mcp_client import get_mcp_tools
from auth import create_authenticated_openai_and_http_clients

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    incident_number: str
    triage_report: str

async def create_triage_graph():
    # 1. Fetch dynamic tools from your lcoal FastMCP server
    mcp_tools, mcp_client = await get_mcp_tools()
    
    print(f"mcp_tools -> {mcp_tools}")
    
    # 2. Instantiate custom corporate gateway client
    openai_client, sync_client, async_client = create_authenticated_openai_and_http_clients()
    
    # 3. Configure ChatOpenAI to route through your internal GenAI gateway
    llm = ChatOpenAI(
        model="azure-openai-chat-gpt52",
        api_key=openai_client.api_key,
        base_url=str(openai_client.base_url),
        http_client=sync_client,
        http_async_client=async_client,
        temperature=0
    )

    # Bind toosl natively to the model instances
    llm_with_tools = llm.bind_tools(mcp_tools)

    # Node A: The Triage Reasoning Agent
    async def triage_agent_node(state: AgentState):
        system_prompt = (
            "You are an Automated ServiceNow Technical Triage Agent.\n"
            "Look up ticket data using 'get_incident_details. Do not guess.\n"
            "Provide the final assessment output in clean markdown formatiing."
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # Node B: Your Original Compilation Node
    def compilation_node(state: AgentState):
        final_ai_msg = state["messages"][-1].content
        # Retun the formatted report directly back into the graph state
        return {"triage_report": str(final_ai_msg)}

    # Build and layout the State Graph
    workflow = StateGraph(AgentState)

    # Define Graph Nodes
    workflow.add_node("agent", triage_agent_node)
    workflow.add_node("tools", ToolNode(mcp_tools))
    workflow.add_node("summarize", compilation_node)

    #Define Edges and Conditional Paths mathcing your exact logic
    workflow.add_edge(START, "agent")

    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            "END": "summarize" # Route to compilation_node when the LLM finishes tool calli
        }
    )

    workflow.add_edge("tools", "agent")
    workflow.add_edge("summarize", END)

    # Compile the graph
    compiled_graph = workflow.compile()

    print(compiled_graph.get_graph().draw_ascii())

    return compiled_graph, mcp_client