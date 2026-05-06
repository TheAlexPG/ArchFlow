export function AgentsSection() {
  return (
    <article id="agents">
      <h2>AI Agents</h2>
      <p>ArchFlow has a built-in multi-agent assistant for working with C4 models.</p>

      <h3>Available agents</h3>
      <ul>
        <li><strong>General</strong> — full architecture assistant. Plans + builds.</li>
        <li><strong>Researcher</strong> — read-only fact-finder.</li>
        <li><strong>Diagram-explainer</strong> — quick inline explanations.</li>
      </ul>

      <h3>How to use</h3>
      <ul>
        <li>Click the chat bubble in the bottom-right corner.</li>
        <li>The agent automatically knows what diagram/object you're viewing.</li>
        <li>Click "AI explain" on a node for a quick explanation.</li>
      </ul>

      <h3>Permissions</h3>
      <p>Workspace admins set per-user agent access at invite time. Levels: read-only / full / disabled.</p>

      <h3>Drafts</h3>
      <p>For important diagrams: fork to draft first, then chat. The agent's changes stay in the draft until you merge.</p>
      <p>See <a href="#agents-recommended-workflow">recommended workflow</a>.</p>
    </article>
  )
}
