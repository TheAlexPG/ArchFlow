# Contributing to ArchFlow

Thanks for considering a contribution — bug fixes, features, docs, and
questions are all welcome. This document walks through the workflow.

---

## 1. Development setup

All the setup is in the [Quick start](README.md#-quick-start) section of the
README. TL;DR:

```bash
git clone https://github.com/TheAlexPG/ArchFlow.git
cd ArchFlow
make setup   # one-time
make dev     # start backend + frontend + infra
```

---

## 2. Branching model

`main` is **protected** and always deployable. You cannot push to it
directly — every change lands via a pull request.

**Branch naming:** `<type>/<short-kebab-description>` where `<type>` is one
of:

| Prefix     | Use for                                                    |
| ---------- | ---------------------------------------------------------- |
| `feat/`    | new user-facing functionality                              |
| `fix/`     | bug fixes                                                  |
| `refactor/`| internal change, no behaviour difference                   |
| `perf/`    | performance improvements                                   |
| `docs/`    | documentation only                                         |
| `chore/`   | tooling / deps / CI / config / dotfiles                    |
| `test/`    | test-only changes                                          |
| `style/`   | CSS / formatting / Prettier-type churn                     |

Examples: `feat/workspace-delete-button`, `fix/drag-snap-back`,
`docs/oauth-setup`.

---

## 3. Commit messages

Conventional-style headline, imperative mood, ~70 chars:

```
<type>(<scope>): <what changed — imperative mood>

<optional body — the WHY, 1–3 short paragraphs>
```

Scope is optional but helps: `feat(backend)`, `fix(landing)`,
`chore(ci)`, etc. Good examples in `git log`.

---

## 4. Pull request workflow

1. **Branch off `main`:** `git switch -c feat/my-thing`.
2. **Keep commits clean.** Small, well-described commits beat one
   catch-all dump. Rebase to tidy history before opening the PR:
   `git rebase -i main`.
3. **Run local checks** before pushing:

   ```bash
   make lint      # ruff + eslint
   make test      # pytest + frontend tests
   ```

4. **Open a PR** targeting `main`. The PR template prompts you for
   summary, test plan, screenshots, migration notes.
5. **CI runs** `build-backend` and `build-frontend` status checks — both
   must be green before the PR can merge.
6. **Merge.** We use **squash merge** by default so `main` stays linear
   and readable. The PR title becomes the squash-commit message — make
   it a clean headline.
7. **Delete your branch** after merge (GitHub offers a button).

---

## 5. Review criteria

Even as a small project we aim for:

- **Correctness.** Tests cover the change. Happy path + at least one
  edge case.
- **No feature creep.** Do the one thing the PR title says. Cleanup
  goes in a separate PR.
- **No commented-out code or dead branches.** Delete it — git remembers.
- **Frontend PRs ship screenshots.** Static screenshots for layout,
  short screen recordings for interactions.
- **Migrations are reversible.** Every Alembic upgrade has a matching
  downgrade. Don't write destructive upgrades without a feature flag.
- **No secrets in code.** `.env` lives on the server, never in the repo.

---

## 6. What's out of scope

- **Destructive operations on prod without a plan.** Migrations that
  drop tables, rewrite constraints, or require downtime need an explicit
  runbook in the PR description.
- **Bumping major versions of framework deps** without a separate chore
  PR that only does the bump.
- **AI-generated code without human review.** Totally fine to use
  assistants — just read what you're submitting.

---

## 7. Reporting issues

Bugs and feature requests go into
[GitHub issues](https://github.com/TheAlexPG/ArchFlow/issues). For
security issues please use
[private security advisories](https://github.com/TheAlexPG/ArchFlow/security/advisories)
instead of public issues.

---

## 8. License

By submitting a PR you agree that your contribution is licensed under
the project's [AGPL-3.0](LICENSE). If your employer has a CLA / IP
policy, sort that out before opening the PR.
