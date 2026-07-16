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

## Project direction

The first implementation focuses on the domain model, database schema, and migration structure. UI comes later.
