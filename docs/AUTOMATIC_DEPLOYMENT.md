# Automatic staging deployment

[English](AUTOMATIC_DEPLOYMENT.md) | [Simplified Chinese](AUTOMATIC_DEPLOYMENT.zh-CN.md)

The MCS21 staging VPS automatically deploys a new commit after it is merged into GitHub
`main` **and has passed CI**. A root-owned systemd timer checks the private repository
approximately every two minutes and invokes the existing guarded `mcs21-deploy` release command with the exact commit
SHA. Team members continue to develop on branches and merge reviewed pull requests; they do
not need to share a server account or Deploy Key.

This is a server-pull deployment. GitHub Actions does not deploy anything; its only role is to
mark a commit as safe by moving the `deploy` branch (see [The CI gate](#the-ci-gate)). The
repository Deploy Key is read-only and remains under the dedicated `mcs21-deploy` service
account on the VPS. No VPS SSH private key or production secret is stored in GitHub.

## Release flow and safeguards

```text
branch -> pull request -> merge into main -> CI passes on that commit
       -> CI moves the `deploy` branch to it
       -> systemd timer fetches `deploy` -> deploy exact commit
       -> database backup and read-only verification
       -> build and preflight -> atomic release switch
       -> service restart and health check -> audit record
```

The underlying release command serializes deployments, preserves the prior release, and rolls
the application back when its post-switch health check fails. The health check also compares the
`commit` that `GET /health/live` reports (read from the release's `.mcs21-release` file, or from
`APP_COMMIT` when that is set) with the commit just deployed, and rolls back if they differ, so a
restart that left old code running cannot pass as a successful deployment. Automatic database handling is
limited to backup and read-only production SQL verification. The runtime account cannot alter
the schema, and the automatic deployment service has no MySQL administrator or migration
credential. A schema change therefore requires a separately reviewed DBA SQL release, and it must be
applied to the database **before** the code that expects it is pushed — pushing first aborts
the deploy and quarantines the SHA, which blocks every later commit behind it. See
[Applying a schema revision to a running deployment](DEPLOYMENT.md#applying-a-schema-revision-to-a-running-deployment).

The verifier distinguishes a fresh audit chain (`OK`) from a valid chain that already contains
application events (`LIVE_DATA`). A live chain is accepted only when the singleton head keeps
the exact release schema marker, points to the newest audit row, and carries the same hash as
that row. `REVIEW`, `MISSING`, and `UNEXPECTED` remain blocking results. This allows ordinary
code-only releases without treating legitimate audit evidence as schema drift or weakening the
database, account, grant, and structural checks.

When deployment of a commit fails, that SHA is quarantined. The timer will not repeatedly
retry the same broken commit; it tries again when `main` changes, or after an administrator
investigates and explicitly clears the quarantine. Scheduled checks that encounter the same
quarantined SHA exit successfully after reporting the skip, so the original failure remains
visible without generating a new systemd failure every two minutes.

## The CI gate

Until the `promote` job existed, the timer deployed whatever was on `main`: a direct push, or a
merge whose CI was red, reached production within about two minutes (threat-model finding F-01).
GitHub branch protection would be the usual answer, but it is unavailable while the repository is
private on the free plan, so the gate is built from a branch instead.

- The `promote` job in `.github/workflows/ci.yml` runs on pushes to `main` only, and only after
  `backend`, `frontend`, `mysql-gate`, `e2e-live` and `tamper-drill` have all passed on that
  commit. It moves the `deploy` branch to the commit through the GitHub REST API. The branch only
  moves **forward**: an older run that finishes late cannot pull it back, and a history that has
  diverged makes the job fail rather than force anything.
- The timer fetches `main` and `deploy`, and deploys the `deploy` commit. The release command
  still requires that commit to be reachable from `main`, which it always is.
- CI runs on the project's own runner on this VPS (deployment/ci-runner/), isolated from production by its own Docker daemon, network and firewall rule. If the runner is down, nothing is promoted until it is back.
- A documentation-only commit (see `changes` in `ci.yml`) skips the test jobs, so `promote` is
  skipped too and `deploy` stays where it was. Nothing served changed, and the next code commit
  that passes moves `deploy` past it.
- On a push to `main`, "documentation-only" means compared with `deploy`, not with the previous
  push. Pushes cancel the run still in progress for the same branch, so a docs-only push right
  after a code merge would otherwise cancel the code's run and then skip the tests itself, and
  the code would wait for the next code commit to be deployed. Compared with `deploy`, that code
  is still in the diff, so the docs push runs every job and promotes both ([#171](https://github.com/jsonrar/fyp-secure-file-platform/pull/171)).
- A commit with red CI is simply never promoted, and the next green commit contains it. The
  price is latency: a merge now reaches staging after CI finishes (about five minutes) plus up to
  two more for the timer, not after two minutes.
- Until CI has promoted anything, the timer reports that `deploy` is missing and deploys nothing,
  without raising a failed unit (fail closed).
- The timer never walks a release backwards: if a manual `mcs21-deploy all main` put the server
  ahead of `deploy`, the scheduled check leaves it alone.
- `sudo mcs21-auto-deploy status` prints `cached_deploy` (what is allowed to ship) next to
  `cached_main` (what is merged); a difference means CI is still running or is red.

What the gate does **not** do. It does not require a review: anyone with push access can still
put a commit on `main`, and if it passes CI it will deploy. It does not stop an administrator
running `sudo mcs21-deploy all main`, which is deliberately kept as the manual escape hatch and
deploys without CI. And if `main` is ever force-pushed so that `deploy` is no longer an ancestor,
`promote` fails with "diverged"; repair it by pointing `deploy` at a known-good commit on `main`
(`gh api --method PATCH repos/jsonrar/fyp-secure-file-platform/git/refs/heads/deploy -f sha=<sha> -F force=true`),
which needs write access and is an administrator decision.

## Operations

Every authorized deploy operator may inspect the current state:

```bash
sudo mcs21-auto-deploy status
systemctl status mcs21-auto-deploy.timer --no-pager
journalctl -u mcs21-auto-deploy.service --no-pager -n 100
sudo mcs21-deploy history
```

After correcting a transient failure, clear quarantine and retry the current CI-passed commit:

```bash
sudo mcs21-auto-deploy retry
```

Administrators may run a forced validation or retain the manual release path:

```bash
sudo mcs21-auto-deploy force
sudo mcs21-deploy all
```

### Pre-deploy backups are pruned

Every deployment first writes a database dump and an archive of the ciphertext objects to
`/var/backups/mcs21-deploy/<UTC stamp>-<sha>`. Since [PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204), after a healthy deployment
`mcs21-deploy` keeps the newest `MCS21_KEEP_DEPLOY_BACKUPS` sets (default 10, never fewer than 3),
deletes older ones, and audits how many it removed. It only considers directories with that name
pattern and never prunes after a failed deployment. Off-server copies are `mcs21-offsite-backup`'s job.
Installed on staging on 2026-10-08; the first run (a forced redeploy of `f826165`) removed 175 sets and kept 10: `/var/backups/mcs21-deploy` went from 81 GB to 7.5 GB and the root disk from 69 % to 51 % used.

## Installed artifacts

The versioned reference files are under `deployment/server/`. On the staging VPS they are
installed as:

- `mcs21-deploy` -> `/usr/local/sbin/mcs21-deploy`, the guarded manual/automatic release
  implementation;
- `mcs21-auto-deploy` -> `/usr/local/sbin/mcs21-auto-deploy`, owned by root and not writable
  by deploy operators;
- `mcs21-auto-deploy.service` and `mcs21-auto-deploy.timer` -> `/etc/systemd/system/`.

### Ops units a release installs by itself

After a release is live and healthy, `mcs21-deploy` installs and enables **two** ops units from the
release: `mcs21-integrity-sweep.{service,timer}` (the daily integrity scan at 05:30,
[BACKUP_AND_RECOVERY.md §9](BACKUP_AND_RECOVERY.md#9-finding-and-restoring-one-damaged-file)) and
`mcs21-security-agent.{service,timer}` (the daily security-agent check at 06:00, which mails when
anything is Critical or High, [SECURITY_AGENT.md](SECURITY_AGENT.md#proactive-alerts-daily)).
Both run as `fypapp` and only read: the sweep reads the object store, the agent reads the database.
The list is closed in the script (`ops_units`), because a file in `/etc/systemd/system` runs as the
account it names, and letting any file in a release become one would turn "a commit that passed
CI" into "arbitrary code as root". Before installing, the script checks that the service runs as
`fypapp`, starts only `/opt/mcs21/current/backend/.venv/bin/python scripts/<name>.py`, has no
`+`/`!` privileged hooks and that the timer starts that same service; then it compares with the
installed copy, replaces it atomically only if it changed, runs `systemd-analyze verify`, reloads
systemd and enables the timer if it is not already. A failure is printed and audited as a warning
and never fails a deployment that is already healthy. `test_ops_units.py` runs the script's own
check against both shipped units and against variants that must be refused, and pins the list to
exactly `(mcs21-integrity-sweep mcs21-security-agent)`.

The other ops units (`mcs21-reconcile`, `mcs21-audit-checkpoint`, the backup and observe units)
stay deliberate manual installs: some run as root or delete data.

This takes effect once the updated `/usr/local/sbin/mcs21-deploy` is installed on the VPS, which
only a person with root can do. The list lives in that script, so it must be reinstalled whenever
the list changes (it did for the security agent). `install` prints nothing when it succeeds. The
units are installed during a deployment, so either wait for the next release or redeploy the
current one:

```bash
sudo install -m 0755 -o root -g root /opt/mcs21/current/deployment/server/mcs21-deploy /usr/local/sbin/mcs21-deploy
sudo mcs21-auto-deploy force
systemctl list-timers mcs21-integrity-sweep.timer mcs21-security-agent.timer
```

Copy the script only after `/opt/mcs21/current` points at a release that contains the list you
want (`grep '^ops_units=' /opt/mcs21/current/deployment/server/mcs21-deploy`); copying it while an
older release is current installs the older script. The alert mail itself
(`/usr/local/sbin/mcs21-alert`) is a manual install too; reinstall it to get the security agent's
pointer to the admin tab, and test it with `sudo systemctl start mcs21-alert@test.service`.

Checked on 2026-10-07: the installed `/usr/local/sbin/mcs21-deploy`, `mcs21-alert`, `mcs21-backup` and
`mcs21-backup-verify` are byte-identical (SHA-256) to `deployment/server/` at `e4b3f13`, and all nine
`mcs21-*` timers (auto-deploy, observe, audit checkpoint, offsite backup, backup, reconcile, integrity
sweep, security agent, backup verify) are active.

The server additionally provides its environment-specific mirror, Deploy Key, release command,
secrets, backup storage, and sudo policy. Environment-specific values must not be copied into
Git.

The timer is enabled with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcs21-auto-deploy.timer
```

Having GitHub Actions perform the deployment itself, instead of only marking commits, would
still require repository administration, protected deployment environment secrets, and an
explicitly reviewed credential design. Never commit a VPS private key or paste it into a
workflow file.
