# -traect

-traect is a weekly attention tracker.

It helps you see how limited attention is allocated across user-defined domains over time, so you can understand tradeoffs instead of trying to optimize everything at once.

## Core idea

The model is intentionally generic:

- `Workspace` groups one setup or context.
- `Domain` is a reusable area of attention, such as Work, Health, or Projects.
- `Week` stores one weekly review.
- `WeekDomainState` stores the state of one domain in one week.

The UI may call these areas “Spheres” later, but the data model stays neutral so it can support other workspaces in the future.

## What the app tracks

- weekly focus
- what had to be sacrificed
- why it happened
- notes for the week
- status and mode for each domain

## What is not in scope for the first version

- tasks
- habits
- calendar features
- notifications
- AI recommendations

## Implemented backend workflow

The first functional slice now supports:

- creating a workspace
- creating, renaming, listing, reordering, archiving, and restoring domains
- creating or updating a weekly review for a workspace
- storing one state per active domain for a week
- retrieving the current week
- listing past weeks in reverse chronological order

## HTTP API

The backend exposes a small HTTP surface:

- `POST /workspaces`
- `GET /workspaces/{workspace_id}`
- `POST /workspaces/{workspace_id}/domains`
- `GET /workspaces/{workspace_id}/domains`
- `PUT /workspaces/{workspace_id}/domains/order`
- `PATCH /domains/{domain_id}`
- `POST /domains/{domain_id}/archive`
- `POST /domains/{domain_id}/restore`
- `PUT /workspaces/{workspace_id}/weeks/{iso_year}/{iso_week}`
- `GET /workspaces/{workspace_id}/weeks/current`
- `GET /workspaces/{workspace_id}/weeks`

UI comes later.
