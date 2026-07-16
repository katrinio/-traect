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

## UI flow

После onboarding app работает через три основных screen:

- `Current` — compact read-only overview current ISO week
- `Edit review` — weekly review editor
- `Domains` — minimal domain management

`Current` отвечает на один вопрос: что происходит сейчас.

Он группирует active `Domain` by `Mode`:

- `Focus`
- `Maintain`
- `Ignore`

`Status` остается отдельным concept и только annotates domain row:

- `Stable`
- `At Risk`
- `Critical`

Так `Mode` и `Status` не смешиваются в один control или one visual bucket.

## Edit review

`Edit review` редактирует current ISO week.

Он содержит:

- mode for each active domain
- status for each active domain
- optional comment for each domain
- focus
- sacrificed
- reason
- notes
- save action

## Workspace setup

Если база пустая, app открывает setup screen.

Он позволяет:

- задать `Workspace` name
- добавить initial `Domain`
- удалить `Domain` до сохранения
- reorder `Domain` до сохранения
- создать `Workspace` и initial `Domain` одним действием

После успешного создания `Workspace` setup disappears and app moves to `Current`.

## Domain management

Для существующего `Workspace` доступен минимальный screen управления `Domain`.

Он позволяет:

- создать `Domain`
- переименовать `Domain`
- reorder active `Domain`
- archive `Domain`
- restore archived `Domain`

Archived `Domain` остаются в historical weekly reviews, но не попадают в new weekly check-ins автоматически.
