# Royal House Poker

Multiplayer Texas Hold'em prototype built with FastAPI, SQLite, browser JavaScript, and WebSockets. The server owns the cards, turn order, betting rules, pots, and payouts. The interface displays only each logged-in player's private cards until showdown.

## Current features

- Email and password registration with JWT login.
- Create and join tables with 2–9 seats and configurable small blinds.
- Texas Hold'em dealing, blinds, dealer rotation, streets, and showdown.
- Fold, check, call, bet, raise, and all-in actions, including minimum raises, short all-ins, side pots, and split pots.
- A server-authoritative 20-second turn timer. On timeout the server checks when no call is due and folds when chips are owed.
- Per-player WebSocket snapshots, multiple tabs, reconnect recovery, and duplicate-action protection.
- A viewport-fitted poker table with a pinned action bar on compact screens, animated cards dealt from the deck, and saved Classic, Gold, or Midnight card faces.
- A live 1,000-run Monte Carlo estimate of win/tie/loss and expected pot share, plus an on-demand 100,000-run browser-worker simulation with progress, uncertainty, and runtime; pot odds, draw/outs hints, a labeled hypothetical implied-odds estimate, possible stronger opponent hand classes, showdown results, hand/action history, and a responsive table with card, chip, pot, and player-state animations.
- Settled hands are stored for participating players with private-card redaction, a profile/statistics dashboard, achievements, and step-by-step hand replay.
- Four table themes, saved locally per browser, plus master/effects/music controls with synthesized Web Audio cues. Ambient audio starts muted and audio playback follows browser gesture rules.
- Game chips only; the project does not process real-money gambling.

## Run the app

From the project directory, start one server instance:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/table` for the poker table, `http://127.0.0.1:8000/profile` for player statistics and hand replay, `http://127.0.0.1:8000` for the landing page, and `http://127.0.0.1:8000/docs` for the API documentation.

The server uses `poker.db` by default and keeps active table state in memory. Stop hands and tables before restarting the server; a restart clears active rooms. Do not remove `.uvicorn.lock` while the server is running. Stop the old server first, then start the new version.

Useful environment settings:

- `DATABASE_URL` selects the SQLAlchemy database URL.
- `SERVER_LOCK_PATH` selects the single-instance lock file.
- `APP_ENV=production` requires a private `SECRET_KEY` of at least 32 UTF-8 bytes.
- `SECRET_KEY` sets the JWT signing key; the development fallback is rejected in production.
- `JWT_ALGORITHM` is restricted to HS256, HS384, or HS512.
- `CORS_ORIGINS` is a comma-separated list of allowed browser origins.

## Tests

The suite uses a disposable SQLite database and lock file in a temporary directory, leaving the normal `poker.db` and a running app untouched:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

The tests cover hand ranking, turn progression, betting limits, side pots, split pots, private cards, timeout actions, WebSocket recovery, duplicate actions, hand-history privacy, PFR/all-in classification, perfect-fold privacy, profile statistics, equity/pot-odds calculations, and 1,000 randomized hands with chip/deck invariants.

## API

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/me`
- `GET /api/rooms`
- `POST /api/rooms`
- `POST /api/rooms/{room_id}/join`
- `POST /api/rooms/{room_id}/start`
- `POST /api/rooms/{room_id}/action`
- `GET /api/me/stats`
- `GET /api/me/hands?limit=30`
- `WS /ws` with `poker.v1` and `auth.<JWT>` WebSocket subprotocols. The bearer token stays out of the URL and normal access logs.

Live table equity is a 1,000-run Monte Carlo estimate; the optional browser simulation runs 100,000 samples. Both are estimates, not exact odds. Implied odds are a break-even estimate based on current equity and remaining effective stacks, not a prediction of future betting. Completed hands and profile history persist in SQLite, while live room state remains in memory and is cleared on server restart. The landing, table, and profile experience are implemented; durable live rooms, exact equity calculation, original audio assets/music, and the remaining roadmap polish are still future work.
