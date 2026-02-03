import json
import os
import re
import time
import uuid
from datetime import datetime

import base64
import click
import m3u8

from vinetrimmer.objects import MenuTrack, Title, Tracks
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.BamSDK import BamSdk
from vinetrimmer.utils.collections import as_list
from vinetrimmer.utils.io import get_ip_info


class DisneyPlus(BaseService):
	"""
	Service code for Disney's Disney+ streaming service (https://disneyplus.com).

	\b
	Authorization: Credentials
	Security: UHD@L1 FHD@L1 HD@L3, HEAVILY monitors high-profit and newly released titles!!

	\b
	Tips: - Some titles offer a setting in its Details tab to prefer "Remastered" or Original format
		  - You can specify which profile is used for its preferences and such in the config file
	"""

	ALIASES = ["DSNP", "disneyplus", "disney+"]
	TITLE_RE = [
		r"^https?://(?:www\.)?disneyplus\.com(?:/[a-z0-9-]+)?(?:/[a-z0-9-]+)?/(?P<type>browse)/(?P<id>entity-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

	]

	AUDIO_CODEC_MAP = {
		"AAC": ["aac"],
		"EC3": ["eac", "atmos"]
	}

	@staticmethod
	@click.command(name="DisneyPlus", short_help="https://disneyplus.com")
	@click.argument("title", type=str, required=False)
	@click.option("-m", "--movie", is_flag=True, default=False, help="Title is a movie.")
	@click.option("-s", "--scenario", default="tv-drm-ctr", help="Capability profile that specifies compatible codecs, streams, bit-rates, resolutions and such.",
		type=click.Choice([
			"android",
			"android-mobile",
			"android-mobile-drm",
			"android-mobile-drm-ctr",
			"android-tablet",
			"android-tablet-drm",
			"android-tablet-drm-ctr",
			"android-tv",
			"android-tv-drm",
			"android-tv-drm-ctr",
			"android~unlimited",
			"apple",
			"apple-mobile",
			"apple-mobile-drm",
			"apple-mobile-drm-cbcs",
			"apple-tablet",
			"apple-tablet-drm",
			"apple-tablet-drm-cbcs",
			"apple-tv",
			"apple-tv-drm",
			"apple-tv-drm-cbcs",
			"apple~unlimited",
			"browser",
			"browser-cbcs",
			"browser-drm-cbcs",
			"browser-drm-ctr",
			"browser~unlimited",
			"cbcs-high",
			"cbcs-regular",
			"chromecast",
			"chromecast-drm",
			"chromecast-drm-cbcs",
			"ctr-high",
			"ctr-regular",
			"handset-drm-cbcs",
			"handset-drm-cbcs-multi",
			"handset-drm-ctr",
			"handset-drm-ctr-lfr",
			"playstation",
			"playstation-drm",
			"playstation-drm-cbcs",
			"restricted-drm-ctr-sw",
			"roku",
			"roku-drm",
			"roku-drm-cbcs",
			"roku-drm-ctr",
			"tizen",
			"tizen-drm",
			"tizen-drm-ctr",
			"tv-drm-cbcs",
			"tv-drm-ctr",
			"tvs-drm-cbcs",
			"tvs-drm-ctr",
			"webos",
			"webos-drm",
			"webos-drm-ctr",
			# 1080p bypass for downgraded l3 devices, keep private!
			"drm-cbcs-multi"
			])
		)
	@click.pass_context
	def cli(ctx, **kwargs):
		return DisneyPlus(ctx, **kwargs)

	def __init__(self, ctx, title, movie, scenario):
		super().__init__(ctx)
		m = self.parse_title(ctx, title)
		self.movie = movie #or m.get("type") == "movies"
		#self.type = m.get("type")
		self.scenario = scenario

		self.vcodec = ctx.parent.params["vcodec"]
		self.acodec = ctx.parent.params["acodec"]
		self.range = ctx.parent.params["range_"]
		self.wanted = ctx.parent.params["wanted"]
		self.quality = ctx.parent.params["quality"] or 1080

		self.playready = True if "certificate_chain" in dir(ctx.obj.cdm) else False # ctx.obj.cdm.device.type == LocalDevice.Types.PLAYREADY

		self.region = None
		self.bamsdk = None
		self.device_token = None
		self.account_tokens = {}

		if self.range == "DV+HDR":
			self.scenario = "android~unlimited"
			
		self.configure()

	def get_titles(self):

		if self.movie:   
			#original_lang = self.get_hulu_series(self.title)['originalLanguage']										 
			data = self.get_hulu_series(self.title)["data"]["page"]
			movie = Title(
				id_=self.title,
				type_=Title.Types.MOVIE,
				name=data['visuals']['title'],
				#year=data['visuals']['metastringParts']['releaseYearRange']['startYear'],
				source=self.ALIASES[0],
				original_lang="en",
				service_data=data["containers"][-1]["visuals"]
			)

			movie.service_data = data["actions"][0]["resourceId"]
			
			return movie

		else:
			data = self.get_hulu_series(self.title)["data"].get("page")
			if not data:
				raise self.log.exit(" - No data returned")

			season_len = len(data["containers"][0]["seasons"])
			if data["containers"][0].get("type") == "episodes":
				if season_len == 0:
					raise self.log.exit(" - No seasons available")

			seasons = list()
			for x, season in enumerate(
				reversed(data["containers"][0]["seasons"]), start=1
			):
				episodes = self.get_hulu_season(season["id"])["data"]["season"]["items"]
				self.log.debug(episodes)
				seasons += [
					Title(
						id_=t2["id"],
						type_=Title.Types.TV,
						name=t2["visuals"]["title"],
						season=t2["visuals"].get("seasonNumber"),
						episode=t2["visuals"].get("episodeNumber"),
						episode_name=t2["visuals"]
						.get("episodeTitle")
						.replace("(Sub) ", ""),
						original_lang="en",
						source=self.ALIASES[0],
						service_data=t2,
					)
					for t2 in episodes
				]

			# Get mediaId from decoded resourceId
			for x in seasons:
				x.service_data["mediaMetadata"] = {}
				x.service_data["mediaMetadata"]["mediaId"] = x.service_data["actions"][0]["resourceId"]

			return seasons

		# get data for every episode in every season via looping due to the fact
		# that the api doesn't provide ALL episodes in the initial bundle api call.
		# TODO: The season info returned might also be paged/limited
		

	def get_tracks(self, title):
		# Refresh token in case it expired
		self.account_tokens = self.get_account_token(
			credential=self.credentials,
			device_family=self.config["bamsdk"]["family"],
			device_token=self.device_token,
		)
		if self.movie:
			tracks = self.get_manifest_tracks(
				self.get_manifest_url(
					media_id=title.service_data,
					scenario=self.scenario
				)
			)
		
		else:
			tracks = self.get_manifest_tracks(
				self.get_manifest_url(
					media_id=title.service_data["mediaMetadata"]["mediaId"],
					scenario=self.scenario
				)	
			)

		if (not any((x.codec or "").startswith("atmos") for x in tracks.audios)
				and not self.scenario.endswith(("-atmos", "~unlimited"))):
			self.log.info(" + Attempting to get Atmos audio from H265 manifest")
			try:
				atmos_scenario = self.get_manifest_tracks(
					self.get_manifest_url(
						media_id=title.service_data["mediaMetadata"]["mediaId"],
						scenario="tv-drm-ctr-h265-atmos"
					)
				)
			except:
				atmos_scenario = self.get_manifest_tracks(
					self.get_manifest_url(
						media_id=title.service_data,
						scenario="tv-drm-ctr-h265-atmos"
					)
				)
			tracks.audios.extend(atmos_scenario.audios)
			tracks.subtitles.extend(atmos_scenario.subtitles)

		for track in tracks:
			track.needs_proxy = False

		for audio in list(tracks.audios):
			# The EAC-3 2.0 in the manifest is simply a duplicate AAC 2.0 track
			if audio.codec == "eac" and audio.channels == "2.0" and "mp4a" in audio.url:
				tracks.audios.remove(audio)

		return tracks

	def get_chapters(self, title):
		return []

	def certificate(self, **_):
		return None if self.playready else self.config["certificate"]

	def license(self, challenge, **_):
		# Refresh token in case it expired
		self.account_tokens = self.get_account_token(
			credential=self.credentials,
			device_family=self.config["bamsdk"]["family"],
			device_token=self.device_token,
		)

		if self.playready:
			res = self.bamsdk.drm.playreadyLicense(
				licence=challenge,  # expects XML
				access_token=self.account_tokens["access_token"]
			)
		else:
			res = self.bamsdk.drm.widevineLicense(
				licence=challenge,  # expects bytes
				access_token=self.account_tokens["access_token"]
			)
		return res

	# Service specific functions

	def configure(self):
		self.session.headers.update({
			"Accept-Language": "en-US,en;q=0.5",
			"User-Agent": self.config["bamsdk"]["user_agent"],
			"Origin": "https://www.disneyplus.com"
		})

		self.log.info("Preparing")

		if (self.range != "SDR" or self.quality > 1080) and self.vcodec != "H265":
			# vcodec must be H265 for High Dynamic Range
			self.vcodec = "H265"
			self.log.info(f" + Switched video codec to H265 to be able to get {self.range} dynamic range")
		self.scenario = self.prepare_scenario(self.scenario, self.vcodec, self.range)
		self.log.info(f" + Scenario: {self.scenario}")

		self.log.info("Getting BAMSDK Configuration")

		ip_info = get_ip_info(self.session, fresh=True)
		self.region = ip_info["countryCode"].upper()
		self.config["location_x"] = ip_info["lat"]
		self.config["location_y"] = ip_info["lon"]
		self.log.info(f" + IP Location: {self.config['location_x']},{self.config['location_y']}")

		self.bamsdk = BamSdk(self.config["bamsdk"]["config"], self.session)
		self.session.headers.update(dict(**{
			k.lower(): v.replace(
				"{SDKPlatform}", self.config["bamsdk"]["platform"]
			).replace(
				"{SDKVersion}", self.config["bamsdk"]["version"]
			) for k, v in self.bamsdk.commonHeaders.items()
		}, **{
			"user-agent": self.config["bamsdk"]["user_agent"]
		}))

		self.log.debug(" + Capabilities:")
		for k, v in self.bamsdk.media.extras.items():
			self.log.debug(f"   {k}: {v}")

		self.log.info("Logging into Disney+")
		self.device_token, self.account_tokens = self.login(self.credentials)

		session_info = self.bamsdk.session.getInfo(self.account_tokens["access_token"])

		self.log.debug(session_info)

		if "errors" in session_info and session_info["errors"][0]["code"] == "access-token.invalid":
			self.account_tokens = self.get_account_token(
				credential=self.credentials,
				device_family=self.config["bamsdk"]["family"],
				device_token=self.device_token,
				refresh=True
			)
			session_info = self.bamsdk.session.getInfo(self.account_tokens["access_token"])
			self.log.debug(session_info)

				
		self.log.info(f" + Account ID: {session_info['account']['id']}")
		self.log.info(f" + Profile ID: {session_info['profile']['id']}")
		self.log.info(f" + Subscribed: {session_info['isSubscriber']}")
		self.log.info(f" + Account Region: {session_info['home_location']['country_code']}")
		self.log.info(f" + Detected Location: {session_info['location']['country_code']}")
		self.log.info(f" + Supported Location: {session_info['inSupportedLocation']}")
		self.log.info(f" + Device: {session_info['device']['platform']}")

		if not session_info["isSubscriber"]:
			raise self.log.exit(" - Cannot continue, account is not subscribed to Disney+.")

	@staticmethod
	def prepare_scenario(scenario, vcodec, range_):
		"""Prepare Disney+'s scenario based on other arguments and settings."""
		if scenario.endswith("~unlimited"):
			# if unlimited scenario, nothing needs to be appended or changed.
			# the scenario will return basically all streams it can.
			return scenario
		if vcodec == "H265":
			scenario += "-h265"
		if range_ == "HDR10":
			scenario += "-hdr10"
		elif range_ == "DV":
			scenario += "-dovi"
		return scenario

	def login(self, credential):
		"""Log into Disney+ and retrieve various authorisation keys."""
		device_token = self.create_device_token(
			family=self.config["bamsdk"]["family"],
			profile=self.config["bamsdk"]["profile"],
			application=self.config["bamsdk"]["applicationRuntime"],
			api_key=self.config["device_api_key"]
		)
		self.log.info(" + Obtained Device Token")
		account_tokens = self.get_account_token(
			credential=credential,
			device_family=self.config["bamsdk"]["family"],
			device_token=device_token,
		)
		self.log.info(" + Obtained Account Token")
		return device_token, account_tokens

	def create_device_token(self, family, profile, application, api_key):
		"""
		Create a Device Token for a specified device type.
		This tells the API's what is possible for your device.
		:param family: Device Family.
		:param profile: Device Profile.
		:param application: Device Runtime, the use case of the device.
		:param api_key: Device API Key.
		:returns: Device Exchange Token.
		"""
		# create an initial assertion grant used to identify the kind of device profile-level.
		# TODO: cache this, it doesn't need to be obtained unless the values change
		device_grant = self.bamsdk.device.createDeviceGrant(
			json={
				"deviceFamily": family,
				"applicationRuntime": application,
				"deviceProfile": profile,
				"attributes": {}
			},
			api_key=api_key
		)
		if "errors" in device_grant:
			raise self.log.exit(
				" - Failed to obtain the device assertion grant: "
				f"{device_grant['errors']}"
			)
		# exchange the assertion grant for a usable device token.
		device_token = self.bamsdk.token.exchange(
			data={
				"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
				"platform": family,
				"subject_token": device_grant["assertion"],
				"subject_token_type": self.bamsdk.token.subject_tokens["device"]
			},
			api_key=api_key
		)
		if "error" in device_token:
			raise self.log.exit(
				" - Failed to exchange the assertion grant for a device token: "
				f"{device_token['error_description']} [{device_token['error']}]"
			)
		return device_token["access_token"]

	def get_account_token(self, credential, device_family, device_token, refresh=False):
		"""
		Get an Account Token using Account Credentials and a Device Token, using a Cache store.
		It also refreshes the token if needed.
		"""
		if not credential:
			raise self.log.exit(" - No credentials provided, unable to log in.")
		tokens_cache_path = self.get_cache(f"tokens_{self.region}_{credential.sha1}.json")
		if os.path.isfile(tokens_cache_path):
			with open(tokens_cache_path, encoding="utf-8") as fd:
				tokens = json.load(fd)
			if os.stat(tokens_cache_path).st_ctime > (time.time() - tokens["expires_in"]) and not refresh:
				self.log.info(" + Using cached tokens...")
				return tokens
			# expired
			self.log.info(" + Refreshing...")
			tokens = self.refresh_token(
				device_family=device_family,
				refresh_token=tokens["refresh_token"],
				api_key=self.config["device_api_key"]
			)
		else:
			# first time
			self.log.info(" + Getting new tokens...")
			tokens = self.create_account_token(
				device_family=self.config["bamsdk"]["family"],
				email=credential.username,
				password=credential.password,
				device_token=device_token,
				api_key=self.config["device_api_key"]
			)

		os.makedirs(os.path.dirname(tokens_cache_path), exist_ok=True)
		with open(tokens_cache_path, "w", encoding="utf-8") as fd:
			json.dump(tokens, fd)

		return tokens

	def create_account_token(self, device_family, email, password, device_token, api_key):
		"""
		Create an Account Token using Account Credentials and a Device Token.
		:param device_family: Device Family.
		:param email: Account Email.
		:param password: Account Password.
		:param device_token: Device Token.
		:param api_key: Device API Key.
		:returns: Account Exchange Tokens.
		"""
		# log in to the account via bamsdk using the device token
		identity_token = self.bamsdk.bamIdentity.identityLogin(
			email=email,
			password=password,
			access_token=device_token
		)
		if "errors" in identity_token:
			raise self.log.exit(
				" - Failed to obtain the identity token: "
				f"{identity_token['errors']}"
			)
		# create an initial assertion grant used to identify the account
		# this seems to tie the account to the device token
		account_grant = self.bamsdk.account.createAccountGrant(
			json={"id_token": identity_token["id_token"]},
			access_token=device_token
		)
		# exchange the assertion grant for a usable account token.
		account_tokens = self.bamsdk.token.exchange(
			data={
				"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
				"platform": device_family,
				"subject_token": account_grant["assertion"],
				"subject_token_type": self.bamsdk.token.subject_tokens["account"]
			},
			api_key=api_key
		)
		# change profile and re-exchange if provided
		if self.config.get("profile"):
			profile_grant = self.change_profile(self.config["profile"], account_tokens["access_token"])
			account_tokens = self.bamsdk.token.exchange(
				data={
					"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
					"platform": device_family,
					"subject_token": profile_grant["assertion"],
					"subject_token_type": self.bamsdk.token.subject_tokens["account"]
				},
				api_key=api_key
			)
		return account_tokens

	def refresh_token(self, device_family, refresh_token, api_key):
		"""
		Refresh a Token using its adjacent refresh token.
		:param device_family: Device Family.
		:param refresh_token: Refresh Token.
		:param api_key: Device API Key.
		:returns: Account Exchange Token.
		"""
		return self.bamsdk.token.exchange(
			data={
				"grant_type": "refresh_token",
				"platform": device_family,
				"refresh_token": refresh_token
			},
			api_key=api_key
		)

	def change_profile(self, profile, access_token):
		"""
		Change to a different account user profile.
		:param profile: profile by name, number, or directly by profile ID.
		:param access_token: account access token.
		:returns: profile grant tokens.
		"""
		if not profile:
			raise self.log.exit(" - Profile cannot be empty")
		try:
			profile_id = uuid.UUID(str(profile))
			self.log.info(f" + Switching profile to {profile_id}")
			# is UUID
		except ValueError:
			profiles = self.bamsdk.account.getUserProfiles(access_token)
			if isinstance(profile, int):
				if len(profiles) < profile:
					raise self.log.exit(
						" - There isn't a {}{} profile for this account".format(
							profile, "tsnrhtdd"[(profile // 10 % 10 != 1) * (profile % 10 < 4) * profile % 10::4]
						)
					)
				profile_data = profiles[profile - 1]
			else:
				profile_data = [x for x in profiles if x["profileName"] == profile]
				if not profile_data:
					raise self.log.exit(f" - Profile {profile!r} does not exist in this account")
				profile_data = profile_data[0]
			profile_id = profile_data["profileId"]
			self.log.info(f" + Switching profile to {profile_data['profileName']!r} ({profile_id})")
		res = self.bamsdk.account.setActiveUserProfile(str(profile_id), access_token)
		if "errors" in res:
			raise self.log.exit(f" - Failed! {res['errors'][0]['description']}")
		return res

	def get_manifest_url(self, media_id, scenario):
		self.log.info(f"Retrieving manifest for {scenario}")
		self.session.headers['x-dss-feature-filtering'] = 'true'
		self.session.headers['x-application-version'] = '1.1.2'
		self.session.headers['x-bamsdk-client-id'] = 'disney-svod'
		self.session.headers['x-bamsdk-platform'] = 'javascript/windows/chrome'
		self.session.headers['x-bamsdk-version'] = '28.0'
		resolution = "1280x720" if str(self.scenario).lower() == "browser" else ""

		json_data = {
			'playback': {
				'attributes': {
					'resolution': {
						'max': [
							f'{resolution}',
						],
					},
					'protocol': 'HTTPS',
					'assetInsertionStrategy': 'SGAI',
					'playbackInitiationContext': 'ONLINE',
					'frameRates': [
						60,
					],
				},
			},
			'playbackId': media_id,
		}

		manifest = self.session.post(
			f'https://disney.playback.edge.bamgrid.com/v7/playback/{scenario}',
			headers={"authorization": f"Bearer {self.account_tokens['access_token']}"},
			json=json_data
		).json()

		self.chaps = {}
		self.chaps["editorial"] = manifest["stream"].get("editorial", {})
		
		self.log.debug(manifest["stream"]["sources"][0]['complete']['url'])
		return manifest["stream"]["sources"][0]['complete']['url']

	def get_manifest_tracks(self, url):
		manifest = self.session.get(url).text
		tracks = Tracks.from_m3u8(m3u8.loads(content=manifest, uri=url), source=self.ALIASES[0])
		if self.acodec:
			tracks.audios = [
				x for x in tracks.audios if (x.codec or "").split("-")[0] in self.AUDIO_CODEC_MAP[self.acodec]
			]
		for video in tracks.videos:
			# This is needed to remove weird glitchy NOP data at the end of stream
			video.needs_repack = True
		for audio in tracks.audios:
			bitrate = re.search(r"(?<=r/composite_)\d+|\d+(?=_complete.m3u8)", as_list(audio.url)[0])
			if not bitrate:
				bitrate = re.search(r"(\d+)(?=_hdri_complete-trimmed\.m3u8)", as_list(audio.url)[0])
				if not bitrate:
					raise self.log.warning(" - Unable to get bitrate for an audio track")
			audio.bitrate = int(bitrate.group()) * 1000
			if audio.bitrate == 1000_000:
				# DSNP lies about the Atmos bitrate
				audio.bitrate = 768_000
		for subtitle in tracks.subtitles:
			subtitle.codec = "vtt"
			subtitle.forced = subtitle.forced or subtitle.extra.name.endswith("--forced--")
			# sdh might not actually occur, either way DSNP CC == SDH :)
			subtitle.sdh = "[cc]" in subtitle.extra.name.lower() or "[sdh]" in subtitle.extra.name.lower()
		return tracks

	def get_hulu_series(self, content_id: str) -> dict:
		self.log.debug(self.config["bamsdk"])
		r = self.session.get(
			url=self.config["bamsdk"]["page"].format(id=content_id),
			params={
				"disableSmartFocus": True,
				"enhancedContainersLimit": 12,
				"limit": 999,
				"authorization": "",
			},
			headers={"authorization": f"Bearer {self.account_tokens['access_token']}"},
		).json()

		return r

	def get_hulu_season(self, season_id: str) -> dict:
		r = self.session.get(
			url=self.config["bamsdk"]["season"].format(id=season_id),
			params={"limit": 999},
			headers={"authorization": f"Bearer {self.account_tokens['access_token']}"},
		).json()

		return r
