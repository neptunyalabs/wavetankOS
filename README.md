# What Is This:
Wavetank OS is a do-it-yourself wave tank solution. For those in need of an in-office or in-classroom wavetank with a real data acquisition program this might be the cheapest & easiest way to get started.

![Wave Tank Example](media/waves_test.gif)

> [!CAUTION]
> This project comes with no guarantee of performance, or safety. In fact with the combination of electricity and a few hundred gallons of water, as well as fast moving mechanical parts We suggest only experienced makers attempt this project as there are many ways to hurt or kill yourself.


# What Is Included:
1. a set of structural plans, a bom, and construction guidance for the physical wavetank.
2. a bill of materials for electronic components as well as pcb schematics and design files. The design only requires soldering connections and headers so this is beginner friendly
3. this python package that runs a data acquisition system, wave maker control, and a live dashboard service to control and view the data in real time, based on pigpio.
4. raspberry pi installation instructions
5. a post-processing data system

#  What kind of measurements are provided:
- 4 Encoder positions with RS-485 differential output, we recommend using a magnetic linear scale for its no friction, waterproof design.
- 4 Ultrasonic Distance channels available for capturing wave height.
- Several Channels Of ADC with a dedicated IC chip.
- An integration with an MPU9250 9 axis (Accel,Gyro,Magnetometer) capture
- A few extra outputs for I2C and debugging
- Proven data-rate is between 20-100 samples per second to S3 storage.

# How To:
Below you'll find a mostly complete set of items you'll need to have to construct the wavetank system.

### Construction Instructions:
1. Tank Construction & Assembly [here](CONSTRUCTION.md)
2. Electronics Construction Overview [here](ELECTRONICS.md)

### Bill of Materials (BOM)
The bill of materials is located here, if you have questions on something feel free to leave a comment, or if you want to contribute an alternative idea feel free suggest alternatives.
https://docs.google.com/spreadsheets/d/107yxzDKXDjfQvaocU3NCo5I_NLpH0Xee_oWynt8TL3E/edit?usp=sharing

### PCB Design Files:
You can order your PCB's from this website, as well as modify the design. If you do make significant improvements to the design please fork this project and submit a PR with your design files.
https://oshwlab.com/neptunya/waveware


### Project Share Folder:
Please see additional media for the construction of the wave tank or assembly of the electronics
https://drive.google.com/drive/folders/0AGw2YOvWZK7JUk9PVA
