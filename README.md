# tempData
For temp monitoring and control using f007th-send

## Installation
Make a user called `nolan` and do:
```sh
cd ~
git clone https://github.com/NolieRavioli/tempData
mkdir ~/tempData/data
touch ~/tempData/auth ~/tempData/data/sensor.log
```

## Usage
You can `nano ~/tempData/f007th-forwarder.py` and change the `# ---------------- Config ----------------` section.

if you are sending to a server with an auth token, you can store your auth token by pasting in the file: `nano ~/tempData/auth`.

run `~/tempData/addAutorun.sh` to make the program start collecting data on boot.
