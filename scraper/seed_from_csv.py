#!/usr/bin/env python3
"""One-off migration: import an existing games.csv into a user's Firestore doc.

Useful for seeding your own account with the data the desktop app produced.
Covers that are already bundled under web/public/covers/<slug>.<ext> are linked
as relative paths (served same-origin); everything else scrapes remote covers
on the next refresh.

Usage:
  FIREBASE_SERVICE_ACCOUNT="$(cat service-account.json)" \
  python scraper/seed_from_csv.py <uid> [games.csv] [covers_dir]

Defaults: games.csv=./games.csv  covers_dir=./web/public/covers
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from create_game_log_all_played_lists import read_csv  # noqa: E402

from google.cloud import firestore  # noqa: E402
from google.oauth2 import service_account  # noqa: E402


def cover_for(title, covers_dir: Path):
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        if (covers_dir / f'{slug}.{ext}').exists():
            return f'covers/{slug}.{ext}'
    return ''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    uid = sys.argv[1]
    csv_path = sys.argv[2] if len(sys.argv) > 2 else 'games.csv'
    covers_dir = Path(sys.argv[3] if len(sys.argv) > 3 else 'web/public/covers')

    info = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
    creds = service_account.Credentials.from_service_account_info(info)
    client = firestore.Client(project=info['project_id'], credentials=creds)

    games = read_csv(csv_path)
    out = []
    for g in games:
        cats = [c for c in (g.get('goty_categories') or '').split(';') if c]
        out.append({
            'title': g['title'],
            'rating': g.get('rating') or 'unrated',
            'review': g.get('review') or '',
            'url': g.get('url') or '',
            'year_played': g.get('year_played') or '',
            'release_year': g.get('release_year') or '',
            'cover': cover_for(g['title'], covers_dir),
            'categories': cats,
        })

    client.document(f'users/{uid}/data/games').set(
        {'games': out, 'updatedAt': firestore.SERVER_TIMESTAMP}
    )
    print(f'Seeded {len(out)} game(s) into users/{uid}/data/games')


if __name__ == '__main__':
    main()
