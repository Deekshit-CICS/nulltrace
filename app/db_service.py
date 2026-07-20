import json
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Configure your MS SQL Connection
connection_string = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=your_server_name;"
    "DATABASE=your_db_name;"
    "UID=your_user;PWD=your_password"
)
connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": connection_string})
engine = create_engine(connection_url)

def save_triage_run(state: dict):
    """
    Takes the final_state from LangGraph and persists it to SQL Server.
    """
    session_id = uuid.uuid4() # Generate ID first to link all tables
    
    with engine.begin() as conn:
        # 1. Insert into triage_sessions
        conn.execute(
            text("""
                INSERT INTO triage_sessions (id, app_id, incident_number, priority) 
                VALUES (:id, :app, :inc, :pri)
            """),
            {"id": session_id, "app": state.get("app_id"), "inc": state.get("incident_number"), "pri": state.get("priority")}
        )
        
        # 2. Insert into triage_metadata
        conn.execute(
            text("""
                INSERT INTO triage_metadata (session_id, short_description, assignment_group) 
                VALUES (:sid, :desc, :group)
            """),
            {"sid": session_id, "desc": state.get("short_description"), "group": state.get("assignment_group")}
        )
        
        # 3. Insert into triage_evidence
        conn.execute(
            text("""
                INSERT INTO triage_evidence (session_id, hostname, asset_details, technical_evidence) 
                VALUES (:sid, :host, :details, :evidence)
            """),
            {
                "sid": session_id, 
                "host": state.get("hostname"), 
                "details": state.get("asset_details"), # JSON string
                "evidence": state.get("technical_evidence")
            }
        )
    return session_id

# Add this to app/db_service.py
def fetch_complete_triage_session_data(session_id: str) -> Optional[dict]:
    """Queries MS SQL and returns a combined dictionary of the current state."""
    with engine.connect() as conn:
        query = text("""
            SELECT 
                s.id AS session_id,
                s.status,
                s.app_id,
                s.priority,
                m.short_description,
                m.historical_resolution,
                m.kba_resolution_notes,
                m.suggested_kba_url,
                e.hostname,
                e.asset_details,
                e.technical_evidence
            FROM triage_sessions s
            LEFT JOIN triage_metadata m ON s.id = m.session_id
            LEFT JOIN triage_evidence e ON s.id = e.session_id
            WHERE s.id = :sid
        """)
        
        result = conn.execute(query, {"sid": session_id}).fetchone()
        if not result:
            return None
            
        # Convert row result to dictionary
        row_dict = dict(result._mapping)
        
        # Parse the asset_details JSON string back into a Python dict if it exists
        if row_dict.get("asset_details"):
            try:
                row_dict["asset_details"] = json.loads(row_dict["asset_details"])
            except Exception:
                row_dict["asset_details"] = None
                
        return row_dict

def get_active_session_by_incident(incident_number: str) -> Optional[dict]:
    """
    Queries MS SQL to see if an incident already has an ongoing or cached triage run.
    """
    with engine.connect() as conn:
        query = text("""
            SELECT TOP 1 id AS session_id, status 
            FROM triage_sessions 
            WHERE incident_number = :inc_num
            ORDER BY created_at DESC  -- Pull the latest run if multiple historical exist
        """)
        
        result = conn.execute(query, {"inc_num": incident_number}).fetchone()
        if not result:
            return None
            
        return dict(result._mapping)
    
def archive_or_delete_old_session(incident_number: str):
    """
    Cleans up old records for an incident before a forced re-run.
    You can either delete rows entirely or append a timestamp suffix to the incident code
    to preserve audit trails.
    """
    with engine.begin() as conn:
        # Example strategy: soft-archive past sessions by changing the identifier key string
        conn.execute(
            text("""
                UPDATE triage_sessions 
                SET incident_number = CONCAT(incident_number, '_ARCHIVED_', FORMAT(GETUTCDATE(), 'yyyyMMddHHmmss'))
                WHERE incident_number = :inc_num
            """),
            {"inc_num": incident_number}
        )