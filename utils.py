from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

def display_triage_steps(final_state: dict):
    """Parses and displays the LangGraph state dictionary step-by-step."""
    print("\n" + "="*80)
    print(" 🚀 LANGGRAPH STATE MACHINE: STEP-BY-STEP EXECUTION LOG")
    print("="*80 + "\n")

    messages = final_state.get("messages", [])
    step_num = 1

    for message in messages:
        # --- STEP 1: USER INPUT ---
        if isinstance(message, HumanMessage):
            print(f"📍 [STEP {step_num}] USER INPUT (HumanMessage)")
            print(f"   💬 prompt: \"{message.content}\"")
            print("-" * 50 + "\n")
            step_num += 1

        # --- STEP 2: AGENT DECISION (TOOL CALLS) ---
        elif isinstance(message, AIMessage) and message.tool_calls:
            print(f"📍 [STEP {step_num}] AGENT THOUGHT & DECISION (AIMessage)")
            print("   🤔 Thought: I need more details from ServiceNow to answer this.")
            for tool_call in message.tool_calls:
                print(f"   🔌 Action: Calling tool '{tool_call['name']}'")
                print(f"   📥 Arguments: {tool_call['args']}")
            print("-" * 50 + "\n")
            step_num += 1

        # --- STEP 3: TOOL EXECUTION ---
        elif isinstance(message, ToolMessage):
            print(f"📍 [STEP {step_num}] TOOL EXECUTION RESULT (ToolMessage)")
            print(f"   🛠️ Tool run: '{message.name}'")
            print("   📤 Database Output retrieved:")
            # Often tool output is a stringified JSON list; we indent it for readability
            print(f"      {message.content}")
            print("-" * 50 + "\n")
            step_num += 1

        # --- STEP 4: FINAL AGENT SYNTHESIS ---
        elif isinstance(message, AIMessage) and not message.tool_calls:
            print(f"📍 [STEP {step_num}] FINAL AGENT RESPONSE (AIMessage)")
            print("   📝 Compiled Markdown Report:")
            # Indent the markdown lines for beautiful spacing
            indented_report = "\n".join(f"      {line}" for line in message.content.splitlines())
            print(indented_report)
            print("-" * 50 + "\n")
            step_num += 1

    # --- GLOBAL STATE VARIABLES ---
    print("="*80)
    print(" 💾 FINAL CONSOLIDATED STATE VARIABLES")
    print("="*80)
    for key, value in final_state.items():
        if key != "messages":  # We already printed messages
            print(f" * **{key}**: {value}")
    print("="*80 + "\n")