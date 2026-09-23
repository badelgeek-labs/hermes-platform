# Hermes Platform Action Plan

## Goal

Deploy a reproducible and idempotent Hermes instance for **Pomo** on the
existing Hetzner VM, while keeping the existing n8n stack fully isolated and
unchanged.

This is the single source of truth for the rollout. The suggested commit at the
end of each phase must never include a token, OAuth credential, or local `.env`
file.

## Status convention

Each action has independent nested statuses:

- **Repo**: the decision is recorded or the required code, script, or Ansible
  implementation exists in this repository.
- **VM**: the result has been applied and verified on the Hetzner VM.
- **n/a**: the action has no direct VM state yet. A dry-run never checks the
  **VM** box.

## Current baseline

- Manual GitHub Actions workflow can run Ansible against the VM over SSH.
  - [x] Repo
  - [x] VM
- The `deploy` account can connect and use privilege escalation.
  - [x] Repo
  - [x] VM
- Docker CLI and the modern `docker compose` plugin are checked by Ansible and
  available on the VM.
  - [x] Repo
  - [x] VM
- Docker is enabled and running on the VM.
  - n/a Repo
  - [x] VM
- Existing n8n resources were inventoried: containers, `n8n_default` network,
  `n8n_*` volumes, and ports `80`, `443`, and `5678`.
  - [x] Repo
  - [x] VM
- The repository documents the n8n isolation boundary and intended Hermes host
  layout.
  - [x] Repo
  - n/a VM
- An operator script starts and watches the workflow for the current branch:
  `./ops/run-ansible-workflow.sh`.
  - [x] Repo
  - [x] VM
- The dedicated `hermes` account and Pomo layout are present with the expected
  ownership and permissions.
  - [x] Repo
  - [x] VM

## Phase 1 — Host preparation (Docker tooling)

- Keep Docker and Compose as external prerequisites: fail when either is
  missing; do not install or upgrade them automatically.
  - [x] Repo
  - [x] VM
- Keep `deploy` outside the `docker` group; use Ansible `become` for Docker
  operations.
  - [x] Repo
  - [x] VM
- Install LazyDocker idempotently through the Docker role and verify its
  configured version is available.
  - [x] Repo
  - [x] VM
- Optionally pin `ansible_python_interpreter` to `/usr/bin/python3.12` to
  remove the interpreter-discovery warning.
  - [ ] Repo
  - [ ] VM
- Configure the local Ansible launcher in `ops/.env`.
  - `DEPLOY_HOST` is the VM hostname or IP address.
  - `DEPLOY_USER` is the SSH account (`deploy`).
  - `DEPLOY_SSH_KEY` is the local path to the private SSH key.
  - This local file is ignored by Git and does **not** configure Hermes.
  - [x] Repo
  - n/a VM
- Use `./ops/run-ansible-local.sh` for a dry run by default; use the `run`
  argument only when remote changes are intended.
  - [x] Repo
  - n/a VM

Suggested commit when this phase is complete: `chore: prepare deployment host`

## Phase 2 — Hermes layout preparation (user and filesystem)

- Manage the Hermes host layout from `hermes_instances`, initially containing
  only `name: pomo`.
  - [x] Repo
  - [x] VM
- Create a dedicated `hermes` system user and group:
  - no SSH login, interactive shell, or sudo access;
  - separate from `deploy`, which remains the SSH/Ansible account only.
  - [x] Repo
  - [x] VM
- Create `/opt/hermes/<name>/` for each instance's Compose definition and
  deployment files, owned by `root:root` and writable only through Ansible
  `become`.
  - [x] Repo
  - [x] VM
- Create `/var/lib/hermes/<name>/` for each instance's persistent Hermes data,
  `.env`, and OAuth credentials, owned by `hermes:hermes` with mode `0700`.
  - [x] Repo
  - [x] VM
- Create `/var/backups/hermes/<name>/` for each instance's backups, owned by
  `hermes:hermes` with mode `0700`.
  - [x] Repo
  - [x] VM
- Verify a second role run leaves the account, permissions, and directories
  unchanged.
  - [x] Repo
  - [ ] VM

Suggested commit when this phase is complete: `chore: prepare Hermes Pomo layout`

