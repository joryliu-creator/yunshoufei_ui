# Temporary billing room routing

Use this reference whenever a user asks which rooms belong to temporary billing,
or asks to generate temporary-billing cases from the project mapping workbook.

## Source of truth

- Read the project-local `房间收费标准映射表.xlsx`; do not infer the room list
  from screenshots, old chat messages, or generated test IDs.
- Filter rows by the mapping column whose value is `临时类` (the workbook may
  display Chinese text differently in a console because of code-page settings).
- Return the room identifier and its mapped charge item/standard together. A
  room can have a different temporary formula than another room.
- Keep one mapping row per room + charge-item + standard combination. If the
  workbook contains duplicate rows, report the ambiguity instead of silently
  selecting one.

## Stability

- Use serial execution and wait for the room/charge-item tree results to be
  visibly loaded before filtering or selecting.
- Prefer real DOM/Playwright locators. Use the in-app browser only when a user
  needs to demonstrate an ambiguous interaction.
