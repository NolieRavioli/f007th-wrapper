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

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling f007th service..."
sudo systemctl enable f007th.service

echo "Starting f007th service..."
sudo systemctl start f007th.service

echo "Service installed and started."
