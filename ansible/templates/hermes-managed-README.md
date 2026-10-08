# Instance managed components

This directory holds versioned, instance-specific code and configuration. In the container, write it under `/mnt/hermes/<instance>`. Track managed changes in this directory's Git repository.

Shared `hermes-platform` components are provided under `/mnt/hermes/platform` and are read-only in the container.

`/opt/data` is runtime state only. Current runtime plugins remain under `/opt/data/plugins` and are not managed by Ansible.

Keep secrets, databases, caches, sessions, and logs outside this managed tree.
