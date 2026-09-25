# Deterministic scheduling context

`SchedulingContext` is the small, structured boundary between the current
agent state and the deterministic scheduler. It is intentionally a projection
of state, not a second copy of `AgentState`.

## Three layers

- `common` contains information shared by every scheduling decision:
  bounded budgets and minimal overall progress. The initial progress metric is
  the number of match results.
- `specific` describes the current action space: available actions, backlog
  data only for those available actions, and search-plan signals when search
  actions are available. Each backlog contains `pending`, `executable`, and
  `batch_size`.
- `last_outcome` records the most recent deterministic action result. It has
  the action, status, changed flag, quantitative counts, and deterministic
  signals. It contains no semantic summary.

Information belongs in `common` when every action decision can use it; it
belongs in `specific` when it describes only the currently available action
namespace; and it belongs in `last_outcome` when it describes the immediately
preceding execution.

The scheduler does not receive the complete `AgentState` because that would
couple action selection to storage artifacts, expose irrelevant mutable data,
and make the scheduling boundary harder to test. The context builder derives
only bounded counts, budgets, and labels needed by the policy.

Semantic summaries and semantic replanning are deliberately not part of this
context. They will be designed separately if a later replanning workflow
needs them.
