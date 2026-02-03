import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
import re
import click
import requests

from vinetrimmer.objects import Title, Tracks, TextTrack ,Track,VideoTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.regex import find

from urllib.parse import urlparse,urljoin
import m3u8
import sys
import uuid
import random
import urllib.parse
import langcodes



class Viu(BaseService):
    """
    Service code for VIU streaming service (https://www.viu.com/).

    \b
    Authorization: Username-Password Cookies
    Security: HD@L3, NonDRM doesn't seem to care about releases.

    VIU has some regions supported:
    - 1: ID, MY
    - 2: SG, HK, TH, PH
    1 & 2 has different api

    \b
    """

    ALIASES = ["VIU", "viu", "Viu"]
    #GEOFENCE = ["us"]
    TITLE_RE = [
        r"(?:https?://(?:www\.)?viu\.com/ott/th/th/vod/)(?P<id>\d+)(?:/[a-zA-Z0-9-%]+)$",
    ]

    @staticmethod
    @click.command(name="Viu", short_help="https://www.viu.com/")
    @click.argument("title", type=str, required=False)
    @click.pass_context
    def cli(ctx, **kwargs):
        return Viu(ctx, **kwargs)

    def __init__(self, ctx, title):
        super().__init__(ctx)
        self.url=title
        self.title=self.parse_input( title)
        
        self.profile = ctx.obj.profile

        self._auth_codes = {}

        self._user_token = None

        self.cdm = ctx.obj.cdm

        self.session.headers.update(
            {"Referer": "https://viu.com/"}  # headers Origin make 403 error
        )
        self._AREA_ID = {
        "HK": 1,
        "SG": 2,
        "TH": 4,
        "PH": 5,
        }
        self._LANGUAGE_FLAG = {
            1: "zh-hk",
            2: "zh-cn",
            3: "en-us",
            4: "th-th",
        }


    def get_titles(self):
        res = self.session.get(url=self.url, allow_redirects=False)
        try:
            match = re.search(
                r"href=\"\/ott\/(.+)\/index\.php\?r=campaign\/connectwithus\&language_flag_id=(\d+)\&area_id=(\d+)\"",
                res.text,
            )
            
            if match:
                self.region = match.group(1)
                
                self.language_flag_id = match.group(2)
                self.area_id = match.group(3)
            else:
                self.region, self.area_id, self.language_flag_id = self.get_region()

            # self.region = 'th'
            # self.language_flag_id = "4"
            # self.area_id = "4"
            self.log.info(f" + Region: {self.region}")
            self.log.debug(f" + Area_id: {self.area_id}")
            self.log.debug(f" + Language_flag_id: {self.language_flag_id}")
        except Exception:
            self.log.exit(f" - Error, response: {res.text}")

        if self.region in ["ms", "id"]:
            self.session.headers.update({"X-Forwarded-For": "139.195.232.194"})
            meta_res = self.session.get(
                url=self.config["endpoints"]["gateway"],
                params={
                    "platform_flag_label": "web",
                    "area_id": self.area_id,
                    "language_flag_id": self.language_flag_id,
                    "platformFlagLabel": "web",
                    "areaId": self.area_id,
                    "languageFlagId": self.language_flag_id,
                    "countryCode": self.region.upper(),
                    "ut": "0",
                    "r": "/vod/detail",
                    "product_id": self.title,
                    "os_flag_id": "1",
                },
            )
            try:
                data = meta_res.json()["data"]
            except Exception:
                self.log.info(f" - Error, response: {meta_res.text}")
                sys.exit()

            if not data["series"].get("product"):
                meta_res2 = self.session.get(
                    url=self.config["endpoints"]["gateway"],
                    params={
                        "platform_flag_label": "web",
                        "area_id": self.area_id,
                        "language_flag_id": self.language_flag_id,
                        "platformFlagLabel": "web",
                        "areaId": self.area_id,
                        "languageFlagId": self.language_flag_id,
                        "countryCode": self.region.upper(),
                        "ut": "0",
                        "r": "/vod/product-list",
                        "os_flag_id": "1",
                        "series_id": data["current_product"]["series_id"],
                        "size": "-1",
                        "sort": "asc",
                    },
                )

                try:
                    product_list = meta_res2.json()["data"]["product_list"]
                    data["series"]["product"] = product_list
                except Exception:
                    self.log.info(f" - Error, response: {meta_res2.text}")
                    sys.exit()
        else:
            self.session.headers.update({"X-Forwarded-For": "103.62.48.237"})
            meta_res = self.session.get(
                url=self.config["endpoints"]["ott"].format(region=self.region),
                params={
                    "area_id": self.area_id,
                    "language_flag_id": self.language_flag_id,
                    "r": "vod/ajax-detail",
                    "platform_flag_label": "web",
                    "product_id": self.title,
                },
            )
            try:
                data = meta_res.json()["data"]
            except Exception:
                self.log.info(f" - Error, response: {meta_res.text}")
                sys.exit()

        product_type = "movie" if data["current_product"]["is_movie"] == 1 else "series"
        self.log.info(f" + Product type: {product_type}")

        if product_type == "movie":
            # api not returned actual released date, trying to parse from title
            try:
                year = re.search(r"(\d){4}",  data["series"]["name"]).group(1)
            except Exception:
                year = None
            return Title(
                        id_=self.title,
                        type_=Title.Types.MOVIE,
                        source=self.ALIASES[0],
                        year=year,
                        name=data["series"]["name"],
                        original_lang=data["series"].get("series_language") or self.lang,
                        service_data=data,
                    )
        else:
            titles_ = []
            for x in sorted(
                data["series"]["product"], key=lambda x: int(x.get("number", 0))
            ):
                episode_title_with_year = f"{data['series']['name'].replace('(', '').replace(')', '')}.{data['series']['release_of_year']}"
                titles_.append(
                    Title(
                            id_=x["product_id"],
                            type_=Title.Types.TV,
                            name=episode_title_with_year,
                            season=1,  # TODO: find season in api response
                            episode=x.get("number", 0),
                            # name=x.get("synopsis", ""),
                            source=self.ALIASES[0],
                            original_lang=data["series"].get("series_language") or self.lang,
                            service_data=x,
                        )
                )
            return titles_

        

    def get_tracks(self, title):
        tracks = Tracks()
        data = title.service_data


        if self.region in ["id", "my" ]:
            stream_info = {
                "current_product": data,
                "time_duration": data.get("time_duration", ""),
            }
        else:
            stream_info = self.session.get(
                url=self.config["endpoints"]["ott"].format(region=self.region),
                params={
                    "area_id": self.area_id,
                    "language_flag_id": self.language_flag_id,
                    "r": "vod/ajax-detail",
                    "platform_flag_label": "web",
                    "product_id": title.id,
                },
            ).json()["data"]

        duration_limit = False
        query = {
            "ccs_product_id": stream_info["current_product"]["ccs_product_id"],
            "language_flag_id": self.language_flag_id or "3",
        }

        def download_playback():
            stream_data = self.session.get(
                url=self.config["endpoints"]["playback"],
                params=query,
                headers={"Authorization": f"Bearer {self._auth_codes[self.region]}"},
            ).json()
            return self.check_error(stream_data).get("stream")
        if not self._auth_codes.get(self.region):
            self._auth_codes[self.region] = self._get_token(self.region)

        self.log.debug(f" + Token play: {self._auth_codes[self.region]}")

        stream_data = None
        try:
            stream_data = download_playback()
        except (Exception, KeyError):
            token = self._login(self.region)
            self.log.debug(f" + Token login: {token}")
            if token is not None:
                query["identity"] = token
            else:
                # The content is Preview or for VIP only.
                # We can try to bypass the duration which is limited to 3mins only
                duration_limit, query["duration"] = True, "180"
            try:
                stream_data = download_playback()
            except (Exception, KeyError):
                if token is None:
                    raise
                self.log.exit(
                    " - Login required, needs password, detected:"
                    f"\nuser: {self.credentials.username}\npwd: {self.credentials.password}"
                )
        if not stream_data:
            self.log.exit(" - Cannot get stream info")


        formats = []
        for vid_format, stream_url in (stream_data.get("airplayurl") or {}).items():
            height = int(re.search(r"s(\d+)p", vid_format).group(1))
            # bypass preview duration limit
            if duration_limit:
                old_stream_url = urllib.parse.urlparse(stream_url)

                query = dict(
                    urllib.parse.parse_qsl(old_stream_url.query, keep_blank_values=True)
                )
                query.update(
                    {
                        "duration": stream_info.get("time_duration") or "9999999",
                        "duration_start": "0",
                    }
                )

                stream_url = old_stream_url._replace(
                    query=urllib.parse.urlencode(query)
                ).geturl()#.replace("viu_var_akm.m3u8", "viu_akm.m3u8")
                if 'var' in stream_url:
                    stream_url=stream_url.replace('_var_', '_')
            formats.append(
                {"format_id": vid_format, "url": stream_url, "height": height}
            )
        
        for x in formats:
            stream_url = x["url"]
            r = self.session.get(stream_url)
            res = r.text
            master= m3u8.loads(res)
            tracks.add(
                Tracks.from_m3u8(master,self.ALIASES[0])
            )


        if self.region in ["id", "my"]:
            # clean subs
            tracks.subtitles.clear()
            # obtain subs - get per eps again
            meta_res = self.session.get(
                url=self.config["endpoints"]["gateway"],
                params={
                    "platform_flag_label": "web",
                    "area_id": self.area_id,
                    "language_flag_id": self.language_flag_id,
                    "platformFlagLabel": "web",
                    "areaId": self.area_id,
                    "languageFlagId": self.language_flag_id,
                    "countryCode": self.region.upper(),
                    "ut": "0",
                    "r": "/vod/detail",
                    "product_id": title.id,
                    "os_flag_id": "1",
                },
            )
            try:
                data = meta_res.json()["data"]
                stream_info = data
            except Exception:
                pass

        for x in stream_info["current_product"].get("subtitle", []):
            tracks.add(
                TextTrack(
                    id_="{}_{}".format(x["product_subtitle_id"], x["code"]),
                    url=x["url"],
                    codec="srt",
                    language=x["code"],
                    source=self.ALIASES[0],
                    # is_original_lang=is_close_match(x["code"], [title.language]),
                    forced=False,
                    sdh=False,
                ))
            if x.get("second_subtitle_url"):
                tracks.add(
                    TextTrack(
                        id_="{}_{}_annotation".format(
                            x["product_subtitle_id"], x["code"]
                        ),
                        url=x["second_subtitle_url"],
                        codec="srt",
                        language=x["code"],
                        source=self.ALIASES[0],
                        # is_original_lang=is_close_match(x["code"], [title.language]),
                        forced=False,
                        sdh=False,
                    ))

        return tracks

    def get_chapters(self, title):
        return []

    def certificate(self, **_):
        return None  # will use common privacy cert

    def license(self, challenge, **_):
        return self.session.post(
            url=self.config["endpoints"]["license"].format(id=self.title),
            headers={
                "authorization": self.token_lic or self.config["auth"],
                "actiontype": "s",
                "drm_level": "l3",
                "hdcp_level": "null",
                "lang_id": "en",
                "languageid": "en",
                "os_ver": "10",
                "x-client": "browser",
                "x-request-id": str(uuid.uuid4()),
                "x-session-id": self.sessionid,
            },
            data=challenge,  # expects bytes
        ).content
    
    def get_region(self):
        region = ""
        area_id = ""
        language_flag_id = ""
        region_search = re.search(r"\/ott\/(.+?)\/(.+?)\/", self.url)
        if region_search:
            region = region_search.group(1)
            language = region_search.group(2)
            if region == "sg":
                area_id = 2
                language_flag_id = ""
                if "zh" in language:
                    language_flag_id = "2"
                else:
                    language_flag_id = "3"
            elif region == "id":
                area_id = 1000
                language_flag_id = "8"
            else:
                area_id = self._AREA_ID.get(str(region).upper()) or "hk"
                if "zh" in language:
                    language_flag_id = "1"
                elif "th" in language:
                    language_flag_id = "4"
                else:
                    language_flag_id = "3"
        return region, area_id, language_flag_id
    
    def parse_input(self, input_):
        re_product = r"vod\/(\d+)\/"
        re_playlist = r".+playlist-(\d+)"
        # re_playlist2 = r".+video.+-(\d+)"
        re_playlist2 = r"containerId=(\d+)"

        product_id = re.search(re_product, input_)
        playlist_id = re.search(re_playlist, input_)
        playlist2_id = re.search(re_playlist2, input_)

        if product_id:
            self.jenis = "product_id"
            input_id = product_id.group(1)
        elif playlist_id or playlist2_id:
            self.jenis = "playlist_id"
            input_ = playlist_id or playlist2_id
            input_id = input_.group(1)
        else:
            self.jenis = "playlist_id_eps"
            input_id = input_.split("-")[-1]

        return input_id

    def get_language_code(self, lang):
        language_code = {
            "en": "en",
            "zh": "zh-Hans",
            "zh-CN": "zh-Hans",
            "zh-Hant": "zh-Hant",
            "ms": "ms",
            "th": "th",
            "id": "id",
            "my": "my",
            "mya": "mya",
        }

        if language_code.get(lang):
            return language_code.get(lang)
    def check_error(self, response):
        code = response["status"]["code"]
        if code > 0:
            message = response["status"]["message"]
            raise Exception(
                self.log.warn(
                    f" - Got an error, code: {code} - message {message} - Trying to bypass it..."
                )
            )
        return response.get("data") or {}

    def get_token(self):
        self.sessionid = str(uuid.uuid4())
        self.deviceid = str(uuid.uuid4())
        res = self.session.post(
            url=self.config["endpoints"]["token"],
            params={
                "ver": "1.0",
                "fmt": "json",
                "aver": "5.0",
                "appver": "2.0",
                "appid": "viu_desktop",
                "platform": "desktop",
                "iid": str(uuid.uuid4()),
            },
            headers={
                "accept": "application/json; charset=utf-8",
                "content-type": "application/json; charset=UTF-8",
                "x-session-id": self.sessionid,
                "Sec-Fetch-Mode": "cors",
                "x-client": "browser",
            },
            json={"deviceId": self.deviceid},
        )
        if res.ok:
            return res.json()["token"]
        else:
            self.log.exit(f" - Cannot get token, response: {res.text}")

    def _get_token(self, country_code):
        rand = "".join(random.choice("0123456789") for _ in range(10))
        self.uuid = str(uuid.uuid4())
        return self.session.post(
            url=self.config["endpoints"]["token2"],
            params={"v": f"{rand}000&"},
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {
                    "countryCode": country_code.upper(),
                    "platform": "browser",
                    "platformFlagLabel": "web",
                    "language": "en",
                    "uuid": self.uuid,
                    "carrierId": "0",
                }
            ).encode("utf-8"),
        ).json()["token"]

    def _login(self, country_code):
        if not self._user_token:
            try:
                user = self.credentials.username
                pwd = self.credentials.password
            except Exception:
                user = None
                pwd = None
            if user == "empty" or not user:
                return
            if pwd == "empty" or not user:
                return
            self.log.debug(f" + auth: {self._auth_codes[country_code]}")
            headers = {
                "Authorization": f"Bearer {self._auth_codes[country_code]}",
                "Content-Type": "application/json",
            }
            data = self.session.post(
                url=self.config["endpoints"]["validate"],
                headers=headers,
                data=json.dumps({"principal": user, "provider": "email"}).encode(),
            ).json()
            if not data.get("exists"):
                self.log.exit(" - Invalid email address")

            data = self.session.post(
                url=self.config["endpoints"]["login"],
                headers=headers,
                data=json.dumps(
                    {
                        "email": user,
                        "password": pwd,
                        "provider": "email",
                    }
                ).encode(),
            ).json()
            self.check_error(data)
            self._user_token = data.get("identity")
            # need to update with valid user's token else will throw an error again
            self._get_token[country_code] = data.get("token")
        return self._user_token


