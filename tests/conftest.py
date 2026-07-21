"""
Shared fixtures: synthetic Instagram and Flickr exports built in code.

Why built rather than committed: the media pipeline genuinely decodes what it
is given (PIL opens every image, cv2 opens every video), so fixtures must be
real files — and generating them keeps personal data out of the repo. The one
committed binary is fixtures/tiny.mp4, which cv2 must be able to read a frame
from.

Every builder writes into a tmp_path the caller owns. That is not tidiness:
folder-mode Instagram extraction rewrites the export in place (media.py's
fix_file_extensions copies mis-labelled files next to the originals) and the
Flickr importer writes flickr_exclude.json / flickr_dedup_report.json /
originals-cache/ into its *input* directory. Fixtures are inputs and outputs
at once, so no test may share one.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# A fixed instant so date-derived output (day headers, month keys, the
# "%B %d, %Y" strings) is stable across runs. 2024-03-15 12:00:00 UTC.
BASE_TS = 1710504000


# --------------------------------------------------------------------------
# media helpers
# --------------------------------------------------------------------------

def write_jpeg(path, size=(64, 48), color=(200, 30, 30)):
    """A genuine, decodable JPEG. Tiny, but real."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=60)
    return path


def write_two_tone_jpeg(path, exif_orientation=None, size=(64, 32)):
    """
    A landscape image split down the middle: left half red, right half blue.

    Orientation is the point. With EXIF orientation 6 (rotate 90 CW) a correct
    pipeline transposes it to portrait with red on TOP; applying the
    correction twice (the historical double-rotation bug) puts red elsewhere.

    The halves are large blocks rather than single pixels deliberately — the
    pipeline re-encodes to lossy WebP, and a 2x1 fixture came back as muddy
    magenta, testing the codec rather than the rotation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    img = Image.new("RGB", size, (255, 0, 0))
    for x in range(w // 2, w):
        for y in range(h):
            img.putpixel((x, y), (0, 0, 255))
    if exif_orientation is not None:
        exif = img.getexif()
        exif[0x0112] = exif_orientation
        img.save(path, "JPEG", quality=95, exif=exif)
    else:
        img.save(path, "JPEG", quality=95)
    return path


def copy_tiny_video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE_DIR / "tiny.mp4", path)
    return path


# --------------------------------------------------------------------------
# Instagram export builder
# --------------------------------------------------------------------------

def _classic_post(uri, ts, title="", extra_media=None, exif=None):
    """One entry of the classic posts_1.json list format."""
    media = [{
        "uri": uri,
        "creation_timestamp": ts,
        "title": "",
        "media_metadata": {},
    }]
    if exif:
        media[0]["media_metadata"] = {
            "photo_metadata": {"exif_data": [exif]}
        }
    for extra in extra_media or []:
        media.append({
            "uri": extra, "creation_timestamp": ts,
            "title": "", "media_metadata": {},
        })
    return {"media": media, "title": title, "creation_timestamp": ts}


def _newer_place_post(ts, name, lat, lng):
    """
    A newer-format posts.json entry carrying place + coordinates.

    Place lives under label_values[title="Place"].dict[0].dict as a
    {label: "Name"} field; latitude/longitude are flat sibling labels. The
    loader matches these onto classic entries by timestamp within +/-1s, so
    callers deliberately pass a ts one second off to exercise that tolerance.
    """
    return {
        "timestamp": ts,
        "media": [],
        "label_values": [
            {"title": "Place", "dict": [{"dict": [
                {"label": "Name", "value": name},
            ]}]},
            {"label": "Latitude", "value": str(lat)},
            {"label": "Longitude", "value": str(lng)},
        ],
    }


def make_instagram_export(
    root,
    username="testuser",
    bio="A test bio",
    website="https://example.com",
    with_stories=True,
    with_video=True,
    with_place=True,
    with_exif_coords=True,
    extra_posts=(),
):
    """
    Build a minimal-but-representative Instagram export folder.

    Returns a dict of the timestamps it planted so tests can assert on
    specific entries without recomputing the arithmetic.
    """
    root = Path(root)
    media_dir = root / "media"
    posts_media = media_dir / "posts"

    ts = {
        "single": BASE_TS,
        "carousel": BASE_TS - 3600,
        "video": BASE_TS - 7200,
        "no_title": BASE_TS - 10800,
        "exif": BASE_TS - 14400,
        "story": BASE_TS - 1800,
        "story_video": BASE_TS - 5400,
    }

    posts = []

    # 1. plain single-image post, with a caption that needs ftfy repair
    #    ("Cafe" mojibake) and an HTML entity to unescape
    write_jpeg(posts_media / "single.jpg", color=(200, 30, 30))
    posts.append(_classic_post(
        "media/posts/single.jpg", ts["single"],
        title="CafÃ© &amp; croissants",
    ))

    # 2. carousel: three media on one post
    for i in range(3):
        write_jpeg(posts_media / f"carousel_{i}.jpg", color=(30, 30 + i * 60, 200))
    posts.append(_classic_post(
        "media/posts/carousel_0.jpg", ts["carousel"], title="Three of them",
        extra_media=["media/posts/carousel_1.jpg", "media/posts/carousel_2.jpg"],
    ))

    # 3. video post
    if with_video:
        copy_tiny_video(posts_media / "clip.mp4")
        posts.append(_classic_post("media/posts/clip.mp4", ts["video"], title="Moving"))

    # 4. untitled post — title falls back to media[0].title (also empty),
    #    so `tt` stays empty and _compact_entries should drop it
    write_jpeg(posts_media / "untitled.jpg", color=(20, 160, 20))
    posts.append(_classic_post("media/posts/untitled.jpg", ts["no_title"]))

    # 5. post whose coordinates come only from EXIF (the classic fallback,
    #    distinct from the newer-format meta map)
    if with_exif_coords:
        write_jpeg(posts_media / "exif.jpg", color=(160, 160, 20))
        posts.append(_classic_post(
            "media/posts/exif.jpg", ts["exif"], title="From exif",
            exif={"latitude": 51.5174266, "longitude": -0.1437195},
        ))

    for extra in extra_posts:
        posts.append(extra)

    (media_dir).mkdir(parents=True, exist_ok=True)
    (media_dir / "posts_1.json").write_text(json.dumps(posts), encoding="utf-8")

    # Newer-format file: place/coords only. Deliberately one second later
    # than the classic entry, to exercise the +/-1s matching tolerance.
    if with_place:
        (media_dir / "posts.json").write_text(json.dumps([
            _newer_place_post(ts["single"] + 1, "Porto, Portugal", 41.1500, -8.6167),
        ]), encoding="utf-8")

    # Stories: note the {"ig_stories": [...]} wrapper, and that a story is
    # only kept when it has BOTH a timestamp and a media uri.
    if with_stories:
        stories = []
        write_jpeg(media_dir / "stories" / "story1.jpg", color=(120, 40, 160))
        stories.append({
            "uri": "media/stories/story1.jpg",
            "creation_timestamp": ts["story"],
            "title": "A story",
            "media_metadata": {},
        })
        copy_tiny_video(media_dir / "stories" / "story2.mp4")
        stories.append({
            "uri": "media/stories/story2.mp4",
            "creation_timestamp": ts["story_video"],
            "title": "",
            "media_metadata": {},
        })
        (media_dir / "stories.json").write_text(
            json.dumps({"ig_stories": stories}), encoding="utf-8")

    # Profile. Both string_map_data AND media_map_data must exist — the
    # loader subscripts them directly and falls back to "Unknown" on any
    # exception, which would quietly weaken every downstream assertion.
    profile_dir = root / "personal_information"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "personal_information.json").write_text(json.dumps({
        "profile_user": [{
            "string_map_data": {
                "Username": {"value": username},
                "Name": {"value": "Test User"},
                "Bio": {"value": bio},
                "Website": {"value": website},
            },
            "media_map_data": {},
        }]
    }), encoding="utf-8")

    # Primary location: the classic inferred_data_primary_location shape.
    loc_dir = profile_dir / "information_about_you"
    loc_dir.mkdir(parents=True, exist_ok=True)
    (loc_dir / "profile_based_in.json").write_text(json.dumps({
        "inferred_data_primary_location": [{
            "string_map_data": {"Town/city name": {"value": "London"}}
        }]
    }), encoding="utf-8")

    return ts


# --------------------------------------------------------------------------
# Flickr export builder
# --------------------------------------------------------------------------

def _photo_json(pid, taken, privacy="public", name="", description="",
                tags=(), albums=(), geo=None, rotation=0, license_="",
                imported=None, ext="jpg"):
    """One flickr_metadata/photo_<id>.json record."""
    doc = {
        "id": str(pid),
        "name": name,
        "description": description,
        "date_taken": taken,
        "date_imported": str(imported if imported is not None else 0),
        "privacy": privacy,
        "rotation": rotation,
        "license": license_,
        "original": f"https://live.staticflickr.com/1/{pid}_abcdef0123_o.{ext}",
        "photopage": f"https://www.flickr.com/photos/tester/{pid}/",
        "tags": [{"tag": t} for t in tags],
        "albums": [{"id": str(a), "title": "", "url": ""} for a in albums],
        "geo": [],
    }
    if geo:
        lat, lng = geo
        # Flickr stores degrees x 1,000,000 as integer strings.
        doc["geo"] = [{
            "latitude": str(int(round(lat * 1_000_000))),
            "longitude": str(int(round(lng * 1_000_000))),
            "accuracy": "16",
        }]
    return doc


def make_flickr_export(root, with_media=True, with_zip=True, exclude_ids=(),
                       otd_date=None):
    """
    Build a Flickr export: metadata for public + non-public items, albums,
    account profile, and local media in both a folder and a zip part.

    Returns a dict describing the planted ids so tests can assert precisely.
    """
    root = Path(root)
    meta = root / "flickr_metadata"
    meta.mkdir(parents=True, exist_ok=True)

    # Realistic 11-digit ids. Length matters: the untitled-filename pattern
    # is `^(\d{6,})_<10 hex>_o\.<ext>$`, so short toy ids silently fail to
    # match and the item imports with no media.
    ids = {
        "plain": 51000000001,
        "geo": 51000000002,
        "collide_a": 51000000003,   # shares a date_taken second with collide_b
        "collide_b": 51000000004,
        "rotated": 51000000005,     # EXIF orientation, no metadata rotation
        "video": 51000000006,
        "zipped": 51000000007,      # media lives only inside a data-download zip
        "untitled": 51000000008,    # untitled-style filename pattern
        "private": 51000000009,     # must never reach the output
        "friends": 51000000010,     # must never reach the output
    }
    taken = "2018-06-01 10:00:00"
    collide_taken = "2018-06-02 11:22:33"
    # Callers testing "On this day" pass a date on today's calendar day in a
    # previous year, so the view always has a Flickr memory to show.
    plain_taken = otd_date or taken

    records = {
        ids["plain"]: _photo_json(
            ids["plain"], plain_taken, name="A plain photo",
            description="Line one<br>Line two <a href=\"https://example.com\">link</a>",
            tags=["holiday", "beach"], albums=[7001], license_="All Rights Reserved",
        ),
        ids["geo"]: _photo_json(
            ids["geo"], "2018-06-03 09:00:00", name="Geotagged",
            geo=(22.285000, 114.152166), tags=["hongkong"], albums=[7001],
            license_="Attribution License",
        ),
        # Two items in the SAME second: the reason entries are keyed by photo
        # id rather than timestamp. A ts-keyed dict silently drops one.
        ids["collide_a"]: _photo_json(ids["collide_a"], collide_taken, name="Collide A"),
        ids["collide_b"]: _photo_json(ids["collide_b"], collide_taken, name="Collide B"),
        ids["rotated"]: _photo_json(ids["rotated"], "2018-06-04 08:00:00", name="Rotated"),
        ids["video"]: _photo_json(
            ids["video"], "2018-06-05 07:00:00", name="A video", ext="mp4"),
        ids["zipped"]: _photo_json(ids["zipped"], "2018-06-06 06:00:00", name="Zipped"),
        ids["untitled"]: _photo_json(ids["untitled"], "2018-06-07 05:00:00"),
        ids["private"]: _photo_json(
            ids["private"], "2018-06-08 04:00:00", privacy="private",
            name="SECRETPRIVATE"),
        ids["friends"]: _photo_json(
            ids["friends"], "2018-06-09 03:00:00", privacy="friends & family",
            name="SECRETFRIENDS"),
    }
    for pid, doc in records.items():
        (meta / f"photo_{pid}.json").write_text(json.dumps(doc), encoding="utf-8")

    # Albums: one real, one synthetic "not in an album" that must be skipped.
    (meta / "albums.json").write_text(json.dumps({"albums": [
        {"id": "7001", "title": "Summer", "description": "",
         "photo_count": "2", "url": "", "photos": ""},
        {"id": "7002", "title": "not in an album 1", "description": "",
         "photo_count": "0", "url": "", "photos": ""},
    ]}), encoding="utf-8")

    (meta / "account_profile.json").write_text(json.dumps({
        "nsid": "12345678@N01",
        "path_alias": "tester",
        "screen_name": "tester",
        "real_name": "Test Person",
        "description": "Flickr bio text",
        "website_url": "https://flickr.example.com",
    }), encoding="utf-8")

    if with_media:
        part = root / "data-download-1"
        # titled pattern: <slug>_<id>_o.<ext>
        write_jpeg(part / f"a-plain-photo_{ids['plain']}_o.jpg")
        write_jpeg(part / f"geotagged_{ids['geo']}_o.jpg")
        write_jpeg(part / f"collide-a_{ids['collide_a']}_o.jpg")
        write_jpeg(part / f"collide-b_{ids['collide_b']}_o.jpg")
        # EXIF orientation 6 == rotate 90 CW; metadata rotation stays 0, so
        # exactly one correction should apply.
        write_two_tone_jpeg(part / f"rotated_{ids['rotated']}_o.jpg",
                            exif_orientation=6)
        # video pattern: <slug>_<id>.<ext>, no _o
        copy_tiny_video(part / f"a-video_{ids['video']}.mp4")
        # untitled pattern: ^<id>_<10 hex>_o.<ext>
        write_jpeg(part / f"{ids['untitled']}_0123456789_o.jpg")

    if with_zip:
        # A real zip part, left un-extracted exactly as Flickr serves it.
        staging = root / "_ziptmp" / "data-download-2"
        write_jpeg(staging / f"zipped_{ids['zipped']}_o.jpg")
        shutil.make_archive(str(root / "data-download-2"), "zip",
                            root_dir=str(root / "_ziptmp"))
        shutil.rmtree(root / "_ziptmp")

    if exclude_ids:
        (root / "flickr_exclude.json").write_text(json.dumps({
            "exclude": {str(i): "test fixture exclusion" for i in exclude_ids}
        }), encoding="utf-8")

    return {"ids": ids, "taken": taken, "collide_taken": collide_taken}


def write_api_cache(root, video_ids=(), photo_ids=()):
    """
    Write a flickr_api_cache.json so video identification can be tested with
    no network at all. Shape mirrors what FlickrAPIClient.sweep() writes.
    """
    photos = {}
    for pid in photo_ids:
        photos[str(pid)] = {"media": "photo", "w": 640, "h": 480}
    for pid in video_ids:
        photos[str(pid)] = {
            "media": "video", "w": 640, "h": 480,
            "video_url": f"https://live.staticflickr.com/video/{pid}/x/700.mp4",
        }
    (Path(root) / "flickr_api_cache.json").write_text(json.dumps({
        "swept_at": "2024-01-01",
        "nsid": "12345678@N01",
        "photos": photos,
    }), encoding="utf-8")


# --------------------------------------------------------------------------
# pytest fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def ig_export(tmp_path):
    root = tmp_path / "ig-export"
    root.mkdir()
    ts = make_instagram_export(root)
    return {"path": root, "ts": ts}


@pytest.fixture
def flickr_export(tmp_path):
    root = tmp_path / "flickr-download"
    root.mkdir()
    info = make_flickr_export(root)
    write_api_cache(root, video_ids=[info["ids"]["video"]])
    info["path"] = root
    return info


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def run_cli(monkeypatch):
    """
    Drive cli.main() in-process with a synthetic argv.

    In-process rather than subprocess so failures surface as real tracebacks
    and coverage sees the code. main() reads sys.argv directly and returns an
    exit code.
    """
    from memento_mori import cli

    def _run(*args):
        argv = ["memento-mori"] + [str(a) for a in args]
        monkeypatch.setattr(sys, "argv", argv)
        return cli.main()

    return _run


@pytest.fixture(autouse=True)
def _no_flickr_api_key(monkeypatch):
    """
    Guarantee the suite never reaches the Flickr API by accident. Tests that
    want a key present set it themselves (and assert it does not leak into
    the output).
    """
    monkeypatch.delenv("FLICKR_API_KEY", raising=False)
