# Other endpoints

These exist but aren't core for most agents. See backend source for full request/response shapes.

## Drafts
- `GET /api/v1/drafts`
- `POST /api/v1/drafts`
- `GET /api/v1/drafts/{draft_id}`
- `PUT /api/v1/drafts/{draft_id}`
- `DELETE /api/v1/drafts/{draft_id}`
- `POST /api/v1/drafts/{draft_id}/apply`
- `POST /api/v1/drafts/{draft_id}/discard`
- `GET /api/v1/drafts/{draft_id}/diff`
- `GET /api/v1/drafts/{draft_id}/conflicts`

## Comments
- `GET /api/v1/comments`
- `POST /api/v1/comments`
- `PUT /api/v1/comments/{comment_id}`
- `DELETE /api/v1/comments/{comment_id}`

## Activity
- `GET /api/v1/activity`

## Versions
- `GET /api/v1/versions`
- `POST /api/v1/versions/snapshot`
- `GET /api/v1/versions/{version_id}`
- `POST /api/v1/versions/compare`
- `POST /api/v1/versions/{version_id}/revert`

## Members & invites
- `GET /api/v1/workspaces/{workspace_id}/members`
- `POST /api/v1/workspaces/{workspace_id}/invites`
- `GET /api/v1/workspaces/{workspace_id}/invites`
- `DELETE /api/v1/workspaces/{workspace_id}/invites/{invite_id}`
- `PATCH /api/v1/workspaces/{workspace_id}/members/{user_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}`
- `POST /api/v1/invites/accept`
- `GET /api/v1/me/invites`
- `POST /api/v1/me/invites/{invite_id}/accept`
- `POST /api/v1/me/invites/{invite_id}/decline`

## Teams
- `GET /api/v1/workspaces/{workspace_id}/teams`
- `POST /api/v1/workspaces/{workspace_id}/teams`
- `DELETE /api/v1/workspaces/{workspace_id}/teams/{team_id}`
- `GET /api/v1/workspaces/{workspace_id}/teams/{team_id}/members`
- `POST /api/v1/workspaces/{workspace_id}/teams/{team_id}/members`
- `DELETE /api/v1/workspaces/{workspace_id}/teams/{team_id}/members/{user_id}`

## Packs
- `GET /api/v1/workspaces/{workspace_id}/packs`
- `POST /api/v1/workspaces/{workspace_id}/packs`
- `PATCH /api/v1/workspaces/{workspace_id}/packs/{pack_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/packs/{pack_id}`
- `PUT /api/v1/workspaces/{workspace_id}/packs/reorder`

## Diagram access
- `GET /api/v1/diagrams/{diagram_id}/access`
- `POST /api/v1/diagrams/{diagram_id}/access/teams`
- `DELETE /api/v1/diagrams/{diagram_id}/access/teams/{team_id}`
- `POST /api/v1/diagrams/{diagram_id}/access/users`
- `DELETE /api/v1/diagrams/{diagram_id}/access/users/{user_id}`

## Flows
- `GET /api/v1/diagrams/{diagram_id}/flows`
- `POST /api/v1/diagrams/{diagram_id}/flows`
- `GET /api/v1/flows/{flow_id}`
- `PUT /api/v1/flows/{flow_id}`
- `DELETE /api/v1/flows/{flow_id}`

## Export / import
- `GET /api/v1/export`
- `POST /api/v1/import`
- `POST /api/v1/import/structurizr`
- `POST /api/v1/import/mermaid`

## Notifications
- `GET /api/v1/notifications`
- `GET /api/v1/notifications/unread-count`
- `POST /api/v1/notifications/{notification_id}/read`
- `POST /api/v1/notifications/read-all`
