# KEPUB conversion cache

BookFlow can derive a Kobo KEPUB from a central EPUB through a local
[`kepubify`](https://github.com/pgaskin/kepubify) binary. Release images bundle
the immutable v4.0.4 asset selected for amd64 or arm64 and verify its SHA-256 at
build time. Runtime conversion still requires an absolute path, exact
`--version` response, and the SHA-256 of that same binary.

```text
KEPUBIFY_BINARY=/usr/local/bin/kepubify
KEPUBIFY_VERSION=kepubify 4.0.4
KEPUBIFY_SHA256=<architecture-specific digest recorded below>
KEPUB_CACHE_DIR=/config/kepub-cache
```

The official image sets the binary/cache defaults and reads the architecture-
specific version and checksum from immutable metadata files written during the
image build. The explicit variables above remain available for verified custom
images and local development.

The configuration adapter rejects a missing, changed, symlinked, or
version-mismatched binary. It uses an argument array rather than a shell, passes
only `LANG`, `LC_ALL`, and `TMPDIR` to the child process, and enforces a timeout.
Do not put secrets in the converter configuration.

## Cache identity and integrity

Each cache object is keyed by:

```text
(source_sha256, converter_version, options_hash)
```

The source checksum is checked before and after conversion. The output is
written to a per-key temporary file, validated as an EPUB-compatible KEPUB ZIP
container (`application/epub+zip`, `mimetype`, container document, and OPF),
then atomically renamed. A corrupt or failed result is removed. A per-key thread
and filesystem lock ensures concurrent requests run only one conversion.

When published into the central library, KEPUBs use `file_format="kepub"`, MIME
type `application/epub+zip`, and `book_files.derived_from_file_id` references
the source EPUB. The reserved SQL in
`bookflow/core/kepub_cache_schema.py` adds a matching database uniqueness
constraint during the next versioned migration.

## Release and compliance

The reviewed pins are:

| Architecture | Asset | SHA-256 |
| --- | --- | --- |
| amd64 | `kepubify-linux-64bit` | `37d7628d26c5c906f607f24b36f781f306075e7073a6fe7820a751bb60431fc5` |
| arm64 | `kepubify-linux-arm64` | `5a15b8f6f6a96216c69330601bca29638cfee50f7bf48712795cff88ae2d03a3` |

Before publishing, attach the generated image digest and SBOM to
[the KEPUB SBOM record](sbom/kepubify.md). Do not publish an image with a
placeholder pin.
