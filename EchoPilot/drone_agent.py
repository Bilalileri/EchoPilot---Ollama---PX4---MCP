import asyncio
import json
import re
from typing import TypedDict, Annotated, List, Dict, Any, operator

from langchain_core.messages import ToolMessage, AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.chat_models import init_chat_model
from speaker import speaker
from voice_recognizer import listen_for_command


class MissionState(TypedDict):
    user_prompt: str
    mission_plan: List[Dict[str, Any]]
    messages: Annotated[List[BaseMessage], operator.add]
    current_step_index: int
    target_location_details: Dict[str, Any]
    tool_schemas: str

import os 
from dotenv import load_dotenv
load_dotenv()


LLM = init_chat_model("groq:llama3-8b-8192")
#LLM = ChatOllama(model="llama3.1:latest")

def extract_json_from_string(text: str) -> list:
    """
    More robustly extracts a JSON list from a string. It first checks for a
    markdown block, but if that fails, it finds the first '[' and the last ']'
    to capture the list, making it resilient to formatting errors from the LLM.
    """
   
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        json_str = match.group(1)
    else:
        
        try:
            start_index = text.find('[')
            end_index = text.rfind(']')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_str = text[start_index : end_index + 1]
            else:
                return [] 
        except Exception:
            return []

   
    try:
        parsed = json.loads(json_str)
        # Handle cases where the LLM might double-encode the JSON
        if isinstance(parsed, str):
            return json.loads(parsed)
        return parsed
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON from string snippet: {json_str}")
        return []

def format_tools_for_prompt(tools: list[BaseTool]) -> str:
    schemas = []
    for tool in tools:
        schema = tool.get_input_schema().schema()
        params = ", ".join([f"{name}: {props.get('type')}" for name, props in schema.get('properties', {}).items()])
        schemas.append(f"- {tool.name}({params}): {tool.description}")
    return "\n".join(schemas)


def planner_node(state: MissionState) -> Dict[str, Any]:
    """
    Generates a mission plan using an improved and more detailed prompt to
    reduce hallucinations and handle a wider range of commands correctly.
    """
    print("--- 🧠 PLANNER NODE: Generating mission plan... ---")
    prompt = f"""
    You are a meticulous, highly intelligent flight operations officer for an autonomous drone. 
    Your single, critical purpose is to convert a user's freeform command into a **perfectly structured, error-free, and executable** JSON list of tool calls. You must adhere strictly to the reasoning process and tool definitions provided.

    --- AVAILABLE TOOLS ---
    {state['tool_schemas']}
    --- END TOOLS ---

    --- YOUR REASONING PROCESS ---
    1.  **Deconstruct User Intent:** Read the user's entire command to understand the overall mission goal. Identify every distinct action requested (e.g., takeoff, fly to a place, move relative, orbit, land, return).

    2.  **Analyze Tool Descriptions:** For each action, find the **single best tool** from the "AVAILABLE TOOLS" list by carefully reading its description.
        - If the command is "go home" or "come back", the `return_to_launch` tool is the correct choice.
        - If the command is "land here" or "land now", the `land` tool is the correct choice.
        - If the command involves a specific named location ("Eiffel Tower", "home depot"), you MUST use `get_coordinates_for_location` first, followed by `fly_to_coordinates`.
        - If the command involves relative movement ("go forward 10 meters", "move up 5 meters", "go left 20 meters"), you MUST use the `fly_relative` tool. DO NOT try to use `fly_to_coordinates` for this.

    3.  **Extract Parameters & Apply Defaults:** Identify all explicit parameters from the user's command (e.g., `altitude_meters`, `velocity_ms`, `radius_meters`). If a required argument is missing, you MUST supply a safe, default value based on the tool's documentation or common sense.
        - Default `altitude_meters` for `arm_and_takeoff` is **20**.
        - Default `radius_meters` for `do_orbit` is **50**. Default `velocity_ms` is **5**.
        - `fly_to_coordinates` and `do_orbit` can have an optional `velocity_ms`. If the user says "fly at 10 m/s", you must add this parameter to the corresponding tool call. Otherwise, omit it to use the drone's safe default.

    4.  **Sanitize Location Names:** Correct obvious spelling mistakes in location names before using them in a tool (e.g., "eifeel tower" becomes "Eiffel Tower").

    5.  **Use Placeholders for Dynamic Data:** For any mission involving a named location, the `fly_to_coordinates` and `do_orbit` steps MUST use the placeholders "TARGET_LAT" and "TARGET_LON" for their `latitude` and `longitude` arguments. This is mandatory.

    6.  **Construct the Final JSON:** Build the final plan as a JSON list. Ensure every step is logical and sequential (e.g., `pre_flight_check` is always first). Verify that every tool call has the correct tool name and a complete `args` dictionary.

    --- EXAMPLES ---

    **User Command 1:** "takeoff, fly 50 meters forward, then return home"
    **Your JSON Response:**
    ```json
    [
      {{"tool": "pre_flight_check", "args": {{}}}},
      {{"tool": "arm_and_takeoff", "args": {{"altitude_meters": 20}}}},
      {{"tool": "fly_relative", "args": {{"forward_meters": 50}}}},
      {{"tool": "return_to_launch", "args": {{}}}}
    ]
    ```

    **User Command 2:** "takeoff to 30m, fly to the Eiffel Tower at 15 m/s, circle it, then land there"
    **Your JSON Response:**
    ```json
    [
      {{"tool": "pre_flight_check", "args": {{}}}},
      {{"tool": "arm_and_takeoff", "args": {{"altitude_meters": 30}}}},
      {{"tool": "get_coordinates_for_location", "args": {{"location_name": "Eiffel Tower"}}}},
      {{"tool": "fly_to_coordinates", "args": {{"latitude": "TARGET_LAT", "longitude": "TARGET_LON", "velocity_ms": 15}}}},
      {{"tool": "do_orbit", "args": {{"latitude": "TARGET_LAT", "longitude": "TARGET_LON", "radius_meters": 50, "velocity_ms": 15}}}},
      {{"tool": "land", "args": {{}}}}
    ]
    ```
    --- END EXAMPLES ---

    Now, generate the complete and executable JSON plan for the following user command. Respond ONLY with the JSON list inside a markdown block.

    User Command: "{state['user_prompt']}"
    """
    response = LLM.invoke(prompt)
    mission_plan = extract_json_from_string(response.content)
    if not mission_plan: 
        print("❌ Error: LLM failed to generate a valid mission plan.")
        print(f"LLM Raw Output:\n{response.content}")
    else: 
        print(f"✅ Generated Mission Plan:\n{json.dumps(mission_plan, indent=2)}")
    return {"mission_plan": mission_plan}


