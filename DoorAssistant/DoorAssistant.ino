// Arduino Mega 2560
// PIR (HC-SR501): OUT -> D38, VCC -> 5V, GND -> GND
// HC-05: TXD -> D19 (RX1), RXD <- D18 (TX1) through a voltage divider

#define PIR_PIN 38

unsigned long lastMotion = 0;
const unsigned long COOLDOWN_MS = 5000;

void setup() {
  pinMode(PIR_PIN, INPUT);

  Serial.begin(9600);      // USB Serial Monitor
  Serial1.begin(9600);     // HC-05 Bluetooth (Serial1 = pins 18/19)

  delay(300);
  Serial.println("SYSTEM READY");
  Serial1.println("BOOT");
}

void loop() {
  int motion = digitalRead(PIR_PIN);

  if (motion == HIGH) {
    unsigned long now = millis();

    if (now - lastMotion >= COOLDOWN_MS) {
      lastMotion = now;

      Serial.println("Detected leaving");
      Serial1.println("EVENT:LEAVING");
    }
  }
}