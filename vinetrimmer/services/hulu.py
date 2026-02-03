import hashlib
import re
import click
import base64
import requests
import xml.etree.ElementTree as ET
from langcodes import Language

from vinetrimmer.objects import TextTrack, Title, Tracks
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.pyhulu import Device, HuluClient

class Hulu(BaseService):
	"""
	Service code for the Hulu streaming service (https://hulu.com).

	\b
	Authorization: Cookies
	Security: 
			Hulu original show/movies 4K SDR: L3/SL2000
			Hulu original show/movies 720/1080/4K HDR/DV:L1/SL3000
			Licensed show/movies 4K SDR 720/1080/4K HDR/DV: L1/SL3000
	"""

	ALIASES = ["HULU"]
	#GEOFENCE = ["us"]
	TITLE_RE = (r"^(?:https?://(?:www\.)?hulu\.com/(?P<type>movie|series)/)?(?:[a-z0-9-]+-)?"
				r"(?P<id>[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})")

	AUDIO_CODEC_MAP = {
		"AAC": "mp4a",
		"EC3": "ec-3"
	}

	@staticmethod
	@click.command(name="Hulu", short_help="https://hulu.com")
	@click.argument("title", type=str, required=False)
	@click.option("-m", "--movie", is_flag=True, default=False, help="Title is a movie.")
	@click.pass_context
	def cli(ctx, **kwargs):
		return Hulu(ctx, **kwargs)

	def __init__(self, ctx, title, movie):
		super().__init__(ctx)
		m = self.parse_title(ctx, title)
		self.movie = movie or m.get("type") == "movie"

		self.vcodec = ctx.parent.params["vcodec"]
		self.acodec = ctx.parent.params["acodec"]

		quality = ctx.parent.params.get("quality") or 0
		if quality != "SD" and quality > 1080 and self.vcodec != "H265":
			self.log.info("Switched video codec to H265 to be able to get 2160p video track")
			self.vcodec = "H265"

		if ctx.parent.params["range_"] == "HDR10":
			self.log.info("Switched dynamic range to DV as Hulu only has HDR10+ compatible DV tracks")
			ctx.parent.params["range_"] = "DV"

		if ctx.parent.params["range_"] != "SDR" and self.vcodec != "H265":
			self.log.info(f"Switched video codec to H265 to be able to get {ctx.parent.params['range_']} dynamic range")
			self.vcodec = "H265"

		self.device = None
		self.playready = True if "certificate_chain" in dir(ctx.obj.cdm) else False # ctx.obj.cdm.device.type == LocalDevice.Types.PLAYREADY
		self.playback_params = {}
		self.hulu_client = None
		self.license_url = None

		self.configure()

	def get_titles(self):
		titles = []

		if self.movie:
			res = self.session.get(self.config["endpoints"]["movie"].format(id=self.title)).json()
			title_data = res["details"]["vod_items"]["focus"]["entity"]
			titles.append(Title(
				id_=self.title,
				type_=Title.Types.MOVIE,
				name=title_data["name"],
				year=int(title_data["premiere_date"][:4]),
				source=self.ALIASES[0],
				service_data=title_data
			))
		else:
			try:
				res = self.session.get(self.config["endpoints"]["series"].format(id=self.title)).json()
			except requests.HTTPError as e:
				res = e.response.json()
				raise self.log.exit(f" - Failed to get titles for {self.title}: {res['message']} [{res['code']}]")

			season_data = next((x for x in res["components"] if x["name"] == "Episodes"), None)
			if not season_data:
				raise self.log.exit(" - Unable to get episodes. Maybe you need a proxy?")

			for season in season_data["items"]:
				episodes = self.session.get(
					self.config["endpoints"]["season"].format(
						id=self.title,
						season=season["id"].rsplit("::", 1)[1]
					)
				).json()
				for episode in episodes["items"]:
					titles.append(Title(
						id_=f"{season['id']}::{episode['season']}::{episode['number']}",
						type_=Title.Types.TV,
						name=episode["series_name"],
						season=int(episode["season"]),
						episode=int(episode["number"]),
						episode_name=episode["name"],
						source=self.ALIASES[0],
						service_data=episode
					))

		playlist = self.hulu_client.load_playlist(titles[0].service_data["bundle"]["eab_id"])
		for title in titles:
			title.original_lang = Language.get(playlist["video_metadata"]["language"])

		return titles

	def remove_parts_mpd(self, mpd):
		pattern = r'<Representation[^>]*id="(?![^"]*ALT_1)[^"]*CENC_CTR_[^"]*"[^>]*width="1920"[^>]*height="1080"[^>]*>.*?</Representation>\s*'
		m = re.sub(pattern, "", mpd, flags=re.DOTALL)
		return m
	
	def get_pssh(self, kid) -> str:
		array_of_bytes = bytearray(b'\x00\x00\x002pssh\x00\x00\x00\x00')
		array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
		array_of_bytes.extend(b'\x00\x00\x00\x12\x12\x10')
		array_of_bytes.extend(bytes.fromhex(str(kid).replace("-", "")))
		pssh: str = base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")
		return pssh

	def get_pssh_mpd(self, xml_mpd):
		root = ET.fromstring(xml_mpd)
		pssh = None
		namespaces = {
			'': 'urn:mpeg:dash:schema:mpd:2011',
			'cenc': 'urn:mpeg:cenc:2013'
		}
		content_protection = root.find(".//{urn:mpeg:dash:schema:mpd:2011}AdaptationSet//{urn:mpeg:dash:schema:mpd:2011}ContentProtection[@schemeIdUri='urn:mpeg:dash:mp4protection:2011'][@value='cenc']", namespaces)
		if content_protection is not None:
			default_kid = content_protection.get('{urn:mpeg:cenc:2013}default_KID')
			kid = default_kid.replace('-', '')
			pssh = self.get_pssh(kid)

		return pssh

	def get_tracks(self, title):
		try:
			playlist = self.hulu_client.load_playlist(title.service_data["bundle"]["eab_id"])
		except requests.HTTPError as e:
			res = e.response.json()
			raise self.log.exit(f" - {res['message']} ({res['code']})")

		self.license_url = playlist["dash_pr_server"] if self.playready else playlist["wv_server"]

		manifest = playlist["stream_url"]

		if 'disney' in manifest:
			mpd = self.session.get(manifest).text
			mpd_data = self.remove_parts_mpd(mpd)
			pssh = self.get_pssh_mpd(mpd_data)

			tracks = Tracks.from_mpd(
				url=manifest,
				session=self.session,
				source=self.ALIASES[0]
			)
			#for track in tracks:
			#	print("pssh:",track.pssh)

			if not self.playready:
				tracks0 = []
				for track in tracks.videos:
					track.psshWV = [pssh]
					if int(track.width) >= int(1920):
						rep = track.extra[0]
						id = rep.get("id")
						if 'ALT_1' in id:
							tracks0.append(track)
					else:
						tracks0.append(track)
				tracks.videos = tracks0
		else:
			tracks = Tracks.from_mpd(
				url=manifest,
				session=self.session,
				source=self.ALIASES[0]
			)

		for track in tracks.videos:
			if track.hdr10:
				# MPD only says HDR10+, but Hulu HDR streams are always Dolby Vision Profile 8 with HDR10+ compatibility
				track.hdr10 = False
				track.dv = True

		for track in tracks.audios:
			if not track.psshPR:
				try:
					track.psshPR = next(x.psshPR for x in tracks.videos if x.psshPR)
				except: pass
			if not track.psshWV:
				try:
					track.psshWV = next(x.psshWV for x in tracks.videos if x.psshWV)
				except: pass
			if not track.psshWV and not track.psshPR:
				raise ValueError("No PSSH found in tracks.videos")

		if self.acodec:
			tracks.audios = [x for x in tracks.audios if (x.codec or "")[:4] == self.AUDIO_CODEC_MAP[self.acodec]]
			
		try:
			for sub_lang, sub_url in playlist["transcripts_urls"]["webvtt"].items():
				tracks.add(TextTrack(
					id_=hashlib.md5(sub_url.encode()).hexdigest()[0:6],
					source=self.ALIASES[0],
					url=sub_url,
					# metadata
					codec="vtt",
					language=sub_lang,
					forced=False,  # TODO: find out if sub is forced
					sdh=False  # TODO: find out if sub is SDH/CC, it's actually quite likely to be true
				))
		except KeyError:
			pass
		
		for track in tracks:
			track.needs_proxy = False
		return tracks

	def get_chapters(self, title):
		return []

	def certificate(self, **_):
		return None  # will use common privacy cert

	def license(self, challenge, track, **_):
		res = self.session.post(
			url=self.license_url,
			data=challenge  # expects bytes
		)
		self.log.debug(res.text) if self.playready else self.log.debug(res.content)
		return res.text if self.playready else res.content

	# Service specific functions

	def configure(self):
		self.device = Device(
			device_code=self.config["device"]["FireTV4K"]["code"],
			device_key=self.config["device"]["FireTV4K"]["key"]
		)
		self.session.headers.update({
			"User-Agent": self.config["user_agent"],
		})
		for schemas in self.config["drm"]["schemas"]:
			if schemas["type"] == "WIDEVINE":
				schemas_widevine = [schemas]
			elif schemas["type"] == "PLAYREADY":
				schemas_playready = [schemas]
		self.playback_params = {
			"all_cdn": False,
			"region": "US",
			"language": "en",
			"interface_version": "1.9.0",
			"network_mode": "wifi",
			"play_intent": "resume",
			"playback": {
				"version": 2,
				"video": {
					"dynamic_range": "DOLBY_VISION",
					"codecs": {
						"values": [x for x in self.config["codecs"]["video"] if x["type"] == self.vcodec],
						"selection_mode": self.config["codecs"]["video_selection"]
					}
				},
				"audio": {
					"codecs": {
						"values": self.config["codecs"]["audio"],
						"selection_mode": self.config["codecs"]["audio_selection"]
					}
				},
				"drm": {
					"multi_key": True,
					"values": schemas_playready if self.playready else schemas_widevine,
					"selection_mode": self.config["drm"]["selection_mode"],
					"hdcp": self.config["drm"]["hdcp"]
				},
				"manifest": {
					"type": "DASH",
					"https": True,
					"multiple_cdns": False,
					"patch_updates": True,
					"hulu_types": True,
					"live_dai": True,
					"secondary_audio": True,
					"live_fragment_delay": 3
				},
				"segments": {
					"values": [{
						"type": "FMP4",
						"encryption": {
							"mode": "CENC",
							"type": "CENC"
						},
						"https": True
					}],
					"selection_mode": "ONE"
				}
			}
		}
		self.hulu_client = HuluClient(
			device=self.device,
			session=self.session,
			version=self.config["device"].get("device_version"),
			**self.playback_params
		)
