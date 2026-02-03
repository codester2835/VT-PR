import os
import re
import time
import json
import m3u8
import base64
import requests

import click

from vinetrimmer.objects import TextTrack, Title, Tracks
from vinetrimmer.services.BaseService import BaseService

class Sonyliv(BaseService):
    """
    SonyLiv India streaming service (https://sonyliv.com).
    \b
    Authorization: Cookies + accessToken(from Browser Local Storage)
    Security: UHD@L3, doesn't seem to care about releases.

    Needs Indian IP address
    Script By https://telegram.me/divine_404
    """

    ALIASES = ["SL", "sonyliv"]

    TITLE_RE = r"^(?:https?://(?:www\.)?sonyliv.com/(?P<type>movies|shows)/[a-z0-9-]+-)?(?P<id>\d+)"

    @staticmethod
    @click.command(name="Sonyliv", short_help="https://sonyliv.com")
    @click.argument("title", type=str, required=False)
    @click.option("-d", "--device", default="chrome",
                type=click.Choice(["chrome", "android", "safari"], case_sensitive=False),
                help="Device to use for requesting manifest.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Sonyliv(ctx, **kwargs)
    
    def __init__(self, ctx, title, device):
        super().__init__(ctx)
        self.m = self.parse_title(ctx, title)
        self.manifestDevice = device

        self.vcodec = ctx.parent.params["vcodec"] or "H264"
        self.acodec = ctx.parent.params["acodec"] or "EC3"
        self.range = ctx.parent.params["range_"] or "SDR"
        self.quality = ctx.parent.params.get("quality") or 1080

        self.profile = ctx.obj.profile

        self.device_id = None
        self.app_version = None
        self.accessToken = None
        self.securityToken = None
        self.license_api = None
        self.cacheData = None

        self.configure()

    def get_titles(self):
        tempHeaders = self.session.headers.copy()
        tempHeaders.update({
            "Host": "apiv2.sonyliv.com",
            "Security_token": self.securityToken,
            "Session_id": self.session.cookies.get('sessionId', None, 'apiv2.sonyliv.com'),
            "Device_id": self.device_id,
            "App_version": self.app_version,
        })

        r = requests.get(
            url = self.config['endpoints']['title'].format(id=self.m['id']),
            headers = tempHeaders,
            cookies = self.reqCookies,
            proxies=self.session.proxies
        )
        try:
            titleRes = json.loads(r.content.decode())
        except json.JSONDecodeError:
            raise ValueError(f"Received Irrelevant Title API Response: {r.text}")

        for correct in titleRes['resultObj']['containers']:
            if int(correct['id']) == int(self.m['id']):
                titleRes = correct.copy()

        if titleRes['metadata']['objectSubtype'] == 'MOVIE_BUNDLE' or titleRes['metadata']['objectSubtype'] == 'MOVIE':
            return Title(
                id_=self.m['id'],
                type_=Title.Types.MOVIE,
                name=titleRes['metadata']['title'],
                year=titleRes['metadata']['emfAttributes']['release_year'] if 'release_year' in titleRes['metadata']['emfAttributes'] else titleRes['metadata']['emfAttributes']['release_date'].split('-')[0],
                original_lang=titleRes['metadata']['language'],
                source=self.ALIASES[0],
                service_data=titleRes,
            )
        
        elif (titleRes['layout'] == "BUNDLE_ITEM"):
            bucket = []

            if (titleRes['metadata']['objectSubtype'] == "EPISODIC_SHOW"):
                ep_count = titleRes['episodeCount']
                r = requests.get(
                    url = self.config['endpoints']['season'].format(id=titleRes['id'], ep_start=0, ep_end=ep_count-1),
                    headers = tempHeaders,
                    cookies = self.reqCookies,
                    proxies=self.session.proxies
                )

                try:
                    seasonRes = json.loads(r.content.decode())
                except json.JSONDecodeError:
                    raise ValueError(f"Received Irrelevant Season API Response: {r.text}")
                
                for episode in seasonRes['resultObj']['containers'][0]['containers']:
                    bucket.append({
                        "episode_id": episode['id'],
                        "series_name": titleRes['metadata']['title'],
                        "season_number": titleRes['metadata']['season'] if ('season' in titleRes['metadata'].keys()) else "1",
                        "episode_number": episode['metadata']['episodeNumber'],
                        "episode_name": episode['metadata']['episodeTitle'],
                        "episode_org_lang": episode['metadata']['language'],
                        "service_data": episode
                    })

            if (titleRes['metadata']['objectSubtype'] == "SHOW"):
                for season in titleRes['containers']:
                    if season['metadata']['objectSubtype'] == "SEASON" and int(season['parents'][0]['parentId']) == int(self.m['id']):
                        ep_count = season['episodeCount']
                        r = requests.get(
                            url = self.config['endpoints']['season'].format(id=season['id'], ep_start=0, ep_end=ep_count-1),
                            headers = tempHeaders,
                            cookies = self.reqCookies,
                            proxies=self.session.proxies
                        )
                        try:
                            seasonRes = json.loads(r.content.decode())
                        except json.JSONDecodeError:
                            raise ValueError(f"Received Irrelevant Season API Response: {r.text}")

                        for episode in seasonRes['resultObj']['containers'][0]['containers']:
                            bucket.append({
                                "episode_id": episode['id'],
                                "series_name": titleRes['metadata']['title'],
                                "season_number": season['metadata']['season'],
                                "episode_number": episode['metadata']['episodeNumber'],
                                "episode_name": episode['metadata']['episodeTitle'],
                                "episode_org_lang": episode['metadata']['language'],
                                "service_data": episode
                            })
                    
                    elif season['metadata']['objectSubtype'] == "EPISODE_RANGE" and int(season['parents'][0]['parentId']) == int(self.m['id']):
                        ep_count = season['episodeCount']
                        r = requests.get(
                            url = self.config['endpoints']['season'].format(id=season['id'], ep_start=0, ep_end=ep_count-1),
                            headers = tempHeaders,
                            cookies = self.reqCookies,
                            proxies=self.session.proxies
                        )

                        try:
                            seasonRes = json.loads(r.content.decode())
                        except json.JSONDecodeError:
                            raise ValueError(f"Received Irrelevant Season API Response: {r.text}")
                        
                        for episode in seasonRes['resultObj']['containers'][0]['containers']:
                            bucket.append({
                                "episode_id": episode['id'],
                                "series_name": titleRes['metadata']['title'],
                                "season_number": season['metadata']['season'],
                                "episode_number": episode['metadata']['episodeNumber'],
                                "episode_name": episode['metadata']['episodeTitle'],
                                "episode_org_lang": episode['metadata']['language'],
                                "service_data": episode
                            })
            
            if not bucket == []:
                return [Title(
                    id_=b['episode_id'],
                    type_=Title.Types.TV,
                    name=b['series_name'],
                    season=b['season_number'],
                    episode=b['episode_number'],
                    episode_name=b['episode_name'],
                    original_lang=b['episode_org_lang'],
                    source=self.ALIASES[0],
                    service_data=b['service_data']
                ) for b in bucket]
        else:
            self.log.exit(" - Title unsupported.")
                                 
    def get_tracks(self, title):
        
        if self.vcodec == 'H265':
            if self.range == 'DV':
                client = '{"device_make":"Amazon","device_model":"AFTMM","display_res":"2160","viewport_res":"2160","supp_codec":"HEVC,H264,AAC,EAC3,AC3,ATMOS","audio_decoder":"EAC3,AAC,AC3,ATMOS","hdr_decoder":"DOLBY_VISION","td_user_useragent":"com.onemainstream.sonyliv.android\/8.95 (Android 7.1.2; en_IN; AFTMM; Build\/NS6281 )"}'
            elif self.range == 'HDR10':
                client = '{"device_make":"Amazon","device_model":"AFTMM","display_res":"2160","viewport_res":"2160","supp_codec":"HEVC,H264,AAC,EAC3,AC3,ATMOS","audio_decoder":"EAC3,AAC,AC3,ATMOS","hdr_decoder":"HDR10","td_user_useragent":"com.onemainstream.sonyliv.android\/8.95 (Android 7.1.2; en_IN; AFTMM; Build\/NS6281 )"}'
            elif self.range == 'SDR':
                client = '{"device_make":"Amazon","device_model":"AFTMM","display_res":"2160","viewport_res":"2160","supp_codec":"HEVC,H264,AAC,EAC3,AC3,ATMOS","audio_decoder":"EAC3,AAC,AC3,ATMOS","hdr_decoder":"HLG","td_user_useragent":"com.onemainstream.sonyliv.android\/8.95 (Android 7.1.2; en_IN; AFTMM; Build\/NS6281 )"}'
        else:
            client = '{"os_name":"Mac OS","os_version":"10.15.7","device_make":"none","device_model":"none","display_res":"1470","viewport_res":"894","conn_type":"4g","supp_codec":"H264,AV1,AAC","client_throughput":"16000","td_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36","hdr_decoder":"UNKNOWN","audio_decoder":"STEREO"}'
            
        tempHeaders = self.session.headers.copy()
        if "X-Playback-Session-Id" in tempHeaders.keys():
            tempHeaders.pop("X-Playback-Session-Id")
        tempHeaders.update({
            "Host": "apiv2.sonyliv.com",
            "Content-Type": "application/json",
            "X-Via-Device": "true",
            "Security_token": self.securityToken,
            "App_version": self.app_version,
            "Device_id": self.device_id,
            "Session_id": self.session.cookies.get('sessionId', None, 'apiv2.sonyliv.com'),
            "Authorization": "Bearer " + self.accessToken,
            "Td_client_hints": client,
        })

        if str(title.type) == "Types.MOVIE":
            if 'containers' not in title.service_data.keys():
                _id_ = title.service_data['metadata']['contentId']
            else:
                for mov in title.service_data['containers']:
                    if mov['metadata']['contentSubtype'] == "MOVIE":
                        _id_ = mov['id']
        else:
            _id_ = title.service_data['metadata']['contentId']

        r = requests.post(
            url = self.config['endpoints']['manifest'].format(id=_id_, bid=self.cacheData['contactId']['id']),
            headers = tempHeaders,
            cookies = self.reqCookies,
            json = {
                "actionType": "play",
                "browser": 'chrome',
                "deviceId": self.device_id,
                "hasLAURLEnabled": True,
                "os": "Mac OS",
                "platform": "web",
                "adsParams":{
                    "idtype": "uuid",
                    "rdid": self.device_id,
                    "is_lat": 0,
                    "ppid": self.cacheData['contactId']['PPID']
                }
            },
            proxies=self.session.proxies
        )
        try:
            manifestRes = json.loads(r.content.decode())
            self.log.debug(f"\n{json.dumps(manifestRes, indent=4)}")
            if manifestRes['resultCode'] != "OK":
                self.log.exit(manifestRes['message'])
        except json.JSONDecodeError:
            raise ValueError(f"Received Irrelevant Manifest API Response: {r.text}")
        
        mpd_url = manifestRes['resultObj']['videoURL']

        try:
            self.license_api = manifestRes['resultObj']['LA_Details']['laURL']
        except Exception as e:
            pass

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.sonyliv.com/",
            "X-Playback-Session-Id": self.device_id,
            "Origin": "https://www.sonyliv.com",
        })

        r = self.session.get(mpd_url)

        if not '.m3u8' in str(mpd_url):
            tracks = Tracks.from_mpd(
                url = mpd_url,
                data = r.content.decode(),
                session = self.session,
                source = self.ALIASES[0],
            )
        
        else:
            tracks = Tracks.from_m3u8(
                m3u8.loads(str(r.content.decode())),
                source = self.ALIASES[0],
            )

        # Checking SDR/HDR/DV
        for video in tracks.videos:
            video.hdr10 = False
            video.dv = False
            video.hlg = False
        av_range_ =  manifestRes['resultObj']['additionalDataJson']['video_quality']
        if av_range_ == "HDR":
            for video in tracks.videos:
                video.hdr10 = True
        if av_range_ == "DOLBY_VISION":
            for video in tracks.videos:
                video.dv = True
        if av_range_ == "HLG":
            for video in tracks.videos:
                video.hlg = True

        # Adding subtitle tracks
        for sub in manifestRes['resultObj']['subtitle']:
            tracks.add(TextTrack(
                id_= sub['subtitleId'],
                source = self.ALIASES[0],
                url = sub['subtitleUrl'],
                codec = "vtt", #hardcoded
                language = sub['subtitleLanguageName'],
            ), warn_only=True)

        for track in tracks:
            track.needs_proxy = True
        return tracks

    def get_chapters(self, title):
        return []

    def certificate(self, **_):
        return None

    def license(self, challenge: bytes, title: Title, **_):

        if self.license_api == None: 

            licHeaders = self.session.headers.copy()
            if "X-Playback-Session-Id" in licHeaders.keys():
                licHeaders.pop("X-Playback-Session-Id")
            licHeaders.update({
                "Host": "apiv2.sonyliv.com",
                "Content-Type": "application/json",
                "Security_token": self.securityToken,
                "Device_id": self.device_id,
                "X-Via-Device": "true",
                "Authorization": "Bearer " + self.accessToken
            })
            r = requests.post(
                url = self.config['endpoints']['license'],
                headers = licHeaders,
                json = {
                    "platform": self.config['device'][self.manifestDevice]['platform'],
                    "deviceId": self.device_id,
                    "actionType": "play",
                    "browser": self.manifestDevice,
                    "assetId": title.service_data['metadata']['contentId'],
                    "os": self.manifestDevice
                }
            )

            try:
                licRes = json.loads(r.content.decode())
            except json.JSONDecodeError:
                raise ValueError(f"Irrelevant License API Response: {r.text}")
            
            self.license_api = licRes['resultObj']['laURL']

            return requests.post(
                url = self.license_api,
                data=challenge,
                # proxies=self.session.proxies,
            ).content  
        
        else:
            return requests.post(
                url = self.license_api,
                data=challenge,
                # proxies=self.session.proxies,
            ).content


    def configure(self):
        self.session.headers.update({
            "User-Agent": self.config['device'][self.manifestDevice]['user-agent'],
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.sonyliv.com/",
            "Origin": "https://www.sonyliv.com",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
        })

        if not self.cookies:
            raise self.log.exit(" - Please add cookies")
        self.reqCookies = {
            "_abck": self.session.cookies.get('_abck', None, '.sonyliv.com'),
            "ak_bmsc": self.session.cookies.get('ak_bmsc', None, '.sonyliv.com'),
            "bm_sz": self.session.cookies.get('bm_sz', None, '.sonyliv.com'),
        }

        self.device_id = self.config['device'][self.manifestDevice]['device_id']
        self.app_version = self.config['device'][self.manifestDevice]['app_version']
        self.prepToken()
  
 
    def prepToken(self):
        cache_path = self.get_cache("{profile}_ProfileCache.json".format(profile=self.profile))

        if not os.path.isfile(cache_path):
            self.cacheData = {"vt_profile": self.profile}
            self.log.info(" + Generating Cache...")
            self.log.info("Enter your access_token from Browser (Dev Tools -> Application -> Local Storage -> 'https://www.sonyliv.com' -> accessToken):")
            self.accessToken = str(input(">"))
            self.cacheData["accessToken"] = { 
                "rawToken": self.accessToken,
                "data": json.loads(base64.b64decode(f"{str(self.accessToken.split('.')[1]) + '=='}"))
            }
            if int(self.cacheData['accessToken']['data']['exp']) < int(time.time()):
                raise self.log.exit(f" - Provided access_token is expired.")

            self.log.info("Getting security_token...")
            self.securityToken = self.getSecurityToken()
            userData = self.refresh()

            self.cacheData["securityToken"] = {
                "rawToken": self.securityToken,
                "data": json.loads(base64.b64decode(f"{str(self.accessToken.split('.')[1]) + '=='}"))
            }
            self.cacheData["contactId"] = {
                "id": userData['resultObj']['contactMessage'][0]['contactID'],
                "PPID": self.getHash(userData['resultObj']['contactMessage'][0]['contactID'])
            }

            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fd:
                json.dump(self.cacheData, fd, indent = 2)
        
        else:
            with open(cache_path, "r+", encoding="utf-8") as fd:
                self.cacheData = json.loads(fd.read())
                if int(self.cacheData['accessToken']['data']['exp']) < int(time.time()):
                    raise self.log.exit("- access_token expired. Delete cache file and update cookies.")
                else:
                    self.accessToken = self.cacheData['accessToken']['rawToken']

                if int(self.cacheData['securityToken']['data']['exp']) < int(time.time()):
                    self.log.info("security_token expired, Getting a new one...")
                    self.securityToken = self.getSecurityToken()
                    userData = self.refresh()

                    self.cacheData["securityToken"] = {
                        "rawToken": self.securityToken,
                        "data": json.loads(base64.b64decode(f"{str(self.securityToken.split('.')[1]) + '=='}"))
                    }
                    self.cacheData["contactId"] = {
                        "id": userData['resultObj']['contactMessage'][0]['contactID'],
                        "PPID": self.getHash(userData['resultObj']['contactMessage'][0]['contactID'])
                    }
                else:
                    self.securityToken = self.cacheData['securityToken']['rawToken']
                    userData = self.refresh()
                    self.cacheData["contactId"] = {
                        "id": userData['resultObj']['contactMessage'][0]['contactID'],
                        "PPID": self.getHash(userData['resultObj']['contactMessage'][0]['contactID'])
                    }
                    self.log.info("Using Account Tokens from Cache.")
                fd.seek(0)
                fd.truncate()
                json.dump(self.cacheData, fd, indent = 2)
        return
        
    def getSecurityToken(self):
        tempHeaders = self.session.headers.copy()
        tempHeaders.update({
            "Host": "www.sonyliv.com",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Site": "none",
        })

        try:
            resp = requests.get(
                url="https://sonyliv.com",
                headers = tempHeaders,
                cookies = self.reqCookies,
                proxies=self.session.proxies
            )
            resp = str(resp.content.decode())
            scToken = resp.split('securityToken:{resultCode:"OK",message:"",errorDescription:"200-10000",resultObj:"')[1].split('",systemTime')[0]
            json.loads(base64.b64decode(f"{scToken.split('.')[1] + '.'}"))
            return scToken
        except Exception as e:
            self.log.exit(e)

    def refresh(self):
        tempHeaders = self.session.headers.copy()
        tempHeaders.update({
            "Host": "apiv2.sonyliv.com",
            "X-Via-Device": "true",
            "Security_token": self.securityToken,
            "App_version": self.app_version,
            "Device_id": self.device_id,
            "Session_id": self.session.cookies.get('sessionId', None, 'apiv2.sonyliv.com'),
            "Authorization": self.accessToken,
        })

        self.reqCookies.update({
            "sessionId": self.session.cookies.get('sessionId', None, 'apiv2.sonyliv.com'),
            "bm_sv": self.session.cookies.get('bm_sv', None, '.sonyliv.com'),
            "AKA_A2": self.session.cookies.get('AKA_A2', None, '.sonyliv.com'),
            "bm_mi": self.session.cookies.get('bm_mi', None, '.sonyliv.com'),
        })

        userData = requests.get(
            url = self.config['endpoints']['refresh'],
            headers = tempHeaders,
            cookies = self.reqCookies,
            proxies=self.session.proxies
        )
        userData = json.loads(userData.content.decode())
        if userData['resultCode'] == "OK" and userData['message'] == "SUCCESS":
            return userData
        else:
            self.log.error(userData)
            self.log.exit("Unintended API Response.")
        
    def getHash(self, contactId):
        tempHeaders = self.session.headers.copy()
        tempHeaders.update({
            "Host": "apiv2.sonyliv.com",
            "Content-Type": "application/json",
            "X-Via-Device": "true",
            "Security_token": self.securityToken,
            "App_version": self.app_version,
            "Device_id": self.device_id,
            "Session_id": self.session.cookies.get('sessionId', None, 'apiv2.sonyliv.com'),
            "Authorization": self.accessToken,            
        })
        hashData = requests.post(
            url = self.config['endpoints']['hash'],
            headers = tempHeaders,
            json = {
                "baseId": contactId
            },
            cookies = self.reqCookies,
            proxies=self.session.proxies
        )
        hashData = json.loads(hashData.content.decode())
        if hashData['resultCode'] == "OK":
            return hashData['resultObj']['ppId']
        else:
            self.log.error(hashData)
            self.log.exit("Unintended API Response.")
