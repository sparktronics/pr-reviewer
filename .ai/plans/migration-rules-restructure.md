# Migration Plan: AI Rules Restructuring

**Created:** 2026-01-04  
**Status:** In Progress  
**Author:** AI Assistant  

---

## 1. Objective

Restructure the AI rules and configuration files to:
- Eliminate contradictions between Cursor and Claude configurations
- Establish `.ai/rules/` as the **single source of truth**
- Create clear separation between development (Cursor) and review (Claude CI) contexts
- Remove irrelevant content (FastAPI)
- Fix outdated references

---

## 2. Current State Analysis

### 2.1 Existing Files

| File | Lines | Purpose | Issues |
|------|-------|---------|--------|
| `.cursorrules` | 178 | Cursor IDE entry point | References non-existent file, overlaps with Claude rules |
| `.claude/rules.md` | 205 | Claude agent (PR review) | Contains irrelevant FastAPI content (~60 lines), contradictions |
| `.github/workflows/claude-code-review.yml` | 58 | Auto PR review on open/sync | References `.claude/rules.md` |
| `.github/workflows/claude.yml` | 51 | On-demand `@claude` assistant | No explicit rules reference |

### 2.2 Identified Contradictions

| Topic | `.cursorrules` | `.claude/rules.md` | Resolution |
|-------|----------------|-------------------|------------|
| Secret storage | "Keep secrets in .env or environment" | "Store secrets in Secret Manager, not environment variables" | **Clarified:** Passwords/PAT → Secret Manager; Config vars → Environment |
| Code style strictness | "readability > rules" | "Follow PEP 8 conventions" (strict) | Adopt: PEP 8 with readability priority |
| Function length | Not mentioned | "under 50 lines" | Adopt as guideline, not hard rule |

### 2.3 Irrelevant Content Removed

From `.claude/rules.md` (lines 145-205):
- FastAPI-specific guidelines
- Pydantic v2 references
- Route definitions guidance
- Lifespan context managers
- FastAPI middleware patterns

### 2.4 Outdated References Fixed

| Location | Previous | Updated |
|----------|----------|---------|
| `.cursorrules` | `pr_regression_review.py` | `main.py` |

---

## 3. Target State

### 3.1 New Directory Structure

```
project-root/
├── .cursorrules                    # Entry point for Cursor (lightweight)
├── .claude/
│   └── rules.md                    # Entry point for Claude CI (lightweight)
├── .github/
│   └── workflows/
│       ├── claude-code-review.yml  # Auto PR review (unchanged)
│       └── claude.yml              # On-demand @claude (unchanged)
├── .ai/                            # ✨ SOURCE OF TRUTH
│   ├── rules/
│   │   ├── code_style.md           # Python syntax, naming, patterns
│   │   ├── tech_stack.md           # Libraries, versions, GCP constraints
│   │   ├── security.md             # Secrets, credentials, sensitive data
│   │   └── testing.md              # Test approach, validation
│   └── plans/
│       ├── template.md             # Standard format for feature plans
│       └── migration-rules-restructure.md  # This file
```

### 3.2 File Responsibilities

| File | Responsibility | References |
|------|----------------|------------|
| `.cursorrules` | Cursor-specific behavior (file creation policy, communication style, git ops) | Imports from `.ai/rules/` |
| `.claude/rules.md` | Claude CI-specific behavior (review focus, comment format) | Imports from `.ai/rules/` |
| `.ai/rules/code_style.md` | Python conventions, type hints, docstrings, imports | Standalone |
| `.ai/rules/tech_stack.md` | GCP, Vertex AI, Cloud Functions, Azure DevOps | Standalone |
| `.ai/rules/security.md` | Secret management, credential handling | Standalone |
| `.ai/rules/testing.md` | Test validation approach | Standalone |

---

## 4. Migration Checklist

### Phase 1: Create Structure ✅
- [x] Create `.ai/` directory
- [x] Create `.ai/rules/` directory
- [x] Create `.ai/plans/` directory
- [x] Write `.ai/rules/code_style.md`
- [x] Write `.ai/rules/tech_stack.md`
- [x] Write `.ai/rules/security.md`
- [x] Write `.ai/rules/testing.md`
- [x] Write `.ai/plans/template.md`
- [x] Write `.ai/plans/migration-rules-restructure.md`

### Phase 2: Update Entry Points ✅
- [x] Rewrite `.cursorrules` (remove duplication, add imports)
- [x] Rewrite `.claude/rules.md` (remove FastAPI, add imports)

### Phase 3: Verify (Pending)
- [ ] Verify `.github/workflows/claude-code-review.yml` path still valid
- [ ] Verify `.github/workflows/claude.yml` works
- [ ] Test Cursor behavior with new rules
- [ ] Test a PR review with Claude

---

## 5. Rollback Plan

If issues arise:
1. Git revert the migration commit
2. Original files are preserved in git history
3. No external dependencies affected

---

## 6. Notes

- The AEM/HTL/frontend domain expertise remains in `main.py`'s `SYSTEM_PROMPT`, not in the rules files (per user preference)
- Both Claude workflows are preserved with their distinct purposes
- FastAPI content removed as irrelevant to this Cloud Functions project
