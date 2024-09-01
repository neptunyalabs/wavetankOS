#!/bin/bash

#RUN WITH: bash <(curl -sL https://gist.githubusercontent.com/SoundsSerious/c0c7646fd37b03fd353602b9d2fc39eb/raw/019f7a2b4b23163b9e6351bc8a0a373a2bdf2185/setup.sh), update if gist chagnes

#Install for 64Bit Ubuntu (debian) systems

#make file `waveware_deploy` with private key
mkdir sw
cd sw
if grep -q microsoft /proc/version; then
  echo "Install WSL..."
else
  echo "Install Linux..."
fi

cd ~/


#Write bashrc file (install permisisons)
eval $(ssh-agent -s)
/bin/cat <<EOM >"/home/$(whoami)/.bashrc"
conda activate py3
EOM
# 
# /bin/cat <<EOM >"/home/$(whoami)/.bash_logout"
# kill $SSH_AGENT_PID
# EOM


#stop pigpiod
sudo killall pigpiod

#initalize git
git config --global user.name "wavetank"

#Install Preliminaries
sudo apt update -y

sudo apt install git -y
sudo apt install gcc -y
sudo apt install g++ -y
sudo apt install build-essential -y
sudo apt install net-tools -y
sudo apt install gfortran -y
sudo apt install libatlas-base-dev -y
sudo apt-get install i2c-tools
sudo pip install smbus
sudo apt install cargo
sudo apt install unzip,nettools -y
sudo apt install make,cmake,gcc,gfortran -y
sudo apt install python3-pip -y
sudo apt install python3-setuptools -y
sudo apt install python3-pigpio -y
sudo apt install libatlas3-base -y
sudo apt install awscli boto3 -y

### Terminal plotting
# git clone https://github.com/mogenson/ploot.git
# cd ploot
# cargo build # or cargo install --path .

#alias to stream hw data
# alias hwstream= "python ~/wave_tank_driver/waveware/hardware.py | ploot"

echo 'Installing Anaconda Python (follow instructions, agree & yes^10)'
if [ -z "$CONDA_EXE" ] 
then
    curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
    bash Miniforge3-$(uname)-$(uname -m).sh
    source ~/.bashrc
    
    ~/miniforge3/bin/conda init bash
    conda create -n py3 python=3.10 -y
    conda activate py3
    conda install -c anaconda pip 
    pip install -U -y pip-tools
    pip install smbus
else
    conda activate py3
fi


#Allow python 3.10 to bind to ports below 1025
sudo setcap 'cap_net_bind_service=+ep' "$(which python3.10)"

#python -m pip install --force-reinstall ninja
pip install git+https://github.com/neptunyalabs/wavetankOS.git

#Install pigpiod source
wget https://github.com/joan2937/pigpio/archive/master.zip
unzip master.zip
cd pigpio-master
make
sudo make install
cd ..

#Add pigpiod to sudo crontab systemd file
sudo bash -c '/bin/cat <<EOM >"/lib/systemd/system/pigpiod.service"
[Unit]
Description=Daemon required to control GPIO pins via pigpio
[Service]
ExecStart=/usr/local/bin/pigpiod
ExecStop=/bin/systemctl kill -s SIGKILL pigpiod
Type=forking
[Install]
WantedBy=multi-user.target
EOM'

sudo systemctl enable pigpiod #run at startup
sudo systemctl start pigpiod #run now too


#TODO: install wavetank daeomon to run on startup

sudo bash -c '/bin/cat <<EOM >"/lib/systemd/system/wavetank.service"
[Unit]
WaveTankOS Firmware & Dashboard
[Service]
ExecStart=/home/$(whoami)/wavetankOS/waveware/fw_main.py
ExecStop=/bin/systemctl kill -s SIGKILL wavetank
Type=forking

#here are the potential enviornmental varables for your use

#where to log on aws (if at all)
#Environment="WAVEWARE_LOG_S3=true"
#Environment="WAVEWARE_S3_BUCKET=custom_aws_bucket_name" 
#Environment="WAVEWARE_FLDR_NAME=v1" 

#where to run the daq / control api
#Environment="WAVEWARE_PORT=8777"
#Environment="FW_HOST=0.0.0.0"  

#control based on speed with correction
#Environment="WAVEWARE_VWAVE_DIRECT=true" 
#use 'step','pwm','off','step-pwm' depending on your motor type
#Environment="WAVE_SPEED_DRIVE_MODE=pwm"  

#Dashboard Customization
#Environment="WAVEWARE_DASH_GRAPH_UPT=3.3"
#Environment="WAVEWARE_DASH_READ_UPT=1.5"

#DAQ Rates
#Environment="WAVEWARE_POLL_RATE=0.033"
#Environment="WAVEWARE_POLL_TEMP=60"
#Environment="WAVEWARE_WINDOW=6" #wavelengths to show for buffer size

[Install]
WantedBy=multi-user.target

EOM'

sudo systemctl enable wavetank #run at startup
sudo systemctl start wavetank #run now too