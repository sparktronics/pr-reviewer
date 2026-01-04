# Claude Code Review Rules

> **Source of Truth:** See `.ai/rules/` for shared coding standards.
> This file contains Claude CI-specific behavior for PR reviews.

## Imports

Apply rules from:
- `.ai/rules/code_style.md` - Python conventions
- `.ai/rules/tech_stack.md` - GCP, Vertex AI, dependencies
- `.ai/rules/security.md` - Secret handling
- `.ai/rules/testing.md` - Validation approach

---

## Review Focus

When reviewing pull requests, prioritize:

1. **Code Quality** - Adherence to code style rules
2. **Potential Bugs** - Logic errors, edge cases, null handling
3. **Performance** - Inefficient patterns, unnecessary operations
4. **Security** - Credential exposure, injection risks
5. **Test Coverage** - Are changes adequately tested?

---

## Review Guidelines

### Be Constructive
- Explain *why* something is an issue, not just *what*
- Suggest specific fixes when possible
- Acknowledge good patterns when you see them

### Severity Levels
- **Blocking:** Must fix before merge (security, bugs, breaking changes)
- **Warning:** Should fix, but not blocking (code quality, performance)
- **Info:** Suggestions for improvement (style, minor enhancements)

### Comment Format
Use clear, actionable feedback:

```
**[SEVERITY]** Brief description

Explanation of the issue and why it matters.

**Suggestion:**
```python
# Proposed fix
```
```

---

## Out of Scope

Do NOT comment on:
- Personal style preferences not in `.ai/rules/`
- Minor formatting (let linters handle it)
- "Improvements" beyond the PR's scope
- Hypothetical future requirements
