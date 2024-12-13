# ruff: noqa: PLR1702
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from ytmusicapi import YTMusic

yt_title_regexes = [
	# Artist "Track", Artist: "Track", Artist - "Track", etc.
	{
		"pattern": r'(.+?)([\s:—-])+\s*"(.+?)"',
		"groups": {"artist": 1, "track": 3},
	},
	# Artist「Track」 (Japanese tracks)
	{
		"pattern": r"(.+?)[『｢「](.+?)[」｣』]",
		"groups": {"artist": 1, "track": 2},
	},
	# Track (... by Artist)
	{
		"pattern": r"(\w[\s\w]*?)\s+\([^)]*\s*by\s*([^)]+)+\)",
		"groups": {"artist": 2, "track": 1},
	},
]

separator_regex = "|".join(
	re.escape(x)
	for x in [
		" -- ",
		"--",
		" ~ ",
		" \u002d ",
		" \u2013 ",
		" \u2014 ",
		" // ",
		"\u002d",
		"\u2013",
		"\u2014",
		":",
		"|",
		"///",
		"~",
	]
)


def format_duration(seconds):
	if not seconds:
		return ""

	seconds = int(seconds)
	minutes, seconds = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)

	return f"{hours:02}:{minutes:02}:{seconds:02}"


# https://github.com/web-scrobbler/web-scrobbler/blob/e8045868cfe70762ce8f826c930719df4939471d/src/core/content/util.ts#L859
def parse_title(channel: str, title: str):
	print(f"\x1b[0;33mparsing {title}\x1b[0m")

	# Remove [genre] or 【genre】 from the beginning of the title
	title = re.sub(
		r"^((\[[^\]]+\])|(【[^】]+】))\s*-*\s*", "", title, flags=re.IGNORECASE
	)

	# Remove track (CD and vinyl) numbers from the beginning of the title
	title = re.sub(
		r"^\s*([a-zA-Z]{1,2}|[0-9]{1,2})[1-9]?\.\s+", "", title, flags=re.IGNORECASE
	)

	# Remove - preceding opening bracket
	title = re.sub(r"-\s*([「【『])", r"\1", title, flags=re.IGNORECASE)

	# 【/(*Music Video/MV/PV*】/)
	title = re.sub(
		r"[(［【][^(［【]*?((Music Video)|(MV)|(PV)).*?[】］)]",
		"",
		title,
		flags=re.IGNORECASE,
	)

	# 【/(東方/オリジナル*】/)
	title = re.sub(
		"[(［【]((オリジナル)|(東方)).*?[】］)]+?", "", title, flags=re.IGNORECASE
	)

	# MV/PV if followed by an opening/closing bracket
	title = re.sub(
		r"((?:Music Video)|MV|PV)([「［【『』】］」])", r"\2", title, flags=re.IGNORECASE
	)

	# MV/PV if ending and with whitespace in front
	title = re.sub(r"\s+(MV|PV)$", "", title, flags=re.IGNORECASE)

	title = re.sub(r"[\(\[][^)\]]lyrics[)\]]", "", title, flags=re.IGNORECASE)

	title = title.strip()

	for regex in yt_title_regexes:
		m = re.search(regex["pattern"], title)
		if m is not None:
			artist = m.group(regex["groups"]["artist"])
			track = m.group(regex["groups"]["track"])
			return (artist, track)

	res = re.split(separator_regex, title)
	if len(res) == 2:
		return (res[0], res[1])

	if (m := re.search(r"(.+?)【(.+?)】", title)) is not None:
		return (m.group(2), m.group(1))

	return (channel, title)


results_cache = {}


def write_result(writer, artists, title, album, time, duration, is_ytm, video_id):
	if is_ytm:  # ytm video
		parsed = False
		artist = ", ".join(artist for artist in artists)
		if title.count(" - ") == 1:
			track = title.split(" - ")[1]
		else:
			track = title
	else:  # regular yt video
		parsed = True
		artist, track = parse_title(artists[0] if artists else "", title)

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

			video_id = parse_qs(urlparse(entry["titleUrl"]).query)["v"][0]

			if video_id in results_cache:
				artist, track, album, duration, _ = results_cache[video_id]
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
			elif entry["header"] == "YouTube Music":
				# only get regular yt history if they're already in the results_cache
				try:
					# try ytm api
					for search_result in ytmusic.search(f'"{video_id}"'):
						if (
							"videoId" in search_result
							and search_result["videoId"] == video_id
						):
							artists = [
								artist["name"] for artist in search_result["artists"]
							]
							album = (
								search_result["album"]["name"]
								if "album" in search_result
								and search_result["album"] is not None
								else ""
							)
							if "duration_seconds" not in search_result:
								error(f"Error: {video_id} missing duration")
								duration = ""
							else:
								duration = search_result["duration_seconds"]

							is_ytm = (
								search_result["videoType"] == "MUSIC_VIDEO_TYPE_ATV"
								or search_result["videoType"] == "MUSIC_VIDEO_TYPE_OMV"
							)
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
							break
					else:  # fall back to yt-dlp
						try:
							ytdlp_result = ytdlp.extract_info(video_id)
							if (
								ytdlp_result is not None
								and ytdlp_result["id"] == video_id
							):
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
									write_result(
										writer,
										artists=[channel],
										title=filmot_result[0]["title"],
										album="",
										is_ytm=False,
										time=entry["time"],
										duration=filmot_result[0]["duration"],
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
