# Hermes workspace instructions

- Put instance-specific code and configuration under `/mnt/hermes/<instance>` in the container and track changes in this managed directory's Git repository.
- Read shared `hermes-platform` components from `/mnt/hermes/platform`; this mount is read-only.
- Treat `/opt/data` as runtime state only. Current plugins stay under `/opt/data/plugins`.
- Keep secrets, databases, caches, sessions, and logs outside the managed directory.
