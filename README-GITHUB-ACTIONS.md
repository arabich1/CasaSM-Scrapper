CSE scraper – GitHub Actions setup

What I implemented for you

- A scheduled GitHub Actions workflow in `.github/workflows/main.yml` that:
  - Triggers every weekday at 09:16 Africa/Casablanca (cron `16 8 * * 1-5` in UTC) and lets the script loop internally every 15 minutes until 16:01.
  - Sets up Python, installs dependencies from `requirements.txt`, and runs `casablanca_scraper.py` in continuous mode (no `--once`).
  - Uploads `cse_groupement.csv` as an artifact for each run (always).
  - Pushes (force-updates) a `data` branch containing only the latest CSV.
  - Creates a GitHub Issue if the job fails (so you get notified).
- `requirements.txt` with pinned dependency minima.
- The scraper (`casablanca_scraper.py`) writes new CSVs with `utf-8-sig`, removes commas from categories, and now enforces weekday-only runs between 09:16 and 16:01 (unless you manually run with `--once`).

What you need to do (manual steps I cannot perform for you)

1) Push this repository to GitHub

- Create a repository on GitHub (or pick an existing one).
- From your local repo root run (PowerShell):

```powershell
git add .
git commit -m "Add CSE scraper and GitHub Actions workflow"
# replace <user>/<repo> below with your GitHub repo URL
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

2) Enable Actions if required

- For new repos GitHub Actions is enabled automatically. If your organization has restrictions, ensure Actions are allowed for the repo.

3) Check the first run

- Go to the repository → “Actions” tab → run the workflow (there will also be an automatic weekday run).
- Open the run logs to confirm the scraper executed successfully.
- Download the artifact `cse_groupement.csv` from the run (or visit branch `data` once it's pushed).

4) TLS / certificates

- The workflow currently passes `--insecure` to avoid TLS trust issues on the Casablanca site. Remove that flag later if the upstream certificate chain stabilizes.

5) Optional: Protect the `data` branch

- If you want `data` to be write-only by the action and not accept PRs, you can protect it via Branch Protection rules. The workflow force-push currently overwrites `data` on each run.

6) Notifications (optional)

- I created issues on failure. If you prefer Slack/email, provide a webhook or SMTP details and I'll add a notifier step.

Small suggestions

- If you want to avoid commits entirely, we can drop the `data` push and rely on artifacts only, or upload CSVs to S3/Google Drive.
- To reduce noise, the workflow pushes only to `data`. The `main` branch remains clean.

If you want I can:
- Add Slack/email notifications (you'll need to provide a webhook or SMTP credentials as a secret).
- Replace issue creation with a different notifier.
- Extend the market window logic further (e.g., holiday calendar, intraday alerts).

Tell me which of these you want next and I'll implement it (or provide exact commands you can run).
