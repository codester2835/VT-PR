git clone https://github.com/chu23465/VT-PR
cd VT-PR
sudo apt update
VER=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))') && echo $VER
VENVCMD=$( sudo apt install python"$VER"-venv )
echo $VENVCMD
"${VENVCMD[@]}"
sudo apt-get install pipx
python -m pipx install poetry==1.8.5
#python -m pipx ensurepath
python -m poetry config virtualenvs.in-project true
python -m poetry lock --no-update
python -m poetry install
rm -r ./binaries/
mkdir ./binaries/
mv -v ./linux_binaries/* ./binaries/
sudo add-apt-repository ppa:ubuntuhandbook1/apps -y
DIS=$(awk -F= '/^NAME/{gsub(/"/, "", $2);print $2}' /etc/os-release) && echo $DIS
if [ $DIS == "Ubuntu" ]; then 
  echo "Adding MKVToolnix to sources"
  sudo wget -O /etc/apt/keyrings/gpg-pub-moritzbunkus.gpg https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg
  env bash -c '. /etc/os-release; echo deb [arch=amd64 signed-by=/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ $VERSION_CODENAME main > /etc/apt/sources.list.d/mkvtoolnix.download.list'
fi;
sudo apt update
sudo apt-get install aria2 7zip
sudo apt-get install libmediainfo0v5
if [ $DIS == "Ubuntu" ]; then 
  sudo apt-get install mkvtoolnix
  which mkvmerge | xargs -I{} cp {} ./binaries/
fi;
which aria2c |  xargs -I{} cp {} ./binaries/
cd ./binaries/
7z x "ffmpeg-n6.1.7z"
if [ $DIS != "Ubuntu" ]; then
  chmod u+rx ./mkvtoolnix.AppImage
  ln -s ./mkvtoolnix.AppImage mkvmerge
fi;
find . -type f -print0 | xargs -0 chmod a+x