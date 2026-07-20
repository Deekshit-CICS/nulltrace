import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
from langchain_core.messages import HumanMessage
from graph import create_triage_graph

# Import a DB service function to fetch data for the frontend
# (You will define this in your db_service.py to run SELECT queries)

from app.db_service import (
    fetch_complete_triage_session_data,
    get_active_session_by_incident,
    archive_or_delete_old_session # <-- Added placeholder name for session lifecycle housecleaning
)

app = FastAPI(title="GOC Toolkit AI Service")

# ============================================================================
# 1. PYDANTIC SCHEMAS
# ============================================================================
class TriageRequest(BaseModel):
    incident_number: str

class TriageInitResponse(BaseModel):
    status: str
    session_id: str
    incident_number: str

class TriageStatusResponse(BaseModel):
    session_id: str
    status: str
    app_id: Optional[str]
    priority: Optional[str]
    short_description: Optional[str]
    historical_resolution: Optional[str]
    kba_resolution_notes: Optional[str]
    suggested_kba_url: Optional[str]
    hostname: Optional[str]
    asset_details: Optional[Dict[str, Any]]
    technical_evidence: Optional[str]

# ============================================================================
# 2. BACKGROUND TASK EXECUTOR
# ============================================================================
async def execute_graph_background(incident_number: str, session_id: str):
    """Runs the compiled LangGraph workflow asynchronously in the background."""
    try:
        graph, mcp_client = await create_triage_graph()
        
        inputs = {
            "messages": [
                HumanMessage(content=f"Analyze operational metrics data and triage ticket {incident_number}"),
            ],
            "incident_number": incident_number,
            "session_id": session_id,
            "triage_report": ""
        }
        
        config = {"configurable": {"thread_id": incident_number}}
        await graph.ainvoke(inputs, config)
        
    except Exception as e:
        print(f"Background Graph Execution Failed for {incident_number}: {str(e)}")

# ============================================================================
# 3. ENDPOINTS
# ============================================================================

@app.post("/api/v1/triage/start", response_model=TriageInitResponse)
async def start_triage(payload: TriageRequest, background_tasks: BackgroundTasks):
    """
    Kicks off multi-agent triage in a background task.
    Deduplicates runs by fetching existing tracking states if they exist in DB.
    """
    try:
        inc_num = payload.incident_number.strip()
        
        # 1. 🛑 CHECK FOR RECENT EXECUTION RUNS
        # Inspect the table to see if this ticket was triggered previously
        existing_session = get_active_session_by_incident(inc_num)
        
        # 1. 🛑 CONDITIONAL DATABASE INTERCEPTOR
        if not payload.force_refresh:
            # Check if this ticket was triggered previously
            existing_session = get_active_session_by_incident(inc_num)
            
            if existing_session:
                # Return the cached tracking ID right away
                return TriageInitResponse(
                    status=existing_session["status"].lower(), 
                    session_id=existing_session["session_id"],
                    incident_number=inc_num
                )
        else:
            # 🔄 FORCE REFRESH TRIGGERED: 
            # Housecleaning step: Unlink or flag old records for this ticket in MS SQL so 
            # our frontend GET endpoint queries aren't confused by dangling historical rows.
            archive_or_delete_old_session(inc_num)
            
        # 2. GREEN FIELD RUN: If it's a new ticket request, spin up background loops
        session_id = str(uuid.uuid4())
        
        background_tasks.add_task(
            execute_graph_background, 
            incident_number=inc_num, 
            session_id=session_id
        )
        
        return TriageInitResponse(
            status="initiated",
            session_id=session_id,
            incident_number=inc_num
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify/initialize triage tracking: {str(e)}")


@app.get("/api/v1/triage/status/{session_id}", response_model=TriageStatusResponse)
async def get_triage_status(session_id: str):
    """
    Target endpoint for your UI's 'Refresh' button.
    Reads the database tables and returns the latest available data state.
    """
    try:
        # Query your MS SQL tables using a JOIN across triage_sessions, triage_metadata, and triage_evidence
        data = fetch_complete_triage_session_data(session_id)
        
        if not data:
            raise HTTPException(status_code=404, detail="Triage session not found.")
            
        return TriageStatusResponse(**data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database read failure: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)