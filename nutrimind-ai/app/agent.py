# ruff: noqa
import datetime
import re
import json
import sys
import os
from typing import Any, AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.workflow import Workflow, START, Edge, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.tools import AgentTool, McpToolset
from google.adk.agents.context import Context
from google.adk.models import Gemini
from google.genai import types
from mcp import StdioServerParameters

from app.config import config

# Initialize model
agent_model = Gemini(model=config.model)

# ==========================================
# MCP Toolset Configuration
# ==========================================
server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
connection_params = StdioServerParameters(
    command=sys.executable,
    args=[server_path]
)

analysis_mcp = McpToolset(
    connection_params=connection_params,
    tool_filter=["calculate_bmr_and_bmi"]
)

meal_mcp = McpToolset(
    connection_params=connection_params,
    tool_filter=["get_pcos_pmdd_recipes"]
)

knowledge_mcp = McpToolset(
    connection_params=connection_params,
    tool_filter=["get_pcos_pmdd_education"]
)

# ==========================================
# Custom State Management Tools
# ==========================================

def save_profile(
    ctx: Context, 
    age: int | None = None, 
    weight_kg: float | None = None, 
    height_cm: float | None = None, 
    symptoms: str | None = None, 
    diagnosis: str | None = None
) -> str:
    """Saves or updates the user's PCOS/PMDD profile details (age, weight, height, symptoms, diagnosis) in state.
    
    Args:
        age: Age in years.
        weight_kg: Weight in kilograms.
        height_cm: Height in centimeters.
        symptoms: Description or list of symptoms.
        diagnosis: Diagnosis (e.g. PCOS, PMDD, or None).
    """
    profile = ctx.state.get("profile_data", {})
    if not isinstance(profile, dict):
        profile = {}
    if age is not None:
        profile["age"] = age
    if weight_kg is not None:
        profile["weight_kg"] = weight_kg
    if height_cm is not None:
        profile["height_cm"] = height_cm
    if symptoms is not None:
        profile["symptoms"] = symptoms
    if diagnosis is not None:
        profile["diagnosis"] = diagnosis
        
    ctx.state["profile_data"] = profile
    return f"Profile successfully updated in state: {profile}"


def save_health_analysis(
    ctx: Context, 
    bmi: float, 
    bmr: float, 
    target_calories: float, 
    protein_g: float, 
    fat_g: float, 
    carb_g: float
) -> str:
    """Saves the calculated health analysis metrics (BMI, BMR, calories, macros) into user state.
    
    Args:
        bmi: Body Mass Index.
        bmr: Basal Metabolic Rate.
        target_calories: Calorie target for PCOS/PMDD management.
        protein_g: Protein target in grams.
        fat_g: Fats target in grams.
        carb_g: Carbohydrates target in grams.
    """
    analysis = {
        "bmi": bmi,
        "bmr": bmr,
        "target_calories": target_calories,
        "macros": {
            "protein": f"{protein_g}g",
            "fat": f"{fat_g}g",
            "carbs": f"{carb_g}g"
        }
    }
    ctx.state["health_analysis"] = analysis
    return f"Health analysis metrics saved in state: {analysis}"


def save_meal_plan(ctx: Context, meal_plan: str) -> str:
    """Saves the generated daily meal plan in state and flags it for user approval.
    
    Args:
        meal_plan: The complete text of the proposed meal plan.
    """
    ctx.state["latest_meal_plan"] = meal_plan
    ctx.state["meal_plan_needs_approval"] = True
    return "Meal plan successfully saved in state and flagged for human approval."


def save_lifestyle_plan(ctx: Context, lifestyle_plan: str) -> str:
    """Saves the generated lifestyle activity plan in state.
    
    Args:
        lifestyle_plan: The complete text of the lifestyle plan.
    """
    ctx.state["lifestyle_plan"] = lifestyle_plan
    return "Lifestyle plan successfully saved in state."


def log_user_progress(ctx: Context, entry: str) -> str:
    """Logs diet progress, food eaten, or lifestyle compliance into history.
    
    Args:
        entry: The tracking log entry.
    """
    history = ctx.state.get("progress_history", [])
    if not isinstance(history, list):
        history = []
    history.append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "type": "user_log",
        "log": entry
    })
    ctx.state["progress_history"] = history
    return f"Progress logged successfully: {entry}"

# ==========================================
# 1. Specialized LlmAgents
# ==========================================

