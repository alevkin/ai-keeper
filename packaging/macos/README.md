# macOS Packaging Notes

AI Keeper currently installs as a user LaunchAgent:

- label: `com.aikeeper.daemon`
- default dashboard: `http://127.0.0.1:8766`
- default app home: `~/.aikeeper`

Future DMG packaging should wrap the existing scripts instead of duplicating
install logic:

1. Run preflight checks for `uv`, `git`, and `launchctl`.
2. Run `scripts/install.sh --port 8766`.
3. Show `scripts/rollback.sh` as the recovery path.

Do not package local data files. The SQLite database and logs remain in the
user-controlled `AIKEEPER_HOME`.
