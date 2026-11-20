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
