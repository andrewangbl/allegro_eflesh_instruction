// Instructions for the user before flashing:
// 1. Generate a new BLE UUID using the UUID generator at https://www.uuidgenerator.net/
// 2. Replace the SERVICE_UUID and CHARACTERISTIC_UUID_TX in the code below with the generated UUIDs.
// 3. Ensure the sensor boards are connected to the correct MUX pins as specified in the code.
// 4. Upload the code to your ESP32 board.

#include <Arduino.h>
#include <MLX90393.h> //LX90393 driver
#include <Wire.h>


// I2C address of the mux
#define PCAADDR 0x70

const int SENSOR_COUNT = 4;  // Number of mux channels in use
int sensor_mux_pins[SENSOR_COUNT] = {0, 1, 2, 3}; // MUX pins for the sensors
// Using all 4 channels of the PCA9546A multiplexer

// extern TwoWire Wire1;

MLX90393 mlx[5]; // Creates an array for 5 MLX90393 sensors per mux branch
MLX90393::txyz data = {0,0,0,0}; // txyz is the struct returned by burst reads: Temperature, X, Y, Z

uint8_t mlx_i2c[5] = {0x0C, 0x10, 0x11, 0x12, 0x13}; // white chip
// uint8_t mlx_i2c[5] = {0x0C, 0x0D, 0x0E, 0x0F, 0x10}; // black chip

void pcaselect(uint8_t i) {
  // if using PCA9546A (4-channel): i up to 3 is correct
  // if PCA9548A (8-channel): allow i up to 7 in pcaselect
  if (i > 3) return;

  Wire.beginTransmission(PCAADDR);
  Wire.write(1 << i); // sets one channel active?
  Wire.endTransmission();
}



void setup() {
  // put your setup code here, to run once:
  // Serial.begin(57600);
  Serial.begin(230400);

  Wire.begin();
  Wire.setClock(400000);
  delay(10);

  //start chips given address, -1 for no DRDY pin, and I2C bus object to use
  // byte status;

  for(int idx=0; idx<SENSOR_COUNT; idx++) {
    pcaselect(sensor_mux_pins[idx]);
    Serial.println("Setting port");
    delay(5);
    // for each of the 5 sensor addresses
    for(int j=0; j<5; j++) {
      mlx[j].begin(mlx_i2c[j], -1, Wire); //initializes the sensors
      mlx[j].setGainSel(1);
      mlx[j].setResolution(1,1,0);
      // status
      // Serial.println("Status (Chip " + String(j) + "): " + String(status));
      mlx[j].startBurst(0xF);
    };
  };
}

void loop() {
  // put your main code here, to run repeatedly:
  for(int idx=0; idx < SENSOR_COUNT; idx++) {
      // myMux.setPort(sensor_mux_pins[idx]);
      pcaselect(sensor_mux_pins[idx]);
      for(int i=0;i<5;i++) {
        mlx[i].readBurstData(data); // fetch latest T,X,Y,Z from sensor i on this mux leg

        Serial.write((byte*)&data, sizeof(data)); // T, X, Y, Z (all 4 fields)
      };
    };
    Serial.println(); // After reading all sensors, prints a newline (\r\n) to mark the end of a “frame”.
}
