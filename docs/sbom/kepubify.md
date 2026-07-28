# kepubify SBOM and notice record

`kepubify` is bundled in release images from an immutable GitHub release asset.
It is never downloaded or updated at runtime.

| Field | Required release value |
| --- | --- |
| Component | `kepubify` |
| Upstream | <https://github.com/pgaskin/kepubify> |
| License | MIT |
| Exact version | `v4.0.4` (`kepubify 4.0.4`) |
| amd64 SHA-256 | `37d7628d26c5c906f607f24b36f781f306075e7073a6fe7820a751bb60431fc5` |
| arm64 SHA-256 | `5a15b8f6f6a96216c69330601bca29638cfee50f7bf48712795cff88ae2d03a3` |
| Source artifacts | `https://github.com/pgaskin/kepubify/releases/download/v4.0.4/kepubify-linux-64bit` and `kepubify-linux-arm64` |
| Container image digest | Supplied by the release workflow provenance/SBOM artifact |
| License text | [`licenses/kepubify-LICENSE-v4.0.4.txt`](licenses/kepubify-LICENSE-v4.0.4.txt) |

## MIT notice

Copyright and license notices for `kepubify` remain with Patrick Gaskin. The
verbatim MIT license from tag v4.0.4 is retained alongside this record.

## SBOM rule

The release pipeline must emit an SPDX or CycloneDX component containing the
exact version and SHA-256 above. `NOASSERTION`, `latest`, a mutable tag, and a
placeholder checksum are not acceptable for a shipped image.
