#!/bin/bash
SERVICE_PATH="/etc/systemd/system/f007th.service"

echo "Creating f007th.service file..."
sudo tee "$SERVICE_PATH" > /dev/null <<EOF
[Unit]
Description=F007th sensor forwarder
After=network.target

[Service]
ExecStart=/bin/bash -c '/home/nolan/tempData/f007th-send -g 17 -l /home/nolan/tempData/data/sensor.log -o | /home/nolan/tempData/f007th-forwarder.py'
WorkingDirectory=/home/nolan
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "Starting gpio-ts..."
sudo modprobe gpio_ts gpios=17 2>/dev/null || true

echo "Ensuring gpio-ts autoloads on boot..."
if ! grep -q '^gpio_ts' /etc/modules; then
    echo "gpio_ts" | sudo tee -a /etc/modules > /dev/null
    echo "Added gpio_ts to /etc/modules"
else
    echo "gpio_ts already present in /etc/modules"
fi

echo "Setting gpio-ts options (gpios=17)..."
sudo tee /etc/modprobe.d/gpio_ts.conf > /dev/null <<EOC
options gpio_ts gpios=17
EOC
echo "gpio-ts options saved to /etc/modprobe.d/gpio_ts.conf"

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling f007th service..."
sudo systemctl enable f007th.service

echo "Starting f007th service..."
sudo systemctl start f007th.service

echo "Service installed and started."
