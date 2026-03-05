"""
Last.fm → Spotify Playlist Creator

Pulls your top tracks from Last.fm and creates corresponding playlists on Spotify.

Setup:
  1. pip install spotipy requests python-dotenv
  2. Copy .env.example to .env and fill in your API credentials
  3. Run: python lastfm_spotify_playlists.py

Spotify App Setup:
  - Create an app at https://developer.spotify.com/dashboard
  - Set redirect URI to: http://localhost:8888/callback

Last.fm API Setup:
  - Register at https://www.last.fm/api/account/create
"""

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from datetime import datetime
import time
import sys
import os

load_dotenv()

# =============================================================================
# CONFIG — Customize these values
# =============================================================================

# API Credentials (loaded from .env file)
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
LASTFM_USERNAME = os.getenv("LASTFM_USERNAME")

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "https://localhost:8888/callback")

# Playlist Settings
NUM_TRACKS = 50  # Number of tracks per playlist

# Time periods to generate playlists for.
# Options: "7day", "1month", "3month", "6month", "12month", "overall"
TIME_PERIODS = ["1month", "3month"]

# Prefix for playlist names (e.g. "Last.fm Top Tracks - Last Month")
PLAYLIST_PREFIX = "Last.fm Top Tracks"

# Set to True to make playlists public
PLAYLIST_PUBLIC = False

# Set to True to update existing playlists instead of creating duplicates
UPDATE_EXISTING = True

# =============================================================================
# CONSTANTS
# =============================================================================

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

PERIOD_LABELS = {
    "7day": "Last 7 Days",
    "1month": "Last Month",
    "3month": "Last 3 Months",
    "6month": "Last 6 Months",
    "12month": "Last 12 Months",
    "overall": "All Time",
}

SPOTIFY_SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"


# =============================================================================
# LAST.FM FUNCTIONS
# =============================================================================


def get_lastfm_top_tracks(period: str, limit: int) -> list[dict]:
    """Fetch top tracks from Last.fm for a given time period."""
    params = {
        "method": "user.gettoptracks",
        "user": LASTFM_USERNAME,
        "api_key": LASTFM_API_KEY,
        "period": period,
        "limit": limit,
        "format": "json",
    }

    print(f"  Fetching top {limit} tracks from Last.fm ({PERIOD_LABELS[period]})...")

    response = requests.get(LASTFM_API_URL, params=params)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        print(f"  Last.fm API error: {data['message']}")
        return []

    tracks = data.get("toptracks", {}).get("track", [])
    results = []
    for track in tracks:
        results.append(
            {
                "name": track["name"],
                "artist": track["artist"]["name"],
                "playcount": int(track["@attr"]["rank"]),
                "scrobbles": int(track.get("playcount", 0)),
            }
        )

    print(f"  Found {len(results)} tracks.")
    return results


# =============================================================================
# SPOTIFY FUNCTIONS
# =============================================================================


def get_spotify_client() -> spotipy.Spotify:
    """Authenticate and return a Spotify client."""
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def search_spotify_track(sp: spotipy.Spotify, track_name: str, artist: str) -> str | None:
    """Search for a track on Spotify and return its URI, or None if not found."""
    # Try exact search first
    query = f'track:"{track_name}" artist:"{artist}"'
    results = sp.search(q=query, type="track", limit=5)
    tracks = results.get("tracks", {}).get("items", [])

    if tracks:
        return tracks[0]["uri"]

    # Fallback: looser search without quotes
    query = f"{track_name} {artist}"
    results = sp.search(q=query, type="track", limit=5)
    tracks = results.get("tracks", {}).get("items", [])

    if tracks:
        # Try to match artist name loosely
        artist_lower = artist.lower()
        for t in tracks:
            for a in t["artists"]:
                if artist_lower in a["name"].lower() or a["name"].lower() in artist_lower:
                    return t["uri"]
        # If no artist match, return the top result anyway
        return tracks[0]["uri"]

    return None


def find_existing_playlist(sp: spotipy.Spotify, user_id: str, name: str) -> str | None:
    """Find an existing playlist by name. Returns playlist ID or None."""
    playlists = sp.current_user_playlists(limit=50)
    while playlists:
        for pl in playlists["items"]:
            if pl["name"] == name and pl["owner"]["id"] == user_id:
                return pl["id"]
        if playlists["next"]:
            playlists = sp.next(playlists)
        else:
            break
    return None


