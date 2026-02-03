import base64
import html
import logging
import os
import shutil
import subprocess
import sys
import traceback
from http.cookiejar import MozillaCookieJar
import urllib3


import time
import click
import requests
from appdirs import AppDirs
from langcodes import Language
from pymediainfo import MediaInfo
from pathlib import Path

from vinetrimmer import services
from vinetrimmer.config import Config, config, credentials, directories, filenames
from vinetrimmer.objects import AudioTrack, Credential, TextTrack, Title, Titles, VideoTrack
from vinetrimmer.objects.tracks import Track
from vinetrimmer.objects.vaults import InsertResult, Vault, Vaults
from vinetrimmer.utils import is_close_match
from vinetrimmer.utils.click import (AliasedGroup, ContextData, acodec_param, language_param, quality_param,
									 range_param, vcodec_param, wanted_param)
from vinetrimmer.utils.collections import as_list, merge_dict
from vinetrimmer.utils.io import load_yaml
from pywidevine import Device, Cdm, RemoteCdm
from pywidevine import PSSH as PSSHWV

from vinetrimmer.vendor.pymp4.parser import Box

from pyplayready.cdm import Cdm as CdmPr
from pyplayready import Device as DevicePR
from pyplayready.system.pssh import PSSH
from pyplayready.crypto.ecc_key import ECCKey
from pyplayready.system.bcert import CertificateChain, Certificate
from Crypto.Random import get_random_bytes


def reprovision_device(prd_path) -> None:
	"""
	Reprovision a Playready Device (.prd) by creating a new leaf certificate and new encryption/signing keys.
	Will override the device if an output path or directory is not specified

	Only works on PRD Devices of v3 or higher
	"""
	prd_path = Path(prd_path)
	if not prd_path.is_file():
		raise Exception("prd_path: Not a path to a file, or it doesn't exist.")

	device = DevicePR.load(prd_path)

	if device.group_key is None:
		raise Exception("Device does not support reprovisioning, re-create it or use a Device with a version of 3 or higher")

	device.group_certificate.remove(0)

	encryption_key = ECCKey.generate()
	signing_key = ECCKey.generate()

	device.encryption_key = encryption_key
	device.signing_key = signing_key

	new_certificate = Certificate.new_leaf_cert(
		cert_id=get_random_bytes(16),
		security_level=device.group_certificate.get_security_level(),
		client_id=get_random_bytes(16),
		signing_key=signing_key,
		encryption_key=encryption_key,
		group_key=device.group_key,
		parent=device.group_certificate
	)
	device.group_certificate.prepend(new_certificate)

	prd_path.parent.mkdir(parents=True, exist_ok=True)
	prd_path.write_bytes(device.dumps())


def get_cdm(log, service, profile=None, cdm_name=None):
	"""
	Get CDM Device (either remote or local) for a specified service.
	Raises a ValueError if there's a problem getting a CDM.
	"""
	if not cdm_name:
		cdm_name = config.cdm.get(service) or config.cdm.get("default")
	if not cdm_name:
		raise ValueError("A CDM to use wasn't listed in the vinetrimmer.yml config")
	if isinstance(cdm_name, dict):
		if not profile:
			raise ValueError("CDM config is mapped for profiles, but no profile was chosen")
		cdm_name = cdm_name.get(profile) or config.cdm.get("default")
		if not cdm_name:
			raise ValueError(f"A CDM to use was not mapped for the profile {profile}")
	
	try:
		try:
			device = Device.load(os.path.join(directories.devices, f"{cdm_name}.wvd"))
		except:
			device_path = os.path.abspath(os.path.join(directories.devices, f"{cdm_name}.prd"))
			if ( int( time.time() ) - int( os.path.getmtime( device_path ) ) ) > 160000: #roughly 2 days
				try:
					reprovision_device(device_path)
					log.info(f" + Reprovisioned Playready Device (.prd) file, {cdm_name}")
				except Exception as e:
					log.warning(f"Reprovision Failed - {e}")
			device = DevicePR.load(device_path)			
		return device
	except FileNotFoundError:
		try:
			device = Device.from_dir(os.path.join(directories.devices, cdm_name))
			return device
		except:
			pass

		cdm_api = next(iter(x for x in config.cdm_api if x["name"] == cdm_name), None)
		if cdm_api:
			device = None
			try:
				device = RemoteCdm(**cdm_api)
			except:
				from vinetrimmer.utils.widevine.device import RemoteDevice
				device = RemoteDevice(**cdm_api) # seller distributed some wack version of serve in pywidevine
			finally:
				return device
		raise ValueError(f"Device {cdm_name!r} not found")


