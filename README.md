# MCP D1 Submissions

A Cloudflare Worker (Python) that acts as an MCP server for submitting hackathon/project entries to a Cloudflare D1 database.

## Add to Claude Code

```bash
claude mcp add impact-lab-submissions --transport http https://mcp-submissions.casper-studios.workers.dev/mcp
```

## Setup

### Prerequisites

- [Node.js](https://nodejs.org/) (for Wrangler CLI)
- A Cloudflare account

### Install Wrangler

```bash
npm install -g wrangler
wrangler login
```

### Create the D1 database

```bash
wrangler d1 create mcp-submissions-db
```

Copy the `database_id` from the output and replace `<YOUR_DATABASE_ID>` in `wrangler.toml`.

### Apply the schema

```bash
wrangler d1 execute mcp-submissions-db --remote --file=schema.sql
```

### Deploy

```bash
wrangler deploy
```

## MCP Tool

### `submit_project`

Submits a hackathon/project entry.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `team_name` | string | yes | Name of the team |
| `github_url` | string | yes | GitHub repository URL |
| `problem_statement` | string | yes | Problem the project addresses |

`submitted_at` is auto-generated server-side (ISO 8601 UTC).

## Connect an MCP Client

Add to your MCP client config (e.g. Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "submissions": {
      "url": "https://mcp-submissions.casper-studios.workers.dev/mcp"
    }
  }
}
```

### Test with curl

```bash
# Initialize
curl -X POST https://mcp-submissions.casper-studios.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'

# List tools
curl -X POST https://mcp-submissions.casper-studios.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Submit a project
curl -X POST https://mcp-submissions.casper-studios.workers.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"submit_project","arguments":{"team_name":"Team Alpha","github_url":"https://github.com/team-alpha/project","problem_statement":"Solving X with Y"}}}'
```

## Local Development

```bash
wrangler dev
```

Then use `http://localhost:8787/mcp` as the endpoint.
