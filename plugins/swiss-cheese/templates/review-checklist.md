# Human review checklist (Swiss Cheese: human-review layer)

Machine layers (lint, types, tests, agent review) have already run — do not re-do their work. Spend human attention only where judgment matters:

- [ ] **Intent**: does this change solve the actual task/ticket, not just something nearby?
- [ ] **Product fit**: would a user/stakeholder accept this behavior? Edge cases that are technically fine but humanly wrong?
- [ ] **Architecture taste**: is this the right *place* and *shape* for the change, even if no rule forbids it?
- [ ] **Irreversibility**: does anything here (schema, API, data migration, public contract) become expensive to undo? Is that recorded in an ADR?
- [ ] **Agent-review findings**: were `blocker`/`high` findings fixed rather than argued away?
- [ ] **Test honesty**: do the tests assert real behavior (not weakened/skipped to pass)?
- [ ] **Security context**: anything the automated security slice can't know — tenant boundaries, legal/PII constraints, abuse potential?
- [ ] **Docs**: will the next person (or agent session) understand why, not just what?

If you rubber-stamped three PRs in a row, say so — a fatigued layer is a hole, and the stack should know about it.
