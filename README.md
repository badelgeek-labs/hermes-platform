# Hermes Platform

Déploiement reproductible et idempotent d'une instance Hermes dédiée à Pomo
sur une VM Hetzner existante. Le déploiement ne doit pas modifier l'instance
n8n déjà présente sur cet hôte.

## Objectif initial

- une instance Hermes isolée pour Pomo ;
- déclenchement manuel depuis GitHub Actions ;
- connexion SSH en tant que `deploy`, puis privilèges élevés uniquement pour
  les opérations Docker nécessaires ;
- données persistantes hors du conteneur ;
- secrets hors Git ;
- Discord comme première interface ;
- aucune image Docker Hermes personnalisée tant qu'elle n'est pas nécessaire.

À terme, le même socle pourra accueillir plusieurs instances isolées (`pomo`,
`personal`, `hokopi`, etc.) ou une instance Hermes à profils multiples. Ce
choix sera fait selon les besoins réels.

## Déploiement

```text
GitHub Actions (manuel)
        |
        | SSH avec DEPLOY_SSH_KEY
        v
deploy@VM
        |
        | Ansible become
        v
Docker Compose
        |
        v
Hermes / Pomo
```

Le workflow est défini dans `.github/workflows/ansible.yml`. Il attend les
variables GitHub `DEPLOY_HOST` et `DEPLOY_USER`, ainsi que le secret
`DEPLOY_SSH_KEY`.

## Chronologie de mise en place

La documentation opérationnelle suit l'ordre réel de déploiement :

1. configurer et valider le lanceur Ansible local ;
2. créer le bot Discord privé ;
3. connecter Hermes au compte ChatGPT/Codex ;
4. préparer les données persistantes et le secret Discord ;
5. déployer le gateway Pomo ;
6. ajouter les procédures d'exploitation et de backup plus tard.

Voir le plan détaillé : [`ACTION_PLAN.md`](ACTION_PLAN.md).

## Préconditions Docker

Le rôle `ansible/roles/docker` vérifie que les commandes suivantes sont
disponibles :

```bash
docker --version
docker compose version
```

Le playbook échoue si l'une de ces commandes est absente. À ce stade, le rôle
ne les installe pas : l'installation idempotente de Docker et du plugin Compose
sera ajoutée lorsqu'elle sera nécessaire.

Le rôle installe également LazyDocker depuis son archive officielle. La version
par défaut est `0.25.2` et peut être remplacée avec `lazydocker_version`.
L'archive utilisée cible l'architecture `x86_64` de la VM actuelle.
Le binaire est disponible à l'emplacement `/usr/local/bin/lazydocker`. Comme
`deploy` n'appartient pas au groupe `docker`, il doit être lancé avec `sudo` sur
la VM. Une nouvelle version doit aussi être ajoutée avec sa somme SHA-256
officielle dans `lazydocker_checksum`.

## Cloisonnement avec n8n

La VM héberge déjà n8n. Ses conteneurs, son réseau Docker et ses volumes ne
font pas partie du périmètre de ce dépôt.

En particulier, Hermes ne doit pas :

- modifier, redémarrer ou recréer les conteneurs `n8n-*` ;
- rejoindre le réseau `n8n_default` ;
- monter ou supprimer des volumes `n8n_*` ;
- utiliser les ports entrants déjà réservés par n8n et Caddy : `80`, `443` et
  `5678`.

Discord étant l'interface initiale, l'instance Pomo ne requiert pas de port
HTTP entrant par défaut. Son projet Compose, son réseau et ses volumes devront
porter un préfixe propre, par exemple `hermes-pomo`.

## Organisation cible sur la VM

Le rôle Ansible `hermes_layout` gère une liste d'instances. La configuration
initiale contient uniquement `pomo` :

```yaml
hermes_instances:
  - name: pomo
```

Pour chaque `name`, le rôle crée l'arborescence suivante :

```text
/opt/hermes/<name>/          # définition Compose, propriétaire : root:root
/var/lib/hermes/<name>/      # données et secrets, propriétaire : hermes:hermes
/var/backups/hermes/<name>/  # sauvegardes, propriétaire : hermes:hermes
```

Le répertoire de plateforme est géré par Ansible avec les privilèges élevés.
Le compte système `hermes`, sans accès SSH ni sudo, possède les données et
sauvegardes. Chaque future instance aura son propre répertoire de données et
son projet Compose `hermes-<name>`. Pour Pomo,
`/var/lib/hermes/pomo/.env` et `auth.json` resteront hors Git avec des droits
restreints. Le détail est documenté dans `ACTION_PLAN.md`.

## Exécution du playbook

Depuis GitHub Actions, déclencher manuellement le workflow **Ansible** sur la
branche voulue. Pour un essai local, Ansible doit être installé et l'hôte doit
être configuré dans `ops/.env` :

```bash
cp ops/.env.example ops/.env
# Edit ops/.env and set DEPLOY_HOST.

./ops/run-ansible-local.sh       # check mode (default; no remote changes)
./ops/run-ansible-local.sh run   # apply changes
```
