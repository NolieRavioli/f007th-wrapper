# tempData
For temp monitoring and heater control using [f007th-send](https://github.com/alex-konshin/f007th-rpi) by `alex-konshin`. 

f007th-send for 64-bit arm.

Using Linux ras4 6.1.21-v8+ #1642 SMP PREEMPT Mon Apr  3 17:24:16 BST 2023 aarch64 GNU/Linux

 - Raspberry Pi 4b (1gig)
 - RXB6 433mhz reciever + 17.3cm antenna
 - HC-SR501 PIR
 - Inland 5V Relay Module

## Installation
Make a user called `nolan` and do:
```sh
cd ~
git clone https://github.com/NolieRavioli/tempData
mkdir ~/tempData/data
touch ~/tempData/auth ~/tempData/data/sensor.log
```

you may have to make the files executable:
```sh
chmod +x ~/tempData/f007th-forwarder.py ~/tempData/f007th-send ~/tempData/rmAutorun.sh ~/tempData/addAutorun.sh
```

you may remove dataExamples to save a tiny bit of space if you'd like
```sh
rm -r ~/tempData/dataExamples/
```

## Usage
You can `nano ~/tempData/f007th-forwarder.py` and change the `Config` section.

store your auth token by pasting in the file: `nano ~/tempData/auth` if you are sending to a server with an auth token.

run `~/tempData/addAutorun.sh` to make the program start collecting data on boot.

run `~/tempData/rmAutorun.sh` to stop the program from running on boot.
