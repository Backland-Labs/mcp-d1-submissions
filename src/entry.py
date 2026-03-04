from workers import Response, WorkerEntrypoint
from urllib.parse import urlparse
import json
import re
from datetime import datetime, timezone

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "mcp-submissions"
SERVER_VERSION = "1.0.0"

TOOL_DEFINITION = {
    "name": "submit_project",
    "description": "Submit a hackathon/project entry with team name, GitHub URL, and problem statement.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "team_name": {
                "type": "string",
                "description": "Name of the team submitting the project",
            },
            "github_url": {
                "type": "string",
                "description": "GitHub repository URL for the project",
            },
            "problem_statement": {
                "type": "string",
                "description": "Description of the problem the project addresses",
            },
        },
        "required": ["team_name", "github_url", "problem_statement"],
    },
}


def jsonrpc_error(req_id, code, message):
    return Response.json(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


def jsonrpc_result(req_id, result):
    return Response.json({"jsonrpc": "2.0", "id": req_id, "result": result})


def validate_github_url(url):
    return bool(re.match(r"^https?://github\.com/.+/.+", url))


def handle_initialize(req_id):
    return jsonrpc_result(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def handle_tools_list(req_id):
    return jsonrpc_result(req_id, {"tools": [TOOL_DEFINITION]})


async def handle_tools_call(req_id, params, db):
    tool_name = params.get("name")
    if tool_name != "submit_project":
        return jsonrpc_error(req_id, -32602, f"Unknown tool: {tool_name}")

    args = params.get("arguments", {})
    team_name = args.get("team_name", "").strip()
    github_url = args.get("github_url", "").strip()
    problem_statement = args.get("problem_statement", "").strip()

    if not team_name:
        return jsonrpc_error(req_id, -32602, "team_name is required and cannot be empty")
    if not github_url:
        return jsonrpc_error(req_id, -32602, "github_url is required and cannot be empty")
    if not validate_github_url(github_url):
        return jsonrpc_error(req_id, -32602, "github_url must be a valid GitHub URL (https://github.com/owner/repo)")
    if not problem_statement:
        return jsonrpc_error(req_id, -32602, "problem_statement is required and cannot be empty")

    submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        await db.prepare(
            "INSERT INTO submissions (team_name, github_url, problem_statement, submitted_at) VALUES (?, ?, ?, ?)"
        ).bind(team_name, github_url, problem_statement, submitted_at).run()
    except Exception as e:
        return jsonrpc_error(req_id, -32603, f"Database error: {str(e)}")

    return jsonrpc_result(req_id, {
        "content": [
            {
                "type": "text",
                "text": f"Project submitted successfully!\n\nTeam: {team_name}\nGitHub: {github_url}\nSubmitted at: {submitted_at}",
            }
        ],
    })


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Handle CORS preflight
        if request.method == "OPTIONS":
            return Response("", status=204, headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            })

        # Only accept POST /mcp
        parsed = urlparse(request.url)
        if parsed.path != "/mcp" or request.method != "POST":
            return jsonrpc_error(None, -32600, "Only POST /mcp is supported")

        # Parse request body
        try:
            text = await request.text()
            body = json.loads(text)
        except Exception:
            return jsonrpc_error(None, -32700, "Parse error: invalid JSON")

        if body.get("jsonrpc") != "2.0":
            return jsonrpc_error(body.get("id"), -32600, "Invalid request: jsonrpc must be '2.0'")

        req_method = body.get("method")
        req_id = body.get("id")
        params = body.get("params", {})

        if req_method == "initialize":
            return handle_initialize(req_id)
        elif req_method == "tools/list":
            return handle_tools_list(req_id)
        elif req_method == "tools/call":
            return await handle_tools_call(req_id, params, self.env.DB)
        else:
            return jsonrpc_error(req_id, -32601, f"Method not found: {req_method}")
