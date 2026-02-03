import base64
import json
import re
import click
import os, sys

import uuid
import xmltodict

from langcodes import Language
from vinetrimmer.objects import AudioTrack, TextTrack, Title, Tracks, VideoTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.vendor.pymp4.parser import Box


class Mubi(BaseService):
    """
    Made By redd / Edit by superman
    and Widevine Group - Chrome CDM API dont share this


    \b
    Authorization: Credentials 
    Security: UHD@L3, doesn't care about releases.
    """

    ALIASES = ["MUBI"]

    TITLE_RE = [
        r'/(?P<id>[^/]+)$',
        r"^(?:https?://(?:www\.)?mubi\.com\/)?(?P<id>[^/]+)$",
        # r"^(?:https?://(?:www\.)?mubi\.com/([a-z0-9-]+/[a-z0-9-]+/films)/)?(?P<id>[a-z0-9-]+)?" with country code url
        # r"^(?:https?://(?:www\.)?mubi\.com/(films)/)?(?P<id>[a-z0-9-]+)?"
    ]

    AUDIO_CODEC_MAP = {
        "AAC": "mp4a",
        "AC3": "ac-3",
        "EC3": "ec-3"
    }

    @staticmethod
    @click.command(name="Mubi", short_help="https://mubi.com/")
    @click.argument("title", type=str, required=False)
   
    @click.pass_context
    def cli(ctx, **kwargs):
        return Mubi(ctx, **kwargs)

    def __init__(self, ctx, title):
        super().__init__(ctx)
        self.parse_title(ctx, title)


        self.vcodec = ctx.parent.params["vcodec"].lower()
        self.acodec = ctx.parent.params["acodec"]
        self.range = ctx.parent.params["range_"]
        self.bearer= None
        self.dtinfo= None
        self.quality = ctx.parent.params["quality"]
        self.headers = {
                "authority": "api.mubi.com",
                "accept": "application/json",
                "accept-language": "en-US",
                "client": self.config["device"]["client_name"],
                "client-version": "20.2",
                "client-device-identifier": self.config["device"]["device_identifier"],
                "client-app": "mubi",
                "client-device-brand": "Google",
                'client-accept-audio-codecs': 'eac3, ac3, aac',
                "client-device-model": self.config["device"]["device_model"],
                "client-device-os": self.config["device"]["device_os"],
                "client-country": "US",
                "content-type": "application/json; charset=UTF-8",
                "host": "api.mubi.com",
                "connection": "Keep-Alive",
                "accept-encoding": "gzip",
                "user-agent": self.config["device"]["user_agent"],
            }
        if self.vcodec=="vp9":
            self.headers["client-accept-video-codecs"]="vp9"
        elif self.vcodec=="h265":
            self.headers["client-accept-video-codecs"]="h265"
        elif self.vcodec=="h264":
            self.headers["client-accept-video-codecs"]="h264"
        else:
            self.headers["client-accept-video-codecs"]="vp9,h265,h264"


        self.configure()

    def get_titles(self):

        self.log.info(" + Getting Metadata.")
        res = self.session.get(
                self.config["endpoints"]["metadata"].format(title_id=self.title)
                ,headers=self.headers).json()
        try:
            res
        except json.JSONDecodeError:
            raise self.log.exit(f" - Failed to load title metadata: {res.text}")
        
        self.title = res['id']   
        
        return Title(
                id_=self.title,
                type_=Title.Types.MOVIE,
                name=res["title"],
                year=res["year"],
                source=self.ALIASES[0],
                service_data=res,
            )
    
    def create_pssh_from_kid(self, kid: str):
        WV_SYSTEM_ID = [237, 239, 139, 169, 121, 214, 74, 206, 163, 200, 39, 220, 213, 29, 33, 237]
        kid = uuid.UUID(kid).bytes

        init_data = bytearray(b'\x12\x10')
        init_data.extend(kid)
        init_data.extend(b'H\xe3\xdc\x95\x9b\x06')

        pssh = bytearray([0, 0, 0])
        pssh.append(32 + len(init_data))
        pssh[4:] = bytearray(b'pssh')
        pssh[8:] = [0, 0, 0, 0]
        pssh[13:] = WV_SYSTEM_ID
        pssh[29:] = [0, 0, 0, 0]
        pssh[31] = len(init_data)
        pssh[32:] = init_data

        return base64.b64encode(pssh).decode('UTF-8')
    
    def get_pssh_from_mpd(self, mpd_url):
        r = self.session.get(mpd_url, headers=self.headers)

        if r.status_code != 200:
            raise Exception(r.text)

        mpd = xmltodict.parse(r.text, dict_constructor=dict)

        for adaption in mpd['MPD']['Period']['AdaptationSet']:
            if adaption['@mimeType'] == 'video/mp4':
                if 'ContentProtection' in adaption:
                    for protection in adaption['ContentProtection']:
                        if protection['@schemeIdUri'].lower() == 'urn:mpeg:dash:mp4protection:2011':
                            return self.create_pssh_from_kid(protection['@cenc:default_KID'])


    def get_tracks(self, title):

        res = self.session.post(
            self.config["endpoints"]["viewing"].format(title_id=self.title),headers=self.headers
        ).json()

        lang = res["audio_track_id"]

        title.original_lang = lang.replace('audio_main_', '')
        
        data = self.session.get(
            self.config["endpoints"]["manifest"].format(title_id=self.title),headers=self.headers
        ).json()

        if self.quality==2160:
            mpd_url = re.sub(r"/default/.*\.mpd$", "/default/2160.mpd", data["url"])
        else:
            mpd_url=data["url"]
        
        pssh = self.get_pssh_from_mpd(mpd_url)
        video_pssh = Box.parse(base64.b64decode(pssh))

        tracks=Tracks.from_mpd(
            url=mpd_url,
            session=self.session,
            source=self.ALIASES[0],
        )

        for track in tracks.videos:
            if not track.pssh:
                track.pssh = video_pssh
        
        for track in tracks.audios:
            if not track.pssh:
                track.pssh = video_pssh

        if self.acodec:
            tracks.audios = [x for x in tracks.audios if (x.codec or "")[:4] == self.AUDIO_CODEC_MAP[self.acodec]]

        return tracks

    def get_chapters(self, title):
        return []

    def certificate(self, **kwargs):
        # TODO: Hardcode the certificate
        # return self.license(**kwargs)
        return None

    def license(self, challenge, **_):

        lic = self.session.post(
            url=self.config["endpoints"]["license"],
            headers={"dt-custom-data": self.dtinfo},
            data=challenge  # expects bytes
        )

        return lic.content  # bytes

        
    def configure(self):

        tokens_cache_path = self.get_cache("tokens_mubi.json")
        self.log.info(" + Loading Cached Token...")
        if os.path.isfile(tokens_cache_path):
            with open(tokens_cache_path, encoding="utf-8") as fd:
                tokens = json.load(fd)
            self.bearer=tokens["authorization"]
            self.dtinfo=tokens["dt-custom-data"]
            self.headers["authorization"]=self.bearer

        else:
            
            self.log.info(" + Retrieving API configuration")
            if not self.credentials.username:
                raise self.log.exit(" - No cookies provided, cannot log in.")
            req_payload = "{\"identifier\":\"%s\",\"magic_link\":true}" % self.credentials.username
            auth_resp = self.session.post(url=self.config["endpoints"]["authtok_url"], data=req_payload, headers=self.headers).json()
            payload = "{\"auth_request_token\":\"%s\",\"identifier\":\"%s\",\"password\":\"%s\"}" % (auth_resp["auth_request_token"], self.credentials.username, self.credentials.password)
            response = self.session.post(url=self.config["endpoints"]["loginurl"], data=payload, headers=self.headers).json()
            json_str = {

                "merchant":"mubi",
                "sessionId":response["token"],
                "userId":str(response["user"]["id"])
                }
            
            self.bearer="Bearer " + response["token"]
            self.dtinfo = base64.b64encode((str(json_str).replace("'", '"').encode('utf-8'))).decode('utf-8')

            save_data={"authorization": f"{self.bearer}","dt-custom-data":self.dtinfo}

            os.makedirs(os.path.dirname(tokens_cache_path), exist_ok=True)
            with open(tokens_cache_path, "w", encoding="utf-8") as fd:
                json.dump(save_data, fd)

