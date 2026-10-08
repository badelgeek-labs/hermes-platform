# Hermes platform references

This directory holds shared `hermes-platform` components managed by Ansible.

`plugins/` contains reference copies for Hermes. In the container, this directory is available at `/mnt/hermes/platform` as read-only.

Do not modify, move, or manage these plugin files from Hermes. Put instance-specific code and configuration in `/mnt/hermes/<instance>` instead.
