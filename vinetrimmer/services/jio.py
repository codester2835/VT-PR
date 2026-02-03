from __future__ import annotations

import base64
import json
import re as rex
import os
import requests
from langcodes import Language
#from typing import Any, Optional, Union
import datetime
import click

from vinetrimmer.objects import MenuTrack, TextTrack, Title, Tracks, Track
from vinetrimmer.services.BaseService import BaseService


class Jio(BaseService):
    """
    Service code for Viacom18's JioCinema streaming service (https://www.jiocinema.com/).

    \b
    Authorization: Token
    Security: UHD@L3 FHD@L3

    """

    PHONE_NUMBER = "" # Add number with country code

    ALIASES = ["JIO", "JioCinema"]
    #GEOFENCE = ["in2"]
    
    @staticmethod
    @click.command(name="Jio", short_help="https://www.jiocinema.com")
    @click.argument("title", type=str)
    @click.option("-m", "--movie", is_flag=True, default=False, help="Title is a Movie.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Jio(ctx, **kwargs)

    def __init__(self, ctx, title: str, movie: bool):
        self.title = title
        self.movie = movie
        super().__init__(ctx)

        assert ctx.parent is not None

        self.vcodec = ctx.parent.params["vcodec"]
        self.acodec = ctx.parent.params["acodec"]
        self.range = ctx.parent.params["range_"]

        self.profile = ctx.obj.profile

        self.token: str
        self.refresh_token: str
        self.license_api = None

        self.configure()

    def get_titles(self):
        titles = []
        if self.movie:
            res = self.session.get(
                url='https://content-jiovoot.voot.com/psapi/voot/v1/voot-tv/content/query/asset-details?ids=include%3A{id}&devicePlatformType=androidtv&responseType=common&page=1'.format(id=self.title)
            )
            try:
                data = res.json()['result'][0]
                self.log.debug(json.dumps(data, indent=4))
            except json.JSONDecodeError:
                raise ValueError(f"Failed to load title manifest: {res.text}")

            titles.append(Title(
                id_=data['id'],
                type_=Title.Types.MOVIE,
                name=rex.sub(r'\([^)]*\)', '', data["fullTitle"]).strip(),
                year=data.get("releaseYear"),
                original_lang=Language.find(data['languages'][0]),
                source=self.ALIASES[0],
                service_data=data
            ))

        else:
            def get_recursive_episodes(season_id):
                total_attempts = 1
                recursive_episodes = []
                season_params = {
                    'sort': 'episode:asc',
                    'responseType': 'common',
                    'id': season_id,
                    'page': 1
                }
                while True:
                    episode = self.session.get(url='https://content-jiovoot.voot.com/psapi/voot/v1/voot-web/content/generic/series-wise-episode', params=season_params).json()
                    if any(episode["result"]):
                        total_attempts += 1
                        recursive_episodes.extend(episode["result"])
                        season_params.update({'page': total_attempts})
                    else:
                        break
                return recursive_episodes
            # params = {
            #     'sort': 'season:asc',
            #     'id': self.title,
            #     'responseType': 'common'
            # }
            re = self.session.get(url='https://content-jiovoot.voot.com/psapi/voot/v1/voot-tv/view/show/{id}?devicePlatformType=androidtv&responseType=common&page=1'.format(id=self.title)).json()['trays'][1]
            self.log.debug(json.dumps(re, indent=4))
            for season in re['trayTabs']:
                season_id = season["id"]
                recursive_episodes = get_recursive_episodes(season_id)
                self.log.debug(json.dumps(recursive_episodes, indent=4))
                for episodes in recursive_episodes:
                    titles.append(Title(
                        id_=episodes["id"],
                        type_=Title.Types.TV,
                        name=rex.sub(r'\([^)]*\)', '', episodes["showName"]).strip(),
                        season=int(float(episodes["season"])),
                        episode=int(float(episodes["episode"])),
                        episode_name=episodes["fullTitle"],
                        original_lang=Language.find(episodes['languages'][0]),
                        source=self.ALIASES[0],
                        service_data=episodes
                    ))

        return titles

    def get_tracks(self, title: Title) -> Tracks:
        #self.log.debug(json.dumps(title.service_data, indent=4))
        json_data = {
            '4k': True,
            'ageGroup': '18+',
            'appVersion': '4.0.9',
            'bitrateProfile': 'xxxhdpi',
            'capability': {
                'drmCapability': {
                    'aesSupport': 'yes',
                    'fairPlayDrmSupport': 'yes',
                    'playreadyDrmSupport': 'yes',
                    'widevineDRMSupport': 'L1',
                },
                'frameRateCapability': [
                    {
                        'frameRateSupport': '60fps',
                        'videoQuality': '2160p',
                    },
                ],
            },
            'continueWatchingRequired': False,
            'dolby': True,
            'downloadRequest': False,
            'hevc': False,
            'kidsSafe': False,
            'manufacturer': 'NVIDIA',
            'model': 'SHIELDTV',
            'multiAudioRequired': True,
            'osVersion': '12',
            'parentalPinValid': True,
            'x-apisignatures': 'o668nxgzwff',
        }

        try:
            res = self.session.post(
                url = f'https://apis-jiovoot.voot.com/playbackjv/v3/{title.id}',
                json=json_data,
            )
        except requests.exceptions.RequestException:
            self.refresh()
            try:
                res = self.session.post(
                    url = f'https://apis-jiovoot.voot.com/playbackjv/v3/{title.id}',
                    json=json_data
                )
            except requests.exceptions.RequestException:
                self.log.exit("Unable to retrive manifest")

        res = res.json()
        self.log.debug(json.dumps(res, indent=4))
        self.license_api = res['data']['playbackUrls'][0].get('licenseurl')
        vid_url = res['data']['playbackUrls'][0].get('url')

        if "mpd" in vid_url:
            tracks = Tracks.from_mpd(
                url=vid_url,
                session=self.session,
                #lang=title.original_lang,
                source=self.ALIASES[0]
            )
        else:
            self.log.exit('No mpd found')
        
        self.log.info(f"Getting audio from Various manifests for potential higher bitrate or better codec")
        for device in ['androidtablet']: #'androidmobile', 'androidweb' ==> what more devices ?
            self.session.headers.update({'x-platform': device})
            audio_mpd_url = self.session.post(url=f'https://apis-jiovoot.voot.com/playbackjv/v3/{title.id}', json=json_data)
            if audio_mpd_url.status_code != 200:
                self.log.warning("Unable to retrive manifest")
            else:
                audio_mpd_url = audio_mpd_url.json()['data']['playbackUrls'][0].get('url')
                if "mpd" in audio_mpd_url:
                    audio_mpd = Tracks([
                        x for x in iter(Tracks.from_mpd(
                            url=audio_mpd_url,
                            session=self.session,
                            source=self.ALIASES[0],
                            #lang=title.original_lang,
                        ))
                    ])
                    tracks.add(audio_mpd.audios)
                else:
                    self.log.warning('No mpd found')

        for track in tracks:
            track.needs_proxy = True

        return tracks

    def get_chapters(self, title: Title) -> list[MenuTrack]:
        return []

    def certificate(self, **kwargs) -> None:
        return self.license(**kwargs)

    def license(self, challenge: bytes, **_) -> bytes:
        assert self.license_api is not None
        self.session.headers.update({
            'x-playbackid': '5ec82c75-6fda-4b47-b2a5-84b8d9079675',
            'x-feature-code': 'ytvjywxwkn',
            'origin': 'https://www.jiocinema.com',
            'referer': 'https://www.jiocinema.com/',
        })
        return self.session.post(
            url=self.license_api,
            data=challenge,  # expects bytes
        ).content

    def refresh(self) -> None:
        self.log.info(" + Refreshing auth tokens...")
        res = self.session.post(
            url="https://auth-jiocinema.voot.com/tokenservice/apis/v4/refreshtoken",
            json={
                'appName': 'RJIL_JioCinema',
                'deviceId': '332536276',
                'refreshToken': self.refresh_token,
                'appVersion': '5.6.0'
            }
        )
        if res.status_code != 200:
            return self.log.warning('Tokens cannot be Refreshed. Something went wrong..')

        self.token = res.json()["authToken"]
        self.refresh_token = res.json()["refreshTokenId"]
        self.session.headers.update({'accesstoken': self.token})
        token_cache_path = self.get_cache("token_{profile}.json".format(profile=self.profile))
        old_data = json.load(open(token_cache_path, "r", encoding="utf-8"))
        old_data.update({
            'authToken': self.token,
            'refreshToken': self.refresh_token
        })
        json.dump(old_data, open(token_cache_path, "w", encoding="utf-8"), indent=4)

    def login(self):
        self.log.info(' + Logging into JioCinema')
        if not self.PHONE_NUMBER:
            self.PHONE_NUMBER = input('Please provide Jiocinema registered Phone number with country code: ')
        guest = self.session.post(
            url="https://auth-jiocinema.voot.com/tokenservice/apis/v4/guest",
            json={
                'appName': 'RJIL_JioCinema',
                'deviceType': 'phone',
                'os': 'ios',
                'deviceId': '332536276',
                'freshLaunch': False,
                'adId': '332536276',
                'appVersion': '5.6.0',
            }
        )
        headers = {
            'accesstoken': guest.json()["authToken"],
            'appname': 'RJIL_JioCinema',
            'devicetype': 'phone',
            'os': 'ios'
        }
        send = self.session.post(
            url="https://auth-jiocinema.voot.com/userservice/apis/v4/loginotp/send",
            headers=headers,
            json={
                'number': '{}'.format(base64.b64encode(self.PHONE_NUMBER.encode("utf-8")).decode("utf-8")),
                'appVersion': '5.6.0'
            }
        )
        if send.status_code != 200:
            self.log.exit("OTP Send Failed!")
        else:
            self.log.info("OTP has been sent. Please write it down below and press Enter")
            otp = input()
            verify_data = {
                'deviceInfo': {
                    'consumptionDeviceName': 'iPhone',
                    'info': {
                        'platform': {
                            'name': 'iPhone OS',
                        },
                        'androidId': '332536276',
                        'type': 'iOS',
                    },
                },
                'appVersion': '5.6.0',
                'number': '{}'.format(base64.b64encode(self.PHONE_NUMBER.encode("utf-8")).decode("utf-8")),
                'otp': '{}'.format(otp)
            }
            verify = self.session.post(
                url="https://auth-jiocinema.voot.com/userservice/apis/v4/loginotp/verify",
                headers=headers,
                json=verify_data
            )
            if verify.status_code != 200:
                self.log.exit("Cannot be verified")
            self.log.info(" + Verified!")

            return verify.json()

    def configure(self) -> None:
        token_cache_path = self.get_cache("token_{profile}.json".format(profile=self.profile))
        if os.path.isfile(token_cache_path):
            tokens = json.load(open(token_cache_path, "r", encoding="utf-8"))
            self.log.info(" + Using cached auth tokens...")
        else:
            tokens = self.login()
            os.makedirs(os.path.dirname(token_cache_path), exist_ok=True)
            with open(token_cache_path, "w", encoding="utf-8") as file:
                json.dump(tokens, file, indent=4)
        self.token = tokens["authToken"]
        self.refresh_token = tokens["refreshToken"]
        self.session.headers.update({
            'deviceid': '332536276',
            'accesstoken': self.token,
            'appname': 'RJIL_JioCinema',
            'uniqueid': 'be277ebe-e50b-441e-bc37-bd803286f3d5',
            'user-agent': 'Dalvik/2.1.0 (Linux; U; Android 9; SHIELD Android TV Build/PPR1.180610.011)',
            'x-apisignatures': 'o668nxgzwff',
            'x-platform': 'androidtv', # base device
            'x-platform-token': 'android',
        })