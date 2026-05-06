export function AgentsA2ASection() {
  return (
    <article id="agents-a2a">
      <h2>Agent-to-Agent (A2A) API</h2>
      <p>External agents can interact with ArchFlow's agents using a workspace API key.</p>

      <h3>Quick start</h3>
      <pre>{`# 1. Create an API key in workspace settings with one of:
#    agents:read   — list + read-only agents (researcher, explainer)
#    agents:invoke — + general agent in read-only mode
#    agents:write  — + general agent in full mode (mutations)
#    agents:admin  — + delete operations

# 2. Discover available agents
curl https://archflow.io/api/v1/agents \\
  -H "Authorization: Bearer ak_live_..."

# 3. Invoke (one-shot)
curl -X POST https://archflow.io/api/v1/agents/researcher/invoke \\
  -H "Authorization: Bearer ak_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"context": {"kind": "diagram", "id": "..."}, "message": "What is in this diagram?", "mode": "read_only"}'

# 4. Streaming chat (SSE)
curl -N -X POST https://archflow.io/api/v1/agents/general/chat \\
  -H "Authorization: Bearer ak_live_..." \\
  -H "Accept: text/event-stream" \\
  -d '{"context": {"kind": "diagram", "id": "..."}, "message": "Add a Redis cache", "mode": "full"}'`}</pre>

      <h3>Event protocol</h3>
      <p>SSE events: session, node, token, tool_call, tool_result, message, applied_change, budget_warning, compaction_applied, requires_choice, view_change, cancelled, usage, done, error, ping.</p>

      <h3>Idempotency</h3>
      <p>For <code>POST /invoke</code>, set the <code>Idempotency-Key</code> header to safely retry.</p>

      <h3>Reconnect</h3>
      <p>If your client disconnects mid-stream, reconnect via <code>GET /api/v1/agents/sessions/&#123;id&#125;/stream?since=N</code> or by sending the <code>Last-Event-ID</code> header.</p>

      <h3>Rate limits</h3>
      <p>Default per-key: 600/hour, 6000/day. Adjust in workspace agent settings.</p>
    </article>
  )
}