profile_agent = LlmAgent(
    name="profile_agent",
    model=agent_model,
    instruction=(
        "You are the Profile Agent. Your role is to collect and manage the user's PCOS/PMDD health profiles.\n"
        "Check the current Saved Profile: {profile_data}.\n"
        "Only ask for details that are missing (age, weight_kg, height_cm, symptoms, or diagnosis). Do not ask again for details already present.\n"
        "Once the user provides details, call the save_profile tool to save them.\n"
        "Be extremely empathetic, warm, and supportive."
    ),
    description="Collects and manages user profiles (age, weight, height, symptoms, and PCOS/PMDD diagnosis).",
    tools=[save_profile],
    output_key="profile_result"
)

health_analysis_agent = LlmAgent(
    name="health_analysis_agent",
    model=agent_model,
    instruction=(
        "You are the Health Analysis Agent. Use your calculate_bmr_and_bmi tool on the user's profile_data "
        "(age, weight, and height) to calculate their BMI, BMR, daily weight loss calories, and macros.\n"
        "Current profile data: {profile_data}.\n"
        "If profile details (age, weight_kg, height_cm) are missing from the state, politely ask the user to provide them first.\n"
        "Once you calculate the metrics, call the save_health_analysis tool to save them in state.\n"
        "Explain the meaning of these numbers to the user with a kind, educational tone."
    ),
    description="Calculates BMI, BMR, and nutritional macro targets (protein, calories) based on user profile.",
    tools=[analysis_mcp, save_health_analysis],
    output_key="analysis_result"
)

meal_planner_agent = LlmAgent(
    name="meal_planner_agent",
    model=agent_model,
    instruction=(
        "You are the Meal Planner Agent. Create a PCOS/PMDD-friendly meal plan for the day "
        "using the user's profile_data and health_analysis.\n"
        "Current profile data: {profile_data}.\n"
        "Current health analysis: {health_analysis}.\n"
        "If the user provides a list of ingredients available at home, use your get_pcos_pmdd_recipes tool to find matching recipes.\n"
        "Once you generate the meal plan, you MUST call the save_meal_plan tool to save the plan in state and flag it for approval. Do not forget to call save_meal_plan."
    ),
    description="Prepares personalized daily diet plans and custom ingredient-based recipes for PCOS/PMDD.",
    tools=[meal_mcp, save_meal_plan],
    output_key="meal_plan_result"
)

lifestyle_agent = LlmAgent(
    name="lifestyle_agent",
    model=agent_model,
    instruction=(
        "You are the Lifestyle Agent. Prepare a daily lifestyle support plan for the user, focusing on "
        "walking, strength training, and sleep hygiene. Provide scientific explanations of why sleep and exercise "
        "are essential alongside diet to manage PCOS/PMDD insulin resistance and hormone balance.\n"
        "Current profile data: {profile_data}.\n"
        "Once you generate the plan, call the save_lifestyle_plan tool to save it."
    ),
    description="Prepares lifestyle support routines including walking, strength training, and sleep education.",
    tools=[save_lifestyle_plan],
    output_key="lifestyle_result"
)

progress_agent = LlmAgent(
    name="progress_agent",
    model=agent_model,
    instruction=(
        "You are the Progress Agent. Help the user log and track their daily diet progress, lifestyle compliance, "
        "and physical symptoms. Retrieve their past logs from the state under 'progress_history' to showcase "
        "milestones, weight loss, or general well-being trends.\n"
        "If the user wants to log food or symptom logs, call the log_user_progress tool."
    ),
    description="Tracks and documents user diet progress, lifestyle compliance, and logged milestones.",
    tools=[log_user_progress],
    output_key="progress_result"
)

motivation_agent = LlmAgent(
    name="motivation_agent",
    model=agent_model,
    instruction=(
        "You are the Motivation Agent. Provide emotional support, mindfulness techniques, and words of encouragement, "
        "especially on low-mood days. Reference their progress history from the state to show how far they have "
        "come and celebrate their consistency.\n"
        "Current profile data: {profile_data}."
    ),
    description="Provides emotional support, mindfulness exercises, and celebrates user progress.",
    output_key="motivation_result"
)

nutrition_knowledge_agent = LlmAgent(
    name="nutrition_knowledge_agent",
    model=agent_model,
    instruction=(
        "You are the Nutrition Knowledge Agent. Answer user questions with educational resources and PCOS/PMDD insights, "
        "explaining topics like insulin resistance, hormone cycling, anti-inflammatory foods, and cycle-syncing. "
        "Use your get_pcos_pmdd_education tool to search for matching scientific content on these topics."
    ),
    description="Answers educational questions about PCOS, PMDD, nutrition, and lifestyle science.",
    tools=[knowledge_mcp],
    output_key="knowledge_result"
)

