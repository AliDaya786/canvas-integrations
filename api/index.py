import os
from fastapi import FastAPI, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

os.environ.setdefault("COMPOSIO_CACHE_DIR", "/tmp/.composio")
from composio import Composio

SLACK_TOOL_VERSION = "20251118_00"
CALENDLY_TOOLKIT_VERSION = "20251111_01"
supabase = create_client(os.environ["SUPABASE_PROJECT_URL"], os.environ["SUPABASE_API_KEY"])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-vercel-ai-ui-message-stream"],
)

def get_composio() -> Composio:
    return Composio()

_mcp_server_cache = None

def get_mcp_server():
    global _mcp_server_cache
    if _mcp_server_cache is not None:
        return _mcp_server_cache

    client = get_composio()
    servers = client.mcp.list()["items"]

    for server in servers:
        if server.name == "mcps-v4":
            _mcp_server_cache = server
            return _mcp_server_cache

    _mcp_server_cache = client.mcp.create(
        name="mcps-v4",
        toolkits=[
            {"toolkit": "composio"},
            {"toolkit": "gmail", "auth_config": os.environ["GMAIL_AUTH_CONFIG_ID"]},
            {"toolkit": "googlecalendar", "auth_config": os.environ["GCALENDAR_AUTH_CONFIG_ID"]},
            {"toolkit": "attio", "auth_config": os.environ["ATTIO_AUTH_CONFIG_ID"]},
            {"toolkit": "hubspot", "auth_config": os.environ["HUBSPOT_AUTH_CONFIG_ID"]},
            {"toolkit": "notion", "auth_config": os.environ["NOTION_AUTH_CONFIG_ID"]},
        ],
        allowed_tools=[
            "COMPOSIO_MULTI_EXECUTE_TOOL",
            "GMAIL_FETCH_EMAILS", "GMAIL_REPLY_TO_THREAD", "GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_SEND_DRAFT",
            "GOOGLECALENDAR_CREATE_EVENT", "GOOGLECALENDAR_FIND_EVENT", "GOOGLECALENDAR_EVENTS_LIST", "GOOGLECALENDAR_DELETE_EVENT", "GOOGLECALENDAR_UPDATE_EVENT",
            "ATTIO_CREATE_RECORD", "ATTIO_FIND_RECORD", "ATTIO_UPDATE_RECORD", "ATTIO_DELETE_RECORD", "ATTIO_LIST_RECORDS",
            "HUBSPOT_CREATE_CONTACT", "HUBSPOT_UPDATE_CONTACT", "HUBSPOT_LIST_CONTACTS", "HUBSPOT_CREATE_COMPANY", "HUBSPOT_UPDATE_COMPANY", "HUBSPOT_LIST_COMPANIES",
            "NOTION_CREATE_NOTION_PAGE", "NOTION_FETCH_DATA", "NOTION_INSERT_ROW_DATABASE", "NOTION_ARCHIVE_NOTION_PAGE", "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        ]
    )
    return _mcp_server_cache


@app.get("/")
async def healthcheck():
    return {"status": "ok"}

TOOL_AUTH_CONFIGS = {
    "slack": "SLACK_AUTH_CONFIG_ID",
    "calendly": "CALENDLY_AUTH_CONFIG_ID",
    "instantly": "INSTANTLY_AUTH_CONFIG_ID",
    "attio": "ATTIO_AUTH_CONFIG_ID",
    "hubspot": "HUBSPOT_AUTH_CONFIG_ID",
    "notion": "NOTION_AUTH_CONFIG_ID",
    "gmail": "GMAIL_AUTH_CONFIG_ID",
    "gcalendar" : "GCALENDAR_AUTH_CONFIG_ID",
}

@app.get("/api/tool_oauth_start")
async def tool_oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")
    tool = request.query_params.get("tool")  

    auth_config_id = os.environ[TOOL_AUTH_CONFIGS[tool]]
    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/tool_oauth_callback?user_id={user_id}&tool={tool}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=auth_config_id,
        callback_url=callback_url,
    )
    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/tool_oauth_callback")
