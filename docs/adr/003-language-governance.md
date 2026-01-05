# ADR 003: Language & Label Governance

**Status:** Accepted
**Date:** 2024-01-05
**Authors:** System Architecture Team

## Context

Language shapes thinking. When developers use trading-narrative words like "breakout," "absorption," "exhaustion," or "trend confirmation," they unconsciously shift the system toward prediction and signal generation—the exact opposite of its evidence-first paradigm.

This ADR establishes mandatory language governance to prevent paradigm drift through vocabulary corruption.

## Decision

We establish the following language governance rules:

---

### Rule 1: Forbidden Terms (NEVER Use)

The following terms are **forbidden** in code, comments, documentation, and UI labels:

| Forbidden Term | Reason | Allowed Alternative |
|----------------|--------|---------------------|
| `breakout` | Trading narrative / prediction | `level_invalidated`, `threshold_exceeded` |
| `absorption` | Trading narrative / interpretation | `trade_driven_liquidity_reduction` |
| `exhaustion` | Trading narrative / prediction | `liquidity_decay_without_refill` |
| `trend` | Prediction concept | `observed_direction`, `structural_pattern` |
| `confirmation` | Prediction concept | `persistence`, `resolution` |
| `signal` | Implies actionable prediction | `observation`, `detection`, `event` |
| `bullish` / `bearish` | Directional prediction | NEVER - not in scope |
| `buy` / `sell` (as recommendation) | Trading advice | NEVER - not in scope |
| `support` / `resistance` | Price prediction | `anchor_level`, `key_level` |
| `reversal` | Prediction concept | `state_transition`, `recovery` |
| `momentum` | Prediction concept | `reaction_velocity`, `change_rate` |
| `overbought` / `oversold` | Valuation judgment | NEVER - not in scope |

---

### Rule 2: Allowed Terms (Preferred Vocabulary)

The following terms are **approved** for use throughout the system:

#### Reaction Types (Evidence-Only)
- `vacuum` - Liquidity falls below threshold for sustained duration
- `sweep` - Consecutive trades remove liquidity across levels
- `chase` - Liquidity reappears only at shifted levels
- `pull` - Liquidity cancelled immediately after shock
- `hold` - Liquidity replenished within bounded window
- `delayed` - Liquidity partially replenished with delay
- `no_impact` - Changes below reaction threshold

#### Structural States (Evidence-Only)
- `stable` - Structural defense observed
- `fragile` - Structural weakening signals detected
- `cracking` - Structural failure signals detected
- `broken` - Structural collapse signals detected

#### Leading Events (Evidence-Only)
- `pre_shock_pull` - Liquidity withdrawal without trade trigger
- `depth_collapse` - Multi-level simultaneous depth reduction
- `gradual_thinning` - Progressive depth reduction over time

#### Descriptive Terms (Allowed)
- `observation` / `observed`
- `detection` / `detected`
- `measurement` / `measured`
- `threshold` / `exceeded`
- `duration` / `sustained`
- `structural` / `structure`
- `evidence` / `evidence_refs`
- `replay` / `replayable`
- `deterministic` / `determinism`
- `persistence` / `persisted`
- `resolution` / `resolved`

---

### Rule 3: API Naming Convention

All API endpoints, parameters, and response fields must use evidence-only language:

```
✅ GOOD                          ❌ BAD
───────────────────────────────────────────────────
GET /reactions                   GET /signals
GET /leading-events              GET /breakout-alerts
GET /belief-states               GET /market-sentiment
reaction_type: VACUUM            signal_type: STRONG_SELL
state: FRAGILE                   sentiment: BEARISH
evidence_refs: [...]             trade_recommendation: [...]
```

---

### Rule 4: PR Review Checklist

Every Pull Request must pass language review:

```markdown
## Language Governance Checklist

- [ ] No forbidden terms in code (variable names, function names)
- [ ] No forbidden terms in comments
- [ ] No forbidden terms in documentation
- [ ] No forbidden terms in UI labels / error messages
- [ ] All new API fields use evidence-only vocabulary
- [ ] All metrics use evidence-first naming (not prediction-style)
```

---

### Rule 5: CI Enforcement

The following grep patterns MUST be checked in CI:

```yaml
# .github/workflows/language-check.yml
language-check:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Check forbidden terms
      run: |
        FORBIDDEN="breakout|absorption|exhaustion|bullish|bearish|overbought|oversold"

        # Check Python files (excluding tests that might test error handling)
        if grep -rniE "$FORBIDDEN" --include="*.py" backend/ poc/; then
          echo "ERROR: Forbidden terms found in code"
          exit 1
        fi

        # Check documentation
        if grep -rniE "$FORBIDDEN" --include="*.md" docs/; then
          echo "ERROR: Forbidden terms found in documentation"
          exit 1
        fi

        echo "Language check passed"
```

---

### Rule 6: Exception Process

If a forbidden term is **absolutely necessary** (e.g., quoting external documentation):

1. Add `# LANGUAGE-EXCEPTION: <reason>` comment above the line
2. Document the exception in this ADR's Appendix
3. Get approval from two maintainers
4. The exception must be read-only (logging/error messages), never used in business logic

---

## Consequences

### Positive

1. **Paradigm Protection:** Vocabulary enforcement prevents unconscious drift
2. **New Developer Safety:** Clear word lists reduce onboarding confusion
3. **Automated Enforcement:** CI catches violations before merge
4. **Audit Trail:** Exceptions are documented and reviewed

### Negative

1. **Initial Friction:** Developers must learn the approved vocabulary
2. **False Positives:** Some edge cases may require exception process

### Neutral

1. **Ongoing Maintenance:** Word lists may need periodic updates

---

## Appendix A: Exception Registry

| Date | File | Term | Reason | Approved By |
|------|------|------|--------|-------------|
| (none yet) | | | | |

---

## Appendix B: Translation Table for New Developers

| If you want to say... | Instead say... |
|-----------------------|----------------|
| "The market broke out" | "The anchor level was invalidated" |
| "Strong absorption at this level" | "High trade-driven liquidity reduction observed" |
| "Momentum is exhausting" | "Reaction velocity decreasing without refill" |
| "Trend confirmed" | "Structural pattern persisted beyond threshold" |
| "Bullish signal" | NEVER - not in scope of this system |
| "Buy opportunity" | NEVER - not in scope of this system |

---

## References

- [ADR-001: Paradigm Principles](./001-paradigm-principles.md)
- [ADR-004: Evidence Integrity Contract](./004-evidence-integrity.md)
