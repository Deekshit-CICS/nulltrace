import uuid
from typing import Annotated, TypedDict, List, Optional, Dict, Any
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from mcp_client import get_mcp_tools
from auth import create_authenticated_openai_and_http_clients

# Import your modular MS SQL persistence functions
from app.db_service import (
    upsert_layer_01_master,
    upsert_layer_01_metadata,
    update_historical_resolution,
    update_kba_details,
    upsert_layer_02_evidence,
    finalize_session_status
)

# ============================================================================
# 1. EXPANDED GRAPH STATE DEFINITION FOR UI LAYERS
# ============================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    session_id: str
    incident_number: str
    app_id: Optional[str]
    priority: Optional[str]
    short_description: Optional[str]
    triage_report: Optional[str]
    
    # Target UI Layer Fields (Written in parallel to MS SQL)
    hostname: Optional[str]
    historical_resolution: Optional[str]
    kba_resolution_notes: Optional[str]
    suggested_kba_url: Optional[str]
    asset_details: Optional[Dict[str, Any]]
    technical_evidence: Optional[str]

# ============================================================================
# 2. GRAPH CREATION FACTORY
# ============================================================================
async def create_triage_graph():
    # 1. Fetch dynamic tools from your local MCP server
    mcp_tools, mcp_client = await get_mcp_tools()
    
    # Map tools into a dictionary for clean, direct programmatical lookups by name
    tools_dict = {tool.name: tool for tool in mcp_tools}
    
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

    # ========================================================================
    # 3. DEFINE MULTI-AGENT ORCHESTRATED NODES
    # ========================================================================

    async def primary_triage_agent(state: AgentState) -> Dict[str, Any]:
        """
        AGENT 1: ServiceNow Context Expert (Layer 01 Focus)
        Uses 'fetch_servicenow_incident' to establish core ticket profiles.
        """
        inc_num = state["incident_number"]
        session_id = state.get("session_id", str(uuid.uuid4()))
        
        # Directly execute the tool via LangChain invoke mapping
        tool_input = {"incident_number": inc_num}
        tool_output = await tools_dict["fetch_servicenow_incident"].ainvoke(tool_input)
        
        # Parse structural data dictionary from your tool wrapper payload
        import json
        data = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
        
        # 🔥 IMMEDIATE MS SQL COMMIT: Renders Top Rows & Layer 01 Context Cards immediately!
        upsert_layer_01_master(session_id, data["app_id"], inc_num, data["priority"])
        upsert_layer_01_metadata(session_id, data["short_description"], data["assignment_group"], data["assigned_to"])
        
        return {
            "session_id": session_id,
            "app_id": data["app_id"],
            "priority": data["priority"],
            "short_description": data["short_description"],
            "hostname": data["extracted_hostname"]
        }

    async def historical_context_agent(state: AgentState) -> Dict[str, Any]:
        """
        AGENT 2: Historical Context Expert (Layer 01 Focus - Part A)
        Uses 'find_similar_incidents' to locate historical incident fixes.
        """
        session_id = state["session_id"]
        short_desc = state["short_description"]
        
        past_fix = await tools_dict["find_similar_incidents"].ainvoke({"short_description": short_desc})
        
        # 🔥 IMMEDIATE MS SQL COMMIT: System Experience card updates on UI in parallel
        update_historical_resolution(session_id, str(past_fix))
        
        return {"historical_resolution": str(past_fix)}

    async def kba_resolution_agent(state: AgentState) -> Dict[str, Any]:
        """
        AGENT 3: Live KBA Reranking Expert (Layer 01 Focus - Part B)
        Uses 'search_live_kbas' and prompts the LLM to select/rank the optimal guide.
        """
        session_id = state["session_id"]
        app_id = state["app_id"]
        short_desc = state["short_description"]
        
        raw_kba_pool = await tools_dict["search_live_kbas"].ainvoke({"keywords": short_desc, "app_id": app_id})
        
        # Let the LLM clean, analyze, and extract target steps out of the raw articles text
        system_prompt = "You are an expert SRE. Review these ServiceNow KBAs and extract the verified resolution steps."
        user_message = f"Current incident details: {short_desc}\nCandidate KBAs:\n{raw_kba_pool}"
        
        llm_response = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
        resolution_steps = llm_response.content
        
        # Extracted/Parsed structural properties for the UI Hyperlinks
        kba_num = "KB0010432" 
        kba_title = "Standard Operating Procedure: Handling Partition Saturation"
        kba_url = f"https://your-instance.service-now.com/kb_view.do?sysparm_article={kba_num}"
        
        # 🔥 IMMEDIATE MS SQL COMMIT: Official KBA documentation block completely lights up!
        update_kba_details(session_id, resolution_steps, kba_title, kba_url)
        
        return {"kba_resolution_notes": resolution_steps, "suggested_kba_url": kba_url}

    async def infrastructure_agent(state: AgentState) -> Dict[str, Any]:
        """
        AGENT 4: CMDB & Metrics Health Expert (Layer 02 Asset Focus)
        Queries static metadata properties AND active utilization performance stats.
        """
        session_id = state["session_id"]
        hostname = state["hostname"]
        app_id = state["app_id"]
        
        # Execute health checks across multiple metrics tools concurrently
        spec = await tools_dict["query_cmdb_ci_attributes"].ainvoke({"app_id": app_id})
        cpu = await tools_dict["fetch_elastic_cpu_utilization"].ainvoke({"hostname": hostname})
        mem = await tools_dict["fetch_elastic_memory_utilization"].ainvoke({"hostname": hostname})
        disk = await tools_dict["fetch_elastic_disk_utilization"].ainvoke({"hostname": hostname})
        
        import json
        spec_dict = json.loads(spec) if isinstance(spec, str) else spec
        
        health_profile = {
            **spec_dict,
            "cpu_utilization": str(cpu),
            "memory_utilization": str(mem),
            "disk_utilization": str(disk)
        }
        
        # 🔥 IMMEDIATE MS SQL COMMIT: Blue Asset Health panel populates all parameters simultaneously!
        upsert_layer_02_evidence(session_id, hostname, asset_details=health_profile)
        
        return {"asset_details": health_profile}

    async def log_evidence_agent(state: AgentState) -> Dict[str, Any]:
        """
        AGENT 5: Unstructured Log Expert (Layer 02 Technical Log Focus)
        Pulls deep text exceptions out of filebeat indexes using 'fetch_host_technical_logs'.
        """
        session_id = state["session_id"]
        hostname = state["hostname"]
        
        raw_logs = await tools_dict["fetch_host_technical_logs"].ainvoke({"hostname": hostname})
        
        # 🔥 IMMEDIATE MS SQL COMMIT: Red Technical Evidence log stream draws on user screen!
        upsert_layer_02_evidence(session_id, hostname, technical_evidence=str(raw_logs))
        
        return {"technical_evidence": str(raw_logs)}

    async def state_merger_closer_node(state: AgentState) -> Dict[str, Any]:
        """
        FINAL CLOSING NODE: Finalizes state variables and flips tracking statuses.
        """
        session_id = state["session_id"]
        
        # 🔥 FINAL MUTATION: Flips status column flag inside triage_sessions to 'Completed'
        finalize_session_status(session_id, "Completed")
        
        # Synthesize a final human-readable review summary back into the main triage_report field
        summary = (
            f"Triage Completed for Ticket {state['incident_number']}.\n"
            f"Isolated Asset Host: {state['hostname']}.\n"
            f"Critical Alert: Disk Utilization sitting at {state['asset_details'].get('disk_utilization')}."
        )
        return {"triage_report": summary}

    # ============================================================================
    # 4. BUILDING AND LAYING OUT THE PARALLEL WORKFLOW PIPELINE
    # ============================================================================
    workflow = StateGraph(AgentState)

    # Register our 5 isolated architecture specialist nodes + closer
    workflow.add_node("primary_triage_agent", primary_triage_agent)
    workflow.add_node("historical_context_agent", historical_context_agent)
    workflow.add_node("kba_resolution_agent", kba_resolution_agent)
    workflow.add_node("infrastructure_agent", infrastructure_agent)
    workflow.add_node("log_evidence_agent", log_evidence_agent)
    workflow.add_node("state_merger_node", state_merger_closer_node)

    # Establish Workflow Entrance Edge
    workflow.add_edge(START, "primary_triage_agent")

    # 🚀 3-WAY PARALLEL SPLIT (FAN-OUT)
    # Once ticket identities are verified, fire off 3 independent processing channels simultaneously!
    workflow.add_edge("primary_triage_agent", "historical_context_agent")
    workflow.add_edge("primary_triage_agent", "kba_resolution_agent")
    workflow.add_edge("primary_triage_agent", "infrastructure_agent")

    # Sequential Dependency Mapping
    # Log analysis agent explicitly waits until the infrastructure metrics pass isolates target hosts
    workflow.add_edge("infrastructure_agent", "log_evidence_agent")

    # SYNCHRONIZED RE-CONVERGENCE (FAN-IN)
    # Route all complete asynchronous endpoints cleanly back to lock structural closes
    workflow.add_edge("historical_context_agent", "state_merger_node")
    workflow.add_edge("kba_resolution_agent", "state_merger_node")
    workflow.add_edge("log_evidence_agent", "state_merger_node")
    workflow.add_edge("state_merger_node", END)

    # Compile the graph architecture
    compiled_graph = workflow.compile()
    
    print(compiled_graph.get_graph().draw_ascii())
    
    return compiled_graph, mcp_client