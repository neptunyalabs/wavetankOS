# What Is This:
Wavetank OS is a do-it-yourself wave tank solution. For those in need of an in-office or in-classroom wavetank with a real data aquisition program this might be the cheapest & easiest way to get started. 

![IMG_2885](https://github.com/user-attachments/assets/2179e094-084b-4762-91b1-377b0703086f)


# What Is Included:
1. a set of structural plans, a bom, and construction guidance for the physical wavetank.
2. a bill of materials for electronic components as well as pcb schematics and design files. The design only requires soldering connections and headers so this is beginer friendly
3. this python package that runs a data aquisition system, wavemaker control, and a live dashboard service to control and view the data in real time, based on pigpio.
4. raspberry pi installation instructions
5. a post-processing data system

#  What kind of measurements are provided:
- 4 Encoder positions with RS-485 differential output, we recommend using a magnetic linear scale for its no friction, waterproof design.
- 4 Ultrasonic Distance channels available for capturing wave height.
- Several Channels Of ADC with a dedicated IC chip.
- An integration with an MPU9250 9 axis (Accel,Gyro,Magnometer) capture
- A few extra outputs for I2C and debugging
- Proven datarate is between 20-100 samples per second to S3 storage.

# How Do I Use The Software
run `wavedash` to run the live dashboard, and `wavedaq` to run the data acquisition system. Use `-h` to expose menus.

# Bill Of Materials
The bill of materials is located here, if you have questions on something feel free to leave a comment, or if you want to contribute an alternative idea feel free suggest alternatives.
https://docs.google.com/spreadsheets/d/107yxzDKXDjfQvaocU3NCo5I_NLpH0Xee_oWynt8TL3E/edit?usp=sharing



# Warning
This project comes with no garuntee of performance, or saftey. In fact with the combination of electricity and a few hundred gallons of water, as well as fast moving mechanical parts I would suggest only experienced makers attempt this project as there are probably several ways to hurt yourself.
