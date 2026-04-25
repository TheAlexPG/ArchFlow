import { Endpoint } from '../Endpoint'

export function MiscSection() {
  return (
    <section id="misc">
      <h2>Other endpoints</h2>
      <p>
        Secondary surfaces — drafts, comments, activity, versions, members &amp;
        invites, teams, packs, diagram access, flows, export/import, and
        notifications. Listed in compact form so you know they exist; consult
        the source or OpenAPI for full request/response shapes.
      </p>

      <h3 id="misc-drafts">Drafts</h3>
      <Endpoint method="GET"    path="/api/v1/drafts" summary="List drafts." />
      <Endpoint method="POST"   path="/api/v1/drafts" summary="Create a draft." />
      <Endpoint method="GET"    path="/api/v1/drafts/{draft_id}" summary="Fetch a draft." />
      <Endpoint method="PUT"    path="/api/v1/drafts/{draft_id}" summary="Update a draft." />
      <Endpoint method="DELETE" path="/api/v1/drafts/{draft_id}" summary="Delete a draft." />
      <Endpoint method="POST"   path="/api/v1/drafts/{draft_id}/apply" summary="Apply the draft to the live workspace." />
      <Endpoint method="POST"   path="/api/v1/drafts/{draft_id}/discard" summary="Mark a draft discarded." />
      <Endpoint method="GET"    path="/api/v1/drafts/{draft_id}/diff" summary="Per-diagram diff vs. live." />
      <Endpoint method="GET"    path="/api/v1/drafts/{draft_id}/conflicts" summary="Apply-time conflict preview." />

      <h3 id="misc-comments">Comments</h3>
      <Endpoint method="GET"    path="/api/v1/comments"             summary="List comments (filter by target)." />
      <Endpoint method="POST"   path="/api/v1/comments"             summary="Add a comment." />
      <Endpoint method="PUT"    path="/api/v1/comments/{comment_id}" summary="Edit a comment." />
      <Endpoint method="DELETE" path="/api/v1/comments/{comment_id}" summary="Delete a comment." />

      <h3 id="misc-activity">Activity</h3>
      <Endpoint method="GET" path="/api/v1/activity" summary="Workspace-wide activity log feed." />

      <h3 id="misc-versions">Versions</h3>
      <Endpoint method="GET"  path="/api/v1/versions"                       summary="List versions for a target." />
      <Endpoint method="POST" path="/api/v1/versions/snapshot"              summary="Snapshot current state." />
      <Endpoint method="GET"  path="/api/v1/versions/{version_id}"          summary="Detailed version payload." />
      <Endpoint method="POST" path="/api/v1/versions/compare"               summary="Diff two versions." />
      <Endpoint method="POST" path="/api/v1/versions/{version_id}/revert"   summary="Revert to a version (creates a new snapshot)." />

      <h3 id="misc-members">Members & invites</h3>
      <Endpoint method="GET"    path="/api/v1/workspaces/{workspace_id}/members"             summary="List workspace members." />
      <Endpoint method="POST"   path="/api/v1/workspaces/{workspace_id}/invites"             summary="Invite a user by email (admin)." />
      <Endpoint method="GET"    path="/api/v1/workspaces/{workspace_id}/invites"             summary="List pending invites." />
      <Endpoint method="DELETE" path="/api/v1/workspaces/{workspace_id}/invites/{invite_id}" summary="Revoke a pending invite." />
      <Endpoint method="PATCH"  path="/api/v1/workspaces/{workspace_id}/members/{user_id}"   summary="Change a member's role." />
      <Endpoint method="DELETE" path="/api/v1/workspaces/{workspace_id}/members/{user_id}"   summary="Remove a member." />
      <Endpoint method="POST"   path="/api/v1/invites/accept"                                 summary="Accept an invite by token." />
      <Endpoint method="GET"    path="/api/v1/me/invites"                                     summary="List invites for the current user." />
      <Endpoint method="POST"   path="/api/v1/me/invites/{invite_id}/accept"                  summary="Accept an in-app invite." />
      <Endpoint method="POST"   path="/api/v1/me/invites/{invite_id}/decline"                 summary="Decline an in-app invite." />

      <h3 id="misc-teams">Teams</h3>
      <Endpoint method="GET"    path="/api/v1/workspaces/{workspace_id}/teams"                       summary="List teams." />
      <Endpoint method="POST"   path="/api/v1/workspaces/{workspace_id}/teams"                       summary="Create a team." />
      <Endpoint method="DELETE" path="/api/v1/workspaces/{workspace_id}/teams/{team_id}"             summary="Delete a team." />
      <Endpoint method="GET"    path="/api/v1/workspaces/{workspace_id}/teams/{team_id}/members"     summary="Team membership." />
      <Endpoint method="POST"   path="/api/v1/workspaces/{workspace_id}/teams/{team_id}/members"     summary="Add a user to a team." />
      <Endpoint method="DELETE" path="/api/v1/workspaces/{workspace_id}/teams/{team_id}/members/{user_id}" summary="Remove a user from a team." />

      <h3 id="misc-packs">Packs</h3>
      <Endpoint method="GET"    path="/api/v1/workspaces/{workspace_id}/packs"           summary="List visual packs." />
      <Endpoint method="POST"   path="/api/v1/workspaces/{workspace_id}/packs"           summary="Create a pack." />
      <Endpoint method="PATCH"  path="/api/v1/workspaces/{workspace_id}/packs/{pack_id}" summary="Update a pack." />
      <Endpoint method="DELETE" path="/api/v1/workspaces/{workspace_id}/packs/{pack_id}" summary="Delete a pack." />
      <Endpoint method="PUT"    path="/api/v1/workspaces/{workspace_id}/packs/reorder"   summary="Reorder packs." />

      <h3 id="misc-access">Diagram access (team / user grants)</h3>
      <Endpoint method="GET"    path="/api/v1/diagrams/{diagram_id}/access"                  summary="List grants." />
      <Endpoint method="POST"   path="/api/v1/diagrams/{diagram_id}/access/teams"            summary="Grant access to a team." />
      <Endpoint method="DELETE" path="/api/v1/diagrams/{diagram_id}/access/teams/{team_id}"  summary="Revoke a team grant." />
      <Endpoint method="POST"   path="/api/v1/diagrams/{diagram_id}/access/users"            summary="Grant access to a user." />
      <Endpoint method="DELETE" path="/api/v1/diagrams/{diagram_id}/access/users/{user_id}"  summary="Revoke a user grant." />

      <h3 id="misc-flows">Flows (per-diagram L4 flow lanes)</h3>
      <Endpoint method="GET"    path="/api/v1/diagrams/{diagram_id}/flows" summary="List flows on a diagram." />
      <Endpoint method="POST"   path="/api/v1/diagrams/{diagram_id}/flows" summary="Create a flow." />
      <Endpoint method="GET"    path="/api/v1/flows/{flow_id}"             summary="Fetch a flow." />
      <Endpoint method="PUT"    path="/api/v1/flows/{flow_id}"             summary="Update a flow." />
      <Endpoint method="DELETE" path="/api/v1/flows/{flow_id}"             summary="Delete a flow." />

      <h3 id="misc-export">Export / import</h3>
      <Endpoint method="GET"  path="/api/v1/export"             summary="Export workspace JSON." />
      <Endpoint method="POST" path="/api/v1/import"             summary="Import a workspace JSON dump." />
      <Endpoint method="POST" path="/api/v1/import/structurizr" summary="Import Structurizr DSL." />
      <Endpoint method="POST" path="/api/v1/import/mermaid"     summary="Import a Mermaid graph." />

      <h3 id="misc-notifications">Notifications</h3>
      <Endpoint method="GET"  path="/api/v1/notifications"               summary="List notifications." />
      <Endpoint method="GET"  path="/api/v1/notifications/unread-count"  summary="Number of unread notifications." />
      <Endpoint method="POST" path="/api/v1/notifications/{notification_id}/read" summary="Mark one as read." />
      <Endpoint method="POST" path="/api/v1/notifications/read-all"      summary="Mark all as read." />
    </section>
  )
}
