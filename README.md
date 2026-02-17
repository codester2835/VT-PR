# VineTrimmer PlayReady

A tool to download and remove DRM from streaming services. Modified to remove Playready DRM in addition to Widevine DRM.

The name `VineTrimmer` comes from `Vine` as in `WideVine` and `Trimmer` as in remove. 


> [!IMPORTANT]
> Read the README thoroughly atleast twice. I cannot stress how important 
> this is. There is a reason why this README is so verbose. 


> [!WARNING]
> DO NOT USE WITH AMAZON. Amazon is currently banning accounts.
I recommend temporarily using [this](https://github.com/DevLARLEY/PlayreadyProxy2).

## History
> This project was recently taken down.  This copy from @chu23465 is mostly original, except for some bug fixes.

## This project is under active development. Expect bugs and errors.

If anyone has anything they would like to see, please add it to the issues or discussions page

## Disclaimer!!!

This project is ONLY for educational/archival/personal purposes. I do not condone piracy in any form. 

By using this project you agree that:
`The developer shall not be held responsible for any account suspensions, terminations, penalties or legal action taken/imposed by third-party platforms. The User acknowledges and agrees that they are solely responsible for complying with all terms, policies, copyright and guidelines of any such platforms.`

I AM NOT taking credit for the entirety of this project. This project is based on a version of an old fork of [devine](https://github.com/devine-dl/devine) that was found floating around online. I AM taking credit for about 20% of the additional stuff that I personally worked on.

Support for sports, sports replays (VOD/PPV/etc) or live streams is not planned. It's a whole thing with OTT panels and restreaming and whatnot. It's a can of worms that I don't plan on opening. 

## Supporters

[@m41c0n](https://github.com/m41c0n)

## Usage

### Windows
1. Install Microsoft Visual C++ Redistributable - [link](https://aka.ms/vs/17/release/vc_redist.x64.exe).

2. Ensure Python is installed in your system (cannot be from the the Microsoft Store). Refer to [link](https://www.python.org/downloads/). I recommend python 3.10.11 (or higher). Python 3.13 does not work.

3. Make sure git is installed in your system by running `git --version`. If not refer to [link](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git).

4. Use below command to download. (Recommended instead of downloading zip)
   ```bash
   git clone https://github.com/codester2835/VT-PR.git
   ```
   
5. Navigate and find `install.bat`.

6. Run `install.bat`.
   
7. Activate venv using `venv.cmd`.

8. For cookies, always extract from homepage of (streaming) service using [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) This also works on Edge. The old `open-cookies.txt`extension is not ManifestV3 compliant and the source code has been removed from github and the extension javascript obfuscated. Remove it.

9. Save cookies to desired folder. Folder name should be `Cookies/{full_service_name}`. As in `Cookies/ParamountPlus` not `Cookies/PMTP`. Pay attention to the path if you are on Linux. Path is case sensitive.

10. Run desired command using poetry.

### Linux

Make sure you have python3 installed. If you have `apt` avaialable -> `sudo apt install python3`

Then: 

```
wget https://github.com/chu23465/VT-PR/raw/refs/heads/dev/install.sh && chmod +x install.sh && bash install.sh
```

I have tested it on only Ubuntu so far. If you have any problems, please open an issue.


## Updating

1. Backup your `vinetrimmer/Cookies/`, `vinetrimmer/Cache/`, `Downloads` directories just in case.
   
2. Open a command prompt and navigate into `VT-PR` directory.
   
3. Use below command:
   ```bash
   git pull origin
   ```

   Make sure `git pull` is successful. If not, do `git stash` and try again. 


### Config

`vinetrimmer.yml` located within the `/vinetrimmer/` folder.

`decryptor:` either `mp4decrypt` or `packager`

(shaka-packager fails to decrypt files downloaded from ISM/Microsoft Smooth Streaming manifests)

`tag:` tag for your release group

CDM can be configured per service or per profile.

```
cdm:
    default: {text}
    Amazon: {text}
```

Credentials can be added depending on which service it is. You need to use full service name ie. `iTunes` instead of `iT`.

```
credentials:
  iTunes: 'username:password'
```
All other option can be left to defaults, unless you know what you are doing. 

## General Options

Usage: 

```
poetry run vt dl [OPTIONS] COMMAND [ARGS] [TITLE]
```

Options:
| Command line argument      | Description                                                                                   | Default Value                     |
|----------------------------|-----------------------------------------------------------------------------------------------|-----------------------------------|
|  -d, --debug               | Flag to enable debug logging                                                                  |  False                            |
|  -p, --profile             | Profile to use when multiple profiles are defined for a service.                              |  "default"                        |
|  -q, --quality             | Download Resolution ie Height of Video Track wanted                                           |  1080                             |
|  -cr, --closest-resolution | If resolution specified is not found, defaults to closest resolution available                |  False                            |
|  -v, --vcodec              | Video Codec                                                                                   |  H264                             |
|  -a, --acodec              | Audio Codec                                                                                   |  None                             |
|  -vb, --vbitrate           | Video Bitrate, `Min` or a number based on output of --list	                                   |  Max                              |
|  -ab, --abitrate           | Audio Bitrate                                                                                 |  Max                              |
|  -ac, --audio-channels     | Select Audio by Channels Configuration, e.g `2.0`, `5.1`, `2.0,5.1`                           |  None                             |
|  -mac, --max-audio-compatability | Select multiple audios for maximum compatibility with all devices                       |  False                            |
|  -aa, --atmos              | Prefer Atmos Audio                                                                            |  False                            |
|  -r, --range               | Video Color Range `HDR`, `HDR10`, `DV`, `SDR`                                                 |  SDR                              |
|  -w, --wanted              | Wanted episodes, e.g. `S01-S05,S07`, `S01E01-S02E03`, `S02-S02E03`                            |  Default to all                   |
|  -le, --latest-episode     | Download only the latest episode on episodes list                                             |  False                            |
|  -al, --alang              | Language wanted for audio.                                                                    |  Defaults to original language    |
|  -sl, --slang              | Language wanted for subtitles.                                                                |  Defaults to original language    |
|  --proxy                   | Proxy URI to use. If a 2-letter country is provided, it will try get a proxy from the config. |  None                             |
|  -A, --audio-only          | Only download audio tracks.                                                                   |  False                            |
|  -S, --subs-only           | Only download subtitle tracks.                                                                |  False                            |
|  -C, --chapters-only       | Only download chapters.                                                                       |  False                            |
|  -ns, --no-subs            | Do not download subtitle tracks.                                                              |  False                            |
|  -na, --no-audio           | Do not download audio tracks.                                                                 |  False                            |
|  -nv, --no-video           | Do not download video tracks.                                                                 |  False                            |
|  -nc, --no-chapters        | Do not download chapters tracks.                                                              |  False                            |
|  -ad, --audio-description  | Download audio description tracks.                                                            |  False                            |
|  --list                    | Skip downloading and list available tracks and what tracks would have been downloaded.        |  False                            |
|  --selected                | List selected tracks and what tracks are downloaded.                                          |  False                            |
|  --cdm                     | Override the CDM that will be used for decryption.                                            |  None                             |
|  --keys                    | Skip downloading, retrieve the decryption keys (via CDM or Key Vaults) and print them.        |  False                            |
|  --cache                   | Disable the use of the CDM and only retrieve decryption keys from Key Vaults. If a needed key is unable to be retrieved from any Key Vaults, the title is skipped.|  False  |
|  --no-cache                | Disable the use of Key Vaults and only retrieve decryption keys from the CDM.                 |  False                            |
|  --no-proxy                | Force disable all proxy use.                                                                  |  False                            |
|  -nm, --no-mux             | Do not mux the downloaded and decrypted tracks.                                               |  False                            |
|  --mux                     | Force muxing when using --audio-only/--subs-only/--chapters-only.                             |  False                            |
|  -ss, --strip-sdh          | Stip SDH subtitles and convert them to CC. Plus fix common errors.                            |  False                            |
|  -mf, --match-forced       | Only select forced subtitles matching with specified audio language                           |  False                            |
|  -?, -h, --help            | Show this message and exit.                                                                   |  False                            |


Currently supported platforms:

COMMANDS :-

| Alaias |  Command        | Service Link                               |
|--------|-----------------|--------------------------------------------|
| AMZN   |  Amazon         | https://amazon.com, https://primevideo.com |
| ATVP   |  AppleTVPlus    | https://tv.apple.com                       |
| DSNP   |  DisneyPlus     | https://disneyplus.com/                    |
| F1TV   |  F1tv           | https://f1tv.formula1.com/                 |
| GLB    |  Globoplay      | https://globoplay.globo.com/               |
| HS     |  Hotstar        | https://www.hotstar.com/                   |
| HULU   |  Hulu           | https://hulu.com                           |
| iT     |  iTunes         | https://itunes.apple.com                   |
| MA     |  MoviesAnywhere | https://moviesanywhere.com                 |
| MAX    |  Max            | https://max.com                            |
| PCOK   |  Peacock        | https://peacocktv.com/                     |
| PMTP   |  ParamountPlus  | https://paramountplus.com                  |

Untested or not fully implemeted services:

| Alaias |   Command       | Service Link                |
|--------|-----------------|-----------------------------|
| iP     |  BBCiPlayer     | https://bbc.co.uk/iplayer   |
| PLAY   |  GooglePlay     | https://play.google.com     |
| MUBI   |  Mubi           | https://mubi.com/           |
| NF     |  Netflix        | https://netflix.com         |
| RKTN   |  RakutenTV      | https://rakuten.tv          |
| SL     |  SonyLiv        | https://sonyliv.com         |
| SNXT   |  Sunnxt         | https://www.sunnxt.com      |
| VIU    |  Viu            | https://www.viu.com/        |



### Amazon Specific Options

Usage: 

```
poetry run vt dl [OPTIONS] AMZN [ARGS] [TITLE]
```

Below flags to be passed after the `AMZN` or `Amazon` keyword in command.

ARGS:

|  Command Line Switch                | Description                                                                                         |
|-------------------------------------|-----------------------------------------------------------------------------------------------------|
|  -b, --bitrate    | Video Bitrate Mode to download in. CVBR=Constrained Variable Bitrate, CBR=Constant Bitrate. (CVBR or CBR or CVBR+CBR) |
|  -c, --cdn        | CDN to download from, defaults to the CDN with the highest weight set by Amazon.                                      |
|  -vq, --vquality  | Manifest quality to request. (SD or HD or UHD)                                                                        |
|  -s, --single     | Force single episode/season instead of getting series ASIN.                                                           |
|  -am, --amanifest | Manifest to use for audio. Defaults to H265 if the video manifest is missing 640k audio. (CVBR or CBR or H265)        |
|  -aq, --aquality  | Manifest quality to request for audio. Defaults to the same as --quality. (SD or HD or UHD)                           |
|  -ism, --ism      | Set manifest override to SmoothStreaming. Defaults to DASH w/o this flag.                                             |
|  -?, -h, --help   | Show this message and exit.                                                                                           |

Remember that not all titles have 4K/Atmos/HDR/DV.

To get Atmos/UHD/4k with Amazon, navigate to -

```
https://www.primevideo.com/mytv
```

Login and get to the code pair page. Extract cookies from that page.

Save it to the path `vinetrimmer/Cookies/Amazon/default.txt`.

When caching cookies, use a profile without PIN. Otherwise it may cause errors.

If you are facing 403 or 400 errors even after saving fresh cookies and clearing `Cache` folder, try logging out of your Amazon account in the browser and logging back in. Then save cookies.

Some titles say `UHD/2160p` is available and if VT is saying `no 2160p track available`, then `UHD/2160p` is only available via renting. As in some titles advertise UHD but UHD will not be available to PrimeVideo customers. You will have to rent the title using the Rent button on the title page in UHD quality.

If you are getting an `AssertionError` with Amazon, then try reprovisioning the device. I have included a batch script in the `vinetrimmer/devices/` directory to do this. Simply execute the script and try again. 

If you are getting `TooManyDevices` error or Amazon is giving you trouble with some weird error, then logout in the browser, log back in, extract and use fresh cookies. Try also deleting `vinetrimmer/Cache/AMZN/`.

If you want to try a different CDM, you will need the corresponding DeviceTypeID (DTID) put into `amazon.yml`. As far as I know, you would need to sniff the traffic from the device (with the CDM) to get the DTID. You can get 1080p keys without the corresponding DTID for the CDM you are using. But you will need the right DTID for the CDM you are using to get 4K keys. 

If you are getting `PRS.NoRights` error, then there are 3 possible explantations for it. One, CDM simply needs to be reprovisioned. Two, you are using the incorrect DTID for the given CDM. Three, the Amazon has revoked or downgraded the CDM to only HD/SD quality.

If your region has ad-free subscription tier, you will need the ad-free subscription tier for 4K/HDR/DV.

### HBOMAX

 - If it throws a `KeyError` exception, logout in the browser, log back in using email and password. Try playing the first few seconds of a movie. After that, navigate back to MAX homepage and export fresh cookies. Save cookies to `vinetrimmer/Cookies/Max/default.txt`.

### Peacock 

 - Has removed Playready support entirely for UHD, now needs Widevine L1.
 - Authorization - cookies saved to `vinetrimmer/Cookies/Peacock/default.txt`

### Hotstar

 - To use, login to Hotstar and navigate to https://www.hotstar.com/{region}/home. Extract cookies from that page and save to path `vinetrimmer\Cookies\Hotstar\default.txt` (Case sensitive).
 - Otherwise add credentials to `vinetrimmer.yml`. An example is given.
 - A free account has access to lots of content.
 - Hotstar requires an Indian (+91) phone number to signup to Indian region, even for free account.
 - Hates VPN's, try using a residential proxy if you have one.
 - All content is licensed via Widevine L3 or has no DRM.

### SonyLiv

 - Needs Indian IP address. Otherwise will result in `list index out of range` error.

### DisneyPlus

 - Needs only credentials added to `vinetrimmer.yml`.
 - Requires you to use `-m` or `--movie` flag if you are downloading a movie. Append flag to end of your command.
 - From my testing, when using with VPN, it causes lots of issues, mainly needing to clear `Cache` folder and login repeatedly. Use residential proxies if available. Don't hammer service. Try waiting a minute or two before logging in again.
 - If you are getting `No 2160p track found` error for a title you know has 4k, then try passing `-r DV` or `-r HDR`. Make sure your account can access highest qualities.
 - Should be more stable now when using proxy. But do be careful. We don't use proxy for downloading segments, which means your IP could get temporarily banned from DSNP servers (i.e persistent 403 errors). If you download the same title multiple times or many titles/episodes at once/too quickly your IP address could get banned. Happened to me while testing.
 - `idp.error.identity.bad-credentials` if you get this error, first try running the same command again. If it still gives out this error, clear `Cache/DisneyPlus/` and try again. If it still errors, reset password for the account and login using new credentials. 

### Hulu

 - Authorization: cookies saved to `vinetrimmer/Cookies/Hulu/default.txt`
 - Windscribe VPN sometimes fails. Simply try again.


### AppleTVPlus
 - For `--keys` to work with ATVP you need to pass the `--no-subs` flag.
 - You only need proxy/VPN to login once, extract cookies and do a first run.

### iTunes

 - iTunes via rential channel on AppleTVPlus.
 - Login to iTunes in a browser. Try playing a movie. It'll redirect you to `tv.apple.com`. Cache cookies from that page to `vinetrimmer/Cookies/iTunes/default.txt`.
 - Requires you to use `-m` or `--movie` flag if you are downloading a movie. Append flag to end of your command.

### MoviesAnywhere

  - Cookies saved from home page of website to `vinetrimmer\Cookies\MoviesAnywhere\default.txt`
  - This service currently gets 720p AVC keys. For 1080p and 2160p you will need a whitelisted L1 or whitelisted SL3000. I have tried many devices and could not find one that got HD and UHD keys. If you find one please let me know. I cannot do anything more.

### Example Commands

Amazon Example:

```bash
poetry run vt dl -al en -sl all --selected -q 2160 -r HDR -w S01E18-S01E25 AMZN -b CBR --ism 0IQZZIJ6W6TT2CXPT6ZOZYX396
```

Above command:
 - gets english audio,
 - gets all available subtitles,
 - selects the HDR + 4K track,
 - gets episodes from S01E18 to S01E25 from Amazon
 - with CBR bitrate,
 - tries to force ISM
 - and the title-ID is 0IQZZIJ6W6TT2CXPT6ZOZYX396

AppleTV Example:

```bash
poetry run vt dl -al en,it -sl en,es -q 720 --proxy http://192.168.0.99:9766 -w S01E01 ATVP umc.cmc.1nfdfd5zlk05fo1bwwetzldy3
```

Above command:
 - gets english, italian audio
 - gets english, spanish subtitles,
 - lists all possible qualities,
 - selects 720p video track,
 - uses the proxy for licensing,
 - gets the first episode of first season (i.e S01E01)
 - of the title-ID umc.cmc.1nfdfd5zlk05fo1bwwetzldy3

Max Example:

```bash
poetry run vt dl -al en -sl en --keys --proxy http://192.168.0.99:9766 MAX https://play.max.com/show/5756c2bf-36f8-4890-b1f9-ef168f1d8e9c
```

Above command:
 - gets english subtitles + audio,
 - skips download and only gets the content keys,
 - from MAX
 - uses specified proxy
 - defaulting to HD for video
 - title-ID is 5756c2bf-36f8-4890-b1f9-ef168f1d8e9c

Hotstar Example:

```bash
poetry run vt dl -al en -sl en -q 4K -v HEVC HS https://www.hotstar.com/in/movies/hridayam/1260083403
```

Above command:
 - gets english subtitles + audio,
 - sets video codec to H265 codec,
 - sets video quality (ie. resolution) to 2160p,
 - Gets highest quality video/audio available.
 - title-ID is 1271342309

## Max Audio Compatability (MAC)

I have added a special flag called `--max-audio-compatability` or `-mac` for maximum compatibility with all devices. If passed with `--acodec aac,ec3 -ac 2.0,5.1` will select 3 audios like below

```
2025-04-24 16:54:23 [I] Tracks : ├─ AUD | [E-AC3] | [ec-3] | 5.1 | 640 kb/s | en-US | [Original]
2025-04-24 16:54:23 [I] Tracks : ├─ AUD | [E-AC3] | [ec-3] | 2.0 | 224 kb/s | en-US | [Original]
2025-04-24 16:54:23 [I] Tracks : ├─ AUD | [AAC] | [mp4a] | 2.0 | 128 kb/s | en-US | [Original]
```

If `-mac` not passed but only `--acodec aac,ec3 -ac 2.0,5.1` passed, will select 2 audios.

```
2025-04-24 17:10:04 [I] Tracks : ├─ AUD | [E-AC3] | [ec-3] | 5.1 | 640 kb/s | en-US | [Original]
2025-04-24 17:10:04 [I] Tracks : ├─ AUD | [AAC] | [mp4a] | 2.0 | 128 kb/s | en-US | [Original]
```

## Proxy
I recommend [Windscribe](https://windscribe.com/). You can sign up, getting 10 GB of traffic credit every month for free. We use the VPN for everything except downloading video/audio. 
Tested so far on Amazon, AppleTVPlus, Max, and DisneyPlus and Hulu.

### Steps:

1. Download Windscribe app and install it.

2. Go to `Options` -> `Connection` -> `Split Tunneling`. Enable it.
   
    Set `Mode` as `Inclusive`.

3. Go to `Options` -> `Connection` -> `Proxy Gateway`. Enable it. Select `Proxy Type` as `HTTP`.
   
   Copy the `IP` field (will look something like `192.168.0.141:9766`).

   Pass above copied to Vinetrimmer with the proxy flag. If you are using other VPNs, extract the proxy (use the browser extension to do this). It will look something like `http(s)://username:pass@host/IP:PORT`. Ex -> `http://user:pass@domain.com:443`. Pass it like below:

   ```bash
   poetry run vt dl -q 1080 --proxy http://user:pass@domain.com:443 AMZN [TITLE]
   ```

4. Skip this step if you are not integrating a new service yourself. In the service, within get_tracks() function we do this below. Set needs_proxy to True if your service needs proxy to get manifest (Ex - Netflix, Hotstar).
    ```python
    for track in tracks:
        track.needs_proxy = False
    ```
    
    This flag signals that this track does not need a proxy and a proxy will not be passed to downloader even if proxy given in CLI options.

   
## Other
 - Errors arise when running VT in non python3 environments. Make sure to use proper python3.
 - To use programs in `scripts` folder, first activate venv then, then - 
      ```bash
      poetry run python scripts/ParseKeybox.py
      ```
 - There is another way of running this instead of using `poetry`. In root folder of VT-PR there is a `vt.py` (which is essentially the same as `vinetrimmer/vinetrimmer.py`). Activate venv, then:
   ```bash
   python vt.py dl ......(rest of the command as before).......
   ```
   This is useful for debugging/stepping through in IDE's without having to deal with poetry.

 ## Nuitka Compile

 - Activate venv
   
 - `python -m pip install nuitka`

 - Verify using command `nuitka --version`

 - Then:
 ```bash
 nuitka --standalone --output-dir=dist --windows-console-mode=force vt.py --include-data-dir=./vinetrimmer/=vinetrimmer/ --include-data-dir=./binaries/=binaries
 ```
 - `--standalone` will give a folder of compiled pythonic objects. Zip it to distribute. This is recommended. 
 - If you don't want to carry around/deal with a zip, instead use `--onefile`. This has the drawback of setting the default folders to the temp folder in whatever OS you are using. This could be fixed with some extra code but that is currently not implemented.
 - Refer to [link](https://nuitka.net/user-documentation/user-manual.html) if anything errors out.

## Additional Features
 - Progress Bars for decryption ([mp4decrypt](https://github.com/chu23465/bentoOldFork), Shaka)
 - ISM manifest support (Microsoft Smooth Streaming) (Experimental)
 - N_m3u8DL-RE downloader support (Experimental)
 - Resume failed download has been implemented. If a track has been successfully downloaded previously and exists in `Temp` directory (encrypted or decrypted), VT will not download said track again.


## Broken / To-Do (Descending order of priority) 

 - [ ] Add a version.py
 - [ ] Pipe last frame of output of external dependencies like mkvmerge, N_m3u8 and decryptors to logfile
 - [ ] First stable release
 - [ ] Shaka with progress bar repository 
 - [ ] Add download speed limit to avoid IP bans.
 - [ ] Single script that installs, and if already installed checks for and applies updates
 - [ ] Replace poetry with uv
 - [ ] Ruff liniting and formatting
 - [ ] Atmos audio with ISM manifest (Amazon)
 - [ ] Add [m4ffdecrypt](https://github.com/Eyevinn/mp4ff)
 - [ ] Hybrid creation with [dovi_tool](https://github.com/quietvoid/dovi_tool/). This feature is in Beta. Only tested so far on DisneyPlus. Needs more work. Ex: filenaming needs correction, temp directory is a mess after hybrid creation, use another tool insteal of `dovi_tool` to get Profile 8.1 DV-HDR10+ instead of DV Profile 5 HDR10 compatible.
 - [ ] Downloader field in config, per service.
 - [ ] Make a script to download latest binaries for vt automatically at startup.
 - [ ] Detect if running as Nuikta compiled binary, then in vt.py set directories relative to binary path
 - [ ] Find a way to estimate final file size for a track. Check if enough space is left on disc for double the amount of selected tracks - since mp4decrypt and Nm3u8 both make copies of the files 
 - [ ] Merge DB script
 - [ ] Modify aria2c to include a progress bar ?
 - [ ] Github Actions Python script that builds and publishes release for every commit to not readme.md
 - [ ] MAX - Fix HDR10/DV --list
 - [ ] Fix original language (Was removed as workaround for a bug)
 - [ ] Make a windscribe.py for proxies modelled after nordvpn.py. Refer to the chrome extension for the code.
 - [ ] Move to requests, curl or otherwise to download subtitles
 - [ ] Replace track.dv, track.hdr10 with track.PQ. Value will be an enum. This will require a major-ish rewrite.
 - [ ] Netflix service is currently broken (will probably be fixed Soon™)
 - [ ] Integrate [subby](https://github.com/vevv/subby)
 - [ ] Licensing before download (?)
 - [ ] Guide for writing a service + debugging
 - [ ] Implement a scan/hammer/cache keys for each service - pass string of zeros as title id. Then copy and rework dl.py to iterate over returned list of titles from scan function


### Amazon Specific 

 - [ ] Refresh Token for Amazon service
 - [ ] Pythonic implementation of init.mp4 builder for ism manifest for avc, hvcc, dv, ac3, eac3, eac3-joc codecs
 - [ ] Make a pure python requests based downloader for ISM/MSS manifest. Write init.mp4 then download each segment to memory, decrypt in memory and write it to a binary merged file. Download segments in batches. Batch size based on thread count passed to program. Download has to be sequentially written. 
 - [ ] `--bitrate CVBR+CBR` is currently broken
 - [ ] Get highest quality CBR and CVBR MPD+ISM by default to AMZN
 - [ ] Specify devices in config for MPD or ISM then load one based on command 
 - [ ] For videos, download init.mp4 using N_m3u8, mediainfo it to get FPS, HDR info
 - [ ] Manifest url caching system for every key/Track object.

If anyone has any idea how to fix above issues, feel free to open a pull request.


## Credits
[@rlaphoenix](https://github.com/rlaphoenix) for [pywidevine](https://github.com/devine-dl/pywidevine)

[@rlaphoenix](https://github.com/rlaphoenix) again as he was the original developer behind the `VineTrimmer` base `Widevine` version (later renamed to `devine`) .

[@DevLARLEY](https://github.com/DevLARLEY) for [pyplayready](https://git.gay/ready-dl/pyplayready)

[@FieryFly](https://github.com/FieryFly) for an additional MAX fix.

[@vevv](https://github.com/vevv) for [subby](https://github.com/vevv/subby)

[@globocom](https://github.com/globocom/) for [m3u8](https://github.com/globocom/m3u8)

`@Wiesiek` on Discord for a few ideas

[DRM-Lab-Project](https://discord.gg/xHjetwZP) for numerous bug fixes and support.

[Playready-Discord](https://discord.gg/aNNKxurrU6) for numerous bug fixes and support.

Various members of the above mentioned Discord servers for testing, bug reporting, fixes etc. Thank You :)

[CDRM-Project](https://discord.cdrm-project.com/) and `@TPD94`, `@radizu` for getting me started on this journey, being a source of inspiration and for keeping a community well and alive.

[@m0ck69](https://github.com/m0ck69) for sharing a DisneyPlus account for testing purposes.

[@methflix](https://github.com/methflix) for sharing a Hulu account for testing purposes.

[@chu23465] (https://github.com/chu23465/) for assembling the initial project.

The services included here were not written by me. They were either found in the mentioned Discord servers or shared by an individual. If anyone feels like they deserve a credit in the README, open an issue and I'll add you.

## Legal
I can not stress enough how important it i that you check the laws in you area as it could save you thousands (litertally)
