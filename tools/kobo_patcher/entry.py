"""PyInstaller entry point; kept outside the package for stable absolute imports."""

from kobo_patcher.app import main

if __name__ == "__main__":
    main()