def create_or_update_playlist(
    sp: spotipy.Spotify, track_uris: list[str], period: str
) -> str:
    """Create a new playlist or update an existing one on Spotify."""
    user_id = sp.current_user()["id"]
    period_label = PERIOD_LABELS[period]
    playlist_name = f"{PLAYLIST_PREFIX} - {period_label}"
    description = (
        f"Top {len(track_uris)} tracks from Last.fm ({period_label}). "
        f"Updated {datetime.now().strftime('%Y-%m-%d')}."
    )

    playlist_id = None
    if UPDATE_EXISTING:
        playlist_id = find_existing_playlist(sp, user_id, playlist_name)

    if playlist_id:
        print(f"  Updating existing playlist: {playlist_name}")
        sp.playlist_change_details(
            playlist_id, description=description, public=PLAYLIST_PUBLIC
        )
        # Replace all tracks
        sp.playlist_replace_items(playlist_id, track_uris[:100])
        # If more than 100, add in batches
        for i in range(100, len(track_uris), 100):
            sp.playlist_add_items(playlist_id, track_uris[i : i + 100])
    else:
        print(f"  Creating new playlist: {playlist_name}")
        playlist = sp.user_playlist_create(
            user_id,
            playlist_name,
            public=PLAYLIST_PUBLIC,
            description=description,
        )
        playlist_id = playlist["id"]
        # Add tracks in batches of 100
        for i in range(0, len(track_uris), 100):
            sp.playlist_add_items(playlist_id, track_uris[i : i + 100])

    return playlist_id


# =============================================================================
# MAIN
# =============================================================================


def process_period(sp: spotipy.Spotify, period: str):
    """Process a single time period: fetch from Last.fm, match on Spotify, create playlist."""
    period_label = PERIOD_LABELS[period]
    print(f"\n{'='*60}")
    print(f"  Processing: {period_label}")
    print(f"{'='*60}")

    # Fetch from Last.fm
    lastfm_tracks = get_lastfm_top_tracks(period, NUM_TRACKS)
    if not lastfm_tracks:
        print("  No tracks found on Last.fm for this period. Skipping.")
        return

    # Match on Spotify
    print(f"  Searching Spotify for {len(lastfm_tracks)} tracks...")
    matched_uris = []
    not_found = []

    for i, track in enumerate(lastfm_tracks, 1):
        uri = search_spotify_track(sp, track["name"], track["artist"])
        if uri:
            matched_uris.append(uri)
        else:
            not_found.append(f"  {track['artist']} - {track['name']}")

        # Progress indicator
        if i % 10 == 0:
            print(f"    ...searched {i}/{len(lastfm_tracks)}")

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    print(f"  Matched {len(matched_uris)}/{len(lastfm_tracks)} tracks on Spotify.")

    if not_found:
        print(f"  Could not find {len(not_found)} tracks:")
        for t in not_found[:10]:  # Show first 10
            print(f"    - {t}")
        if len(not_found) > 10:
            print(f"    ... and {len(not_found) - 10} more")

    if not matched_uris:
        print("  No tracks matched on Spotify. Skipping playlist creation.")
        return

    # Create/update playlist
    playlist_id = create_or_update_playlist(sp, matched_uris, period)
    print(f"  Playlist ready! https://open.spotify.com/playlist/{playlist_id}")


def main():
    # Validate config
    missing = []
    if not LASTFM_API_KEY:
        missing.append("LASTFM_API_KEY")
    if not LASTFM_USERNAME:
        missing.append("LASTFM_USERNAME")
    if not SPOTIFY_CLIENT_ID:
        missing.append("SPOTIFY_CLIENT_ID")
    if not SPOTIFY_CLIENT_SECRET:
        missing.append("SPOTIFY_CLIENT_SECRET")
    if missing:
        print("ERROR: Missing environment variables in .env file:")
        for var in missing:
            print(f"  - {var}")
        print("\nSee .env.example for the required format.")
        sys.exit(1)

    valid_periods = set(PERIOD_LABELS.keys())
    for p in TIME_PERIODS:
        if p not in valid_periods:
            print(f"ERROR: Invalid time period '{p}'. Must be one of: {valid_periods}")
            sys.exit(1)

    print("Last.fm → Spotify Playlist Creator")
    print(f"Periods: {', '.join(PERIOD_LABELS[p] for p in TIME_PERIODS)}")
    print(f"Tracks per playlist: {NUM_TRACKS}")

    # Authenticate with Spotify (opens browser on first run)
    print("\nAuthenticating with Spotify...")
    sp = get_spotify_client()
    user = sp.current_user()
    print(f"Logged in as: {user['display_name']} ({user['id']})")

    # Process each time period
    for period in TIME_PERIODS:
        process_period(sp, period)

    print(f"\n{'='*60}")
    print("  Done! All playlists have been created/updated.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()