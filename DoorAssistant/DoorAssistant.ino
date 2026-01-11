#define TRIG_PIN 2
#define ECHO_PIN 3
#define DISTANCE_THRESHOLD_CM 50

unsigned long lastEvent = 0;
const unsigned long COOLDOWN_MS = 3000;

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  Serial.begin(9600);      // USB Serial Monitor
  Serial1.begin(9600);     // HC-05 Bluetooth (Serial1 = pins 18/19)

  delay(300);
  Serial.println("SYSTEM READY");
  Serial1.println("BOOT");
}

long getDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  
  long distance = duration / 58;
  return distance;
}

void loop() {
  long distance = getDistance();

  // If object detected close (person leaving)
  if (distance > 0 && distance <= DISTANCE_THRESHOLD_CM) {
    unsigned long now = millis();

    if (now - lastEvent >= COOLDOWN_MS) {
      lastEvent = now;

      // Send event for server to capture
      Serial.println("EVENT:LEAVING");
      Serial1.println("EVENT:LEAVING");
    }
  }

  delay(100);  // Small delay to avoid overwhelming the sensor
}