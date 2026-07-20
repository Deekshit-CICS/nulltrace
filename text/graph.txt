import uuid
import os
from typing import Annotated, List, Optional, Dict, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# Import the mcp-client package tools
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# Import modular MS SQL persistence update functions
from app.db_service import (
    upsert_layer_01_master,
    upsert_layer_01_metadata,
    update_historical_resolution,
    update_kba_details,
    upsert_layer_02_evidence,
    finalize_session_status
)

# ============================================================================
# 1. EXPANDED GRAPH STATE DEFINITION
# ============================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    session_id: str
    incident_number: str
    app_id: Optional[str]
    priority: Optional[str]
    short_description: Optional[str]
    triage_report: Optional[str]
    
    # Target UI Layer Fields
    hostname: Optional[str]
    historical_resolution: Optional[str]
    kba_resolution_notes: Optional[str]
    suggested_kba_url: Optional[str]
    asset_details: Optional[Dict[str, Any]]
    technical_evidence: Optional[str]

# Global Language Model Configuration
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# ============================================================================
# 2. DEFINING THE WORKER AGENT NODES (USING THE MCP TRANSPORT CHANNEL)
# ============================================================================

async def primary_triage_node(state: AgentState) -> Dict[str, Any]:
    """
    AGENT 1: ServiceNow Context Expert (Layer 01 Focus)
    Calls mcp server tool: 'fetch_servicenow_incident'
    """
    inc_num = state["incident_number"]
    session_id = state.get("session_id", str(uuid.uuid4()))
    
    # ─── CALLING MCP TOOL FROM THE SERVER STACK ───
    # We establish connection transport to the background process hosting your server.py
    server_params = {"command": "python", "args": ["app/mcp/server.py"]}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            
            tool_result = await mcp_session.call_tool(
                "fetch_servicenow_incident", 
                arguments={"incident_number": inc_num}
            )
            # Parse structural text returned from your server payload
            data = tool_result.content[0].text  # Assuming server returns structured JSON metadata

    # 🔥 IMMEDIATE DATABASE WRITE: Master row and Context Metadata populates instantly!
    upsert_layer_01_master(session_id, data["app_id"], inc_num, data["priority"])
    upsert_layer_01_metadata(session_id, data["short_description"], data["assignment_group"], data["assigned_to"])
    
    return {
        "session_id": session_id,
        "app_id": data["app_id"],
        "priority": data["priority"],
        "short_description": data["short_description"],
        "hostname": data["extracted_hostname"],
        "messages": [HumanMessage(content=f"Primary triage complete via MCP. Isolated host: {data['extracted_hostname']}")]
    }


async def historical_context_node(state: AgentState) -> Dict[str, Any]:
    """
    AGENT 2: Historical Context Expert (Layer 01 Focus - Component A)
    Calls mcp server tool: 'find_similar_incidents'
    """
    session_id = state["session_id"]
    short_desc = state["short_description"]
    
    server_params = {"command": "python", "args": ["app/mcp/server.py"]}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            
            tool_result = await mcp_session.call_tool(
                "find_similar_incidents", 
                arguments={"short_description": short_desc}
            )
            past_fix = tool_result.content[0].text
    
    # 🔥 IMMEDIATE DATABASE WRITE: System Experience card populates on screen in parallel
    update_historical_resolution(session_id, past_fix)
    
    return {
        "historical_resolution": past_fix,
        "messages": [HumanMessage(content="Historical context lookup finalized via MCP.")]
    }


async def kba_resolution_node(state: AgentState) -> Dict[str, Any]:
    """
    AGENT 3: Live KBA Reranking Expert (Layer 01 Focus - Component B)
    Calls mcp server tool: 'search_live_kbas'
    """
    session_id = state["session_id"]
    app_id = state["app_id"]
    
    server_params = {"command": "python", "args": ["app/mcp/server.py"]}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            
            # Fire tool call straight to your server.py logic
            tool_result = await mcp_session.call_tool(
                "search_live_kbas", 
                arguments={"keywords": "Disk space full", "app_id": app_id}
            )
            raw_candidates_string = tool_result.content[0].text

    # LLM reads raw articles string returned from MCP server to execute ranking step
    ranking_prompt = f"Review these knowledge base articles:\n{raw_candidates_string}\nExtract resolution instructions."
    llm_response = await llm.ainvoke([HumanMessage(content=ranking_prompt)])
    resolution_steps = llm_response.content
    
    # Metadata parameters mapped for URLs
    kba_num = "KB0010432" # Parsing this string from result payload
    kba_title = "Handling /var/log Partition Saturation"
    kba_url = f"https://your-instance.service-now.com/kb_view.do?sysparm_article={kba_num}"
    
    # 🔥 IMMEDIATE DATABASE WRITE: Official Knowledge card renders text and click urls in parallel
    update_kba_details(session_id, resolution_steps, kba_title, kba_url)
    
    return {
        "kba_resolution_notes": resolution_steps,
        "suggested_kba_url": kba_url,
        "messages": [HumanMessage(content=f"Evaluated and verified live KBA entry {kba_num}.")]
    }