## Phase 3 — Discord and runtime secrets

- Create and configure the Discord application/bot for Pomo manually:
  1. <https://discord.com/developers/applications>:
     - [x] **New Application** → name: **Hermes Pomo** → **Create**.
  2. **Settings** → **Bot**:
     - [x] Select **Add Bot** and confirm, only if this button is shown.
     - [x] **Public Bot**: off.
     - [x] **Requires OAuth2 Code Grant**: off.
  3. **Settings** → **Bot** → **Privileged Gateway Intents**:
     - [x] **Message Content Intent**: on.
     - [x] **Presence Intent**: off.
     - [x] **Server Members Intent**: on.
  4. **Settings** → **Bot** → token:
     - [x] **Reset Token** / **Copy** → store it in a password manager only.
     - [x] Never paste it into Git, a terminal, or chat.
  5. **Settings** → **Installation**:
     - [x] **Guild Install**: on.
     - [x] **User Install**: off.
     - [x] **Install Link**: **None** / **Aucune**.
  6. **Settings** → **OAuth2** → **URL Generator**:
     - [x] **OAuth2 Scopes**: `bot` and `applications.commands`.
     - [x] **Guild Install**, if Discord asks for an installation type.
     - [x] **Bot Permissions** → **General Channel Permissions** → **View
           Channels**.
     - [x] **Bot Permissions** → **Text Permissions** → **Send Messages** and
           **Read Message History**.
     - [x] **Bot Permissions** → **Text Permissions** → **Embed Links**, **Attach
           Files**, **Send Messages in Threads**, and **Add Reactions**.
     - [x] Verify **Administrator** and permissions other than the seven listed
           above are unchecked.
     - If the bot is already in the server, update its bot role through Discord
       **Server Settings** → **Roles**; do not invite it again.
     - [x] Copy the generated URL → open it → choose the target server →
           **Authorize**.
     - [x] Ensure the signed-in account has **Manage Server** on the target
           server. If the list is empty: Discord **+** → **Create My Own**, or ask
           a server administrator for that permission.
  7. Discord client → **User Settings** → **Advanced**:
     - [x] **Developer Mode**: on.
     - [x] Right-click the owner account → **Copy User ID**.
  - [x] Repo
  - [x] VM
- Keep Discord application creation manual. It belongs to the Discord account
  owner and cannot safely remove the one-time token handling.
  - [x] Repo
  - n/a VM
- Distinguish the two `.env` files:
  - `ops/.env` is local SSH configuration for the Ansible launcher;
  - `/var/lib/hermes/pomo/.env` is the future Hermes runtime file mounted at
    `/opt/data/.env` inside the container.
  - [x] Repo
  - n/a VM
- Add `DISCORD_BOT_TOKEN` as a GitHub Actions secret and write it with Ansible
  to `/var/lib/hermes/pomo/.env` without logging its value.
  - [x] Repo
  - [x] VM
- Keep each instance's identity outside the public repository. Use the GitHub
  Actions repository-variable convention `HERMES_SOUL_<UPPERCASE_INSTANCE_NAME>`:
  `HERMES_SOUL_POMO` for Pomo.
  - [x] Repo
  - [x] VM
- Render each instance identity to `/var/lib/hermes/<name>/SOUL.md`, owned by
  `hermes:hermes` with mode `0600`, using `no_log: true`. The mounted file is
  then `/opt/data/SOUL.md` inside the official container.
  - [x] Repo
  - [x] VM
- Apply runtime secrets and instance identities only through GitHub Actions.
  The local Ansible launcher must not fetch GitHub variables or secrets, and
  must not write `.env` or `SOUL.md`.
  - [x] Repo
  - n/a VM
- Configure `DISCORD_ALLOWED_USERS` with the owner account ID. Do not set
  `DISCORD_ALLOW_ALL_USERS`: its documented default is `false`.
  Leave `DISCORD_ALLOWED_CHANNELS` unset so Hermes can respond in every Pomo
  server channel that its Discord role can access.
  - [x] Repo
  - [x] VM
- Verify the runtime `.env` contains only:

  ```dotenv
  DISCORD_BOT_TOKEN=<GitHub Actions secret>
  DISCORD_ALLOWED_USERS=<owner Discord User ID>
  ```

  - [x] Repo
  - [x] VM