def get_service_config(service):
	"""Get both service config and service secrets as one merged dictionary."""
	#print(filenames.service_config.format(service=service.lower())) # This line is probably where the error while loading config under Linux originates #TO-DO
	service_config = load_yaml(filenames.service_config.format(service=service.lower()))

	user_config = (load_yaml(filenames.user_service_config.format(service=service.lower())) or load_yaml(filenames.user_service_config.format(service=service)))

	if user_config:
		merge_dict(service_config, user_config)

	return service_config


def get_profile(service):
	"""
	Get the default profile for a service from the config.
	"""
	profile = config.profiles.get(service)
	if profile is False:
		return None  # auth-less service if `false` in config
	if not profile:
		profile = config.profiles.get("default")
	if not profile:
		raise ValueError(f"No profile has been defined for '{service}' in the config.")

	return profile


def get_cookie_jar(service, profile):
	"""Get the profile's cookies if available."""
	cookie_file = os.path.join(directories.cookies, service.lower(), f"{profile}.txt")
	if not os.path.isfile(cookie_file):
		cookie_file = os.path.join(directories.cookies, service, f"{profile}.txt")
	if os.path.isfile(cookie_file):
		cookie_jar = MozillaCookieJar(cookie_file)
		with open(cookie_file, "r+", encoding="utf-8") as fd:
			unescaped = html.unescape(fd.read())
			fd.seek(0)
			fd.truncate()
			fd.write(unescaped)
		cookie_jar.load(ignore_discard=True, ignore_expires=True)
		return cookie_jar
	return None

def save_cookies(service_name, service, profile):
	"""Save cookies from service session to profile's cookies."""
	cookie_file = os.path.join(directories.cookies, service_name.lower(), f"{profile}.txt")
	if not os.path.isfile(cookie_file):
		cookie_file = os.path.join(directories.cookies, service_name	, f"{profile}.txt")

	if os.path.isfile(cookie_file):
		cookie_jar = MozillaCookieJar(cookie_file)
		for cookie in service.session.cookies:
			cookie_jar.set_cookie(cookie)
		cookie_jar.save(ignore_discard=True, ignore_expires=True)

def get_credentials(service, profile="default"):
	"""Get the profile's credentials if available."""
	cred = credentials.get(service, {})

	if isinstance(cred, dict):
		cred = cred.get(profile)
	elif profile != "default":
		return None

	if cred:
		if isinstance(cred, list):
			return Credential(*cred)
		else:
			return Credential.loads(cred)


@click.group(name="dl", short_help="Download from a service.", cls=AliasedGroup, context_settings=dict(
	help_option_names=["-?", "-h", "--help"],
	max_content_width=116,  # max PEP8 line-width, -4 to adjust for initial indent
	default_map=config.arguments
))
@click.option("--debug", is_flag=True, hidden=True)  # Handled by vinetrimmer.py
@click.option("-p", "--profile", type=str, default=None,
			  help="Profile to use when multiple profiles are defined for a service.")
@click.option("-q", "--quality", callback=quality_param, default=None,
			  help="Download Resolution, defaults to best available.")
@click.option("-cr", "--closest-resolution", is_flag=True, default=False,
			  help="If resolution specified not found, defaults to closest resolution available")
@click.option("-v", "--vcodec", callback=vcodec_param, default="H264",
			  help="Video Codec, defaults to H264.")
@click.option("-a", "--acodec", callback=acodec_param, default=None,
			  help="Audio Codec")
@click.option("-vb", "--vbitrate", "vbitrate", type=str,
			  default=None,
			  help="Video Bitrate, defaults to Max.")