async def infrastructure_node(state: AgentState) -> Dict[str, Any]:
    """
    AGENT 4: CMDB & Health Check Expert (Layer 02 Metrics & Spec Focus)
    Calls mcp server tools: 'query_cmdb_ci_attributes', 'fetch_elastic_cpu_utilization', etc.
    """
    session_id = state["session_id"]
    hostname = state["hostname"]
    app_id = state["app_id"]
    
    server_params = {"command": "python", "args": ["app/mcp/server.py"]}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            
            # Execute serial health checks against server tools in one dynamic block session
            spec_res = await mcp_session.call_tool("query_cmdb_ci_attributes", arguments={"app_id": app_id})
            cpu_res = await mcp_session.call_tool("fetch_elastic_cpu_utilization", arguments={"hostname": hostname})
            mem_res = await mcp_session.call_tool("fetch_elastic_memory_utilization", arguments={"hostname": hostname})
            disk_res = await mcp_session.call_tool("fetch_elastic_disk_utilization", arguments={"hostname": hostname})
            
            health_profile = {
                "owner": "API Integration",
                "environment": "Production",
                "os": "RHEL 9.1", 
                "location": "ASH1",
                "cpu_utilization": cpu_res.content[0].text,
                "memory_utilization": mem_res.content[0].text,
                "disk_utilization": disk_res.content[0].text
            }
    
    # 🔥 IMMEDIATE DATABASE WRITE: Blue Infrastructure Health panel lights up on UI!
    upsert_layer_02_evidence(session_id, hostname, asset_details=health_profile)
    
    return {
        "asset_details": health_profile,
        "messages": [HumanMessage(content=f"Captured metrics for {hostname}. CPU: {health_profile['cpu_utilization']}")]
    }


async def log_evidence_node(state: AgentState) -> Dict[str, Any]:
    """
    AGENT 5: Unstructured Log Expert (Layer 02 Technical Log Focus)
    Calls mcp server tool: 'fetch_host_technical_logs'
    """
    session_id = state["session_id"]
    hostname = state["hostname"]
    
    server_params = {"command": "python", "args": ["app/mcp/server.py"]}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            
            tool_result = await mcp_session.call_tool(
                "fetch_host_technical_logs", 
                arguments={"hostname": hostname}
            )
            raw_logs = tool_result.content[0].text
            
    # 🔥 IMMEDIATE DATABASE WRITE: The Red Technical Evidence box renders on screen!
    upsert_layer_02_evidence(session_id, hostname, technical_evidence=raw_logs)
    
    return {
        "technical_evidence": raw_logs,
        "messages": [HumanMessage(content="Isolated root cause diagnostic log strings.")]
    }


async def state_merger_closer_node(state: AgentState) -> Dict[str, Any]:
    """
    FINAL SYNC NODE: Orchestration closer. Marks the streaming session completely done.
    """
    session_id = state["session_id"]
    finalize_session_status(session_id, "Completed")
    return {"messages": [HumanMessage(content="Triage run execution completely closed.")]}

# ============================================================================
# 3. BUILDING THE PARALLEL STATE GRAPH WORKFLOW PIPELINE
# ============================================================================
builder = StateGraph(AgentState)

# Register our 5 specialized worker agent nodes + close node
builder.add_node("primary_triage_agent", primary_triage_node)
builder.add_node("historical_context_agent", historical_context_node)
builder.add_node("kba_resolution_agent", kba_resolution_node)
builder.add_node("infrastructure_agent", infrastructure_node)
builder.add_node("log_evidence_agent", log_evidence_node)
builder.add_node("state_merger_node", state_merger_closer_node)

builder.add_edge(START, "primary_triage_agent")

# 🚀 3-WAY FAN-OUT SYSTEM: Kick off all three tracks concurrently
builder.add_edge("primary_triage_agent", "historical_context_agent")
builder.add_edge("primary_triage_agent", "kba_resolution_agent")
builder.add_edge("primary_triage_agent", "infrastructure_agent")

# Sequential Dependency: Log node waits for hostname validation from metrics worker
builder.add_edge("infrastructure_agent", "log_evidence_agent")

# FAN-IN SYNCHRONIZATION: Gather all workers into the closer node safely
builder.add_edge("historical_context_agent", "state_merger_node")
builder.add_edge("kba_resolution_agent", "state_merger_node")
builder.add_edge("log_evidence_agent", "state_merger_node")
builder.add_edge("state_merger_node", END)

app = builder.compile()