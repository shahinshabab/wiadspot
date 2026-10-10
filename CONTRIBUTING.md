# Branching workflow

| Branch | Purpose |
|---|---|
| `main` | Production. Only receives merges from `dev` (or a `hotfix/*` branch in an emergency). |
| `dev` | Development / integration. Every feature branch merges here first. |
| `feature/*`, `fix/*` | Short-lived work branches, created from `dev`. |

## Flow

1. `git checkout dev && git pull && git checkout -b feature/my-change`
2. Commit, push, and open a pull request **into `dev`**.
3. When `dev` is tested and ready to release, open a pull request `dev` → `main`.
4. Never commit or open feature PRs directly against `main`.
5. After a hotfix lands on `main`, merge `main` back into `dev`.
