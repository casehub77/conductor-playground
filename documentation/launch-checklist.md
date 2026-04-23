# Launch Checklist

1. Run a full rebuild:

   ```bash
   python3 scripts/update_data.py --mode full --allow-fallback
   ```

2. Confirm validation passes in `data/processed/validation_report.json`.
3. Inspect `data/processed/ingestion_report.json` for stale-source warnings.
4. Review top 25 rankings in every active division.
5. Review current champions and fix labels in `overrides/champion_overrides.csv`.
6. Review obvious name duplicates and fix in `overrides/fighter_aliases.csv`.
7. Add verified Instagram handles for high-traffic fighters in `overrides/instagram_handles.csv`.
8. Start a local server and inspect homepage, fighter pages, rankings, and champions pages.
9. Enable GitHub Pages from the `docs/` folder.
10. Run the GitHub Actions refresh workflow manually.
11. Add real ad code by replacing `.ad-slot` placeholders.

