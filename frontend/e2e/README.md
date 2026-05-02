# Playwright E2E — Sovereign Defence frontend

End-to-end smoke tests that hit the **deployed** stack (frontend + 5
FastAPI services + sovdef26 ADB) via the public OCI Native Ingress LB.

## Run

```bash
cd frontend
npm install                      # picks up @playwright/test from devDependencies
npx playwright install chromium  # one-time browser download
npx playwright test
```

Override the target URL when running against a local dev server:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:5173 npx playwright test
```

## What is covered

| Spec                  | Surface                                              |
|-----------------------|------------------------------------------------------|
| `sidebar-nav.spec.ts` | Routes for all 6 views load and side-nav highlights. |
| `use-case-data.spec.ts` | Each view renders a use-case-specific element from real data (no MSW). |

## What is *not* covered

- Authenticated flows — the demo is open to the LB.
- Mutating endpoints (`/scenes/upload`) — would write to live ADB and bucket.
- Cross-browser — only Chromium is in the default project. Uncomment the
  Firefox project in `playwright.config.ts` to enable.

## Failing in CI

Playwright captures traces, screenshots, and video on failure. The CI
report uploads them as artefacts via `reporter: ['github']`.
