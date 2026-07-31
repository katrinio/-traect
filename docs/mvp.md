# -traect MVP Sketch

Historical product sketch: этот документ фиксирует исходный MVP-набросок. Текущая live-карта продукта находится в [README](../README.md), продуктовые правила — в [principles](principles.md), storage/API details — в [storage](storage.md).

## Философия

-traect — это не трекер привычек, не планировщик и не second brain.

Это еженедельный снимок того, как распределяются жизненные ресурсы.

Подробные продуктовые определения и правила интерпретации описаны в [принципах -traect](principles.md).

Цель проекта — не поддерживать все сферы жизни на максимуме одновременно, а понимать, **какие компромиссы принимаются**, как меняется траектория жизни и какие закономерности повторяются.

---

# MVP

## Сущности

### Domain

Произвольная область внимания.

Например:

- Work
- Health
- Sport
- Projects
- Friends
- Home
- Finance

Никакой логики — только название, порядок, архивность и необязательный minimum acceptable level.

---

### Week

Еженедельная запись.

Содержит:

- номер недели
- год
- основной фокус недели
- чем пришлось пожертвовать (необязательно)
- причина (необязательно)
- заметки (необязательно)

---

### WeekDomainState

Состояние одного `Domain` за конкретную неделю.

Поля:

- domain
- condition
- attention
- комментарий

Condition:

- Stable
- At risk
- Critical

Attention:

- Primary focus
- Maintained
- Paused

Пример:

```
Sport

Condition
🟢 Stable

Attention this week
Maintained

Comment
Running twice this week.
```

---

## Weekly Summary

Каждая неделя также содержит:

Main focus

```
Work
```

Sacrificed

```
Reading
```

Reason

```
Release
```

Notes

```
Very little sleep.
```

---

# Экраны

## Current

Текущая неделя.

Показывает состояние всех активных `Domain`.

```
Work      ▲ Primary focus  ✓ Stable
Sport     ✓ Maintained     ✓ Stable
Health    ✓ Maintained     ⚠ At risk
Reading   ○ Paused         ! Critical
Friends   ✓ Maintained     ✓ Stable
```

---

## Weekly Check-in

Простая форма, которую можно заполнить за 2–3 минуты.

Check-in описывает фактически прошедшую или текущую неделю и не является планом следующей недели. В одной записи допускается не более одного Domain с attention `Primary focus`.

---

## History

Журнал сохранённых недель.

```
2026 W29

Main focus
Work

🟢 Sport
🟡 Health
🔴 Reading
🟢 Friends
```

---

## Patterns

В текущем интерфейсе аналитика находится на экране `Patterns`.

### Attention history

```
Work      ████
Projects  ██
Health    █
```

---

### Condition history

```
Health

🟢 74%

🟡 20%

🔴 6%
```

---

### Sacrifices

```
Reading

Sacrificed 14 times

Usually because

• Work (8)
• Health (3)
• Travel (2)
```

---

# Что сознательно не входит в MVP

- цели
- задачи
- трекер привычек
- календарь
- уведомления
- таймеры
- интеграции
- AI-рекомендации
- ежедневный дневник
- оценка продуктивности

---

# Долгосрочная цель

-traect должен помогать отвечать на вопросы вроде:

- Что я обычно бросаю первым, когда становится тяжело?
- Какие сферы чаще всего проседают одновременно?
- Сколько сфер я действительно могу удерживать с attention `Primary focus` или `Maintained`?
- Что чаще всего становится причиной провалов?
- Какие жертвы в итоге оказались оправданными?
- Повторяю ли я одни и те же компромиссы каждые несколько месяцев?

Проект должен стать личным журналом управленческих решений о собственной жизни, а не очередным инструментом продуктивности.
