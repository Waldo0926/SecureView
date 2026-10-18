# CI workflow

`ci.yml` is the GitHub Actions workflow from the team repository. It ran on the team's self-hosted runners, so it is kept here for reference and does not run in this repository.

Jobs:

- `backend`: dependency audit and backend unit tests with coverage.
- `frontend`: npm audit, frontend tests with coverage, type check and production build.
- `mysql-gate`: the full backend suite on MySQL 8.4.
- `e2e-live`: live end-to-end tests against a real backend and MySQL, plus Playwright browser tests.
- `tamper-drill`: the isolated ciphertext tamper drill.
- `promote`: on `main`, moves the `deploy` branch to a commit that passed every job. The server only deploys that branch.

The latest results are in [docs/test report](../docs/test%20report/README.md).