async def tool_oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    tool = request.query_params.get("tool")
    print(f"{tool} connected for user: {user_id}")

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.get("/api/calendly-webhook")
async def calendly_webhook_setup(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    client = get_composio()

    user_info = client.tools.execute(
        slug="CALENDLY_GET_USER",
        user_id=user_id,
        version=CALENDLY_TOOLKIT_VERSION,
        arguments={"uuid": "me"},
    )

    resource = user_info["data"]["resource"]
    org_url = resource["current_organization"]
    user_url = resource["uri"]

    target_url = f"{os.environ['BACKEND_BASE_URL'].rstrip('/')}/calendly-webhook?user_id={user_id}"

    client.tools.execute(
        slug="CALENDLY_CREATE_WEBHOOK_SUBSCRIPTION",
        user_id=user_id,
        version=CALENDLY_TOOLKIT_VERSION,
        arguments={
            "url": target_url,
            "events": ["invitee.created"],
            "scope": "user",
            "organization": org_url,
            "user": user_url,
        },
    )

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.post('/calendly-webhook')
async def calendly_webhook_handler(request: Request, payload: dict = Body(...)):
    user_id = request.query_params.get("user_id")
    invitee = payload.get("payload", {})
    scheduled_event = invitee.get("scheduled_event", {})

    supabase.table("calendly_events").insert({
        "user_id": user_id,
        "event_name": scheduled_event.get("name"),
        "invitee_name": invitee.get("name"),
        "invitee_email": invitee.get("email"),
        "start_time": scheduled_event.get("start_time"),
        "end_time": scheduled_event.get("end_time"),
        "cancel_url": invitee.get("cancel_url"),
        "reschedule_url": invitee.get("reschedule_url"),
    }).execute()

@app.get("/api/slack_channels")
async def slack_channels(request: Request):
    user_id = request.query_params.get("user_id")
    client = get_composio()
    result = client.tools.execute(
        slug="SLACK_LIST_ALL_CHANNELS",
        user_id=user_id,
        version="20251126_02",
        arguments={"limit": 100, "types": "public_channel,private_channel,im,mpim"},
    )
    channels = result.get("data", {}).get("channels", [])
    return [{"id": c["id"], "name": c.get("name") or c.get("user") or c["id"]} for c in channels]

@app.post('/api/send-slack')
async def send_slack(payload: dict = Body(...)):
    print("Payload:", payload)
    record = payload.get("record", {})
    user_id = record.get("user_id")

    user = supabase.table("users").select("channel_id, message_format").eq("name", user_id).single().execute()

    text = (
        f"{user.data['message_format'] or ''}\n\n"
        f"Event: {record.get('event_name')}\n"
        f"Invitee: {record.get('invitee_name')} ({record.get('invitee_email')})\n"
        f"Start - end: {record.get('start_time')} - {record.get('end_time')}\n"
        f"Cancel: {record.get('cancel_url')}\n"
        f"Reschedule: {record.get('reschedule_url')}"
    )

    get_composio().tools.execute(
        slug="SLACK_SEND_MESSAGE",
        user_id=user_id,
        version=SLACK_TOOL_VERSION,
        arguments={"channel": user.data["channel_id"], "text": text},
    )
    return {"status": "sent"}

@app.post('/api/chat')
async def chat(payload: dict = Body(...)):
    from anthropic import Anthropic
    from datetime import date
    from fastapi.responses import StreamingResponse
    import json
    import uuid

    user_id = payload.get("user_id")
    messages = [{"role": m["role"], "content": "".join(p["text"] for p in m.get("parts", []) if p.get("type") == "text")} for m in payload.get("messages", [])]
    today = date.today()
    mcp_url = f"{get_mcp_server().mcp_url}?user_id={user_id}"
    print(f"Messages: {messages}")

    import time
    start = time.time()
    try:
        response = Anthropic().beta.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=f"Today: {today}. Be concise.",
            messages=messages,
            mcp_servers=[{"type": "url", "url": mcp_url, "name": "crm"}],
            betas=["mcp-client-2025-04-04"]
        )
        print(f"MCP call: {time.time() - start:.1f}s")
        print(response)
    except Exception as e:
        print(f"Error: {e}")
        raise
    result = "No response"
    for block in reversed(response.content):
        if hasattr(block, 'text'):
            result = block.text
            break

    msg_id = str(uuid.uuid4())
    chunks = [
        f'data: {json.dumps({"type":"start","messageId":msg_id})}\n\n',
        f'data: {json.dumps({"type":"text-start","id":msg_id})}\n\n',
        f'data: {json.dumps({"type":"text-delta","id":msg_id,"delta":result})}\n\n',
        f'data: {json.dumps({"type":"text-end","id":msg_id})}\n\n',
        f'data: {json.dumps({"type":"finish"})}\n\n',
        'data: [DONE]\n\n',
    ]
    return StreamingResponse(
        iter(chunks),
        media_type="text/event-stream",
        headers={"x-vercel-ai-ui-message-stream": "v1"}
    )




