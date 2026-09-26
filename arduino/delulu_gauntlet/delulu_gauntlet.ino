/*
 * Delulu Detector - Round 1: Reflex Round
 * Arduino UNO R4 WiFi (also builds for a classic Uno) sketch. Reads sensors and prints ONE JSON object per line over
 * serial. No scoring or game logic lives here; the Raspberry Pi does all of it.
 *
 * Flow:
 *   1. IDLE: player turns the rotary dial to set a claim (0-100).
 *   2. Player presses the button -> claim is LOCKED (dial read at that instant).
 *   3. Random wait of RANDOM_DELAY_MIN_MS..RANDOM_DELAY_MAX_MS.
 *      Pressing during this wait = FALSE START (reported, round ends).
 *   4. CUE: onboard LED (pin 13) + full 12x8 LED matrix on the R4 WiFi
 *      + optional buzzer beep. No external LED needed.
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
#define CUE_LED_PIN           LED_BUILTIN  // onboard "L" LED, no wiring needed
#define USE_BUZZER            1      // 0 if no buzzer is connected (harmless either way)
#define BUZZER_PIN            6      // Grove buzzer / piezo (optional)
#define RANDOM_SEED_PIN       A1     // leave UNCONNECTED (floating = noise seed)

// Grove button module outputs HIGH when pressed -> 0 (our hardware: idles LOW, HIGH when pressed).
// Plain tactile button wired pin->GND using INPUT_PULLUP -> 1.
#define BUTTON_ACTIVE_LOW     0

#define SERIAL_BAUD           115200
#define ROUND_ID              1      // round TYPE: 1 = Reflex Round
#define RANDOM_DELAY_MIN_MS   1500
#define RANDOM_DELAY_MAX_MS   4000
#define REACTION_TIMEOUT_MS   3000   // no press this long after cue = timeout
#define RELEASE_SETTLE_MS     80     // button must stay released this long after a press
#define PRESS_CONFIRM_MS      10     // a press needs this much contact to count (ignores flicker)
#define PRESS_BOUNCE_MS       3      // a release shorter than this while confirming is bounce, not a let-go
#define PRESS_CONFIRM_MAX_MS  30     // give up if PRESS_CONFIRM_MS of contact isn't reached this soon
#define BUZZER_FREQ_HZ        2000
#define BUZZER_MS             120
#define DIAL_ADC_MAX          1023   // raise/lower if your pot doesn't hit the rails
// ---------------------------------------------------------------------------

#if defined(ARDUINO_UNOR4_WIFI)
#include "Arduino_LED_Matrix.h"
ArduinoLEDMatrix matrix;
const uint32_t MATRIX_ALL_ON[3]  = {0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF};
const uint32_t MATRIX_ALL_OFF[3] = {0, 0, 0};
#endif

unsigned long seq = 0;

bool buttonPressed() {
#if BUTTON_ACTIVE_LOW
  return digitalRead(BUTTON_PIN) == LOW;
#else
  return digitalRead(BUTTON_PIN) == HIGH;
#endif
}

// Block until the button is released and has stayed released for RELEASE_SETTLE_MS.
void waitForRelease() {
  unsigned long releasedAt = millis();
  while (true) {
    if (buttonPressed()) {
      releasedAt = millis();
    } else if (millis() - releasedAt >= RELEASE_SETTLE_MS) {
      return;
    }
  }
}

// Used for every press (lock, false start, reaction). If the button reads
// pressed, record that first contact edge once, then keep sampling until the
// button has read pressed for PRESS_CONFIRM_MS in total. Bounces (releases
// shorter than PRESS_BOUNCE_MS) don't reset the first-contact time; their
// released time just doesn't count toward PRESS_CONFIRM_MS.
// Returns true for a real press and sets firstAt to the millis() of the first
// contact edge, so reaction time is measured from first contact, not from
// confirmation. Returns false (firstAt untouched) if the button is released for
// PRESS_BOUNCE_MS or longer, or if confirmation takes over PRESS_CONFIRM_MAX_MS
// (noise, not a press).
bool confirmedPress(unsigned long &firstAt) {
  if (!buttonPressed()) {
    return false;
  }
  const unsigned long contactMs = millis();   // first contact edge, never reset
  const unsigned long startUs = micros();
  unsigned long lastUs = startUs;
  unsigned long pressedUs = 0;                // accumulated time read as pressed
  unsigned long releasedSinceUs = 0;
  bool released = false;
  while (pressedUs < PRESS_CONFIRM_MS * 1000UL) {
    unsigned long nowUs = micros();
    if (nowUs - startUs >= PRESS_CONFIRM_MAX_MS * 1000UL) {
      return false;
    }
    if (buttonPressed()) {
      pressedUs += nowUs - lastUs;
      released = false;
    } else if (!released) {
      released = true;
      releasedSinceUs = nowUs;
    } else if (nowUs - releasedSinceUs >= PRESS_BOUNCE_MS * 1000UL) {
      return false;                           // really let go: not a press
    }
    lastUs = nowUs;
  }
  firstAt = contactMs;
  return true;
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
#if defined(ARDUINO_UNOR4_WIFI)
  matrix.loadFrame(MATRIX_ALL_ON);
#endif
#if USE_BUZZER
  tone(BUZZER_PIN, BUZZER_FREQ_HZ, BUZZER_MS);
#endif
}

void cueOff() {
  digitalWrite(CUE_LED_PIN, LOW);
#if defined(ARDUINO_UNOR4_WIFI)
  matrix.loadFrame(MATRIX_ALL_OFF);
#endif
#if USE_BUZZER
  noTone(BUZZER_PIN);
#endif
}

void setup() {
  Serial.begin(SERIAL_BAUD);
#if BUTTON_ACTIVE_LOW
  pinMode(BUTTON_PIN, INPUT_PULLUP);
#else
  pinMode(BUTTON_PIN, INPUT);
#endif
  pinMode(CUE_LED_PIN, OUTPUT);
#if defined(ARDUINO_UNOR4_WIFI)
  matrix.begin();
#endif
#if USE_BUZZER
  pinMode(BUZZER_PIN, OUTPUT);
#endif
  cueOff();
  randomSeed(analogRead(RANDOM_SEED_PIN));
  printStatus("ready");
}

void loop() {
  // 1-2. Wait for the lock press; the dial value at that moment is the claim.
  unsigned long lockAt = 0;
  if (!confirmedPress(lockAt)) {
    return;  // not pressed, or bounce / noise
  }
  int claim = readClaim();
  seq++;
  printStatus("locked");
  waitForRelease();

  // 3. Random wait; any press now is a false start.
  unsigned long waitMs = random(RANDOM_DELAY_MIN_MS, RANDOM_DELAY_MAX_MS + 1);
  unsigned long waitStart = millis();
  unsigned long pressAt = 0;
  while (millis() - waitStart < waitMs) {
    if (confirmedPress(pressAt)) {
      Serial.print(F("{\"type\":\"status\",\"state\":\"false_start\",\"into_wait_ms\":"));
      Serial.print(pressAt - waitStart);
      Serial.print(F(",\"wait_ms\":"));
      Serial.print(waitMs);
      Serial.println(F("}"));
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
  while (!confirmedPress(pressAt)) {
    if (millis() - cueAt >= REACTION_TIMEOUT_MS) {
      cueOff();
      printResult(claim, -1, false, true);
      waitForRelease();  // a late press must not count as the next lock press
      printStatus("ready");
      return;
    }
  }
  unsigned long reactionMs = pressAt - cueAt;
  cueOff();
  printResult(claim, (long)reactionMs, false, false);
  waitForRelease();
  printStatus("ready");
}
