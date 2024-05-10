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

if [ -f "~/.ssh/id_rsa" ]; then
    echo 'Setting Up Github Account (first input)'
    ssh-keygen -t rsa -b 4096 -C "$1"
    git config --global user.email "$1"
    eval $(ssh-agent -s)
    ssh-add ~/.ssh/id_rsa

    echo 'Add your public key to your github account'
    cat < ./.ssh/id_rsa.pub
fi


#Write bashrc file (install permisisons)
eval $(ssh-agent -s)
/bin/cat <<EOM >"/home/$(whoami)/.bashrc"
conda activate py3
export PLOT_STREAM=true
EOM

/bin/cat <<EOM >"/home/$(whoami)/.bash_logout"
kill $SSH_AGENT_PID
EOM

#echo "@reboot /usr/local/bin/pigpiod" | sudo crontab -

#Add the github identity file using deploy key
CNFG="/home/$(whoami)/.ssh/config"
echo "touch $CNFG"
touch "$CNFG" #ensure config file
echo "write config $CNFG"
/bin/cat <<EOM >$CNFG
Host github.com
    Hostname github.com
    IdentityFile=/home/$(whoami)/.ssh/waveware_deploy
Host gist.github.com
    Hostname gist.github.com
    IdentityFile=/home/$(whoami)/.ssh/waveware_deploy
EOM

ssh-add ~/.ssh/waveware_deploy

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

### Terminal plotting
git clone https://github.com/mogenson/ploot.git
cd ploot
cargo build # or cargo install --path .

#alias to stream hw data
alias hwstream= "python ~/wave_tank_driver/waveware/hardware.py | ploot"

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
pip install git+ssh://git@github.com/neptunyalabs/wave_tank_driver.git

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


