# memento_mori/cli.py

import os
import json
import argparse
import multiprocessing
from pathlib import Path
import traceback
import sys

from memento_mori.extractor import InstagramArchiveExtractor
from memento_mori.loader import InstagramDataLoader
from memento_mori.media import InstagramMediaProcessor
from memento_mori.generator import InstagramSiteGenerator
from memento_mori import merger


def _import_flickr_source(args, output_dir, ig_posts):
    """
    Run the Flickr import and return its `sources.flickr` section.

    ig_posts supplies the timestamps used to detect Instagram cross-posts;
    an empty dict (a Flickr-only site) makes the dedup pass a no-op.
    """
    from memento_mori.flickr import import_flickr
    print(f"\n📷 IMPORTING FLICKR from {args.flickr}")
    return import_flickr(
        args.flickr, output_dir,
        ig_timestamps=list(ig_posts.keys()),
        thread_count=args.threads,
        quality=args.quality,
        max_dimension=args.max_dimension,
        api_key=os.environ.get("FLICKR_API_KEY"),
        refresh=args.flickr_refresh,
        verbose=args.verbose,
    )


def _describe_sources(sources):
    """One-line summary of what a package holds, for the run banner."""
    parts = []
    instagram = sources.get("instagram") or {}
    if instagram:
        parts.append(f"{len(instagram.get('posts') or {})} posts, "
                     f"{len(instagram.get('stories') or {})} stories")
    flickr = sources.get("flickr") or {}
    if flickr:
        parts.append(f"{len(flickr.get('items') or {})} Flickr items")
    for key, section in sources.items():
        if key not in ("instagram", "flickr"):
            parts.append(f"{key} source")
    return "; ".join(parts) or "no sources"


def _check_fresh_would_not_clobber(output_dir, providing):
    """
    Refuse a fresh build that would drop sources an existing site has.

    A fresh run rebuilds data.json from only what it was given. Before this
    guard, running an Instagram-only build over a combined site silently
    dropped the whole Flickr section from the sidecar — the site kept its
    pages until the next regenerate, then lost them. Fresh over an existing
    site is allowed only when it re-provides everything already there.

    Returns True when it is safe to continue.
    """
    sidecar_path = Path(output_dir) / "data.json"
    if not sidecar_path.exists():
        return True
    try:
        with open(sidecar_path, encoding="utf-8") as f:
            existing = merger.migrate_sidecar(json.load(f))
    except (OSError, json.JSONDecodeError):
        return True          # unreadable sidecar: nothing to protect
    have = {k for k, v in (existing.get("sources") or {}).items() if v}
    dropped = have - set(providing)
    if not dropped:
        return True
    print(f"Error: {sidecar_path} already contains: {', '.join(sorted(dropped))}.")
    print("   A fresh run rebuilds the site from only what it is given, so "
          "that data would be lost.")
    print("   Use --merge --input <archive> to add a newer Instagram export,")
    print("   or --regenerate --flickr <path> to add or refresh Flickr,")
    print(f"   or delete {sidecar_path} to start over deliberately.")
    return False


