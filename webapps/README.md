# Optional webapps alongside TravelServer

The backup daemon is fully self-contained and network-independent: nothing
here is required for backups to work. These examples are for yesting other
web applications on the same box, reading the mirrored `BACKUP/` folders
**read-only**.

Install Docker + Compose with:

```bash
sudo ./install.sh --with-docker
```

The daemon's own dashboard is on port **8000** (see `[webui]` in the config);
the examples below deliberately use other ports (Immich: 2283, PiGallery2: 8183).

## Before you start

1. Let the SSDs be mounted by the daemon (insert them; it mounts any labeled
   filesystem under `/mnt/travelserver/`). Find the exact paths with:
   ```bash
   lsblk -o NAME,LABEL,MOUNTPOINT
   ```
2. `cp webapps/.env.example webapps/.env` and set `TRAVEL1_BACKUP` /
   `TRAVEL2_BACKUP` to those `BACKUP` folder paths (and, for Immich, a
   `DB_PASSWORD` plus local-disk locations for its own data — never store
   Immich's database or uploads on the backup SSDs).

## Option A: Immich (read-only external library)

Immich indexes an existing folder tree without importing/copying it:

```bash
cd webapps
cp .env.example .env   # then edit
docker compose -f docker-compose.immich.yml --env-file .env up -d
```

Then in Immich (http://rock5a:2283), after creating the admin account:

1. Administration → Libraries → **External Library** → *Create External Library*.
2. Import paths: `/usr/src/app/external/TRAVEL1` and, if you want the mirror
   indexed too, `/usr/src/app/external/TRAVEL2` (the content is identical —
   usually one is enough; the mirror exists for resilience, not browsing).
3. Run a scan. Immich will never write to those folders: they are mounted `:ro`.

The compose here is an example skeleton. For production, prefer the compose
file pinned to your Immich release from the
[Immich releases page](https://github.com/immich-app/immich/releases) and add
the two `:ro` volumes from `docker-compose.immich.yml`.

## Option B: PiGallery2 (minimal gallery)

Fast, single-container gallery that just serves the directory tree:

```bash
cd webapps
cp .env.example .env   # then edit
docker compose -f docker-compose.pigallery2.yml --env-file .env up -d
```

Browse http://rock5a:8183 — point its default library at `/app/data/images`,
which is the read-only TRAVEL1 `BACKUP/` folder.

## Safety notes

- Both example mounts are **read-only** — the webapp cannot modify, move, or
  delete backups. Keep it that way.
- Do not scrape/index the `index.db` SQLite files; that's the daemon's dedupe
  index.
- Immich/PiGallery2 containers read the same files the backup daemon writes.
  A photo being indexed mid-copy appears as `*.part` in the day folder and is
  ignored by both (scan again if a day folder was empty on first pass).
- If you retire a webapp: `docker compose down` — the backups are untouched.