def prepare_tool_call_node(state: MissionState) -> Dict[str, Any]:
    """
    Node 2: Prepare Tool Call.
    This node is now more robust. It not only substitutes placeholders but also
    injects necessary coordinates if the LLM forgot to include them in the plan.
    """
    print("--- ⚙️ PREPARING TOOL CALL NODE (Robust Version) ---")
    plan = state["mission_plan"]
    index = state["current_step_index"]
    
    step = plan[index]
    tool_name = step["tool"]
    tool_args = step.get("args", {}).copy()

    
    # Check if we have stored location details from a previous step.
    if state.get("target_location_details"):
        coords = state["target_location_details"]
        
        # If the current tool is one that requires coordinates, we forcefully
        # add/overwrite them. This makes the system resilient to the LLM
        # forgetting to add the "TARGET_LAT" placeholders in the plan.
        if tool_name in ["fly_to_coordinates", "do_orbit"]:
            print(f"Injecting/overwriting coordinates for '{tool_name}'...")
            tool_args["latitude"] = coords["latitude"]
            tool_args["longitude"] = coords["longitude"]

    print(f"Executing Step {index + 1}/{len(plan)}: Calling '{tool_name}' with args {tool_args}")
    
    return {
        "messages": [
            AIMessage(
                content="", 
                tool_calls=[{"id": f"call_{index}", "name": tool_name, "args": tool_args}]
            )
        ]
    }


