# BookFlow Kobo Patcher

This is a Windows x64 Tkinter application packaged as one `BookFlowKoboPatcher.exe`.
It has no runtime dependency outside Windows and Python's standard library (PyInstaller is used only for packaging).

The patcher only identifies a mounted volume as a Kobo when all of these existing files are present:

- `.kobo\Kobo\Kobo eReader.conf`
- `.kobo\KoboReader.sqlite`
- `.kobo\version`

It never opens the SQLite database. It changes only `api_endpoint` in `[OneStoreServices]`; ambiguous duplicate sections or endpoint lines are rejected. Before a patch, the original is preserved once as `Kobo eReader.conf.bookflow-original.backup`, and every mutating action creates another timestamped backup. Writes are staged and verified on the same volume before replacing the configuration.

`Restore from BookFlow backup` works offline. `Restore official Kobo sync` also works without a backup and changes only the endpoint to `https://storeapi.kobo.com`; it is not a factory reset.

If a write and its automatic rollback both fail, leave the Kobo connected. The
patcher reports that condition explicitly; use a BookFlow backup restore
before ejecting the device.

## Build on Windows

Use Python 3.12 on Windows x64:

```powershell
cd tools\kobo_patcher
.\build.ps1
```

The command refuses a non-64-bit interpreter and places the EXE, a SHA-256 file
and an SPDX SBOM in `dist`. The tagged GitHub workflow checks that the archive
contains Python 3.12 and Tkinter, verifies the checksum/SBOM and, when signing
secrets are configured, verifies the Authenticode signature before publishing.
An unsigned local build is suitable for development only.

The generated generic EXE asks users to paste an `SM1.<payload>.<signature>` pairing code. The code carries the BookFlow origin but no token. The server validates the signature and code freshness during the claim/complete exchange.
