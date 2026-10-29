# Running SilverFile with Docker

The step-by-step guide for graders is in the [README](../README.md#running-silverfile-with-docker-for-graders). This page has the other commands and troubleshooting.

One image runs everything (`Dockerfile`). `docker-compose.yml` starts the tax_math MCP server (`tax-math`) and
the staff dashboard, and runs `run.py`, the evals and the tests on demand (`app`).

| Task | Command |
|---|---|
| Staff dashboard | http://127.0.0.1:8000 (published on this machine only) |
| Evals (through tax-math) | `docker compose run --rm app python -m evals.run_evals` |
| Evals, tax math in-process | `docker compose run --rm -e TAX_MATH_MCP_URL= app python -m evals.run_evals` |
| Tests | `docker compose run --rm app python -m pytest -q -p no:cacheprovider` |
| Taxpayer session (needs the key) | `docker compose run --rm app python run.py --case data/fixtures/skeleton_case.json` |
| Resume a session | `docker compose run --rm app python run.py --thread-id <session id>` |
| List sessions | `docker compose run --rm app python run.py --sessions` |
| Logs | `docker compose logs -f dashboard tax-math` |
| Stop (keeps sessions) | `docker compose down` |
| Stop and delete all sessions | `docker compose down -v` |

## Demo dashboard

The demo uses the same port, so stop the normal dashboard first:

```bash
docker compose stop dashboard
docker compose run --rm --service-ports dashboard python -m src.dashboard --demo --host 0.0.0.0
# Ctrl-C to stop it, then: docker compose start dashboard
```

Without Docker: `python -m src.dashboard --demo`.

**What persists.** Sessions live in `/app/state/silverfile.sqlite` on the `state` volume, which `app` and the
dashboard share. The demo database, its case files and HTML drafts (`run.py --html output/draft.html`) live
in `/app/output` on the `output` volume. Both survive `docker compose down` and are deleted only by
`down -v`. `data/` (policy.md, fixtures) comes from the image and is never a volume.

**Restart check, no key needed:**

1. Start the demo dashboard (above). It prints `Demo database: /app/output/demo.sqlite (9 new returns)`.
2. Open http://127.0.0.1:8000, open *demo-wage-conflict*, enter a staff ID and choose Continue.
3. Ctrl-C, then `docker compose down` (no `-v`) and `docker compose up -d`.
4. Start the demo again: it prints `(0 new returns)`, and *demo-wage-conflict* shows your decision under
   "Decisions so far".

With a key, the same works for a taxpayer session: start one with `run.py --case ...`, note the session id,
press Ctrl-D (the session is saved), `down`, `up -d`, then `run.py --thread-id <session id>`.

**Notes.**

- `.env` is read at run time (`env_file`) and never copied into the image (`.dockerignore`). Compose sets
  `TAX_MATH_MCP_URL=http://tax-math:8001/mcp` and the database path itself, overriding the `localhost` and
  `data/` values in `.env`, which are for running outside Docker.
- Port 8001 is not published: only the containers reach tax-math.
- `constraints.txt` pins the image to the exact versions we tested (`pip install -r requirements.txt -c
  constraints.txt`). After changing `requirements.txt`, regenerate it inside the container, not on your Mac
  (some packages differ by platform): `docker compose build`, then
  `docker compose run --rm --no-deps -T app pip freeze > constraints.txt` (`-T`: without it the TTY adds `\r` to every line).
- The code in the image is read-only to the app (it runs as user `silverfile`, uid 1000); only `/app/state`
  and `/app/output` are writable. To run your own case file, mount it read-only, for example
  `docker compose run --rm -v "$PWD/cases:/app/cases:ro" app python run.py --case cases/mine.json`, and mount it
  again at the same path to resume.
- If run.py or the dashboard says the tax_math server is unreachable, check `docker compose ps`: tax-math
  should be `healthy`. A `421 Invalid Host header` means it is listening on 127.0.0.1 instead of 0.0.0.0.
- Port 8000 already in use (a local dashboard, say): stop that, or change `127.0.0.1:8000:8000` to
  `127.0.0.1:8080:8000` and open http://127.0.0.1:8080.