@click.option("-ab", "--abitrate", "abitrate", type=int,
			  default=None,
			  help="Audio Bitrate, defaults to Max.")		
@click.option("-ac", "--audio-channels", type=str, default=None, 
			  help="Select Audio by Channels Configuration, e.g `2.0`, `5.1`, `2.0,5.1`")
@click.option("-mac", "--max-audio-compatability", is_flag=True, default=False,
			  help="Select multiple audios for maximum compatibility with all devices")
@click.option("-aa", "--atmos", is_flag=True, default=False,
			  help="Prefer Atmos Audio")
@click.option("-r", "--range", "range_", callback=range_param, default="SDR",
			  help="Video Color Range, defaults to SDR.")
@click.option("-w", "--wanted", callback=wanted_param, default=None,
			  help="Wanted episodes, e.g. `S01-S05,S07`, `S01E01-S02E03`, `S02-S02E03`, e.t.c, defaults to all.")
@click.option("-le", "--latest-episode", is_flag=True, default=False,
			  help="Download the latest episode on episodes list.")
@click.option("-al", "--alang", callback=language_param, default="orig",
			  help="Language wanted for audio.")
@click.option("-sl", "--slang", callback=language_param, default="all",
			  help="Language wanted for subtitles.")
@click.option("--proxy", type=str, default=None,
			  help="Proxy URI to use. If a 2-letter country is provided, it will try get a proxy from the config.")
@click.option("-A", "--audio-only", is_flag=True, default=False,
			  help="Only download audio tracks.")
@click.option("-S", "--subs-only", is_flag=True, default=False,
			  help="Only download subtitle tracks.")
@click.option("-C", "--chapters-only", is_flag=True, default=False,
			  help="Only download chapters.")
@click.option("-ns", "--no-subs", is_flag=True, default=False,
			  help="Do not download subtitle tracks.")
@click.option("-na", "--no-audio", is_flag=True, default=False,
			  help="Do not download audio tracks.")
@click.option("-nv", "--no-video", is_flag=True, default=False,
			  help="Do not download video tracks.")
@click.option("-nc", "--no-chapters", is_flag=True, default=False,
			  help="Do not download chapters tracks.")
@click.option("-ad", "--audio-description", is_flag=True, default=False,
			  help="Download audio description tracks.")
@click.option("--list", "list_", is_flag=True, default=False,
			  help="Skip downloading and list available tracks and what tracks would have been downloaded.")
@click.option("--selected", is_flag=True, default=False,
			  help="List selected tracks and what tracks are downloaded.")
@click.option("--cdm", type=str, default=None,
			  help="Override the CDM that will be used for decryption.")
@click.option("--keys", is_flag=True, default=False,
			  help="Skip downloading, retrieve the decryption keys (via CDM or Key Vaults) and print them.")
@click.option("--cache", is_flag=True, default=False,
			  help="Disable the use of the CDM and only retrieve decryption keys from Key Vaults. "
				   "If a needed key is unable to be retrieved from any Key Vaults, the title is skipped.")
@click.option("--no-cache", is_flag=True, default=False,
			  help="Disable the use of Key Vaults and only retrieve decryption keys from the CDM.")
@click.option("--no-proxy", is_flag=True, default=False,
			  help="Force disable all proxy use.")
@click.option("-nm", "--no-mux", is_flag=True, default=False,
			  help="Do not mux the downloaded and decrypted tracks.")
@click.option("--mux", is_flag=True, default=False,
			  help="Force muxing when using --audio-only/--subs-only/--chapters-only.")
@click.option("-ss", "--strip-sdh", is_flag=True, default=False,
			  help="Stip SDH subtitles and convert them to CC. Plus fix common errors.")
@click.option("-mf", "--match-forced", is_flag=True, default=False,
			  help="Only select forced subtitles matching with specified audio language")
