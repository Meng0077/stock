# Coding Guidelines

## Core principle

Prefer the smallest correct implementation.

If code is not required by the current task or acceptance criteria,
do not add it.

## Avoid over-engineering

- Do not add speculative abstractions.
- Do not design for hypothetical future requirements.
- Do not add helper functions unless they materially improve readability.
- Do not create additional layers just for architectural cleanliness.
- Reuse existing abstractions instead of creating parallel implementations.
- Minimize the diff.

## Defensive programming

Do not add defensive programming unless explicitly required.

In particular, do not add:

- extra input validation
- fallback behavior
- retries
- timeouts
- caching
- logging
- metrics
- compatibility layers
- fault injection
- additional configuration
- generic exception handling

Let unexpected programming errors propagate unless the current layer
is explicitly responsible for converting them into domain errors.

Do not catch `Exception` simply to make the program appear robust.

## Implementation workflow

When modifying existing code:

1. Understand the existing flow.
2. Identify the minimum change required.
3. Remove unnecessary complexity when appropriate.
4. Implement only the stated requirement.
5. Stop when the acceptance criteria are satisfied.

Before adding code, ask:

> Is this required by the current task?

If not, do not add it.

## Learning-oriented development

This project is also used for learning.

Prefer code where the core control flow is visible and easy to explain.

For example, prefer:

    input
      -> model
      -> tool call
      -> tool execution
      -> model
      -> result

over abstractions that hide this flow.

Do not optimize for production hardening unless the task explicitly
asks for production readiness.

## Tests

Tests should verify the behavior required by the current task.

Do not add tests for hypothetical edge cases unless requested.

Do not rewrite production code solely to make tests more elaborate.