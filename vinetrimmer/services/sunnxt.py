import base64
import os
from pathlib import Path
import click
import hashlib
import json
import re
import requests

from Crypto.Cipher import AES
from Cryptodome.Util import Padding
import uuid

from langcodes import Language
from vinetrimmer.objects import Title, Tracks
from vinetrimmer.objects.tracks import TextTrack
from vinetrimmer.services.BaseService import BaseService


class Sunnxt(BaseService):
    """
    Service Code for Sunnxt Streaming Service (https://www.sunnxt.com)

    ### Authorization
    - Requires Login

    ### Security
    - Supports UHD,FHD @ L3.

    ### Tips
    - The content library can be browsed without an account at: https://www.sunnxt.com

    Made by: MrHulk
    """

    ALIASES = ["SNXT", "SUNNXT"]
    GEOFENCE = [""]
    
    TITLE_RE = r"https:\/\/www\.sunnxt\.com\/(?P<slug>[a-zA-Z0-9\-]+)\/(?P<type>[a-zA-Z]+)\/(?P<id>[0-9]+)"

    @staticmethod
    @click.command(name="Sunnxt", short_help="https://www.sunnxt.com")
    @click.argument("url", type=str)
    @click.option("--login", is_flag=True, default=False, help="Login to get Token")
    @click.option("-nt", "--notitle", is_flag=True, default=False, help="Don't grab episode title...")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Sunnxt(ctx, **kwargs)

    def __init__(self, ctx, url: str, login: bool, notitle: bool):
        super().__init__(ctx)
        m = self.parse_title(ctx, url)
        self.slug = m.get("slug")
        self.type = m.get("type")
        self.id = m.get("id")

        self.login = login
        self.notitle = notitle
        self.licenseUrl = None

        self.token_cache_path = Path(self.get_cache("token.json"))

        if self.login:
            self._login()

        if self.token_cache_path.is_file():
            try:
                with open(self.token_cache_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    self.device_id = data.get("device_id")
                    self.client_key = data.get("client_key")
                    self.secret_key = (
                        self.config["secret_key"][-4:] + self.device_id[-8:] + self.config["secret_key"][:4]
                    )
            except (json.JSONDecodeError, KeyError) as e:
                self.log.error(f"Error reading token file: {e}")
                self.log.exit("Token file is invalid or corrupted. Please log in again using the --login command.")
        else:
            self.log.exit("No valid token found. Please log in using the --login command.")
        self.configure()
        
    def get_titles(self):
        self.log.info(f"+ Content Id: {self.id}")
        res = self.session.get(self.config["endpoints"]["contentDetail"].format(titleid=self.id))
        data = self.is_valid(res, "Content")
        
        if data["results"][0]["generalInfo"]["type"] in ["movie", "musicvideo"]:
            return [
                Title(
                    id_=self.id,
                    type_=Title.Types.MOVIE,
                    name=data["results"][0]["generalInfo"]["title"],
                    year=data["results"][0]["content"]["releaseDate"][:4],
                    original_lang=Language.find(data["results"][0]["content"]["language"][0]).to_alpha3(),
                    source=self.ALIASES[0],
                    service_data=data,
                )
            ]
        elif data["results"][0]["generalInfo"]["type"] in ["vodchannel", "vod"]:
            episodes = []
            index = 1
            while index < 50:
                tv_res = self.session.get(
                    self.config["endpoints"]["tv_content"].format(_id=self.id, index=index)
                )
                tv_res = self.is_valid(tv_res, "tv content")
                if tv_res["results"] == []:
                    break
                for episode in tv_res["results"]:
                    ep_number = self.get_episode_number(episode["generalInfo"]["displayTitle"])
                    if ep_number is None:
                        continue
                    episodes.append(
                        Title(
                            id_=episode["_id"],
                            type_=Title.Types.TV,
                            name=episode["globalServiceName"],
                            season=1,  # TODO
                            episode=self.get_episode_number(episode["generalInfo"]["displayTitle"]),
                            episode_name=None if self.notitle else episode["generalInfo"]["displayTitle"],
                            year=None,
                            original_lang=Language.find(data["results"][0]["content"]["language"][0]).to_alpha3(),
                            source=self.ALIASES[0],
                        )
                    )
                index += 1
            return episodes
        elif data["results"][0]["generalInfo"]["type"] == "videoalbum":
            videos = []
            video_res = self.session.get(
                self.config["endpoints"]["tv_content"].format(_id=self.id, index=1)
            )
            video_res = self.is_valid(video_res, "Video res")
            for video in video_res["results"]:
                if video["_id"] is None:
                    continue
                videos.append(
                    Title(
                        id_=video["_id"],
                        type_=Title.Types.MOVIE,
                        name=video["title"],
                        year=video["releaseDate"][:4],
                        original_lang=Language.find(data["results"][0]["content"]["language"][0]).to_alpha3(),
                        source=self.ALIASES[0],
                        service_data=data,
                    )
                )
            return videos

    def get_tracks(self, title):
        tracks = Tracks()
        res = self.session.get(
            url=self.config["endpoints"]["playback"].format(titleid=title.id),
            headers={
                "user-agent": self.config["UA"],
                "clientKey": self.client_key,
            },
        )

        data = self.decrypt(res.json()["response"], self.secret_key)

        if data["status"] != "SUCCESS":
            self.log.exit(f" - Got error: {data['message']}")

        if data["results"][0]["videos"]["status"] != "SUCCESS":
            self.log.exit(f" - Got error: {data['results'][0]['videos']['message']}")

        for value in data["results"][0]["videos"]["values"]:
            if not value["link"].startswith("https"):
                continue

            if "dash-cenc" in value["format"]:
                self.licenseUrl = value["licenseUrl"]
                tracks.add(
                    Tracks.from_mpd(url=value["link"], session=self.session, source=self.ALIASES[0]),
                    warn_only=True,
                )

        if "subtitles" in data["results"][0] and len(data["results"][0]["subtitles"]["values"]) > 0:
            tracks.add(
                TextTrack(
                    id_=hashlib.md5(data["results"][0]["subtitles"]["values"][0]["link_sub"].encode()).hexdigest(),
                    url=data["results"][0]["subtitles"]["values"][0]["link_sub"] + ".vtt",
                    codec="vtt",
                    language=Language.find(data["results"][0]["subtitles"]["values"][0]["language"]).to_alpha3(),
                    source=self.ALIASES[0],
                )
            )
        return tracks

    def get_chapters(self, title):
        return []

    def certificate(self, challenge, **_):
        return self.license(challenge)

    def license(self, challenge, **_):
        return self.session.post(url=self.licenseUrl, data=challenge).content

    def configure(self):
        self.session.headers.update(
            {
                "contentlanguage": "tamil,telugu,malayalam,kannada,hindi,bengali,marathi",
                "origin": "https://www.sunnxt.com",
                "referer": "https://www.sunnxt.com/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "x-myplex-maturity-level": "",
                "x-myplex-platform": "AndroidTV",
            }
        )

    def decrypt(self, data: str, secret_key: bytes):
        cipher = AES.new(secret_key.encode("utf-8"), AES.MODE_CBC, iv=bytes([0] * 16))
        return json.loads(Padding.unpad(cipher.decrypt(base64.b64decode(data)), 16).decode())

    def encrypt(self, data: dict) -> str:
        cipher = AES.new(self.config["secret_key"].encode("utf-8"), AES.MODE_CBC, iv=bytes([0] * 16))
        encrypted = cipher.encrypt(
            Padding.pad(json.dumps(data, separators=(",", ":")).encode(), 16)
        )
        return base64.b64encode(encrypted).decode()

    def get_episode_number(self, title):
        match = re.search(r"\b(?:EP?-?)(\d+)", title, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def is_valid(self, res, stage):
        try:
            data = res.json()
        except ValueError as e:
            self.log.exit(f"Failed to get {stage} response. {e}")

        if data.get("status") != "SUCCESS":
            self.log.exit(f" - Got error: status - {data.get('status')}. msg - {data.get('message')}")

        return data

    def _login(self):
        reg_data = {
            "serialNo": str(uuid.uuid4()),
            "os": "AndroidSony",
            "osVersion": "9",
            "make": "NVIDIA",
            "model": "SHIELD Android TV",
            "resolution": "3840x2160",
            "profile": "work",
            "deviceType": "Android",
            "clientSecret": self.config["client_secret"],
        }

        self.log.info("Registering device...")
        reg_res = requests.post(
            self.config["endpoints"]["register_device_url"],
            data={"payload": self.encrypt(reg_data), "version": 1},
            headers={
                "User-Agent": self.config["UA"],
                "X-myplex-platform": "AndroidTV",
                "ContentLanguage": "telugu",
                "Accept-Language": "en",
            },
        )

        reg_data_decrypted = self.decrypt(reg_res.json().get("response", {}), secret_key=self.config["secret_key"])

        client_key = reg_data_decrypted.get("clientKey")
        device_id = reg_data_decrypted.get("deviceId")

        if not client_key or not device_id:
            self.log.error("Failed to get client key or device ID from registration response.")
            return

        os.makedirs(os.path.dirname(self.token_cache_path), exist_ok=True)
        with open(self.token_cache_path, "w", encoding="utf-8") as f:
            json.dump({"client_key": client_key, "device_id": device_id}, f)

        self.log.info(f"Successfully saved client key to: {self.token_cache_path}")

        self.session.headers["clientKey"] = client_key

        self.log.info("Fetching pairing code...")
        pairing_resp = self.session.get(self.config["endpoints"]["code_url"])
        pairing_resp.raise_for_status()

        pairing_data = pairing_resp.json().get("results", {})
        confirmation_url = pairing_data.get("confirmation_url")
        auth_code = pairing_data.get("auth_code")

        if not confirmation_url or not auth_code:
            self.log.exit("Failed to obtain pairing code or confirmation URL.")

        self.log.info(f"Go to https://www.{confirmation_url} and enter: {auth_code}")
        input("Press Enter after completing the authentication...")

        self.log.info("Linking device...")
        link_resp = self.session.post(
            self.config["endpoints"]["link_url"], data={"device_code": pairing_data.get("device_code")}
        )
        link_resp.raise_for_status()

        self.log.info(f"Device linked successfully: {link_resp.json()}")