@click.pass_context
def dl(ctx, profile, cdm, *_, **__):
	log = logging.getLogger("dl")

	service = ctx.params.get("service_name") or services.get_service_key(ctx.invoked_subcommand)
	if not service:
		log.exit(" - Unable to find service")

	profile = profile or get_profile(service)
	service_config = get_service_config(service)
	vaults = []
	for vault in config.key_vaults:
		try:
			vaults.append(Config.load_vault(vault))
		except Exception as e:
			log.error(f" - Failed to load vault {vault['name']!r}: {e}")
	vaults = Vaults(vaults, service=service)
	local_vaults = sum(v.type == Vault.Types.LOCAL for v in vaults)
	remote_vaults = sum(v.type == Vault.Types.REMOTE for v in vaults)
	log.info(f" + {local_vaults} Local Vault{'' if local_vaults == 1 else 's'}")
	log.info(f" + {remote_vaults} Remote Vault{'' if remote_vaults == 1 else 's'}")

	try:
		device = get_cdm(log, service, profile, cdm)
	except ValueError as e:
		raise log.exit(f" - {e}")

	device_name = device.system_id if "vmp" in dir(device) else device.get_name().replace("_", " ").upper()
	s = "" if "vmp" in dir(device) else "S"
	log.info(f" + Loaded {device.__class__.__name__}: {device_name} ({s}L{device.security_level})")
	cdm = Cdm.from_device(device) if "vmp" in dir(device) else CdmPr.from_device(device)

	if profile:
		cookies = get_cookie_jar(service, profile)
		credentials = get_credentials(service, profile)
		if not cookies and not credentials and service_config.get("needs_auth", True):
			raise log.exit(f" - Profile {profile!r} has no cookies or credentials")
	else:
		cookies = None
		credentials = None

	ctx.obj = ContextData(
		config=service_config,
		vaults=vaults,
		cdm=cdm,
		profile=profile,
		cookies=cookies,
		credentials=credentials,
	)

