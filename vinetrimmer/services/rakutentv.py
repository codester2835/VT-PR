from __future__ import annotations

import os
import base64
import datetime
import hashlib
import hmac
import re
import urllib.parse
import click
from requests.exceptions import HTTPError

from vinetrimmer.config import config, directories
from vinetrimmer.objects import TextTrack, Title, Tracks
from vinetrimmer.services.BaseService import BaseService
from copy import copy
from langcodes import *
from pymediainfo import MediaInfo

import requests
from requests.adapters import HTTPAdapter, Retry

class RakutenTV(BaseService):
	"""
	Service code for Rakuten's Rakuten TV streaming service (https://rakuten.tv).

	\b
	Authorization: Credentials
	Security: FHD-UHD@L1, SD-FHD@L3; with trick

	\b
	Maximum of 3 audio tracks, otherwise will fail because Rakuten blocks more than 3 requests.
	Subtitles requests expires fast, so together with video and audio it will fail.
	If you want subs, use -S or -na -nv -nc, and download the rest separately.

	\b
	Command for Titles with no SDR (if not set range to HDR10 it will fail):
	poetry vt dl -r HDR10 [OPTIONS] RKTN -m https://www.rakuten.tv/...

	\b
	TODO: - TV Shows are not yet supported as there's 0 TV Shows to purchase, rent, or watch in my region

	\b
	NOTES: - Only movies are supported as my region's Rakuten has no TV shows available to purchase at all
	"""

	ALIASES = ["RKTN", "rakuten", "rakutentv"]
	TITLE_RE = r"^(?:https?://(?:www\.)?rakuten\.tv/([a-z]+/|)movies(?:/[a-z]{2})?/)(?P<id>[a-z0-9-]+)"

	@staticmethod
	@click.command(name="RakutenTV", short_help="https://rakuten.tv")
	@click.argument("title", type=str, required=False)
	@click.option(
		"-dev",
		"--device",
		default=None,
		type=click.Choice(
			[
				"web",  # Device: Web Browser - Maximum Quality: 720p - DRM: Widevine
				"android",  # Device: Android Phone - Maximum Quality: 720p - DRM: Widevine
				"atvui40",  # Device: AndroidTV - Maximum Quality: 2160p - DRM: Widevine
				"lgui40",  # Device: LG SMART TV - Maximum Quality: 2160p - DRM: Playready
				"smui40",  # Device: Samsung SMART TV - Maximum Quality: 2160p - DRM: Playready
			],
			case_sensitive=True,
		),
		help="The device you want to make requests with.",
	)
	@click.option(
		"-m", "--movie", is_flag=True, default=False, help="Title is a movie."
	)
	@click.pass_context
	def cli(ctx, **kwargs):
		return RakutenTV(ctx, **kwargs)

	def __init__(self, ctx, title, device, movie):
		super().__init__(ctx)
		assert ctx.parent is not None

		self.playready = True if "certificate_chain" in dir(ctx.obj.cdm) else False
		self.vcodec = ctx.parent.params["vcodec"] or "H264"
		self.resolution = "UHD" if self.vcodec.lower() == "h265" else "FHD"
		self.device = device
		super().__init__(ctx)

		self.device = "lgui40" if self.playready else "android"
		self.parse_title(ctx, title)
		self.movie = movie or "movies" in title
		self.range = ctx.parent.params["range_"] or "SDR"

		self.configure()

	def get_titles(self):
		self.pair_device()
		title_url = self.config["endpoints"]["title"].format(
			title_id=self.title
		) + urllib.parse.urlencode(
			{
				"classification_id": self.classification_id,
				"device_identifier": self.config["clients"][self.device][
					"device_identifier"
				],
				"device_serial": self.config["clients"][self.device]["device_serial"],
				"locale": self.locale,
				"market_code": self.market_code,
				"session_uuid": self.session_uuid,
				"timestamp": f"{int(datetime.datetime.now().timestamp())}005",
			}
		)

		
		title = self.session.get(url=title_url).json()
		if "errors" in title:
			error = title["errors"][0]
			if error["code"] == "error.not_found":
				self.log.exit(f"Title [{self.title}] was not found on this account.")
			else:
				self.log.exit(
					f"Unable to get title info: {error['message']} [{error['code']}]"
				)
		title = self.get_info(title["data"])

		if self.movie:
			titles = Title(
				id_=self.title,
				type_=Title.Types.MOVIE,
				name=title["title"],
				year=title["year"],
				#synopsis=title["plot"],
				original_lang="en",  # TODO: Check if RakutenTV has language data in the API.
				source=self.ALIASES[0],
				service_data=title,
			)
		else:
			self.log.exit(" - TV shows are not yet supported")

		return titles

	def get_tracks(self, title):
		# Obtener tracks para todos los idiomas de audio disponibles
		all_tracks = None
		
		for audio_lang in self.audio_languages:
			self.log.info(f"Getting tracks for audio language: {audio_lang}")
			
			# Obtener stream info para este idioma específico
			stream_info = self.get_avod(audio_lang) if self.kind == "avod" else self.get_me(audio_lang)
			
			if "errors" in stream_info:
				error = stream_info["errors"][0]
				if "error.streaming.no_active_right" in stream_info["errors"][0]["code"]:
					self.log.exit(
						" x You don't have the rights for this content\n   You need to rent or buy it first"
					)
				else:
					self.log.exit(
						f" - Failed to get track info: {error['message']} [{error['code']}]"
					)
			
			stream_info = stream_info["data"]["stream_infos"][0]
			
			if all_tracks is None:
				# Primera iteración: crear el objeto tracks principal
				self.license_url = stream_info["license_url"]
				
				all_tracks = Tracks.from_mpd(
					url=stream_info["url"],
					session=self.session,
					source=self.ALIASES[0],
				)
				
				# Procesar subtítulos (solo una vez)
				subtitle_tracks = []
				for subtitle in stream_info.get("all_subtitles", []):
					if subtitle["format"] == "srt":
						subtitle_tracks += [
							TextTrack(
								id_=hashlib.md5(subtitle["url"].encode()).hexdigest()[0:6],
								source=self.ALIASES[0],
								url=subtitle["url"],
								codec="srt",
								forced=subtitle["forced"],
								language=subtitle["locale"],
							)
						]
				
				all_tracks.add(subtitle_tracks)
				
				if not all_tracks.subtitles:
					subtitle_tracks = []
					for subtitle in stream_info.get("all_subtitles", []):
						if subtitle["format"] == "['vtt']":
							subtitle_tracks += [
								TextTrack(
									id_=hashlib.md5(subtitle["url"].encode()).hexdigest()[0:6],
									source=self.ALIASES[0],
									url=subtitle["url"].replace("['vtt']", "vtt"),
									codec="vtt",
									forced=subtitle["forced"],
									language=subtitle["locale"],
								)
							]
					
					all_tracks.add(subtitle_tracks)
			else:
				# Iteraciones adicionales: obtener tracks de audio adicionales
				temp_tracks = Tracks.from_mpd(
					url=stream_info["url"],
					session=self.session,
					source=self.ALIASES[0],
				)
				
				# Agregar solo los tracks de audio nuevos
				for audio_track in temp_tracks.audios:
					# Verificar que no sea duplicado basado en el idioma y codec
					is_duplicate = False
					for existing_audio in all_tracks.audios:
						if (existing_audio.language == audio_track.language and 
							existing_audio.codec == audio_track.codec):
							is_duplicate = True
							break
					
					if not is_duplicate:
						all_tracks.audios.append(audio_track)

		# Procesar HDR para videos
		for video in all_tracks.videos:
			if "HDR10" in video.url:
				video.hdr10 = True

		# Aplicar el método append_tracks mejorado
		self.append_tracks(all_tracks)

		return all_tracks

	def get_chapters(self, title):
		return []

	def certificate(self, **kwargs):
		return self.config["certificate"]

	def license(self, challenge, **_):
		if self.playready:
			res = self.session.post(
				url=self.license_url,
				data=challenge,
			)

			if "errors" in res.text:
				res = res.json()
				if res["errors"][0]["message"] == "HttpException: Forbidden":
					self.log.exit(
						" x This CDM is not eligible to decrypt this\n"
						"   content or has been blacklisted by RakutenTV"
					)
				elif res["errors"][0]["message"] == "HttpException: An error happened":
					self.log.exit(
						" x This CDM seems to be revoked and\n"
						"   therefore it can't decrypt this content",
					)
			return res.content
		else:
			res = self.session.post(
				url=self.license_url,
				data=challenge,
			)

			if "errors" in res.text:
				res = res.json()
				if res["errors"][0]["message"] == "HttpException: Forbidden":
					self.log.exit(
						" x This CDM is not eligible to decrypt this\n"
						"   content or has been blacklisted by RakutenTV"
					)
				elif res["errors"][0]["message"] == "HttpException: An error happened":
					self.log.exit(
						" x This CDM seems to be revoked and\n"
						"   therefore it can't decrypt this content",
					)
			return res.content

	# Service specific functions

	def configure(self):
		self.session.headers.update(
			{
				"Origin": "https://rakuten.tv/",
				"User-Agent": "Mozilla/5.0 (Linux; Android 11; SHIELD Android TV Build/RQ1A.210105.003; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/99.0.4844.88 Mobile Safari/537.36",
			}
		)

	def generate_signature(self, url):
		up = urllib.parse.urlparse(url)
		digester = hmac.new(
			self.access_token.encode(),
			f"POST{up.path}{up.query}".encode(),
			hashlib.sha1,
		)
		return (
			base64.b64encode(digester.digest())
			.decode("utf-8")
			.replace("+", "-")
			.replace("/", "_")
		)

	def pair_device(self):
		# TODO: Make this return the tokens, move print out of the func
		# log.info_("Logging into RakutenTV as an Android device")
		if not self.credentials:
			self.log.exit(" - No credentials provided, unable to log in.")
		try:
			res = self.session.post(
				url=self.config["endpoints"]["auth"],
				params={
					"device_identifier": self.config["clients"][self.device][
						"device_identifier"
					]
				},
				data={
					"app_version": self.config["clients"][self.device]["app_version"],
					"device_metadata[uid]": self.config["clients"][self.device][
						"device_serial"
					],
					"device_metadata[os]": self.config["clients"][self.device][
						"device_os"
					],
					"device_metadata[model]": self.config["clients"][self.device][
						"device_model"
					],
					"device_metadata[year]": self.config["clients"][self.device][
						"device_year"
					],
					"device_serial": self.config["clients"][self.device][
						"device_serial"
					],
					"device_metadata[trusted_uid]": False,
					"device_metadata[brand]": self.config["clients"][self.device][
						"device_brand"
					],
					"classification_id": 69,
					"user[password]": self.credentials.password,
					"device_metadata[app_version]": self.config["clients"][self.device][
						"app_version"
					],
					"user[username]": self.credentials.username,
					"device_metadata[serial_number]": self.config["clients"][
						self.device
					]["device_serial"],
				},
			).json()
		except HTTPError as e:
			if e.response.status_code == 403:
				self.log.exit(
					" - Rakuten returned a 403 (FORBIDDEN) error. "
					"This could be caused by your IP being detected as a proxy, or regional issues. Cannot continue."
				)
		if "errors" in res:
			error = res["errors"][0]
			if "exception.forbidden_vpn" in error["code"]:
				self.log.exit(" x RakutenTV is detecting this VPN or Proxy")
			else:
				self.log.exit(f" - Login failed: {error['message']} [{error['code']}]")
		self.access_token = res["data"]["user"]["access_token"]
		self.ifa_subscriber_id = res["data"]["user"]["avod_profile"][
			"ifa_subscriber_id"
		]
		self.session_uuid = res["data"]["user"]["session_uuid"]
		self.classification_id = res["data"]["user"]["profile"]["classification"]["id"]
		self.locale = res["data"]["market"]["locale"]
		self.market_code = res["data"]["market"]["code"]

	def get_info(self, title):
		self.kind = title["labels"]["purchase_types"][0]["kind"]

		self.available_resolutions = [x for x in title["labels"]["video_qualities"]]
		if any(x["abbr"] == "UHD" for x in title["labels"]["video_qualities"]):
				self.resolution = "UHD"
		elif any(x["abbr"] == "FHD" for x in title["labels"]["video_qualities"]):
				self.resolution = "FHD"
		elif any(x["abbr"] == "HD" for x in title["labels"]["video_qualities"]):
				self.resolution = "HD"
		else:
				self.resolution = "SD"

		self.available_hdr_types = [x for x in title["labels"]["hdr_types"]]
		if any(x["abbr"] == "HDR10_PLUS" for x in self.available_hdr_types) and any(
			x["abbr"] == "HDR10_PLUS"
			for x in title["view_options"]["support"]["hdr_types"]
		):
			self.hdr_type = "HDR10_PLUS"
		elif any(x["abbr"] == "DOLBY_VISION" for x in self.available_hdr_types) and any(
			x["abbr"] == "DOLBY_VISION"
			for x in title["view_options"]["support"]["hdr_types"]
		):
			self.hdr_type = "DOLBY_VISION"
		elif any(x["abbr"] == "HDR10" for x in self.available_hdr_types) and any(
			x["abbr"] == "HDR10" for x in title["view_options"]["support"]["hdr_types"]
		):
			self.hdr_type = "HDR10"

		else:
			self.hdr_type = "NONE"

		# FIJO: Obtener TODOS los idiomas de audio disponibles
		if len(title["view_options"]["private"]["offline_streams"]) == 1:
			# Caso 1: Un solo stream con múltiples idiomas
			self.audio_languages = [
				x["abbr"]
				for x in title["view_options"]["private"]["streams"][0][
					"audio_languages"
				]
			]
		else:
			# Caso 2: Múltiples streams, obtener todos los idiomas únicos
			all_audio_languages = []
			for stream in title["view_options"]["private"]["streams"]:
				for audio_lang in stream["audio_languages"]:
					if audio_lang["abbr"] not in all_audio_languages:
						all_audio_languages.append(audio_lang["abbr"])
			self.audio_languages = all_audio_languages

		# TODO: Look up only for languages chosen by the user
		print(f"\nAvailable audio languages: {', '.join(self.audio_languages)}")
		selected = input("Type your desired languages, maximum of 3, UPPER CASE (ex: ENG,SPA,FRA): ")

		selected_langs = [lang.strip() for lang in selected.split(",") if lang.strip() in self.audio_languages]
		if not selected_langs:
			self.log.exit("No selected language. Exiting.")
		self.audio_languages = selected_langs

		# Log para debug
		self.log.info(f"Selected audio languages: {self.audio_languages}")

		return title

	def get_avod(self, audio_language=None):
		# Si no se especifica idioma, usar el primero disponible
		if audio_language is None:
			audio_language = self.audio_languages[0]
			
		stream_info_url = self.config["endpoints"]["manifest"].format(
			kind="avod"
		) + urllib.parse.urlencode(
			{
				"device_stream_video_quality": self.resolution,
				"device_identifier": self.config["clients"][self.device][
					"device_identifier"
				],
				"market_code": self.market_code,
				"session_uuid": self.session_uuid,
				"timestamp": f"{int(datetime.datetime.now().timestamp())}122",
			}
		)
		stream_info_url += "&signature=" + self.generate_signature(stream_info_url)
		return self.session.post(
			url=stream_info_url,
			data={
				"hdr_type": self.hdr_type,
				"audio_quality": "5.1",  # Will get better audio in different request to make sure it wont error
				"app_version": self.config["clients"][self.device]["app_version"],
				"content_id": self.title,
				"video_quality": self.resolution,
				"audio_language": audio_language,  # Usar el idioma especificado
				"video_type": "stream",
				"device_serial": self.config["clients"][self.device]["device_serial"],
				"content_type": "movies" if self.movie else "episodes",
				"classification_id": self.classification_id,
				"subtitle_language": "MIS",
				"player": self.config["clients"][self.device]["player"],
			},
		).json()

	def get_me(self, audio_language=None):
		# Si no se especifica idioma, usar el primero disponible
		if audio_language is None:
			audio_language = self.audio_languages[0]
			
		stream_info_url = self.config["endpoints"]["manifest"].format(
			kind="me"
		) + urllib.parse.urlencode(
			{
				"audio_language": audio_language,  # Usar el idioma especificado
				"audio_quality": "5.1",  # Will get better audio in different request to make sure it wont error
				"classification_id": self.classification_id,
				"content_id": self.title,
				"content_type": "movies" if self.movie else "episodes",
				"device_identifier": self.config["clients"][self.device][
					"device_identifier"
				],
				"device_serial": "not_implemented",
				"device_stream_audio_quality": "5.1",
				"device_stream_hdr_type": self.hdr_type,
				"device_stream_video_quality": self.resolution,
				"device_uid": "affa434b-8b7c-4ff3-a15e-df1fe500e71e",
				"device_year": self.config["clients"][self.device]["device_year"],
				"disable_dash_legacy_packages": "false",
				"gdpr_consent": self.config["gdpr_consent"],
				"gdpr_consent_opt_out": 0,
				"hdr_type": self.hdr_type,
				"ifa_subscriber_id": self.ifa_subscriber_id,
				"locale": self.locale,
				"market_code": self.market_code,
				"player": self.config["clients"][self.device]["player"],
				"player_height": 1080,
				"player_width": 1920,
				"publisher_provided_id": "046f58b1-d89b-4fa4-979b-a9bcd6d78a76",
				"session_uuid": self.session_uuid,
				"strict_video_quality": "false",
				"subtitle_formats": ["vtt"],
				"subtitle_language": "MIS",
				"timestamp": f"{int(datetime.datetime.now().timestamp())}122",
				"video_type": "stream",
			}
		)
		stream_info_url += "&signature=" + self.generate_signature(stream_info_url)
		return self.session.post(
			url=stream_info_url,
		).json()

	def append_tracks(self, tracks):
		# Método mejorado que busca tracks adicionales para todos los idiomas
		codec = tracks.videos[0].codec[:4]
		
		# Buscar tracks de video adicionales
		if "avc1" in codec:
			for n in range(100):
				ismv = re.sub(
					rf"{codec}-[0-9]",
					rf"{codec}-{len(tracks.videos) + 1}",
					tracks.videos[-1].url,
				)
				if self.session.head(ismv).status_code != 200:
					break
				video = copy(tracks.videos[-1])
				video.url = ismv
				video.id = hashlib.md5(ismv.encode()).hexdigest()
				with open(f"{directories.temp}/video_bytes.mp4", "wb+") as chunkfile:
					data = self.session.get(
						url=ismv, headers={"Range": "bytes=0-50000"}
					)
					chunkfile.write(data.content)
				info = MediaInfo.parse(f"{directories.temp}/video_bytes.mp4")
				if info.video_tracks:
					video.height = info.video_tracks[0].height
					video.width = info.video_tracks[0].width
					video.bitrate = info.video_tracks[0].maximum_bit_rate
					if not video.bitrate:
						video.bitrate = info.video_tracks[0].bit_rate
				else:
					continue
				os.remove(f"{directories.temp}/video_bytes.mp4")
				tracks.videos.append(video)

		# Buscar tracks de audio adicionales para TODOS los idiomas
		if self.audio_languages:
			for language in self.audio_languages:
				for codec in ["dts", "ec-3", "ac-3", "mp4a"]:
					# Intentar encontrar tracks de audio para este idioma y codec
					isma = re.sub(
						rf"audio-{self.audio_languages[0].lower()}-mp4a-1",
						rf"audio-{language.lower()}-{codec}-1",
						tracks.audios[0].url,
					)
					
					# Verificar si el track existe
					if self.session.head(isma).status_code != 200:
						continue
					
					# Verificar si ya existe este track (evitar duplicados)
					track_exists = False
					for existing_audio in tracks.audios:
						if existing_audio.url == isma:
							track_exists = True
							break
					
					if track_exists:
						continue
					
					# Crear nuevo track de audio
					audio = copy(tracks.audios[0])
					audio.codec = codec
					audio.url = isma
					audio.id = hashlib.md5(isma.encode()).hexdigest()
					audio.language = Language.get(language.lower())
					audio.is_original_lang = (
						True
						if audio.language.language == tracks.videos[0].language.language
						and tracks.videos[0].is_original_lang
						else False
					)
					
					# Obtener información del track
					try:
						with open(f"{directories.temp}/audio_bytes.mp4", "wb+") as bytetest:
							data = self.session.get(
								url=isma, headers={"Range": "bytes=0-50000"}
							)
							bytetest.write(data.content)
						info = MediaInfo.parse(f"{directories.temp}/audio_bytes.mp4")
						audio.bitrate = info.audio_tracks[0].bit_rate
						if codec != "mp4a":  # TODO: Don't assume
							audio.channels = "6"
						os.remove(f"{directories.temp}/audio_bytes.mp4")
						tracks.audios.append(audio)
						self.log.info(f"Added audio track: {language} - {codec}")
					except Exception as e:
						self.log.warning(f"Failed to process audio track {language}-{codec}: {str(e)}")
						if os.path.exists(f"{directories.temp}/audio_bytes.mp4"):
							os.remove(f"{directories.temp}/audio_bytes.mp4")

	def get_session(self):
		session = requests.Session()
		session.mount("https://", HTTPAdapter(
			max_retries=Retry(
				total=5,
				backoff_factor=1,
				status_forcelist=[429, 500, 502, 503, 504],
			)
		))
		session.headers.update(config.headers)
		session.cookies.update(self.cookies or {})
		return session