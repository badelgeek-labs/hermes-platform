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
2. préparer l'hôte et l'arborescence Hermes ;
3. créer le bot Discord privé et préparer ses secrets ;
4. définir, déployer et démarrer le runtime Compose isolé, puis connecter
   Hermes au compte ChatGPT/Codex ;
5. ajouter les procédures d'exploitation et de backup plus tard.

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
/var/lib/hermes/platform/    # composants partagés, propriétaire : hermes:hermes
/var/lib/hermes/<name>/      # données et secrets, propriétaire : hermes:hermes
/var/lib/hermes/<name>-managed/ # composants gérés par instance, propriétaire : hermes:hermes
/var/backups/hermes/<name>/  # sauvegardes, propriétaire : hermes:hermes
```

Le répertoire platform contient les copies partagées des plugins de ce dépôt
sous `platform/plugins/`. Pour chaque instance, `-managed/` contient les
répertoires `config`, `skills`, `plugins`, `workflows`, `scripts`, `templates`
et `tests`, ainsi que `README.md` et `AGENTS.md`. Il est monté en lecture-
écriture dans le conteneur sous `/mnt/hermes/<name>`; platform reste en lecture
seule. Les plugins runtime existants restent sous `/opt/data/plugins`; Ansible
ne crée, ne copie ni ne supprime leur contenu.

Le répertoire de plateforme est géré par Ansible avec les privilèges élevés.
Le compte système `hermes`, sans accès SSH ni sudo, possède les espaces de
données, composants et sauvegardes. Le dépôt Git local de
`<name>-managed` est initialisé s'il n'existe pas, avec un `.gitignore`
générique pour les secrets, l'état runtime et les caches. Ansible crée le
commit initial `chore: initialize Hermes instance workspace` si le dépôt n'a
pas encore de commit, n'a pas de remote et ne contient que les fichiers
bootstrap attendus. Une relance peut donc finaliser ce commit. Aucun contenu
métier n'est ajouté, et un dépôt existant qui ne satisfait pas ces conditions
n'est jamais réinitialisé ni modifié. Chaque instance garde son propre
répertoire runtime et son projet Compose `hermes-<name>`. Pour Pomo,
`/var/lib/hermes/pomo/.env`, `auth.json` et `SOUL.md` restent hors Git avec des
droits restreints. Le détail est documenté dans `ACTION_PLAN.md`.

## Identité de chaque instance

Chaque instance Hermes possède son propre `SOUL.md`, stocké dans son répertoire
de données persistant et monté dans le conteneur à `/opt/data/SOUL.md`. Son
contenu n'est pas versionné dans ce dépôt public : GitHub Actions le reçoit via
une Repository Variable nommée `HERMES_SOUL_<INSTANCE_EN_MAJUSCULES>`, par exemple
`HERMES_SOUL_POMO`. Ansible le déploie avec le propriétaire `hermes:hermes` et
le mode `0600`.

Le déploiement de `SOUL.md`, des tokens et des autres secrets s'effectue
uniquement via GitHub Actions. Le lanceur Ansible local ne récupère ni les
variables ni les secrets GitHub et ne les écrit pas sur la VM.

## Runtime Compose

Le modèle [`ansible/templates/hermes-compose.yaml.j2`](ansible/templates/hermes-compose.yaml.j2)
définit un service `hermes` par instance. Pour `pomo`, il produit le projet
Compose `hermes-pomo`, le réseau isolé `hermes-pomo-network` et le conteneur
généré par Compose `hermes-pomo-hermes-1`.

Il utilise l'image officielle Hermes épinglée par digest et conserve le
répertoire de données de l'instance à `/opt/data` en lecture-écriture. Il monte
également `/var/lib/hermes/platform/` en lecture seule à
`/mnt/hermes/platform`, puis `/var/lib/hermes/<name>-managed/` en lecture-
écriture à `/mnt/hermes/<name>`. Le Compose reste dans `/opt/hermes/<name>/`,
hors du futur dépôt managed. Aucun port ni socket Docker n'est exposé. Le rôle
`hermes_deployment` rend ce modèle avec l'UID/GID réel du compte système
`hermes`, converge uniquement le projet ciblé et vérifie que le service tourne
et que les trois bind mounts apparaissent dans les mounts du conteneur avec les
chemins et modes attendus. Le rôle `hermes_runtime` récupère ces deux valeurs
dynamiquement : aucun UID/GID n'est écrit en dur.

Après le déploiement, le contrôle Ansible inspecte les mounts du conteneur. Pour
un contrôle manuel, depuis `/opt/hermes/<name>/`, exécuter :

```bash
docker compose exec hermes sh -c 'mount | grep /mnt/hermes; test -d /opt/data'
docker inspect --format '{{json .Mounts}}' "$(docker compose ps -q hermes)"
sudo -u hermes git -C /var/lib/hermes/<name>-managed status --short --branch
sudo -u hermes git -C /var/lib/hermes/<name>-managed remote -v
```

La dernière commande ne doit afficher aucune remote par défaut.

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
