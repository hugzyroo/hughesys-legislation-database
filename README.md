# Hughesy's Legislation Database — 26 Act update-check setup

## What this package does

Preserves the 26-Act app and its original public address when deployed to the **existing** GitHub repository. Adds a GitHub Actions scheduled checker that attempts to download and parse the current consolidated versions of **only those 26 Acts** from the NT legislation portal. It creates a candidate HTML database and an import report as GitHub Actions artifacts for review. **It does not automatically publish unverified legal text.**

The `sw.js` service worker is network-first for app navigation and offline-fallback to its cached copy. After a reviewed update is deployed, reopening the app online downloads the new HTML and retains offline use. iOS may delay service worker activation; refresh/reopen online and test airplane mode.

## Upload

1. On your laptop extract this ZIP. Upload **all files and the `.github/workflows` folder** into the ROOT of your existing GitHub repository `hugzyroo/hughesys-legislation-database` on branch `main` (replace existing matching files). Do not create another Netlify project.
2. The GitHub-connected Netlify site should redeploy. Confirm `https://hughesysdatabase.netlify.app/` still opens and works offline.
3. In GitHub go to **Actions** > **Check 26 NT Acts for updates (review required)** > **Run workflow**. The scheduled checker then runs daily.
4. Open the completed workflow run, download the `legislation-review-...` artifact, and inspect `candidate_report.json` and the changed sections against official PDFs before replacing `index.html`.

## Important caveats

- This is an **experimental importer**; the official website structure and PDF extraction can change. It has NOT been end-to-end verified against all 26 official PDFs.
- It does not implement unattended automatic publication, because section parsing mistakes could create inaccurate policing reference material. Downloading candidate updates on GitHub is automatic; publishing requires review.
- The importer labels retrieved dates as retrieval dates, **not** official 'as in force' dates.
- GitHub Actions schedule may be delayed or disabled after prolonged inactivity; check Actions history.
- The official NT legislation site is authoritative. Don't use personal notes for confidential operational material; local browser storage is not synced or guaranteed permanent.
- Your app still includes its pre-existing 26 Act texts until a reviewed update is published.
