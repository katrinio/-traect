# -traect

-traect — это weekly attention tracker.

Он помогает видеть, как ограниченное внимание распределяется между user-defined domains со временем, чтобы понимать компромиссы, а не пытаться одновременно держать все на максимуме.

## Core idea

Модель намеренно generic:

- `Workspace` группирует один setup или context.
- `Domain` — reusable area of attention, например Work, Health или Projects.
- `Week` хранит один weekly review.
- `WeekDomainState` хранит состояние одного `Domain` в одной `Week`.

Пока UI может называть эти области “Spheres”, но data model остается neutral, чтобы позже поддерживать другие workspaces.

## Что трекает app

- weekly focus
- what had to be sacrificed
- why it happened
- notes for the week
- status и mode для каждого domain

## Что не входит в first version

- tasks
- habits
- calendar features
- notifications
- AI recommendations

## Implemented backend workflow

Первый functional slice уже умеет:

- создавать `Workspace`
- создавать, переименовывать, list, reorder, archive и restore `Domain`
- создавать или обновлять weekly review для `Workspace`
- хранить one state per active domain for a week
- получать current week
- получать past weeks в reverse chronological order

## HTTP API

Backend exposes небольшой HTTP surface:

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

## First screen

Сейчас app показывает Weekly Review page как первый usable screen.

Он содержит:

- current ISO week
- every active domain
- status, mode и comment для каждого domain
- focus, sacrificed, reason и notes for the week
- одну save action
