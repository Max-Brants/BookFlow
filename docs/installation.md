# Installation

BookFlow is typically deployed with Docker Compose.

## Quick Start

1. Download the compose file from this project, then create a local `.env` file
   with the exact immutable image digest you intend to run:

```bash
curl -O https://raw.githubusercontent.com/Timminater/BookFlow/main/compose/docker-compose.yml
printf '%s\n' 'BOOKFLOW_IMAGE=ghcr.io/timminater/bookflow@sha256:<published-release-digest>' > .env
```

   Replace `<published-release-digest>` with the full digest of a reviewed
   release. The compose file deliberately has no image default, so Docker
   Compose fails before starting if this variable is absent.

2. Validate and start the service:

```bash
docker compose config
docker compose up -d
```

3. Open `http://localhost:8084`

4. Configure the sources, metadata providers, and delivery settings you want to use

## Next Steps

- For volume and path setup, see [Directory and Volume Setup](configuration.md)
- For environment-based setup, see [Environment Variables](environment-variables.md)
- For authentication and user management, see [Users & Requests](users-and-requests.md) and [OIDC](oidc.md)
- For Unraid deployment, backups, rollback, and secret rotation, see [Deployment Operations](deployment.md)

## Notes

- Universal search is the default mode for new installs
- Direct Download is optional and must be enabled and configured before it can be used
- Torrent and usenet setups require matching download paths between BookFlow and your download client
