# Server anti-patterns

Patterns to avoid in the 2048 suggestion server. They came out of review, stated so the next change can spot them without the original diff.

## One owner for process-wide state

Work for one instance follows that instance, not a process global. Bind it to the call, including a worker thread's copy of the context. A test that reseats the global hides the split.

## An arrival is not an outcome

A dependency answering is not the same as accepting the answer. Set the status when the outcome is known, before that work closes. Discarded attempts stay on the parent record and off the caller's response.

## Failures are part of the record

An error path still records its input, status, and a short output. Quiet paths come from one list.

## A dependency's clock is not the caller's

A timestamp and a duration may need different clocks. Time inside a dependency is not time the caller waited. An event stays inside its record, and two durations keep two names.

## One address per process

A setting that means "this machine" in one process means "myself" in another. Give each process its own setting. What is on for the running service is off in CI, and both env examples say so.

## A secret leaves only with a destination that can keep it

Send a credential only where it stays protected. Log the decision to withhold it, not the secret. Every documented address follows the same rule.

## A name says which thing it is

The operation and its parameters have different names. A binding has fields, not positions. Comment a choice the names do not explain.

## Defaults must meet every multi-call suite

A new process-wide control (rate limit, budget, shared client) is not done when a unit test passes with an injected override. Suites that share one app across many cases—especially opt-in e2e—still run on **defaults** unless they say otherwise. Prefer: one test on the real default that exhausts the cap, and any shared-client suite that needs more room raises the setting from the call volume it already declares.

## Isolation helpers must pin every env-backed field

`Settings(**partial)` still fills omitted fields from the process env and `.env`. A helper that claims isolation must pass **every** model field as an init kwarg, and a test must poison the env (or assert the pinned key set equals `Settings.model_fields`) so a new setting cannot land unpinned.
