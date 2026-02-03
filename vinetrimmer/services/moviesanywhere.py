import base64
import json
import click
import re
import requests
from requests import JSONDecodeError
from httpx import URL
import uuid
import xmltodict
import struct
import binascii
import os
import yt_dlp
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
import time

from datetime import datetime
from langcodes import Language
from vinetrimmer.objects import AudioTrack, TextTrack, Title, Tracks, VideoTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.vendor.pymp4.parser import Box


class MoviesAnywhere(BaseService):
	"""
	Service code for US' streaming service MoviesAnywhere (https://moviesanywhere.com).

	\b
	Authorization: Cookies
	Security: SD-HD@L3, FHD SDR@L1 (any active device), FHD-UHD HDR-DV@L1 (whitelisted devices).

	NOTE: Can be accessed from any region, it does not seem to care.
		  Accounts can only mount services when its US based though.

	"""
	ALIASES = ["MA", "MoviesAnywhere"]

	TITLE_RE = r"https://moviesanywhere\.com(?P<id>.+)"

	VIDEO_CODEC_MAP = {
		"H264": ["avc"],
		"H265": ["hvc", "hev", "dvh"]
	}
	AUDIO_CODEC_MAP = {
		"AAC": ["mp4a", "HE", "stereo"],
		"AC3": ["ac3"],
		"EC3": ["ec3", "atmos"]
	}

	@staticmethod
	@click.command(name="MoviesAnywhere", short_help="https://moviesanywhere.com")
	@click.argument("title", type=str)
   
	@click.pass_context
	def cli(ctx, **kwargs):
		return MoviesAnywhere(ctx, **kwargs)

	def __init__(self, ctx, title):
		super().__init__(ctx)
		self.parse_title(ctx, title)
		self.configure()
		self.playready = True if "certificate_chain" in dir(ctx.obj.cdm) else False #ctx.obj.cdm.device.type == LocalDevice.Types.PLAYREADY
		self.atmos = ctx.parent.params["atmos"]
		self.vcodec = ctx.parent.params["vcodec"]
		self.acodec = ctx.parent.params["acodec"]
		self.range = ctx.parent.params["range_"]
		self.quality = ctx.parent.params["quality"] or 1080

		if self.range != "SDR" or self.quality > 1080:
			self.log.info(" + Setting VideoCodec to H265")
			self.vcodec = "H265"

	def get_titles(self):
		self.headers={
			"authorization": f"Bearer {self.access_token}",
			"install-id": self.install_id,
		}
		res = self.session.post(
			url="https://gateway.moviesanywhere.com/graphql",
			json={
				"platform": "web",
				"variables": {"slug": self.title}, # Does not seem to care which platform will be used to give the best tracks available
				"extensions": '{"persistedQuery":{"sha256Hash":"5cb001491262214406acf8237ea2b8b46ca6dbcf37e70e791761402f4f74336e","version":1}}',  # ONE_GRAPH_PERSIST_QUERY_TOKEN
			},
			headers={
				"authorization": f"Bearer {self.access_token}",
				"install-id": self.install_id,
			}
		)

		try:
			self.content = res.json()
		except JSONDecodeError:
			self.log.exit(" - Not able to return title information")

		title_data = self.content["data"]["page"]

		title_info = [
			x
			for x in title_data["components"]
			if x["__typename"] == "MovieMarqueeComponent"
		][0]
		
		title_info["title"] = re.sub(r" \(.+?\)", "", title_info["title"])

		title_data = self.content["data"]["page"]
		try:
			Id = title_data["components"][0]["mainAction"]["playerData"]["playable"]["id"]
		except KeyError:
			self.log.exit(" - Account does not seem to own this title")
		
		return Title(
				id_=Id,
				type_=Title.Types.MOVIE,
				name=title_info["title"],
				year=title_info["year"],
				original_lang="en",
				source=self.ALIASES[0],
				service_data=title_data,
			)
	
	def get_pssh_init(self, url):
		init = 'init.mp4'

		files_to_delete = [init]
		for file_name in files_to_delete:
			if os.path.exists(file_name):
				os.remove(file_name)
	
		ydl_opts = {
			'format': 'bestvideo[ext=mp4]/bestaudio[ext=m4a]/best',
			'allow_unplayable_formats': True,
			'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
			'no_warnings': True,
			'quiet': True,
			'outtmpl': init,
			'no_merge': True,
			'test': True,
		}
	
		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			info_dict = ydl.extract_info(url, download=True)
			url = info_dict.get("url", None)
			if url is None:
				raise ValueError("Failed to download the video")
			video_file_name = ydl.prepare_filename(info_dict)

		raw = Path(init).read_bytes()
		wv = raw.rfind(bytes.fromhex('edef8ba979d64acea3c827dcd51d21ed'))
		if wv != -1:
			psshWV = base64.b64encode(raw[wv-12:wv-12+raw[wv-9]]).decode('utf-8')

		playready_system_id = binascii.unhexlify("9A04F07998404286AB92E65BE0885F95")
		pssh_boxes = []
		mp4_file = "init.mp4"

		with open(mp4_file, "rb") as f:
			data = f.read()

		index = 0
		while index < len(data):
			if index + 8 > len(data):
				break

			box_size, box_type = struct.unpack_from(">I4s", data, index)
			if box_size < 8 or index + box_size > len(data):
				break  

			if box_type == b'moov' or box_type == b'moof':
				sub_index = index + 8
				while sub_index < index + box_size:
					sub_size, sub_type = struct.unpack_from(">I4s", data, sub_index)
					if sub_type == b'pssh':
						system_id = data[sub_index + 12: sub_index + 28]
						if system_id == playready_system_id:
							pssh_data_size = struct.unpack_from(">I", data, sub_index + 28)[0]
							pssh_data = data[sub_index + 32: sub_index + 32 + pssh_data_size]
							pssh_boxes.append(pssh_data)
					sub_index += sub_size

			if box_type == b'pssh':
				system_id = data[index + 12: index + 28]
				if system_id == playready_system_id:
					pssh_data_size = struct.unpack_from(">I", data, index + 28)[0]
					pssh_data = data[index + 32: index + 32 + pssh_data_size]
					pssh_boxes.append(pssh_data)

			index += box_size

		if pssh_boxes:
			for i, pssh_data in enumerate(pssh_boxes):
				pssh_box = (
					struct.pack(">I", len(pssh_data) + 32) +  
					b"pssh" +  
					struct.pack(">I", 0) +  
					playready_system_id +  
					struct.pack(">I", len(pssh_data)) +  
					pssh_data  
				)
				base64_pssh = base64.b64encode(pssh_box).decode()
				#print(base64_pssh)
				psshPR = base64_pssh

				header_offset = 6
				xml_data = pssh_data[header_offset:].decode("utf-16le", errors='ignore')
				xml_start = xml_data.find("<WRMHEADER")
				xml_end = xml_data.find("</WRMHEADER>")
				
				if xml_start != -1 and xml_end != -1:
					xml_content = xml_data[xml_start:xml_end + len("</WRMHEADER>")]
					xml_root = ET.fromstring(xml_content)
					#print(ET.tostring(xml_root, encoding="utf-8").decode())
				else:
					raise Exception("Failed to locate XML content in PSSH.")
		else:
			raise Exception("No PlayReady PSSH boxes found.")


		for file_name in files_to_delete:
			if os.path.exists(file_name):
				os.remove(file_name)
		return psshWV, psshPR

	def get_tracks(self, title):
		player_data = self.content["data"]["page"]["components"][0]["mainAction"]["playerData"]["playable"]
		videos = []
		audios = []
		for cr in player_data["videoAssets"]["dash"].values():
			if not cr:
				continue
			for manifest in cr:
				tracks = Tracks.from_mpd(
					url=manifest["url"],
					source=self.ALIASES[0],
					session=self.session,
				)

				for video in tracks.videos:
					psshWV, psshPR = self.get_pssh_init(manifest["url"])
					video.psshWV = psshWV
					video.psshPR = psshPR
					video.license_url = manifest["playreadyLaUrl"] if self.playready else manifest["widevineLaUrl"]
					video.contentId = URL(video.license_url).params._dict["ContentId"][
						0
					]
					videos += [video]
				# Extract Atmos audio track if available.
				for audio in tracks.audios:
					audio.psshWV = psshWV
					audio.psshPR = psshPR
					audio.license_url = manifest["playreadyLaUrl"] if self.playready else manifest["widevineLaUrl"]
					audio.contentId = URL(audio.license_url).params._dict["ContentId"][
						0
					]
					if "atmos" in audio.url:
						audio.atmos = True
					audios += [audio]

		corrected_video_list = []
		for res in ("uhd", "hdp", "hd", "sd"):
			for video in videos:
				if f"_{res}_video" not in video.url or not video.url.endswith(
					f"&r={res}"
				):
					continue

				if corrected_video_list and any(
					video.id == vid.id for vid in corrected_video_list
				):
					continue

				if "dash_hevc_hdr" in video.url:
					video.hdr10 = True
				if "dash_hevc_dolbyvision" in video.url:
					video.dv = True

				corrected_video_list += [video]

		tracks.add(corrected_video_list)
		tracks.audios = audios
		tracks.videos = [x for x in tracks.videos if (x.codec or "")[:3] in self.VIDEO_CODEC_MAP[self.vcodec]]

		return tracks

	def get_chapters(self, title):
		return []

	def certificate(self, **_):
		return None  # will use common privacy cert

	def license(self, challenge: bytes, track: Tracks, **_) -> bytes:
		if not isinstance(challenge, bytes):
			challenge = bytes(challenge, 'utf-8')

		playback_session_id = str(uuid.uuid4())

		license_message = requests.post(
			headers = {
				'accept': '*/*',
				'accept-language': 'en-US,en;q=0.9,en-IN;q=0.8',
				'cache-control': 'no-cache',
				'content-type': 'application/octet-stream',
				'dnt': '1',
				'origin': 'https://moviesanywhere.com',
				'pragma': 'no-cache',
				'priority': 'u=1, i',
				'referer': 'https://moviesanywhere.com/',
				'sec-ch-ua-mobile': '?0',
				'sec-fetch-dest': 'empty',
				'sec-fetch-mode': 'cors',
				'sec-fetch-site': 'same-site',
				'soapaction': '"http://schemas.microsoft.com/DRM/2007/03/protocols/AcquireLicense"',
				'user_agent': 'Dalvik/2.1.0 (Linux; U; Android 14; SM-S911B Build/UP1A.231005.007)',
			},
			params = {
				"authorization": self.access_token, 
				"playbackSessionId": playback_session_id
			},
			url=track.license_url,
			data=challenge,  # expects bytes
		)

		self.log.debug(license_message.text)

		if "errorCode" in license_message.text:
			self.log.exit(f" - Cannot complete license request: {license_message.text}")

		return license_message.content

		
	def configure(self):
		access_token = None
		install_id = None
		for cookie in self.cookies:
			if cookie.name == "secure_access_token":
				access_token = cookie.value
			elif cookie.name == "install_id":
				install_id = cookie.value

		self.access_token = access_token
		self.install_id = install_id

		self.session.headers.update(
			{
				"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
				"Origin": "https://moviesanywhere.com",
				"Authorization": f"Bearer {self.access_token}",
			}
		)