# ==========================================
# 2. Coordinator (Orchestrator) Agent
# ==========================================

# Wrap specialized agents in tools
profile_tool = AgentTool(profile_agent)
health_analysis_tool = AgentTool(health_analysis_agent)
meal_planner_tool = AgentTool(meal_planner_agent)
lifestyle_tool = AgentTool(lifestyle_agent)
progress_tool = AgentTool(progress_agent)
motivation_tool = AgentTool(motivation_agent)
nutrition_knowledge_tool = AgentTool(nutrition_knowledge_agent)

coordinator_agent = LlmAgent(
    name="coordinator_agent",
    model=agent_model,
    instruction=(
        "You are the NutriMind Coordinator Agent. You are the user's primary interface for PCOS/PMDD management.\n"
        "Your first priority is to check if the user's profile is complete.\n"
        "Current Saved Profile in State: {profile_data}.\n\n"
        "Rules for Profile Collection:\n"
        "1. If profile_data is missing any details (age, weight_kg, height_cm, symptoms, or diagnosis), call the profile_agent tool to collect them. "
        "Only ask for the missing details! Do not ask for details that are already present in Current Saved Profile.\n"
        "2. If the user just provided new details, call the save_profile tool to save them in state immediately.\n"
        "3. If the profile is complete, do not ask for it again. Proceed with their requests (BMR, meal planning, lifestyle advice) using the saved profile.\n\n"
        "Rules for Tool Calling (Delegation):\n"
        "- When the user requests a meal plan, recipe, or diet, you MUST call the meal_planner_agent tool immediately. Do not write a mock plan or say you are doing it later. Call the tool!\n"
        "- When the user requests BMR/BMI calculations or health analysis, call the health_analysis_agent tool immediately.\n"
        "- When the user requests exercise, sleep, or walking guidelines, call the lifestyle_agent tool.\n"
        "- When the user wants to log progress or view log history, call the progress_agent tool.\n"
        "- When the user wants emotional support, encouragement, or motivation, call the motivation_agent tool.\n"
        "- When the user asks general educational questions, call the nutrition_knowledge_agent tool.\n\n"
        "Always synthesize responses nicely and output a warm, supportive, and structured answer. "
        "Wait for tools to finish. Do not end execution with a placeholder acknowledgement without tool calling."
    ),
    tools=[
        profile_tool,
        health_analysis_tool,
        meal_planner_tool,
        lifestyle_tool,
        progress_tool,
        motivation_tool,
        nutrition_knowledge_tool,
        save_profile
    ]
)

# ==========================================
# 3. Workflow Graph Nodes
# ==========================================

