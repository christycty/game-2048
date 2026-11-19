# Server anti-patterns

Patterns to avoid in the 2048 suggestion server. They came out of review, stated so the next change can spot them without the original diff.

## One exporter per app

A process-global tracer provider sends nested spans to whichever app was created last. The HTTP span stays on the app that was instrumented, so one request is split across collectors. Bind that app's tracer for the request, including the threadpool copy of the context. Do not assign OpenTelemetry's private provider globals. A test that points the global provider at the app before each call hides the split.

## A completed body is not a successful move

Tokens and timings mean the provider returned a body. A parse failure or an illegal move is still an error, and the status has to be set before the span closes. The suggester owns the retry text: an illegal move is remembered, a blank reason asks for JSON again. Keep those discarded attempts on the suggest span when a later attempt succeeds. Leave them off the HTTP response.

## Trace the error response

The stuck board raises before a suggestion span exists. The HTTP span still needs the board, an error status, and a short output. Health stays untraced. The paths to skip live in one list.

## Provider time is not client time

Event timestamps need a unix clock. The duration stays on a monotonic clock. Ollama's load and prefill can run past a short client span, and Phoenix mis-draws an event that falls outside it, so clamp the stamp into the open span. End-to-end time is the client elapsed time. The provider total keeps its own name. The first-token event uses Phoenix's streaming name even though this call does not stream.

## One collector URL for the process that dials it

The host process uses localhost. Compose must not read that name, or the container exports to itself. Give Compose its own variable, defaulting to the host gateway. Dev and prod export. CI turns export off, including on the API image, because the default is on. Say that in both env examples.

## A key leaves the process only for a collector that can keep it

Send the API key on HTTPS, and on HTTP only to loopback or the Compose host name. Any other HTTP URL drops the key. Log that the key was withheld, and do not log the key. The collector URLs in the env examples have to follow this same rule.

## Names say which thing they are

The model id is an attribute. The span name is the operation, so two retries are not two spans named with the model. A request binding has fields, not a pair read back by index. Comment a choice the names do not explain: why the prompt is attached before the call, why two clocks are started, why a Phoenix event name says "stream".
