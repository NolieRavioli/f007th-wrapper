# tempData
For temp monitoring and heater control using [f007th-send](https://github.com/alex-konshin/f007th-rpi) by `alex-konshin`. 

**f007th-send** compiled on: *Linux ras4 6.1.21-v8+ #1642 SMP PREEMPT Mon Apr  3 17:24:16 BST 2023 aarch64 GNU/Linux*

**f007th-send-32** compiled on: *Linux ras0 6.1.21+ #1642 Mon Apr  3 17:19:14 BST 2023 armv6l GNU/Linux*

 - Raspberry Pi 4b (1gig)
 - RXB6 433mhz reciever + 17.3cm antenna
 - HC-SR501 PIR
 - Inland 5V Relay Module

## Prerequisites

Make a user called `nolan`.

```sh
sudo apt-get update
sudo apt-get install -y python3 libcurl4-openssl-dev libmicrohttpd-dev
```

### [gpio-ts](https://github.com/alex-konshin/gpio-ts)
```sh
sudo apt update
sudo apt install -y raspberrypi-kernel-headers build-essential
```

```sh
cd ~
git clone https://github.com/alex-konshin/gpio-ts.git
cd gpio-ts
make all
```

```sh
sudo insmod gpio-ts.ko gpios=17
sudo mkdir -p /lib/modules/$(uname -r)/kernel/drivers/gpio/
sudo cp ~/gpio-ts/gpio-ts.ko /lib/modules/$(uname -r)/kernel/drivers/gpio/
sudo depmod
```

## Installation

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

### [f007th-send](https://github.com/alex-konshin/f007th-rpi)

the binary is precompiled for 64-bit, if you are running a 32-bit raspberry pi, you can try
```sh
cd ~/tempData/
mv f007th-send f007th-send-64
mv f007th-send-32 f007th-send
```

if this doesnt work, you can compile it for your OS:

```sh
cd ~
git clone https://github.com/alex-konshin/f007th-rpi.git
/bin/bash f007th-rpi/build.sh
```
if the build.sh doesnt fail:
```sh
mv ~/tempData/f007th-send ~/tempData/f007th-send-64
mv ~/f007th-rpi/bin/f007th-send ~/tempData/f007th-send
```

## Usage
You can `nano ~/tempData/f007th-forwarder.py` and change the `Config` section.

store your auth token by pasting in the file: `nano ~/tempData/auth` if you are sending to a server with an auth token.

run `~/tempData/addAutorun.sh` to make the program start collecting data on boot.

run `~/tempData/rmAutorun.sh` to stop the program from running on boot.