def decide_next_step_node(state: MissionState) -> Dict[str, Any]:
    print("--- 🤔 DECIDE NEXT STEP NODE (Safety Check) ---")
    last_tool_message = state["messages"][-1]
    if isinstance(last_tool_message, ToolMessage):
        is_error = getattr(last_tool_message, 'status', None) == 'error'
        if is_error or '"status": "Error"' in last_tool_message.content:
            error_message = f"Mission failed at step {state['current_step_index'] + 1} ('{last_tool_message.name}'). Reason: {last_tool_message.content}"
            print(f"\n❌ CRITICAL ERROR: {error_message}\n")
            return {}
    updates = {}
    if "target_location_details" in state and state["target_location_details"]:
        updates["target_location_details"] = state["target_location_details"]
    if isinstance(last_tool_message, ToolMessage) and last_tool_message.name == "get_coordinates_for_location":
        try:
            result = json.loads(last_tool_message.content)
            if result.get("status") == "Success":
                print(f"✅ Storing location details: {result}")
                updates["target_location_details"] = result
        except (json.JSONDecodeError, KeyError):
            pass
    new_index = state["current_step_index"] + 1
    updates["current_step_index"] = new_index
    print(f"✅ Step successful. Advancing to step index {new_index}")
    return updates

def should_plan_or_end(state: MissionState) -> str:
    print("--- Router: Should Plan? ---")
    if state.get("mission_plan"): return "prepare_tool_call"
    else:
        print("No mission plan generated. Ending.")
        return END

def should_continue_or_end(state: MissionState) -> str:
    print("--- Router: Should Continue? ---")
    last_message = state["messages"][-1]
    is_error = getattr(last_message, 'status', None) == 'error'
    if is_error or ('"status": "Error"' in getattr(last_message, 'content', '')):
        return END
    if state["current_step_index"] >= len(state["mission_plan"]):
        print("🎉 Mission plan fully executed. Ending.")
        return END
    else:
        return "prepare_tool_call"

async def run_mission():
    

    
    # Connect to the MCP server and get the tools
    client = MultiServerMCPClient({
        "PX4DroneControlServer": {"command": "python3", "args": ["drone_server.py"], "transport": "stdio"}
    })
    print("Loading tools from MCP server...")
    tools = await client.get_tools()
    executor_node = ToolNode(tools)
    print(f"✅ Tools loaded: {[tool.name for tool in tools]}")
    
    # Define and compile the graph (same as before)
    workflow = StateGraph(MissionState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("prepare_tool_call", prepare_tool_call_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("decide_next_step", decide_next_step_node)
    workflow.set_entry_point("planner")
    workflow.add_conditional_edges("planner", should_plan_or_end)
    workflow.add_edge("prepare_tool_call", "executor")
    workflow.add_edge("executor", "decide_next_step")
    workflow.add_conditional_edges("decide_next_step", should_continue_or_end)
    app = workflow.compile()
    
       
    await asyncio.to_thread(speaker.say, "Drone assistant is ready. Please state your mission.")
    
    while True:
        # Listen for a command in a separate thread to avoid blocking
        user_command = await asyncio.to_thread(listen_for_command)

        if user_command:
            if "quit" in user_command or "exit" in user_command:
                await asyncio.to_thread(speaker.say, "Shutting down. Goodbye.")
                break
                
            await asyncio.to_thread(speaker.say, "Understood. Planning the mission now.")

            initial_state = {
                "user_prompt": user_command,
                "current_step_index": 0,
                "messages": [],
                "target_location_details": {},
                "tool_schemas": format_tools_for_prompt(tools),
            }

            mission_successful = True
            async for event in app.astream(initial_state):
                print("\n" + "="*50)
                for key, value in event.items():
                    print(f"## Node '{key}' Ran ##")
                    print(value)
                    
                    if key == "executor":
                        last_message = value['messages'][-1]
                        is_error = getattr(last_message, 'status', None) == 'error' or '"status": "Error"' in last_message.content
                        if is_error:
                            mission_successful = False
                            await asyncio.to_thread(speaker.say, f"An error occurred during the {last_message.name} step.")
                        else:
                            try:
                                result_data = json.loads(last_message.content)
                                status_message = result_data.get("message", "step completed.")
                                await asyncio.to_thread(speaker.say, f"Step {last_message.name} successful. {status_message}")
                            except json.JSONDecodeError:
                                await asyncio.to_thread(speaker.say, f"Step {last_message.name} completed.")
                print("="*50 + "\n")
            
            if mission_successful:
                await asyncio.to_thread(speaker.say, "Mission completed successfully.")
            else:
                await asyncio.to_thread(speaker.say, "Mission was aborted due to an error.")
        else:
            await asyncio.to_thread(speaker.say, "I didn't catch that. Please try again.")
        
        await asyncio.to_thread(speaker.say, "I am ready for the next mission command.")



if __name__ == "__main__":
    asyncio.run(run_mission())