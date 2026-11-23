# Client anti-patterns

Patterns to avoid in the 2048 client. They came out of review, stated so the next change can spot them without the original diff.

## One source for a shared fact

A size, duration, or layout ratio that already has a name should not be copied as a raw number in another layer. The slide step belongs to the board's cell and gap. A settle delay belongs next to the slide duration. A test that repeats the formula still passes when the copies drift. Assert the shared source.

## Pass randomness and identity in

A rule should be a pure function of its arguments. A module-level id counter, or a direct read of `Math.random`, makes the result depend on earlier calls. Tests then stub a global. Pass the random function in, and take the next id from the tiles in that call.

## Assertions should name the rule they check

The test name and the assertion message should describe the behavior under test. A wrong merge is not a missing spawn. A merge example does not belong in a test whose name says the tile only slides. Name a helper for the check it performs.

## One shape per helper

A fallback chain that fills missing fields is several object shapes hiding in one function. Pass the values the caller already knows, such as the cell a tile started in, so the rendered tile has one shape.

## Match the surrounding code

Indentation, semicolons, and quotes should match the files next to the change. Drop a wrapper that adds nothing. A control that does not work yet should look inactive. Comment a choice the names do not explain: why nodes stay in id order, why a timer outlives the transition, why a listener reads refs.

## Gesture state belongs to one pointer

Clear a swipe only when the pointer that started it ends. A release from another pointer must leave the active gesture alone.

## Stopping a timed loop must release the busy hold it owned

A pause between Auto Play steps can keep `busy` true so AI stays inactive through the gap. **Stop** (and any other path that clears `autoPlaying` without starting a slide or request) must drop that hold when nothing else is in flight. Prefer clearing busy inside the stop helper when `!animating && !suggesting`, not only inside the gap timer’s “already stopped” branch. A test that clicks **Stop** during the gap and asserts **AI** / **Auto Play** are enabled *before* the gap elapses locks this in.

## Every loop entry must share the failed-apply exit

Auto Play can start from a fresh suggest or from a pending **Play** move. If one path stops the loop when `handleMove` returns false and the other ignores the return value, the UI can sit on **Stop** with no further suggest. Treat “apply failed” the same on every entry: hint, stop Auto Play, release busy. Cover the pending-start failure in a test, not only the in-loop suggest failure.

## Cover each loop exit that re-enables controls

Happy-path loop tests are not enough. For an async suggest → apply → settle → gap cycle, assert the full control/status/token exit tuple after every exit the product promises (**Stop** including during the gap or retry backoff, **New Game**, win/loss, fallback exhaustion, spend hard-ceiling 429, exhausted capacity retries, transport failure, mode switch, and manual takeover): **AI** `disabled` state, **Auto Play** `disabled` + `aria-pressed`, mode `<fieldset>` `disabled` state, **Play** button absence (`queryByRole("button", { name: /Play / })`), `role="status"` cleared or showing the expected hint, `shouldReportOutcome() === false` when a suggest token is dropped, and no further `suggestMove` / `applyMove` calls after the exit. Capacity-busy and fallback retries must keep Auto Play on until exhaustion.
