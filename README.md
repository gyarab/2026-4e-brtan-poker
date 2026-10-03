# 2026-4e-brtan-poker

Tento projekt je základem pro multiplayer Texas Hold'em backend v Pythonu s FastAPI, SQLite databází, autentizací a WebSocket lobby pro reálnou hru.

## Co je hotové
- Registrace a přihlášení uživatelů
- JWT autentizace
- Vytváření a připojování k herním místnostem
- Základní herní stav a přehled stolů
- WebSocket komunikace pro realtime lobby a stav stolů
- Základní poker logika pro buildování herního loopu

## Spuštění

1. Nainstalujte závislosti:
   c:/python314/python.exe -m pip install -r requirements.txt
2. Spusťte backend:
   c:/python314/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
3. Pokud už server běží, zastavte ho před novým spuštěním. V jednom projektu nesmí běžet více uvicorn instancí, protože každá má vlastní in-memory seznam místností. Pokud se z nějakého důvodu lock zůstal v .uvicorn.lock, smažte ho ručně a spusťte server znovu.
4. Otevřete aplikaci v prohlížeči:
   http://127.0.0.1:8000
5. Otevřete API dokumentaci:
   http://127.0.0.1:8000/docs

## Testy

c:/python314/python.exe -m pytest -q

## Hlavní endpointy
- POST /api/auth/register
- POST /api/auth/login
- GET /api/me
- GET /api/rooms
- POST /api/rooms
- POST /api/rooms/{room_id}/join
- POST /api/rooms/{room_id}/start
- POST /api/rooms/{room_id}/action
- WebSocket /ws?token=...

## Poznámka
Tato verze je funkční základ pro backend a reálnou hru. V následujících krocích bude rozšířena o plnou pokerovou logiku, analýzu handů, statistiky a komplexnější hráčské akce.
