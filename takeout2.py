#!/usr/bin/env python3
# ruff: noqa: PLR1702
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from common import dearrow_title, format_duration, parse_title
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from ytmusicapi import YTMusic

results_cache = {}


def write_result(writer, artists, title, album, time, duration, is_ytm, video_id):
	if is_ytm:  # ytm video
		parsed = False
		if len(artists) >= 3:
			artist = ", ".join(artists[:-1]) + " & " + artists[-1]
		else:
			artist = " & ".join(artists)
		if title.count(" - ") == 1:
			track = title.split(" - ")[1]
		else:
			track = title
	else:  # regular yt video
		parsed = True
		artist, track = parse_title(
			artists[0] if artists else "", dearrow_title(video_id) or title
		)

	if artist in {
		"cpol",
		"cpol_",
		"Mafham",
		"mrekk",
		"NaPiii_",
		"JappaDeKappa",
		"Whitecat",
		"Akatsuki",
		"Hugofrost",
		"4096",
		"Honest Trailers",
	}:  # manual blacklist :skull:
		return

	print(artist, "-", track)
	results_cache[video_id] = [artist, track, album, duration, "parsed" if parsed else ""]
	writer.writerow([
		artist,
		album,
		track,
		time,
		"",
		format_duration(duration),
	])


def main():
	start_index = 0
	scrobble_percent = 0.5  # scrobble if >50% of the song has been played
	ytmusic = YTMusic()
	ytdlp = YoutubeDL({
		"extract_flat": "in_playlist",
		"noprogress": True,
		"quiet": True,
		"simulate": True,
	})

	with open("watch-history.json", encoding="utf-8") as f:
		history = json.load(f)

	try:
		with open("results_cache.json", "r", encoding="utf-8") as f:
			global results_cache
			results_cache = json.load(f)
	except FileNotFoundError:
		pass

	output_folder = Path("out/")
	if output_folder.exists():
		shutil.rmtree(output_folder)
	output_folder.mkdir()

	csv_file = None
	entry_count = 0
	with open("errors.txt", "a", encoding="utf-8") as err_file:

		def error(s: str):
			print(f"\x1b[0;31m{s}\x1b[0m")
			err_file.write(s + "\n")

		prev_timestamp = None
		for i, entry in enumerate(history[start_index:], start=start_index):
			# split output into 2800 row files
			if entry_count % 2800 == 0:
				if csv_file is not None:
					csv_file.close()
				csv_file = output_folder.joinpath(f"part{entry_count // 2800}.csv").open(
					"w"
				)
				writer = csv.writer(csv_file)

			if "watch" not in entry["titleUrl"]:  # not a youtube or ytm video
				continue

			timestamp = datetime.fromisoformat(entry["time"])
			if prev_timestamp is not None:
				timestamp_diff = prev_timestamp - timestamp
			else:
				timestamp_diff = timedelta(days=9999)  # surely this is fine right
			prev_timestamp = timestamp

			video_id = parse_qs(urlparse(entry["titleUrl"]).query)["v"][0]

			if video_id in results_cache:
				cached_result = results_cache[video_id]
				if cached_result is None:
					continue
				artist, track, album, duration, _ = cached_result

				if scrobble_percent * timedelta(seconds=duration) > timestamp_diff:
					continue

				print(artist, "-", track)
				writer.writerow([
					artist,
					album,
					track,
					entry["time"],
					"",
					format_duration(duration),
				])
				entry_count += 1
			else:
				try:
					# try ytm api
					found_result = False
					for j, search_result in enumerate(ytmusic.search(f'"{video_id}"')):
						if (
							"videoId" in search_result
							and search_result["videoId"] == video_id
						):
							if j != 0:
								error(f"{video_id} {j}")
							found_result = True
							break
					if found_result:
						artists = [artist["name"] for artist in search_result["artists"]]

						album = (
							search_result["album"]["name"]
							if "album" in search_result
							and search_result["album"] is not None
							else ""
						)

						if "duration_seconds" not in search_result:
							error(f"Error: {video_id} missing duration")
							duration = 0
						else:
							duration = search_result["duration_seconds"]

						is_ytm = (
							search_result["videoType"] == "MUSIC_VIDEO_TYPE_ATV"
							or search_result["videoType"] == "MUSIC_VIDEO_TYPE_OMV"
						)

						if (
							scrobble_percent * timedelta(seconds=duration)
							> timestamp_diff
						):
							continue

						if entry["header"] == "YouTube" and not is_ytm:
							# only add regular yt history if they're youtube music videos
							error(f"check {video_id}: {search_result["title"]}")

						write_result(
							writer,
							artists=artists,
							title=search_result["title"],
							album=album,
							time=entry["time"],
							duration=duration,
							is_ytm=is_ytm,
							video_id=video_id,
						)
						entry_count += 1
					else:  # fall back to yt-dlp
						if entry["header"] == "YouTube Music":
							try:
								ytdlp_result = ytdlp.extract_info(video_id)
								if (
									ytdlp_result is not None
									and ytdlp_result["id"] == video_id
								):
									if (
										scrobble_percent * timedelta(seconds=duration)
										> timestamp_diff
									):
										continue

									write_result(
										writer,
										artists=ytdlp_result.get("artists", []),
										title=ytdlp_result["title"],
										album=ytdlp_result.get("album", ""),
										is_ytm="album" in ytdlp_result,
										time=entry["time"],
										duration=ytdlp_result["duration"],
										video_id=video_id,
									)
									entry_count += 1
								else:
									error(f"Error: couldn't find {video_id}")
							except DownloadError:
								resp = requests.get(
									"https://filmot.com/api/getvideos",
									params={
										"key": "md5paNgdbaeudounjp39",
										"id": video_id,
									},
								)
								found = False
								if resp.ok:
									filmot_result = resp.json()
									if not filmot_result:
										found = False
									else:
										channel = filmot_result[0][
											"channelname"
										].removesuffix(" - Topic")

										duration = filmot_result[0]["duration"]
										if (
											scrobble_percent * timedelta(seconds=duration)
											> timestamp_diff
										):
											continue

										write_result(
											writer,
											artists=[channel],
											title=filmot_result[0]["title"],
											album="",
											is_ytm=False,
											time=entry["time"],
											duration=duration,
											video_id=video_id,
										)
										entry_count += 1

								if not found:
									error(f"Error: {video_id} is unavailable")
				except (Exception, KeyboardInterrupt):  # catch-all
					print(video_id, i)
					with open("results_cache.json", "w", encoding="utf-8") as f:
						json.dump(results_cache, f, ensure_ascii=False)
					raise
	with open("results_cache.json", "w", encoding="utf-8") as f:
		json.dump(results_cache, f, ensure_ascii=False)
	print(f"{entry_count} entries")


if __name__ == "__main__":
	main()