@node
def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Security Checkpoint: Scrub PII, detect prompt injection, and log decisions."""
    user_text = ""
    if node_input and node_input.parts:
        user_text = "".join(part.text for part in node_input.parts if part.text)
    
    # Initialize state keys to prevent KeyError in agent instructions
    if "profile_data" not in ctx.state:
        ctx.state["profile_data"] = {}
    if "health_analysis" not in ctx.state:
        ctx.state["health_analysis"] = {}
    
    # 1. PII Scrubbing
    cleaned_text = user_text
    email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    phone_pattern = r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"
    cleaned_text = re.sub(email_pattern, "[EMAIL_REDACTED]", cleaned_text)
    cleaned_text = re.sub(phone_pattern, "[PHONE_REDACTED]", cleaned_text)
    
    # Audit log entry
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "event": "security_check",
        "input_length": len(user_text),
        "pii_scrubbed": cleaned_text != user_text,
    }
    
    # 2. Prompt Injection Detection
    injection_keywords = ["ignore previous instructions", "system prompt", "overwrite instructions", "bypass check"]
    has_injection = any(kw in user_text.lower() for kw in injection_keywords)
    
    # 3. Domain specific warning (Medical Disclaimer check)
    has_drug_request = any(kw in user_text.lower() for kw in ["metformin", "spironolactone", "birth control", "prescription", "medication"])
    if has_drug_request:
        log_entry["warning"] = "User inquired about prescription medication. Disclaimer logged."
        log_entry["severity"] = "WARNING"
    else:
        log_entry["severity"] = "INFO"
        
    if has_injection:
        log_entry["severity"] = "CRITICAL"
        log_entry["event"] = "prompt_injection_detected"
        print(json.dumps(log_entry))
        return Event(
            content=types.Content(
                role="model", 
                parts=[types.Part.from_text(text="[SECURITY EVENT] Prompt injection attempt detected. Request blocked.")]
            ),
            route="security_event"
        )
    
    print(json.dumps(log_entry))
    
    # Pass clean content downstream
    cleaned_content = types.Content(role="user", parts=[types.Part.from_text(text=cleaned_text)])
    return Event(output=cleaned_content, route="success", state={"cleaned_input": cleaned_text})


@node
def security_failure_node(node_input: Any):
    """Handles security event routing by passing the security violation message."""
    return node_input


@node
def router_node(ctx: Context, node_input: Any) -> Event:
    """Routes the output based on whether a meal plan needs user approval."""
    # Check if meal planner set this flag
    if ctx.state.get("meal_plan_needs_approval"):
        return Event(output=node_input, route="needs_approval")
    return Event(output=node_input, route="final")


@node
async def approve_meal_plan(ctx: Context, node_input: Any) -> AsyncGenerator[Any, Any]:
    """Asks the user to approve a generated meal plan (Human-in-the-Loop)."""
    approval_count = ctx.state.get("approval_count", 0)
    interrupt_id = f"meal_approval_{approval_count}"
    
    if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
        meal_plan = ctx.state.get("latest_meal_plan", "No meal plan generated yet.")
        msg = (
            f"**NutriMind AI — Proposed PCOS/PMDD Meal Plan:**\n\n"
            f"{meal_plan}\n\n"
            f"✋ **Human Review Required:** Do you approve this meal plan? "
            f"Please reply 'yes' to save it, or type your feedback to request modifications."
        )
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=msg
        )
        return
    
    user_response = ctx.resume_inputs[interrupt_id]
    ctx.state["approval_count"] = approval_count + 1
    
    if "yes" in user_response.lower() or "approve" in user_response.lower():
        ctx.state["meal_plan_needs_approval"] = False
        ctx.state["meal_plan_approved"] = True
        yield Event(
            output=f"Approved: {user_response}", 
            route="approved", 
            state={"meal_plan_needs_approval": False, "meal_plan_approved": True}
        )
    else:
        ctx.state["meal_plan_needs_approval"] = False
        ctx.state["meal_plan_approved"] = False
        ctx.state["meal_plan_feedback"] = user_response
        msg = f"Meal plan rejected. Feedback received: '{user_response}'. Re-routing to planner..."
        yield Event(
            content=types.Content(role="model", parts=[types.Part.from_text(text=msg)]),
            output=f"Feedback: {user_response}",
            route="rejected",
            state={"meal_plan_needs_approval": False, "meal_plan_approved": False, "meal_plan_feedback": user_response}
        )


@node
def log_progress(ctx: Context, node_input: str) -> Event:
    """Logs the approved meal plan to user's history."""
    approved_plan = ctx.state.get("latest_meal_plan", "")
    progress_history = ctx.state.get("progress_history", [])
    
    progress_history.append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "type": "meal_plan",
        "plan": approved_plan
    })
    
    msg = "✅ Your PCOS/PMDD Meal Plan has been successfully saved to your Progress Log!"
    return Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)]),
        output=msg,
        state={"progress_history": progress_history}
    )


@node
def final_output_node(node_input: Any):
    """End node passing coordinator's response to client."""
    return node_input


# ==========================================
# 4. Workflow Definition (ADK 2.0 Graph)
# ==========================================

root_agent = Workflow(
    name="nutrimind_workflow",
    description="A multi-agent graph system for personalized PCOS/PMDD diet, lifestyle, and emotional support.",
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=coordinator_agent, route="success"),
        Edge(from_node=security_checkpoint, to_node=security_failure_node, route="security_event"),
        Edge(from_node=coordinator_agent, to_node=router_node),
        Edge(from_node=router_node, to_node=approve_meal_plan, route="needs_approval"),
        Edge(from_node=router_node, to_node=final_output_node, route="final"),
        Edge(from_node=approve_meal_plan, to_node=log_progress, route="approved"),
        Edge(from_node=approve_meal_plan, to_node=coordinator_agent, route="rejected"),
        Edge(from_node=log_progress, to_node=coordinator_agent)
    ]
)

app = App(
    name="app",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True)
)
