import hashlib
import re

import requests

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


def dearrow_title(video_id: str):
	results = requests.get(
		f"https://sponsor.ajay.app/api/branding/{hashlib.sha256(video_id.encode()).hexdigest()[:4]}"
	).json()
	try:
		result = next(
			result for video_id2, result in results.items() if video_id == video_id2
		)
		return re.sub(
			r"(^|\s)>(\S)",
			r"\1\2",
			next(
				title["title"]
				for title in result["titles"]
				if title["votes"] >= 0 or title["locked"]
			),
		)
	except StopIteration:
		return None


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

	# 【/(*Official * Video*】/)
	title = re.sub(
		r"[(［【][^(［【]*?Official .*Video.*?[】］)]",
		"",
		title,
		flags=re.IGNORECASE,
	)

	# 【/(*lyrics/full*】/)
	title = re.sub(
		r"[(［【][^(［【]*?((lyrics)).*?[】］)]",
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

	# (lyrics)
	title = re.sub(r"[\(\[][^)\]]lyrics[)\]]", "", title, flags=re.IGNORECASE)

	# eg. TVアニメ「進撃の巨人」The Final Season Part 2ノンクレジットOP ｜
	title = re.sub(
		r"TVアニメ[「『][^」』]*[」』][^｜|／]*[｜|／]\s*", "", title, flags=re.IGNORECASE
	)

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


def parse_ytm(artists, title):
	if len(artists) >= 3:
		artist = ", ".join(artists[:-1]) + " & " + artists[-1]
	else:
		artist = " & ".join(artists)
	if title.count(" - ") == 1:
		track = title.split(" - ")[1]
	else:
		track = title
	return artist, track
