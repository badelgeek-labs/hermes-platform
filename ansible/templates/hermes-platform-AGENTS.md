# Hermes platform instructions

- Treat `/mnt/hermes/platform` as read-only shared references managed by Ansible.
- Do not modify, move, or manage files under `/mnt/hermes/platform/plugins`.
- Put instance-specific code and configuration in `/mnt/hermes/<instance>`.
- Keep runtime state under `/opt/data`.
