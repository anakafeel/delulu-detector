/*
 * Delulu Detector - Round 1: Reflex Round
 * Arduino Uno sketch. Reads sensors and prints ONE JSON object per line over
 * serial. No scoring or game logic lives here; the Raspberry Pi does all of it.
 *
 * Flow:
 *   1. IDLE: player turns the rotary dial to set a claim (0-100).
 *   2. Player presses the button -> claim is LOCKED (dial read at that instant).
 *   3. Random wait of RANDOM_DELAY_MIN_MS..RANDOM_DELAY_MAX_MS.
 *      Pressing during this wait = FALSE START (reported, round ends).
 *   4. CUE: LED on + buzzer beep.
 *   5. Measure ms from cue to button press (or time out after REACTION_TIMEOUT_MS).
 *
 * Serial: 115200 baud, 8N1, newline-terminated JSON.
 *
 * Result line (the only line the Pi scores):
 *   {"type":"result","round_id":1,"seq":3,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}
 *   false start: "actual":null,"false_start":true
 *   timeout:     "actual":null,"timeout":true
 * Informational lines (Pi ignores them, handy in the Serial Monitor):
 *   {"type":"status","state":"ready"} / "locked" / "cue"
 */

// ----------------------------- Pin / config -------------------------------
#define DIAL_PIN              A0     // Grove rotary angle sensor (SIG)
#define BUTTON_PIN            2      // Grove button (SIG) or tactile button
#define CUE_LED_PIN           4      // Cue LED (Grove LED socket or LED + 220R)
#define BUZZER_PIN            6      // Grove buzzer / piezo (optional)
#define RANDOM_SEED_PIN       A1     // leave UNCONNECTED (floating = noise seed)

// Grove button module outputs HIGH when pressed -> 0.
// Plain tactile button wired pin->GND using INPUT_PULLUP -> 1.
#define BUTTON_ACTIVE_LOW     0

#define SERIAL_BAUD           115200
#define ROUND_ID              1      // round TYPE: 1 = Reflex Round
#define RANDOM_DELAY_MIN_MS   1500
#define RANDOM_DELAY_MAX_MS   4000
#define REACTION_TIMEOUT_MS   3000   // no press this long after cue = timeout
#define DEBOUNCE_MS           30
#define BUZZER_FREQ_HZ        2000
#define BUZZER_MS             120
#define DIAL_ADC_MAX          1023   // raise/lower if your pot doesn't hit the rails
// ---------------------------------------------------------------------------

unsigned long seq = 0;

bool buttonPressed() {
#if BUTTON_ACTIVE_LOW
  return digitalRead(BUTTON_PIN) == LOW;
#else
  return digitalRead(BUTTON_PIN) == HIGH;
#endif
}

// Block until the button is released and has stayed released for DEBOUNCE_MS.
void waitForRelease() {
  unsigned long releasedAt = millis();
  while (true) {
    if (buttonPressed()) {
      releasedAt = millis();
    } else if (millis() - releasedAt >= DEBOUNCE_MS) {
      return;
    }
  }
}

int readClaim() {
  long raw = 0;
  for (int i = 0; i < 8; i++) {           // small average to calm the pot
    raw += analogRead(DIAL_PIN);
  }
  raw /= 8;
  long claim = map(raw, 0, DIAL_ADC_MAX, 0, 100);
  return (int)constrain(claim, 0, 100);
}

void printStatus(const char *state) {
  Serial.print(F("{\"type\":\"status\",\"state\":\""));
  Serial.print(state);
  Serial.println(F("\"}"));
}

void printResult(int claim, long actualMs, bool falseStart, bool timedOut) {
  Serial.print(F("{\"type\":\"result\",\"round_id\":"));
  Serial.print(ROUND_ID);
  Serial.print(F(",\"seq\":"));
  Serial.print(seq);
  Serial.print(F(",\"claim\":"));
  Serial.print(claim);
  Serial.print(F(",\"actual\":"));
  if (actualMs < 0) {
    Serial.print(F("null"));
  } else {
    Serial.print(actualMs);
  }
  Serial.print(F(",\"unit\":\"ms\",\"false_start\":"));
  Serial.print(falseStart ? F("true") : F("false"));
  Serial.print(F(",\"timeout\":"));
  Serial.print(timedOut ? F("true") : F("false"));
  Serial.println(F("}"));
}

void cueOn() {
  digitalWrite(CUE_LED_PIN, HIGH);
  tone(BUZZER_PIN, BUZZER_FREQ_HZ, BUZZER_MS);
}

void cueOff() {
  digitalWrite(CUE_LED_PIN, LOW);
  noTone(BUZZER_PIN);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
#if BUTTON_ACTIVE_LOW
  pinMode(BUTTON_PIN, INPUT_PULLUP);
#else
  pinMode(BUTTON_PIN, INPUT);
#endif
  pinMode(CUE_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  cueOff();
  randomSeed(analogRead(RANDOM_SEED_PIN));
  printStatus("ready");
}

void loop() {
  // 1-2. Wait for the lock press; the dial value at that moment is the claim.
  if (!buttonPressed()) {
    return;
  }
  delay(DEBOUNCE_MS);
  if (!buttonPressed()) {
    return;  // bounce / noise
  }
  int claim = readClaim();
  seq++;
  printStatus("locked");
  waitForRelease();

  // 3. Random wait; any press now is a false start.
  unsigned long waitMs = random(RANDOM_DELAY_MIN_MS, RANDOM_DELAY_MAX_MS + 1);
  unsigned long waitStart = millis();
  while (millis() - waitStart < waitMs) {
    if (buttonPressed()) {
      printResult(claim, -1, true, false);
      waitForRelease();
      printStatus("ready");
      return;
    }
  }

  // 4. Cue.
  cueOn();
  unsigned long cueAt = millis();
  printStatus("cue");

  // 5. Measure reaction.
  while (!buttonPressed()) {
    if (millis() - cueAt >= REACTION_TIMEOUT_MS) {
      cueOff();
      printResult(claim, -1, false, true);
      printStatus("ready");
      return;
    }
  }
  unsigned long reactionMs = millis() - cueAt;
  cueOff();
  printResult(claim, (long)reactionMs, false, false);
  waitForRelease();
  printStatus("ready");
}