@dl.result_callback()
@click.pass_context
def result(ctx, service, quality, closest_resolution, range_, wanted, alang, slang, acodec, audio_only, subs_only, chapters_only, audio_description, audio_channels, max_audio_compatability, match_forced,
		   list_, keys, cache, no_cache, no_subs, no_audio, no_video, no_chapters, atmos, vbitrate, abitrate: int, no_mux, mux, selected, latest_episode, strip_sdh, *_, **__):
	def ccextractor():
		log.info("Extracting EIA-608 captions from stream with CCExtractor")
		track_id = f"ccextractor-{track.id}"
		# TODO: Is it possible to determine the language of EIA-608 captions?
		cc_lang = track.language
		try:
			cc = track.ccextractor(
				track_id=track_id,
				out_path=filenames.subtitles.format(id=track_id, language_code=cc_lang),
				language=cc_lang,
				original=False,
			)
		except EnvironmentError:
			log.warning(" - CCExtractor not found, cannot extract captions")
		else:
			if cc:
				title.tracks.add(cc)
				log.info(" + Extracted")
			else:
				log.info(" + No captions found")

	log = service.log

	service_name = service.__class__.__name__

	urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) # Disable insecure request warnings

	if service_name in ["DisneyPlus", "Hulu"]: # Always retrieve fresh keys for DSNP so that content_keys variable has 2 kid:key pairs, change this to fetch all keys for title from cache
		global content_keys
		no_cache = True

	log.info("Retrieving Titles")
	try:
		titles = Titles(as_list(service.get_titles()))
	except requests.HTTPError as e:
		log.debug(traceback.format_exc())
		raise log.exit(f" - HTTP Error {e.response.status_code}: {e.response.reason}")
	if not titles:
		raise log.exit(" - No titles returned!")
	titles.order()
	titles.print()

	if latest_episode:
		titles = Titles(as_list(titles[-1]))

	for title in titles.with_wanted(wanted):
		if title.type == Title.Types.TV:
			log.info("Getting tracks for {title} S{season:02}E{episode:02}{name} [{id}]".format(
				title=title.name,
				season=title.season or 0,
				episode=title.episode or 0,
				name=f" - {title.episode_name}" if title.episode_name else "",
				id=title.id,
			))
		else:
			log.info("Getting tracks for {title}{year} [{id}]".format(
				title=title.name,
				year=f" ({title.year})" if title.year else "",
				id=title.id,
			))

		try:
			title.tracks.add(service.get_tracks(title), warn_only=True)
			title.tracks.add(service.get_chapters(title))
			#if not next((x for x in title.tracks.videos if x.language.language in (v_lang or lang)), None) and title.tracks.videos:
			 #   lang = [title.tracks.videos[0].language["language"]]
			  #  log.info("Defaulting language to {lang} for tracks".format(lang=lang[0].upper()))
		except requests.HTTPError as e:
			log.debug(traceback.format_exc())
			raise log.exit(f" - HTTP Error {e.response.status_code}: {e.response.reason}")
		title.tracks.sort_videos()
		title.tracks.sort_audios(by_language=alang)
		title.tracks.sort_subtitles(by_language=slang)
		title.tracks.sort_chapters()

		for track in title.tracks:
			if track.language == Language.get("none"):
				track.language = title.original_lang
			track.is_original_lang = is_close_match(track.language, [title.original_lang])

		if not list(title.tracks):
			log.error(" - No tracks returned!")
			continue
		if not selected:			
			log.info("> All Tracks:")
			title.tracks.print()

		try:
			# Modified video track selection to choose closest resolution if exact match not found
			if quality and closest_resolution:
				available_resolutions = [int(track.height) for track in title.tracks.videos]
				if available_resolutions == []:
					log.error(" - No video tracks available")
					continue
				if quality not in available_resolutions:
					closest_res = min(available_resolutions, key=lambda x: abs(x - quality))
					log.warning(f" - No {quality}p resolution available, using closest available: {closest_res}p")
					quality = closest_res

			if range_ == "DV+HDR":
				title.tracks.select_videos_multi(["HDR10", "DV"], by_quality=quality, by_vbitrate=vbitrate)
			else:
				title.tracks.select_videos(by_quality=quality, by_vbitrate=vbitrate, by_range=range_, one_only=True)
			title.tracks.select_audios(by_language=alang, by_bitrate=abitrate, with_descriptive=audio_description, by_codec=acodec, by_channels=audio_channels, max_audio_compatability=max_audio_compatability)
			forced = alang if (match_forced and alang) else True
			title.tracks.select_subtitles(by_language=slang, with_forced=forced)
		except ValueError as e:
			log.error(f" - {e}")
			continue

		if no_video:
			title.tracks.videos.clear()
		if no_audio:
			title.tracks.audios.clear()
		if no_subs:
			title.tracks.subtitles.clear()
		if no_chapters:
			title.tracks.chapters.clear()	
		if audio_only or subs_only or chapters_only:
			title.tracks.videos.clear()
			if audio_only:
				if not subs_only:
					title.tracks.subtitles.clear()
				if not chapters_only:
					title.tracks.chapters.clear()
			elif subs_only:
				if not audio_only:
					title.tracks.audios.clear()
				if not chapters_only:
					title.tracks.chapters.clear()
			elif chapters_only:
				if not audio_only:
					title.tracks.audios.clear()
				if not subs_only:
					title.tracks.subtitles.clear()

			if not mux:
				no_mux = True

		log.info("> Selected Tracks:")
		title.tracks.print()
		   

		if list_:
			continue  # only wanted to see what tracks were available and chosen

		skip_title = False

		#Download might fail as auth token expires quickly for Hotstar. This is a problem for big downloads like a 4k track. So we reverse tracks and download audio first and large video later.
		for track in (list(title.tracks)[::-1] if service_name == "Hotstar" else title.tracks):
			if not keys:
				log.info(f"Downloading: {track}")
			if (service_name == "AppleTVPlus" or service_name == "iTunes") and "VID" in str(track):
				track.encrypted = True
			if track.encrypted:
				if not track.get_pssh(service.session):
					raise log.exit(" - Failed to get PSSH")

				if track.psshPR:
					log.info(f" + PSSH (PR): {track.psshPR}")
				if track.psshWV: 
					log.info(f" + PSSH (WV): {track.psshWV}")

				if not track.get_kid(service.session):
					raise log.exit(" - Failed to get KID")
				log.info(f" + KID: {track.kid}")
			if not keys:
				if track.needs_proxy:
					proxy = next(iter(service.session.proxies.values()), None)
				else:
					proxy = None

				if service:
					save_cookies(service_name, service, ctx.obj.profile)
				if isinstance(track, TextTrack):
					time.sleep(5) # Sleep 5 seconds before downloading each subtitle track to avoid 403 errors
				track.download(directories.temp, headers=service.session.headers, proxy=proxy, session=service.session)
				log.info(" + Downloaded")
			if isinstance(track, VideoTrack) and track.needs_ccextractor_first and not no_subs:
				ccextractor()
			if track.encrypted:
				log.info("Decrypting...")
				if track.key:
					log.info(f" + KEY: {track.key} (Static)")
				elif not no_cache:
					track.key, vault_used = ctx.obj.vaults.get(track.kid, title.id) #To-Do return all keys for title.id for DSNP, HULU
					if track.key:
						log.info(f" + KEY: {track.key} (From {vault_used.name} {vault_used.type.name} Key Vault)")
						for vault in ctx.obj.vaults.vaults:
							if vault == vault_used:
								continue
							result = ctx.obj.vaults.insert_key(
								vault, service_name.lower(), track.kid, track.key, title.id, commit=True
							)
							if result == InsertResult.SUCCESS:
								log.info(f" + Cached to {vault} vault")
							elif result == InsertResult.ALREADY_EXISTS:
								log.info(f" + Already exists in {vault} vault")
				if not track.key:
					if cache:
						skip_title = True
						break

					session_id = ctx.obj.cdm.open()
					log.info(f"CDM Session ID - {session_id.hex()}")

					if "common_privacy_cert" in dir(ctx.obj.cdm) and track.psshWV:
						ctx.obj.cdm.set_service_certificate(
							session_id,
							service.certificate(
								challenge=ctx.obj.cdm.service_certificate_challenge,
								title=title,
								track=track,
								session_id=session_id
							) or ctx.obj.cdm.common_privacy_cert
						)
						license = service.license(
								challenge=ctx.obj.cdm.get_license_challenge(session_id=session_id, pssh=PSSHWV(track.psshWV)),
								title=title,
								track=track,
								session_id=session_id
							)
						assert license
						ctx.obj.cdm.parse_license(
							session_id,
							license
						)
					elif "common_privacy_cert" not in dir(ctx.obj.cdm) and track.psshPR:
						challenge = ctx.obj.cdm.get_license_challenge(session_id, PSSH(track.psshPR).wrm_headers[0])
						license = service.license(
								challenge=challenge,
								title=title,
								track=track,
							 session_id=session_id
							)
						assert license

						log.debug(license)

						if isinstance(license, bytes):
							license = license.decode("utf-8")
						
						ctx.obj.cdm.parse_license(
							session_id, 
							license # expects the XML License not base64 encoded str.
						)
					else:
						raise log.exit("Unable to license")

					if service:
						save_cookies(service_name, service, ctx.obj.profile)
					content_keys = [
						(str(x.kid).replace("-", ""), x.key.hex()) for x in ctx.obj.cdm.get_keys(session_id) if x.type == "CONTENT"
					] if "common_privacy_cert" in dir(ctx.obj.cdm) else [
						(str(x.key_id).replace("-", ""), x.key.hex()) for x in ctx.obj.cdm.get_keys(session_id)
					]

					ctx.obj.cdm.close(session_id)

					if not content_keys:
						raise log.exit(" - No content keys were returned by the CDM!")
					log.info(f" + Obtained content keys from the CDM")
					
					for kid, key in content_keys:
						if kid == "b770d5b4bb6b594daf985845aae9aa5f":
							# Amazon HDCP test key
							continue
						log.info(f" + {kid}:{key}")
						
					# cache keys into all key vaults
					for vault in ctx.obj.vaults.vaults:
						log.info(f"Caching to {vault} vault")
						cached = 0
						already_exists = 0
						for kid, key in content_keys:
							result = ctx.obj.vaults.insert_key(vault, service_name.lower(), kid, key, title.id)
							if result == InsertResult.FAILURE:
								log.warning(f" - Failed, table {service_name.lower()} doesn't exist in the vault.")
							elif result == InsertResult.SUCCESS:
								cached += 1
							elif result == InsertResult.ALREADY_EXISTS:
								already_exists += 1
						ctx.obj.vaults.commit(vault)
						log.info(f" + Cached {cached}/{len(content_keys)} keys")
						if already_exists:
							log.info(f" + {already_exists}/{len(content_keys)} keys already existed in vault")
						if cached + already_exists < len(content_keys):
							log.warning(f"	Failed to cache {len(content_keys) - cached - already_exists} keys")
					# use matching content key for the tracks key id
					track.key = next((key for kid, key in content_keys if kid == track.kid), None)
					if track.key:
						log.info(f" + KEY: {track.key} (From CDM)")
					else:
						raise log.exit(f" - No content key with the key ID \"{track.kid}\" was returned")
				if keys:
					continue
				# TODO: Move decryption code to Track
				if not config.decrypter:
					raise log.exit(" - No decrypter specified")
				if service_name in ["DisneyPlus", "Hulu"] or (config.decrypter == "packager" and not (track.descriptor == Track.Descriptor.ISM)) :
					platform = {"win32": "win", "darwin": "osx"}.get(sys.platform, sys.platform)
					names = ["shaka-packager", "packager", f"packager-{platform}"]
					executable = next((x for x in (shutil.which(x) for x in names) if x), None)
					if not executable:
						raise log.exit(" - Unable to find packager binary")
					dec = os.path.splitext(track.locate())[0].replace("enc", "dec") + ".mp4"
					
					os.makedirs(directories.temp, exist_ok=True)
					try:
						os.makedirs(directories.temp, exist_ok=True)
						args = [
							executable,
							"input={},stream={},output={}".format(
								track.locate(),
								track.__class__.__name__.lower().replace("track", ""),
								dec
							),
							"--enable_raw_key_decryption", "--keys",
							",".join([
								f"label=0:key_id={track.kid.lower()}:key={track.key.lower()}",
								# Apple TV+ needs this as shaka pulls the incorrect KID, idk why
								f"label=1:key_id=00000000000000000000000000000000:key={track.key.lower()}",
							]) if service_name not in ["DisneyPlus", "Hulu"] else 
							",".join(
								[# This right here is a hack as DSNP/HULU sometimes has 2 kids and returns 2 keys. FFS.
									"label={}:key_id={}:key={}".format(
										content_keys.index(pair),
										pair[0],
										pair[1]
									)
									for pair
									in content_keys
								]
							), 
							"--temp_dir", directories.temp
						]
						subprocess.run(args, check=True)
					except subprocess.CalledProcessError:
						raise log.exit(" - Failed!")
					
				elif service_name not in ["DisneyPlus", "Hulu"] or (config.decrypter == "mp4decrypt" or (track.descriptor == Track.Descriptor.ISM)):
					executable = shutil.which("mp4decrypt")
					if not executable:
						raise log.exit(" - Unable to find mp4decrypt binary")
					dec = os.path.splitext(track.locate())[0].replace("enc", "dec") + ".mp4"
					os.makedirs(directories.temp, exist_ok=True)
					try:
						os.makedirs(directories.temp, exist_ok=True)
						subprocess.run([
							executable,
							"--show-progress",
							"--key", f"{track.kid.lower()}:{track.key.lower()}",
							track.locate(),
							dec,
						])
					except subprocess.CalledProcessError:
						raise log.exit(" - Failed!")
				else:
					log.exit(f" - Unsupported decrypter: {config.decrypter}")
				track.swap(dec)
				log.info(" + Decrypted")

			if keys:
				continue

			if isinstance(track, AudioTrack) and track.descriptor == Track.Descriptor.ISM and track.atmos:
				#--enable-libmfx is the only difference between 6.1.1 and 7.X. 
				#FFMPEG 6.1.1 is necessary as that version correctly puts in place an init.mp4 for EAC-3-JOC ie Atmos 
				#https://github.com/GyanD/codexffmpeg/releases/tag/6.1.1
				#https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest
				executable = shutil.which("ffmpeg") 
				if not executable:
					raise log.exit(" - Unable to find ffmpeg binary")
				eac3 = os.path.splitext(track.locate())[0] + ".eac3" 
				os.makedirs(directories.temp, exist_ok=True)
				try:
					os.makedirs(directories.temp, exist_ok=True)
					exec_string = f"{executable} -i {track.locate()} -hide_banner -loglevel error -map 0 -c:a copy {eac3}"
					subprocess.run(exec_string, check=True)
				except subprocess.CalledProcessError:
					raise log.exit(" - Failed!")
				track.swap(eac3)
				log.info(" + Fixed ISM Atmos")

			if track.needs_repack or (config.decrypter == "mp4decrypt" and isinstance(track, (VideoTrack, AudioTrack))):
				log.info("Repackaging stream with FFmpeg (to fix malformed streams)")
				track.repackage()
				log.info(" + Repackaged")

			if isinstance(track, VideoTrack) and track.needs_ccextractor and not no_subs:
				ccextractor()

			if isinstance(track, TextTrack) and strip_sdh:
				track.strip_sdh()
				log.info("Stripped SDH subtitles to CC with subby")


		if skip_title:
			for track in title.tracks:
				track.delete()
			continue
		if keys:
			continue

		if range_ == "DV+HDR":
			try:
				hybrid_path = title.tracks.make_hybrid()
				log.info(f" + Hybrid DV+HDR created: {hybrid_path}")
			except Exception as e:
				log.warning(f" - Skipped Hybrid DV+HDR: {e}")

		if not list(title.tracks) and not title.tracks.chapters:
			continue
		# mux all final tracks to a single mkv file
		if no_mux:
			if title.tracks.chapters:
				final_file_path = directories.downloads
				if title.type == Title.Types.TV:
					final_file_path = os.path.join(final_file_path, title.parse_filename(folder=True))
				os.makedirs(final_file_path, exist_ok=True)
				chapters_loc = filenames.chapters.format(filename=title.filename)
				title.tracks.export_chapters(chapters_loc)
				shutil.move(chapters_loc, os.path.join(final_file_path, os.path.basename(chapters_loc)))
			for track in title.tracks:
				media_info = MediaInfo.parse(track.locate())
				#log.debug(media_info)
				final_file_path = directories.downloads
				if title.type == Title.Types.TV:
					final_file_path = os.path.join(
						final_file_path, title.parse_filename(folder=True)
					)
				os.makedirs(final_file_path, exist_ok=True)
				filename = title.parse_filename(media_info=media_info)
				if isinstance(track, (AudioTrack, TextTrack)):
					filename += f".{track.language}"
				extension = track.codec if isinstance(track, TextTrack) else os.path.splitext(track.locate())[1][1:]
				if isinstance(track, AudioTrack) and extension == "mp4":
					extension = "m4a"
				track.move(os.path.join(final_file_path, f"{filename}.{track.id}.{extension}"))
		else:
			log.info("Muxing tracks into an MKV container")
			muxed_location, returncode = title.tracks.mux(title.filename)
			if returncode == 1:
				log.warning(" - mkvmerge had at least one warning, will continue anyway...")
			elif returncode >= 2:
				raise log.exit(" - Failed to mux tracks into MKV file")
			log.info(" + Muxed")
			for track in title.tracks:
				track.delete()
			if title.tracks.chapters:
				try:
					os.unlink(filenames.chapters.format(filename=title.filename))
				except FileNotFoundError:
					pass
			media_info = MediaInfo.parse(muxed_location)
			final_file_path = directories.downloads
			if title.type == Title.Types.TV:
				final_file_path = os.path.join(
					final_file_path, title.parse_filename(media_info=media_info, folder=True)
				)
			os.makedirs(final_file_path, exist_ok=True)
			# rename muxed mkv file with new data from mediainfo data of it
			if audio_only:
				extension = "mka"
			elif subs_only:
				extension = "mks"
			else:
				extension = "mkv"
			shutil.move(
				muxed_location,
				os.path.join(final_file_path, f"{title.parse_filename(media_info=media_info)}.{extension}")
			)

	log.info("Processed all titles!")


def load_services():
	for service in services.__dict__.values():
		if callable(getattr(service, "cli", None)):
			dl.add_command(service.cli)


load_services()
