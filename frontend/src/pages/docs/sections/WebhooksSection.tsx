import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function WebhooksSection() {
  return (
    <section id="webhooks">
      <h2>Webhooks</h2>
      <p>
        Webhooks deliver workspace events to an HTTPS endpoint of your
        choice. Each delivery is signed with the per-webhook secret so you
        can verify authenticity. The secret is shown only at creation time.
      </p>

      <h3 id="webhooks-events">Event catalog</h3>
      <Endpoint
        method="GET"
        path="/api/v1/webhooks/events"
        summary="Returns the canonical list of event names you can subscribe to."
        auth="public"
      >
        <CodeBlock title="200 response (current set)" language="json">
{`[
  "object.created",   "object.updated",   "object.deleted",
  "connection.created","connection.updated","connection.deleted",
  "diagram.created",  "diagram.updated",  "diagram.deleted",
  "draft.applied"
]`}
        </CodeBlock>
      </Endpoint>

      <h3 id="webhooks-create">Create</h3>
      <Endpoint
        method="POST"
        path="/api/v1/webhooks"
        summary="Subscribe an HTTPS URL to one or more events."
        auth="JWT"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "url": "https://hooks.example.com/archflow",
  "events": ["object.created", "connection.created"]
}`}
        </CodeBlock>
        <CodeBlock title="201 response (secret returned once)" language="json">
{`{
  "id": "uuid",
  "url": "https://hooks.example.com/archflow",
  "events": ["object.created", "connection.created"],
  "enabled": true,
  "failure_count": 0,
  "last_delivery_at": null,
  "last_status": null,
  "created_at": "...",
  "secret": "whsec_<hex>"
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="webhooks-list">List</h3>
      <Endpoint
        method="GET"
        path="/api/v1/webhooks"
        summary="List your webhooks (without secrets)."
        auth="JWT"
      />

      <h3 id="webhooks-delete">Delete</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/webhooks/{webhook_id}"
        summary="Permanently delete a webhook."
        auth="JWT"
      />

      <h3 id="webhooks-test">Test ping</h3>
      <Endpoint
        method="POST"
        path="/api/v1/webhooks/{webhook_id}/test"
        summary="Queue a synthetic webhook.ping delivery for end-to-end validation."
        auth="JWT"
      />

      <h3 id="webhooks-payload">Delivery payload</h3>
      <p>
        Each delivery is a <code>POST</code> with a JSON body of the form{' '}
        <code>{`{"event": "<name>", "data": {...}}`}</code>. The body is
        signed using HMAC-SHA256 with the per-webhook secret and the digest
        is sent as a header. Verify it before trusting the payload.
      </p>
    </section>
  )
}