def main():
    """Main entry point for the Memento Mori CLI."""
    parser = argparse.ArgumentParser(
        description="Transform Instagram data export into a viewer."
    )

    parser.add_argument(
        "--input",
        type=str,
        help="Path to Instagram data (ZIP or folder). If not specified, auto-detection will be used.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output",
        help="Output directory for generated website [default: ./output]",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="Number of parallel processing threads [default: auto]",
    )
    parser.add_argument(
        "--search-dir",
        type=str,
        default=".",
        help="Directory to search for Instagram exports when auto-detecting [default: current directory]",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=70,
        help="WebP conversion quality (1-100) [default: 70]",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=1920,
        help="Maximum dimension for images in pixels [default: 1920]",
    )
    parser.add_argument(
        "--thumbnail-size",
        type=str,
        default="292x292",
        help="Size of thumbnails [default: 292x292]",
    )
    parser.add_argument(
        "--no-auto-detect",
        action="store_true",
        help="Disable auto-detection (requires --input to be specified)",
    )
    parser.add_argument(
        "--gtag-id",
        type=str,
        help="Google Analytics tag ID (e.g., 'G-DX1ZWTC9NZ') to add tracking to the generated site",
    )
    parser.add_argument(
        "--theme",
        type=str,
        help="Path to a theme directory whose templates/ shadow the default "
             "templates and whose static/ is overlaid on the default CSS/JS/"
             "vendor assets. Lets a site customise look and markup without "
             "editing the generator. Applies to fresh, --merge and "
             "--regenerate builds alike.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge a newer export (--input) into an existing generated site in --output",
    )
    parser.add_argument(
        "--city-tags",
        type=str,
        help="Path to city tags JSON exported from the editor [default: <output>/city_tags.json]",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Re-render the site HTML from the existing output's data.json; "
             "skips archive extraction and media processing entirely",
    )
    parser.add_argument(
        "--flickr",
        type=str,
        help="Path to a Flickr data export folder to import as a separate "
             "section (combinable with --regenerate to add Flickr to an "
             "already-generated site)",
    )
    parser.add_argument(
        "--flickr-refresh",
        action="store_true",
        help="Re-run the Flickr API metadata sweep and retry previously "
             "failed media downloads",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output for debugging",
    )

    args = parser.parse_args()

    # Set defaults for threads if not specified
    if args.threads <= 0:
        args.threads = max(1, multiprocessing.cpu_count() - 1)

    # Parse thumbnail size
    try:
        if "x" in args.thumbnail_size:
            width, height = map(int, args.thumbnail_size.lower().split("x"))
            thumbnail_size = (width, height)
        else:
            size = int(args.thumbnail_size)
            thumbnail_size = (size, size)
    except ValueError:
        print(f"Invalid thumbnail size: {args.thumbnail_size}, using default 292x292")
        thumbnail_size = (292, 292)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load city tags if a tags file exists (used by all modes)
    city_tags_path = Path(args.city_tags) if args.city_tags else output_dir / "city_tags.json"
    city_tags = None
    if city_tags_path.exists():
        try:
            with open(city_tags_path, "r", encoding="utf-8") as f:
                raw_tags = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error reading city tags file {city_tags_path}: {e}")
            return 1
        raw_favorites = raw_tags.get("favorites", {}) or {}
        city_tags = {
            "version": raw_tags.get("version", 1),
            "posts": raw_tags.get("posts", {}) or {},
            "stories": raw_tags.get("stories", {}) or {},
            # Flickr tags are keyed by photo id, not timestamp
            "flickr": raw_tags.get("flickr", {}) or {},
            "cities": raw_tags.get("cities", {}) or {},
            # Tri-state: absent (None) means "no override — use the
            # Instagram profile bio"; present (even "") is authoritative
            "bio": raw_tags["bio"] if "bio" in raw_tags else None,
            "favorites": {
                "posts": raw_favorites.get("posts", {}) or {},
                "stories": raw_favorites.get("stories", {}) or {},
                "flickr": raw_favorites.get("flickr", {}) or {},
            },
        }
        favorite_count = sum(
            len(v) for v in city_tags["favorites"].values()
        )
        print(f"Loaded city tags: {len(city_tags['posts'])} posts, "
              f"{len(city_tags['stories'])} stories, "
              f"{len(city_tags['flickr'])} flickr, "
              f"{favorite_count} favorites "
              f"from {city_tags_path}")
    elif args.city_tags:
        print(f"Error: --city-tags file not found: {args.city_tags}")
        return 1

    # Regenerate mode: re-render HTML from the existing site's data.json
    # without touching an archive — the fast path for tag iteration
    if args.regenerate:
        if args.merge or args.input:
            print("Error: --regenerate cannot be combined with --merge or --input.")
            return 1
        sidecar_path = output_dir / "data.json"
        if not sidecar_path.exists():
            print(f"Error: --regenerate requires {sidecar_path} (generate a site first).")
            return 1
        with open(sidecar_path, "r", encoding="utf-8") as f:
            raw_sidecar = json.load(f)
        # v1 sidecars are converted in memory; keep the original aside once
        # before the v2 write replaces it.
        if "sources" not in raw_sidecar:
            merger.backup_v1_sidecar(output_dir)
        sidecar = merger.migrate_sidecar(raw_sidecar)
        sources = sidecar.get("sources") or {}

        # Flickr: re-import when --flickr is given (the way to add Flickr to
        # an existing site), else the sidecar's section carries forward as-is
        if args.flickr:
            ig_posts = (sources.get("instagram") or {}).get("posts") or {}
            sources["flickr"] = _import_flickr_source(args, output_dir, ig_posts)

        data = {
            "schema_version": merger.SCHEMA_VERSION,
            "location": sidecar.get("location") or {"location": "Unknown"},
            "sources": sources,
            "city_tags": city_tags,
        }
        if not args.gtag_id:
            args.gtag_id = (sidecar.get("settings") or {}).get("gtag_id")
        print(f"\n♻️  REGENERATE MODE")
        print(f"   {_describe_sources(sources)} from {sidecar_path}")
        generator = InstagramSiteGenerator(data, output_dir, gtag_id=args.gtag_id, theme_dir=args.theme)
        if generator.generate():
            print("\n✅ PROCESS COMPLETE")
            print(f"   Website regenerated at: {output_dir}")
            return 0
        print("\n❌ ERROR: Failed to regenerate website.")
        return 1

    # In merge mode, load the existing site's data before doing any
    # expensive work, and require an explicit input (auto-detect could pick
    # an archive that is already part of the site)
    existing = None
    if args.merge:
        if not args.input:
            print("Error: --merge requires --input pointing to the new archive.")
            return 1
        try:
            existing = merger.load_existing_site_data(output_dir, verbose=args.verbose)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return 1
        print(f"\n🔀 MERGE MODE")
        print(f"   Existing site: {output_dir} ({len(existing['posts'])} posts, "
              f"{len(existing['stories'])} stories, from {existing['source']})")
        if existing["source"] == "html" and not args.gtag_id:
            print("   Note: existing site has no data.json; if it used --gtag-id, pass it again.")

    # Initialize extractor with input path if specified
    extractor = InstagramArchiveExtractor(input_path=args.input)

    # Handle input selection. Instagram is optional now: a run needs at
    # least one source, and --flickr on its own is a complete site.
    have_instagram = False
    if args.input:
        print(f"Using specified input: {args.input}")
        have_instagram = True
    elif not args.no_auto_detect:
        print(f"Auto-detecting Instagram archive in {args.search_dir}...")
        detected_archive = extractor.auto_detect_archive(search_dir=args.search_dir)
        if detected_archive:
            print(f"Detected archive: {detected_archive}")
            have_instagram = True
        elif not args.flickr:
            print("No Instagram archive detected. Specify one with --input,")
            print("or pass --flickr <export> to build a Flickr-only site.")
            return 1
    elif not args.flickr:
        print("Error: No input specified and auto-detection is disabled.")
        print("Please provide an input path with --input,")
        print("or pass --flickr <export> to build a Flickr-only site.")
        return 1

    # Flickr-only: no Instagram archive to extract or process, so skip
    # straight to importing Flickr and generating. (Pair --flickr with
    # --no-auto-detect to force this when an Instagram zip is also present —
    # which also avoids auto-detect opening every Flickr media zip.)
    if not have_instagram:
        if not _check_fresh_would_not_clobber(output_dir, {"flickr"}):
            return 1
        print("\n📷 FLICKR-ONLY MODE — building without an Instagram archive")
        try:
            flickr_source = _import_flickr_source(args, output_dir, {})
        except FileNotFoundError as e:
            print(f"\n❌ ERROR: {e}")
            return 1
        data = {
            "schema_version": merger.SCHEMA_VERSION,
            "location": {"location": "Unknown"},
            "sources": {"flickr": flickr_source},
            "city_tags": city_tags,
        }
        print("\n🌐 GENERATING WEBSITE")
        generator = InstagramSiteGenerator(data, output_dir, gtag_id=args.gtag_id, theme_dir=args.theme)
        if generator.generate():
            print("\n✅ PROCESS COMPLETE")
            print(f"   Website generated at: {output_dir}")
            print(f"   {_describe_sources(data['sources'])}")
            return 0
        print("\n❌ ERROR: Failed to generate website.")
        return 1

    if not args.merge and not _check_fresh_would_not_clobber(
        output_dir, {"instagram"} | ({"flickr"} if args.flickr else set())
    ):
        return 1

    try:
        # Extract archive
        print("\n📦 EXTRACTING ARCHIVE")
        print(f"   Source: {extractor.input_path}")
        extraction_dir = extractor.extract()
        print(f"   Extracted to: {extraction_dir}")

        # Get file mapper from extractor
        file_mapper = extractor.file_mapper

        # Initialize loader with the same file mapper
        print("\n📋 LOADING DATA")
        loader = InstagramDataLoader(extraction_dir, file_mapper, verbose=args.verbose)

        # Load and process data
        data = loader.load_all_data()
        
        if args.verbose:
            print("\n🔍 VERBOSE: Data Loading Details")
            print(f"   Profile data found: {'Yes' if loader.profile_data else 'No'}")
            print(f"   Location data found: {'Yes' if loader.location_data else 'No'}")
            print(f"   Posts data found: {'Yes' if loader.posts_data else 'No'}")
            print(f"   Insights data found: {'Yes' if loader.insights_data else 'No'}")
            print(f"   Combined data entries: {len(loader.combined_data) if loader.combined_data else 0}")
            
            # Show file paths that were found
            print("\n   File paths found:")
            for file_type, file_path in file_mapper.file_map.items():
                if isinstance(file_path, list):
                    print(f"      {file_type}: {len(file_path)} files")
                    if args.verbose:
                        for i, path in enumerate(file_path[:3]):  # Show first 3 only
                            print(f"         - {path}")
                        if len(file_path) > 3:
                            print(f"         - ... and {len(file_path)-3} more")
                else:
                    print(f"      {file_type}: {file_path}")
        
        print(f"   Found {data['post_count']} posts from {data['profile']['username']}")

        # In merge mode, only process posts/stories not already in the site
        if args.merge:
            posts_to_process = merger.compute_delta(existing["posts"], data["posts"])
            stories_to_process = merger.compute_delta(
                existing["stories"], data.get("stories", {})
            )
            print(f"\n🔀 COMPUTING MERGE DELTA")
            print(f"   Posts: {len(existing['posts'])} existing, "
                  f"{len(data['posts'])} in new archive, {len(posts_to_process)} new")
            print(f"   Stories: {len(existing['stories'])} existing, "
                  f"{len(data.get('stories', {}))} in new archive, {len(stories_to_process)} new")
        else:
            posts_to_process = data["posts"]
            stories_to_process = data.get("stories", {})

        # Process media files
        print(f"\n🖼️  PROCESSING MEDIA")
        print(f"   Using {args.threads} threads, quality {args.quality}, max dimension {args.max_dimension}...")
        media_processor = InstagramMediaProcessor(
            extraction_dir, output_dir, thread_count=args.threads,
            quality=args.quality, max_dimension=args.max_dimension
        )
        media_result = media_processor.process_media_files(
            posts_to_process, data["profile"]["profile_picture"], stories_to_process
        )

        if args.merge:
            # Union existing site data with the newly processed entries
            merged_posts = merger.merge_timestamp_dicts(
                existing["posts"], media_result["updated_post_data"]
            )
            merged_stories = merger.merge_timestamp_dicts(
                existing["stories"], media_result.get("updated_stories_data") or {}
            )
            # Backfill place names/coordinates onto entries the new archive
            # knows about but that were kept from the existing site
            updated_meta = merger.apply_post_metadata(merged_posts, data["posts"])
            updated_meta += merger.apply_post_metadata(
                merged_stories, data.get("stories", {})
            )
            if updated_meta:
                print(f"   Added place/location metadata to {updated_meta} existing items")
            data["posts"] = merged_posts
            data["stories"] = merged_stories
            data["profile"]["profile_picture"] = media_result["shortened_profile"]
            if not data["profile"]["profile_picture"] and existing.get("profile"):
                # Fall back to the already-processed picture from the sidecar
                data["profile"]["profile_picture"] = existing["profile"].get(
                    "profile_picture", ""
                )
            # Reuse the previous run's gtag ID unless a new one was given
            if not args.gtag_id and existing["settings"].get("gtag_id"):
                args.gtag_id = existing["settings"]["gtag_id"]
        else:
            # Update data with shortened filenames
            data["posts"] = media_result["updated_post_data"]
            data["profile"]["profile_picture"] = media_result["shortened_profile"]

            # Update stories data if it exists
            if "stories" in data and media_result.get("updated_stories_data"):
                data["stories"] = media_result["updated_stories_data"]

        # Assemble the source-shaped package. Instagram is whatever this run
        # loaded and processed.
        sources = {
            "instagram": {
                "profile": data["profile"],
                "posts": data["posts"],
                "stories": data.get("stories") or {},
            }
        }

        # Every OTHER source the existing site had carries forward untouched.
        # This generic loop is the point of the sources registry: a future
        # importer needs no merge-path code to survive an Instagram merge.
        if args.merge and existing:
            for key, section in (existing.get("sources") or {}).items():
                if key != "instagram" and section:
                    sources[key] = section

        # A --flickr import always wins over the carried-forward section
        if args.flickr:
            sources["flickr"] = _import_flickr_source(
                args, output_dir, data["posts"]
            )

        # Generate website with the loaded data
        print("\n🌐 GENERATING WEBSITE")
        package = {
            "schema_version": merger.SCHEMA_VERSION,
            "location": data.get("location") or {"location": "Unknown"},
            "sources": sources,
            "city_tags": city_tags,
        }
        generator = InstagramSiteGenerator(package, output_dir, gtag_id=args.gtag_id, theme_dir=args.theme)
        success = generator.generate()

        if success:
            stats = media_result["stats"]
            print("\n✅ PROCESS COMPLETE")
            print(f"   Website generated at: {output_dir}")
            print(f"   Posts processed: {data['post_count']}")
            print(f"   Media files processed: {stats['thumbnail_count'] + stats['webp_count']}")
            print(f"   Space saved: {stats['space_saved_mb']:.2f} MB ({stats['percentage_saved']:.1f}%)")
            print(f"   Fixed file extensions: {stats['extension_fixes']}")
            return 0
        else:
            print("\n❌ ERROR: Failed to generate website.")
            return 1

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        if args.verbose:
            print("\n🔍 VERBOSE: Exception traceback")
            traceback.print_exc(file=sys.stdout)
        return 1


if __name__ == "__main__":
    exit(main())
