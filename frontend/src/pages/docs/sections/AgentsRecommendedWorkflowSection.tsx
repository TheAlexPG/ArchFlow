export function AgentsRecommendedWorkflowSection() {
  return (
    <section id="agents-recommended-workflow">
      <h2 id="agents-recommended-workflow">Recommended workflow with the agent</h2>
      <p>
        The ArchFlow agent can read <em>and write</em> your diagrams. On
        important diagrams the recommended approach is to let the agent work
        inside a <strong>draft</strong> so your live diagram stays clean until
        you are satisfied with the result.
      </p>

      <h3>On important diagrams: fork to draft first</h3>
      <ol className="list-decimal pl-6 my-3 space-y-1">
        <li>Open the diagram you want to evolve.</li>
        <li>
          In the canvas toolbar, click <strong>Fork to draft</strong> &mdash;
          give it a name.
        </li>
        <li>The view switches to the draft.</li>
        <li>
          Open the chat bubble &mdash; agent context is already the draft.
        </li>
        <li>Iterate freely; nothing on live is affected.</li>
        <li>
          When happy, click <strong>Compare &amp; merge</strong> &mdash; review
          the diff, resolve conflicts, merge into live.
        </li>
      </ol>

      <h3>Automatic draft creation</h3>
      <p>
        When you send the agent a message that would modify a live diagram, the
        agent may automatically fork it into a draft (depending on your{' '}
        <code>mode</code> setting and server policy). If it does, the chat
        bubble shows a <em>Draft created</em> banner with a{' '}
        <strong>Review &amp; merge &rarr;</strong> link.
      </p>

      <h3>Why this flow</h3>
      <ul>
        <li>Live diagrams stay clean while you experiment.</li>
        <li>
          Reviews and merges go through the same UI as human-made drafts.
        </li>
        <li>You stay in control of when changes hit live.</li>
      </ul>

      <h3>Working-in selector</h3>
      <p>
        The <strong>Working in:</strong> dropdown in the chat header lets you
        switch the agent context between the live diagram and any open draft
        without leaving the bubble. The agent always operates on whatever
        target is selected there.
      </p>
    </section>
  )
}
