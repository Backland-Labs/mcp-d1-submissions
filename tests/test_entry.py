import asyncio
import importlib
import json
import sys
import types
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


class FakeResponse:
    def __init__(self, body="", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    @staticmethod
    def json(payload, status=200, headers=None):
        merged_headers = {"Content-Type": "application/json"}
        if headers:
            merged_headers.update(headers)
        return FakeResponse(json.dumps(payload), status=status, headers=merged_headers)


class FakeWorkerEntrypoint:
    pass


class FakeRequest:
    def __init__(self, method, url, body):
        self.method = method
        self.url = url
        self._body = body

    async def text(self):
        return self._body


@pytest.fixture(scope="module")
def entry_module():
    workers_module = types.ModuleType("workers")
    workers_module.Response = FakeResponse
    workers_module.WorkerEntrypoint = FakeWorkerEntrypoint
    sys.modules["workers"] = workers_module
    sys.modules.pop("src.entry", None)
    return importlib.import_module("src.entry")


@pytest.fixture
def worker_with_db(entry_module):
    worker = entry_module.Default()
    statement = Mock()
    statement.bind.return_value = statement
    statement.run = AsyncMock(return_value=None)
    db = Mock()
    db.prepare.return_value = statement
    worker.env = SimpleNamespace(DB=db)
    return worker, db, statement


def call_fetch(worker, payload, method="POST", path="/mcp"):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    request = FakeRequest(method=method, url=f"https://example.com{path}", body=body)
    return asyncio.run(worker.fetch(request))


def parse_response_json(response):
    return json.loads(response.body)


def test_initialize_response(worker_with_db, entry_module):
    worker, _, _ = worker_with_db
    response = call_fetch(
        worker,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    payload = parse_response_json(response)

    assert response.status == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert payload["result"]["protocolVersion"] == entry_module.PROTOCOL_VERSION
    assert payload["result"]["serverInfo"]["name"] == entry_module.SERVER_NAME
    assert payload["result"]["serverInfo"]["version"] == entry_module.SERVER_VERSION
    assert payload["result"]["capabilities"] == {"tools": {}}


def test_tools_list_response(worker_with_db):
    worker, _, _ = worker_with_db
    response = call_fetch(
        worker,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    payload = parse_response_json(response)

    assert response.status == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 2
    assert len(payload["result"]["tools"]) == 1
    assert payload["result"]["tools"][0]["name"] == "submit_project"


def test_submit_project_valid_call_inserts_record(worker_with_db):
    worker, db, statement = worker_with_db
    response = call_fetch(
        worker,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "submit_project",
                "arguments": {
                    "team_name": "Team Alpha",
                    "github_url": "https://github.com/team-alpha/project",
                    "problem_statement": "Improve onboarding throughput",
                },
            },
        },
    )
    payload = parse_response_json(response)

    assert response.status == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 3
    assert "error" not in payload
    assert payload["result"]["content"][0]["type"] == "text"
    assert "Project submitted successfully!" in payload["result"]["content"][0]["text"]

    db.prepare.assert_called_once()
    statement.bind.assert_called_once()
    statement.run.assert_awaited_once()

    bound_args = statement.bind.call_args.args
    assert bound_args[0] == "Team Alpha"
    assert bound_args[1] == "https://github.com/team-alpha/project"
    assert bound_args[2] == "Improve onboarding throughput"
    datetime.strptime(bound_args[3], "%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    [
        (
            {"github_url": "https://github.com/org/repo", "problem_statement": "Problem"},
            "team_name is required and cannot be empty",
        ),
        (
            {
                "team_name": "   ",
                "github_url": "https://github.com/org/repo",
                "problem_statement": "Problem",
            },
            "team_name is required and cannot be empty",
        ),
        (
            {"team_name": "Team", "problem_statement": "Problem"},
            "github_url is required and cannot be empty",
        ),
        (
            {
                "team_name": "Team",
                "github_url": "   ",
                "problem_statement": "Problem",
            },
            "github_url is required and cannot be empty",
        ),
        (
            {"team_name": "Team", "github_url": "https://github.com/org/repo"},
            "problem_statement is required and cannot be empty",
        ),
        (
            {
                "team_name": "Team",
                "github_url": "https://github.com/org/repo",
                "problem_statement": "   ",
            },
            "problem_statement is required and cannot be empty",
        ),
    ],
)
def test_submit_project_missing_or_empty_required_fields(
    worker_with_db, arguments, expected_message
):
    worker, db, _ = worker_with_db
    response = call_fetch(
        worker,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "submit_project", "arguments": arguments},
        },
    )
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == expected_message
    db.prepare.assert_not_called()


@pytest.mark.parametrize(
    "github_url",
    [
        "not-a-url",
        "http://github.com/org/repo",
        "https://gitlab.com/org/repo",
        "https://github.com/org",
        "https://github.com//repo",
        "https://github.com/org/repo/issues",
    ],
)
def test_submit_project_invalid_github_url_formats(worker_with_db, github_url):
    worker, db, _ = worker_with_db
    response = call_fetch(
        worker,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "submit_project",
                "arguments": {
                    "team_name": "Team",
                    "github_url": github_url,
                    "problem_statement": "Problem",
                },
            },
        },
    )
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == (
        "github_url must be a valid GitHub URL (https://github.com/owner/repo)"
    )
    db.prepare.assert_not_called()


def test_unknown_method_returns_method_not_found(worker_with_db):
    worker, _, _ = worker_with_db
    response = call_fetch(
        worker,
        {"jsonrpc": "2.0", "id": 6, "method": "unknown/method", "params": {}},
    )
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32601
    assert payload["error"]["message"] == "Method not found: unknown/method"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/mcp"),
        ("POST", "/not-mcp"),
    ],
)
def test_non_post_requests_or_wrong_path_rejected(worker_with_db, method, path):
    worker, db, _ = worker_with_db
    response = call_fetch(
        worker,
        {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}},
        method=method,
        path=path,
    )
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32600
    assert payload["error"]["message"] == "Only POST /mcp is supported"
    db.prepare.assert_not_called()


def test_invalid_json_returns_parse_error(worker_with_db):
    worker, _, _ = worker_with_db
    response = call_fetch(worker, "{not valid json")
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32700
    assert payload["error"]["message"] == "Parse error: invalid JSON"


def test_missing_jsonrpc_field_rejected(worker_with_db):
    worker, _, _ = worker_with_db
    response = call_fetch(
        worker,
        {"id": 8, "method": "initialize", "params": {}},
    )
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32600
    assert payload["error"]["message"] == "Invalid request: jsonrpc must be '2.0'"


def test_non_object_json_body_rejected(worker_with_db):
    worker, _, _ = worker_with_db
    response = call_fetch(worker, [1, 2, 3])
    payload = parse_response_json(response)

    assert payload["error"]["code"] == -32600
    assert payload["error"]["message"] == "Invalid request: body must be a JSON object"