Suggested commit when this phase is complete: `feat: prepare dynamic Hermes runtime configuration`

## Phase 4 — Hermes runtime and deployment

- Use the official `nousresearch/hermes-agent` image.
  - [x] Repo
  - n/a VM
- Pin the tested image by immutable digest before the first deployment.
  - [x] Repo
  - [ ] VM
- Derive each Compose project name as `hermes-<name>`; Pomo is therefore
  `hermes-pomo`.
  - [x] Repo
  - [ ] VM
- Retrieve the `hermes` UID and GID while rendering the Compose definition and
  use them for `HERMES_UID` and `HERMES_GID`; do not hard-code `deploy` UID/GID
  `1000`.
  - [x] Repo
  - [ ] VM
- Use a dedicated Hermes network; never join `n8n_default`.
  - [x] Repo
  - [ ] VM
- Configure `restart: unless-stopped`. Do not add a fabricated health check:
  the pinned image exposes no built-in health check and the API endpoint stays
  disabled with no inbound port for this deployment.
  - [x] Repo
  - [ ] VM
- Mount only `/var/lib/hermes/<name>` at `/opt/data` for each instance's
  persistent state.
  - [x] Repo
  - [ ] VM
- Do not expose an inbound HTTP port initially; Discord uses outbound
  connectivity.
  - [x] Repo
  - [ ] VM
- Do not use `network_mode: host` or mount the Docker socket.
  - [x] Repo
  - [ ] VM
- Confirm that no port, volume, network, container, or Compose project name
  overlaps with n8n.
  - [x] Repo
  - [ ] VM
- Add an Ansible role that renders the Compose definition and deploys runtime
  configuration idempotently.
  - [x] Repo
  - [ ] VM
- Start or update only the targeted `hermes-<name>` Compose project.
  - [x] Repo
  - [ ] VM
- After the first service start, complete ChatGPT/Codex OAuth with
  `docker compose exec -it hermes hermes model`, then choose **ChatGPT or Codex
  Subscription** in the browser device-login flow.
  - [x] Repo
  - [ ] VM
- Keep OpenRouter as a fallback if the selected ChatGPT plan is not eligible;
  do not create `OPENROUTER_API_KEY` initially.
  - [x] Repo
  - n/a VM
- Verify OAuth persists as `/var/lib/hermes/pomo/auth.json`; it is a secret and
  must be mode `0600`.
  - [ ] Repo
  - [ ] VM
- Add post-deployment checks: container state and relevant logs, then verify
  Discord connectivity instead of relying on a fabricated Docker health check.
  - [ ] Repo
  - [ ] VM
- Prove that a second workflow run reports no unexpected changes.
  - [ ] Repo
  - [ ] VM
- Prove that n8n containers, volumes, network, and public ports remain
  unchanged before and after Hermes deployment.
  - [ ] Repo
  - [ ] VM

Suggested commit when this phase is complete: `feat: deploy Pomo Hermes runtime`

## Phase 5 — Operations

- Define backup and restore procedures for Pomo persistent data.
  - [ ] Repo
  - [ ] VM
- Define log access and basic failure diagnosis commands.
  - [ ] Repo
  - [ ] VM
- Document the upgrade and rollback procedure for the Hermes image.
  - [ ] Repo
  - [ ] VM
- Schedule and perform the pending VM operating-system updates and reboot in a
  maintenance window, taking n8n availability into account.
  - [ ] Repo
  - [ ] VM

Suggested commit when this phase is complete: `docs: add Pomo operations runbook`

## Future architecture decision

- Decide between separate isolated Hermes instances (`pomo`, `personal`,
  `hokopi`, ...) and one Hermes instance with multiple profiles.
  - [ ] Repo
  - n/a VM
- If instances are separate, standardize one Compose project, environment file,
  persistent-data directory, and backup location per instance.
  - [ ] Repo
  - [ ] VM
- If profiles are shared, document tenant isolation, secret boundaries, and
  upgrade impact before onboarding another profile.
  - [ ] Repo
  - [ ] VM

Suggested commit when this phase is complete: `docs: decide Hermes instance topology`
