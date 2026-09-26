/*
 * Delulu Detector - Round 1 (Reflex) + Round 2 (Steady Hands)
 * Arduino UNO R4 WiFi (also builds for a classic Uno) sketch. Reads sensors and prints ONE JSON object per line over
 * serial. No scoring or game logic lives here; the Raspberry Pi does all of it.
 *
 * Round selection (Pi -> Arduino, one short line, newline-terminated, CR ignored):
 *   R1  -> Reflex Round (the default after boot, so an Arduino with no Pi command behaves as before)
 *   R2  -> Steady Hands Round
 *   ?   -> just report the current mode
 * Every command is answered (between rounds) with
 *   {"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}
 * and anything else with {"type":"status","state":"error","error":"unknown_command"}.
 * Commands are only read between rounds; a round in progress finishes first.
 *
 * Round 1 flow (Reflex):
 *   1. IDLE: player turns the rotary dial to set a claim (0-100).
 *   2. Player presses the button -> claim is LOCKED (dial read at that instant).
 *   3. Random wait of RANDOM_DELAY_MIN_MS..RANDOM_DELAY_MAX_MS.
 *      Pressing during this wait = FALSE START (reported, round ends).
 *   4. CUE: onboard LED (pin 13) + full 12x8 LED matrix on the R4 WiFi
 *      + optional buzzer beep. No external LED needed.
 *   5. Measure ms from cue to button press (or time out after REACTION_TIMEOUT_MS).
 *
 * Round 2 flow (Steady Hands):
 *   1-2. Same claim lock as Round 1 (claim = claimed steadiness).
 *   3. After the button is released: "get ready" countdown of STEADY_COUNTDOWN_MS
 *      (3-2-1 on the R4 WiFi matrix, blinking L LED on a classic Uno).
 *   4. HOLD: matrix fully on + L LED for STEADY_HOLD_MS. The accelerometer is sampled
 *      every STEADY_SAMPLE_US. Button presses during the hold are ignored.
 *   5. Tremor metric, computed here with running sums (no sample buffer):
 *      actual = RMS over samples of |v_i - mean(v)| in mg, where v_i is the 3-axis
 *      reading. Subtracting the window's mean vector removes gravity and makes it
 *      orientation-independent. peak = largest |v_i - running mean of the samples
 *      before it| (after STEADY_PEAK_WARMUP samples), also in mg.
 *   Accelerometer: Grove 3-Axis Digital Accelerometer LIS3DHTR (0x19) on the Grove I2C port
 *   (main Wire bus, SDA/SCL). Auto-detected at boot (LIS3DH first, then ADXL345, MPU-6050),
 *   raw Wire register access, no extra libraries. If none is found, Round 2 reports
 *   an error result right after the lock press; Round 1 is unaffected.
 *
 * Serial: 115200 baud, 8N1, newline-terminated JSON.
 *
 * Result lines (the only lines the Pi scores):
 *   {"type":"result","round_id":1,"seq":3,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}
 *     false start: "actual":null,"false_start":true
 *     timeout:     "actual":null,"timeout":true
 *   {"type":"result","round_id":2,"seq":4,"claim":72,"actual":14.3,"unit":"mg_rms","peak":61.2,"samples":500,"false_start":false,"timeout":false}
 *     sensor problem: "actual":null,"peak":null,...,"error":"no_accel" (or "accel_read")
 * Informational lines (Pi ignores them, handy in the Serial Monitor):
 *   boot: {"type":"status","state":"ready","accel":"LIS3DH@0x19"}   ("accel":"none" if not found)
 *   {"type":"status","state":"ready"} / "locked" / "cue" / "countdown" / "hold"
 *   "locked" also carries the claim just read: {"type":"status","state":"locked","claim":72}
 * Live dial, only while waiting for the lock press (the browser UI shows it as the claim is set):
 *   {"type":"dial","value":57}
 *   Smoothed, sent when the value changes by 1 or more (with a little hysteresis so it doesn't
 *   flicker between two values), at most every DIAL_REPORT_MS, and once after boot, after every
 *   round and after every command so the Pi always has the current value. The claim that locks
 *   is this same smoothed value, so the number shown at rest is the number that locks.
 */

#include <Wire.h>

// ----------------------------- Pin / config -------------------------------
#define DIAL_PIN              A0     // Grove rotary angle sensor (SIG)
#define BUTTON_PIN            2      // Grove button (SIG) or tactile button
#define CUE_LED_PIN           LED_BUILTIN  // onboard "L" LED, no wiring needed
#define USE_BUZZER            1      // 0 if no buzzer is connected (harmless either way)
#define BUZZER_PIN            6      // Grove buzzer / piezo (optional)
#define RANDOM_SEED_PIN       A1     // leave UNCONNECTED (floating = noise seed)
// Accelerometer: any Grove I2C port (SDA/SCL = A4/A5). On the UNO R4 WiFi the Qwiic
// connector is Wire1; change this to Wire1 if you plug the sensor in there.
#define ACCEL_WIRE            Wire

// Grove button module outputs HIGH when pressed -> 0 (our hardware: idles LOW, HIGH when pressed).
// Plain tactile button wired pin->GND using INPUT_PULLUP -> 1.
#define BUTTON_ACTIVE_LOW     0

#define SERIAL_BAUD           115200
#define ROUND_REFLEX          1      // round TYPE ids, reported as "round_id"
#define ROUND_STEADY          2
#define DEFAULT_ROUND         ROUND_REFLEX   // mode after boot until the Pi sends R1 / R2
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
#define DIAL_SAMPLE_MS        10     // live dial: sample the pot this often while waiting for a claim
#define DIAL_SMOOTH_DIV       8      // exponential smoothing, new sample weight 1/8 (~80 ms time constant)
#define DIAL_REPORT_MS        100    // at most one {"type":"dial"} line this often
#define DIAL_HYST_TENTHS      3      // must move 0.3 past the next value's edge before it is reported

// Round 2 (Steady Hands)
#define STEADY_COUNTDOWN_MS   1500   // "get ready" 3-2-1 before the hold
#define STEADY_HOLD_MS        5000   // hold-still window
#define STEADY_SAMPLE_US      10000  // accelerometer sample period (10 ms = 100 Hz)
#define STEADY_PEAK_WARMUP    10     // samples before "peak" is tracked (running mean must settle)
#define STEADY_MIN_SAMPLE_PCT 80     // fewer good samples than this % of expected = "accel_read" error
#define I2C_TIMEOUT_US        25000  // a stuck I2C bus can't hang the sketch
// ---------------------------------------------------------------------------

#if defined(ARDUINO_UNOR4_WIFI)
#include "Arduino_LED_Matrix.h"
ArduinoLEDMatrix matrix;
const uint32_t MATRIX_ALL_ON[3]  = {0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF};
const uint32_t MATRIX_ALL_OFF[3] = {0, 0, 0};
// Round 2 countdown digits 3, 2, 1 (12x8, row-major, MSB first).
const uint32_t MATRIX_COUNTDOWN[3][3] = {
  {0x0F010800, 0x80300081, 0x080F0000},   // 3
  {0x0F010800, 0x80100600, 0x801F8000},   // 2
  {0x0600A002, 0x00200200, 0x200F8000},   // 1
};
#endif

unsigned long seq = 0;
uint8_t roundMode = DEFAULT_ROUND;

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

// ============================ Dial (claim) ============================
// One value is both what the browser shows ({"type":"dial"}) and what locks as the claim
// (readClaim()), so they can never disagree: the pot, smoothed in fixed point (ADC count
// * 256), mapped to 0-100 (floor, like map()), with a little hysteresis so it doesn't
// flicker between two neighbours. It is only updated between rounds (updateLiveDial()).
long dialSmooth = -1;                // -1 = not primed yet
int dialValue = -1;                  // the claim: shown live and locked by readClaim()
int dialReported = -1;               // last value sent to the Pi
bool dialForce = true;               // send the current value even if it didn't change
unsigned long dialSampleAt = 0;
unsigned long dialReportAt = 0;

void dialRequestReport() {
  dialForce = true;
}

void printDial(int value) {
  Serial.print(F("{\"type\":\"dial\",\"value\":"));
  Serial.print(value);
  Serial.println(F("}"));
}

// dialSmooth -> dialValue, with hysteresis around the current value.
void dialTrack() {
  const long fullScale = (long)DIAL_ADC_MAX * 256L;
  // "+ DIAL_SMOOTH_DIV" undoes the smoothing's integer lag (always under DIAL_SMOOTH_DIV
  // units), so the top of the pot still reaches 100.
  long tenths = (dialSmooth + DIAL_SMOOTH_DIV) * 1000L / fullScale;   // 0-1000
  tenths = constrain(tenths, 0L, 1000L);
  const int value = (int)(tenths / 10);
  if (dialValue < 0 || value == dialValue || value == 0 || value == 100) {
    dialValue = value;               // first value, no change, or the ends of the scale
  } else if (value > dialValue) {
    if (tenths >= (long)(dialValue + 1) * 10L + DIAL_HYST_TENTHS) {
      dialValue = value;
    }
  } else if (tenths < (long)dialValue * 10L - DIAL_HYST_TENTHS) {
    dialValue = value;
  }
}

// Restart the smoothing from a fresh 8-sample average (boot, and after each round, when
// the knob may have moved while it wasn't sampled). Hysteresis still applies, so a knob
// left alone keeps its value.
void dialPrime() {
  long raw = 0;
  for (int i = 0; i < 8; i++) {
    raw += analogRead(DIAL_PIN);
  }
  dialSmooth = raw * 256L / 8;
  dialSampleAt = millis();
  dialTrack();
}

void dialSample() {
  if (dialSmooth < 0) {
    dialPrime();
    return;
  }
  const unsigned long now = millis();
  if (now - dialSampleAt < DIAL_SAMPLE_MS) {
    return;
  }
  dialSampleAt = now;
  const long sample = (long)analogRead(DIAL_PIN) * 256L;
  dialSmooth += (sample - dialSmooth) / DIAL_SMOOTH_DIV;
  dialTrack();
}

// Called every loop() between rounds: sample, and report the value when it changed
// (or a report was requested), at most every DIAL_REPORT_MS.
void updateLiveDial() {
  dialSample();
  const unsigned long now = millis();
  if (now - dialReportAt < DIAL_REPORT_MS) {
    return;
  }
  if (dialForce || dialValue != dialReported) {
    printDial(dialValue);
    dialReported = dialValue;
    dialForce = false;
    dialReportAt = now;
  }
}

// The claim at the lock press: exactly the value the UI shows at rest (the live dial
// reports every change within DIAL_REPORT_MS, and "locked" carries this value too).
int readClaim() {
  if (dialValue < 0) {
    dialPrime();
  }
  return dialValue;
}

void printStatus(const char *state) {
  Serial.print(F("{\"type\":\"status\",\"state\":\""));
  Serial.print(state);
  Serial.println(F("\"}"));
}

// Round 1 result line. Byte-for-byte the same format as before Round 2 existed.
void printResult(int claim, long actualMs, bool falseStart, bool timedOut) {
  Serial.print(F("{\"type\":\"result\",\"round_id\":"));
  Serial.print(ROUND_REFLEX);
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

// ============================ Accelerometer (I2C) ============================
enum AccelKind : uint8_t { ACCEL_NONE = 0, ACCEL_LIS3DH, ACCEL_ADXL345, ACCEL_MPU6050 };

struct AccelCandidate {
  uint8_t addr;
  uint8_t idReg;
  uint8_t idValue;
  AccelKind kind;
};

// Probed in this order; the Grove LIS3DHTR at 0x19 (our hardware) comes first. The other
// parts are a cheap fallback for other Grove kits. None of these addresses overlap.
const AccelCandidate ACCEL_CANDIDATES[] = {
  {0x19, 0x0F, 0x33, ACCEL_LIS3DH},   // LIS3DH / LIS3DHTR (Grove default, our part)
  {0x18, 0x0F, 0x33, ACCEL_LIS3DH},
  {0x53, 0x00, 0xE5, ACCEL_ADXL345},  // ADXL345 (Grove default)
  {0x1D, 0x00, 0xE5, ACCEL_ADXL345},
  {0x68, 0x75, 0x68, ACCEL_MPU6050},  // MPU-6050 (AD0 low)
  {0x69, 0x75, 0x68, ACCEL_MPU6050},  // MPU-6050 (AD0 high)
};

AccelKind accelKind = ACCEL_NONE;
uint8_t accelAddr = 0;
float accelMgPerLsb = 1.0f;          // raw count -> mg

bool i2cWriteReg(uint8_t addr, uint8_t reg, uint8_t value) {
  ACCEL_WIRE.beginTransmission(addr);
  ACCEL_WIRE.write(reg);
  ACCEL_WIRE.write(value);
  return ACCEL_WIRE.endTransmission() == 0;
}

bool i2cReadRegs(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t len) {
  ACCEL_WIRE.beginTransmission(addr);
  ACCEL_WIRE.write(reg);
  if (ACCEL_WIRE.endTransmission() != 0) {
    return false;
  }
  uint8_t got = (uint8_t)ACCEL_WIRE.requestFrom(addr, len);
  if (got != len) {
    while (ACCEL_WIRE.available() > 0) {
      ACCEL_WIRE.read();
    }
    return false;
  }
  for (uint8_t i = 0; i < len; i++) {
    buf[i] = (uint8_t)ACCEL_WIRE.read();
  }
  return true;
}

bool i2cPresent(uint8_t addr) {
  ACCEL_WIRE.beginTransmission(addr);
  return ACCEL_WIRE.endTransmission() == 0;
}

// Put the detected part in +-2 g at 100 Hz output rate (matches the 100 Hz sampling). Returns false if a write fails.
// (kind is a plain uint8_t: the IDE's auto-generated prototypes land above the enum.)
bool configureAccel(uint8_t kind, uint8_t addr) {
  switch (kind) {
    case ACCEL_LIS3DH: {
      // Primary part: Grove 3-Axis Digital Accelerometer (LIS3DHTR) at 0x19.
      // CTRL_REG1 0x57: ODR 100 Hz, X/Y/Z on. CTRL_REG4 0x88: BDU (no torn samples), +-2 g,
      // high-res 12-bit = 1 mg/LSB. Same settings as the I2C scanner run on our board (plus BDU),
      // where it read ~980 mg at rest with 3-8 mg sample-to-sample jitter.
      // Both registers are read back so a half-configured sensor isn't reported as ready.
      accelMgPerLsb = 1.0f;          // readAccel() already shifts the left-justified 12-bit value
      uint8_t r1 = 0, r4 = 0;
      return i2cWriteReg(addr, 0x20, 0x57) && i2cWriteReg(addr, 0x23, 0x88) &&
             i2cReadRegs(addr, 0x20, &r1, 1) && i2cReadRegs(addr, 0x23, &r4, 1) &&
             r1 == 0x57 && r4 == 0x88;
    }
    case ACCEL_ADXL345:
      // POWER_CTL standby, DATA_FORMAT full-res +-2 g (3.9 mg/LSB), BW_RATE 100 Hz, POWER_CTL measure.
      accelMgPerLsb = 3.9f;
      return i2cWriteReg(addr, 0x2D, 0x00) && i2cWriteReg(addr, 0x31, 0x08) &&
             i2cWriteReg(addr, 0x2C, 0x0A) && i2cWriteReg(addr, 0x2D, 0x08);
    case ACCEL_MPU6050: {
      // PWR_MGMT_1: wake, PLL on gyro X. SMPLRT_DIV 9 + CONFIG DLPF 44 Hz -> 100 Hz. ACCEL_CONFIG +-2 g (16384 LSB/g).
      accelMgPerLsb = 1000.0f / 16384.0f;
      bool ok = i2cWriteReg(addr, 0x6B, 0x01);
      delay(10);
      return ok && i2cWriteReg(addr, 0x19, 0x09) && i2cWriteReg(addr, 0x1A, 0x03) &&
             i2cWriteReg(addr, 0x1C, 0x00);
    }
    default:
      return false;
  }
}

// Probe every candidate; remember the first one whose ID register matches and configures.
void detectAccel() {
  accelKind = ACCEL_NONE;
  accelAddr = 0;
  for (uint8_t i = 0; i < sizeof(ACCEL_CANDIDATES) / sizeof(ACCEL_CANDIDATES[0]); i++) {
    const AccelCandidate &c = ACCEL_CANDIDATES[i];
    if (!i2cPresent(c.addr)) {
      continue;
    }
    uint8_t id = 0;
    if (!i2cReadRegs(c.addr, c.idReg, &id, 1) || id != c.idValue) {
      continue;
    }
    if (configureAccel(c.kind, c.addr)) {
      accelKind = c.kind;
      accelAddr = c.addr;
      delay(80);                     // let the first conversions land (LIS3DH HR turn-on is 7/ODR = 70 ms)
      return;
    }
  }
}

// One reading in raw counts (multiply by accelMgPerLsb for mg).
bool readAccel(int16_t v[3]) {
  uint8_t b[6];
  switch (accelKind) {
    case ACCEL_LIS3DH:
      if (!i2cReadRegs(accelAddr, 0x28 | 0x80, b, 6)) return false;   // 0x80 = auto-increment
      for (uint8_t a = 0; a < 3; a++) {
        v[a] = (int16_t)((uint16_t)b[2 * a] | ((uint16_t)b[2 * a + 1] << 8)) / 16;  // 12-bit left-justified
      }
      return true;
    case ACCEL_ADXL345:
      if (!i2cReadRegs(accelAddr, 0x32, b, 6)) return false;
      for (uint8_t a = 0; a < 3; a++) {
        v[a] = (int16_t)((uint16_t)b[2 * a] | ((uint16_t)b[2 * a + 1] << 8));
      }
      return true;
    case ACCEL_MPU6050:
      if (!i2cReadRegs(accelAddr, 0x3B, b, 6)) return false;
      for (uint8_t a = 0; a < 3; a++) {
        v[a] = (int16_t)(((uint16_t)b[2 * a] << 8) | (uint16_t)b[2 * a + 1]);
      }
      return true;
    default:
      return false;
  }
}

void printAccelLabel() {
  switch (accelKind) {
    case ACCEL_LIS3DH:  Serial.print(F("LIS3DH@0x"));  break;
    case ACCEL_ADXL345: Serial.print(F("ADXL345@0x")); break;
    case ACCEL_MPU6050: Serial.print(F("MPU6050@0x")); break;
    default:            Serial.print(F("none"));       return;
  }
  if (accelAddr < 0x10) Serial.print('0');
  Serial.print(accelAddr, HEX);
}

// ============================ Tremor metric ============================
// Running sums in raw counts: exact integer math, ~50 bytes of RAM, no sample buffer.
// sum |v_i - mean|^2 = sum over axes of (n * sum(x^2) - sum(x)^2) / n
struct TremorStats {
  uint16_t n;
  int32_t sum[3];
  int64_t sumSq[3];
  float peakSq;                      // raw counts^2
};

TremorStats tremor;

void tremorReset() {
  memset(&tremor, 0, sizeof(tremor));
}

void tremorAdd(const int16_t v[3]) {
  if (tremor.n >= STEADY_PEAK_WARMUP) {
    float d2 = 0;
    for (uint8_t a = 0; a < 3; a++) {
      float d = (float)v[a] - (float)tremor.sum[a] / (float)tremor.n;   // vs running mean so far
      d2 += d * d;
    }
    if (d2 > tremor.peakSq) tremor.peakSq = d2;
  }
  for (uint8_t a = 0; a < 3; a++) {
    tremor.sum[a] += v[a];
    tremor.sumSq[a] += (int32_t)v[a] * (int32_t)v[a];
  }
  tremor.n++;
}

float tremorRmsMg() {
  if (tremor.n == 0) return 0;
  int64_t acc = 0;                   // n^2 * mean squared deviation, exact
  for (uint8_t a = 0; a < 3; a++) {
    acc += (int64_t)tremor.n * tremor.sumSq[a] - (int64_t)tremor.sum[a] * (int64_t)tremor.sum[a];
  }
  if (acc < 0) acc = 0;
  return sqrt((float)acc) / (float)tremor.n * accelMgPerLsb;
}

float tremorPeakMg() {
  return sqrt(tremor.peakSq) * accelMgPerLsb;
}

// ============================ Round selection ============================
void printModeStatus() {
  Serial.print(F("{\"type\":\"status\",\"state\":\"mode\",\"round_id\":"));
  Serial.print(roundMode);
  Serial.print(F(",\"accel\":\""));
  printAccelLabel();
  Serial.println(F("\"}"));
}

void handleCommand(char *cmd, bool overflow) {
  // trim spaces / tabs
  while (*cmd == ' ' || *cmd == '\t') cmd++;
  size_t len = strlen(cmd);
  while (len > 0 && (cmd[len - 1] == ' ' || cmd[len - 1] == '\t')) cmd[--len] = '\0';
  if (len == 0 && !overflow) {
    return;                          // blank line: ignore
  }
  if (!overflow && len == 2 && (cmd[0] == 'R' || cmd[0] == 'r') && (cmd[1] == '1' || cmd[1] == '2')) {
    roundMode = (cmd[1] == '1') ? ROUND_REFLEX : ROUND_STEADY;
    if (roundMode == ROUND_STEADY && accelKind == ACCEL_NONE) {
      detectAccel();                 // sensor may have been plugged in after boot
    }
    printModeStatus();
  } else if (!overflow && len == 1 && cmd[0] == '?') {
    printModeStatus();
  } else {
    Serial.println(F("{\"type\":\"status\",\"state\":\"error\",\"error\":\"unknown_command\"}"));
  }
  dialRequestReport();               // re-send the dial after every answer (the Pi may have just connected)
}

// Non-blocking: collect bytes until '\n' and act on the line. Only called between rounds.
void pollSerialCommands() {
  static char buf[8];
  static uint8_t len = 0;
  static bool overflow = false;
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[len] = '\0';
      handleCommand(buf, overflow);
      len = 0;
      overflow = false;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    } else {
      overflow = true;
    }
  }
}

// ============================ Rounds ============================
void playReflexRound(int claim) {
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

void printSteadyResult(int claim, bool ok, const char *error) {
  Serial.print(F("{\"type\":\"result\",\"round_id\":"));
  Serial.print(ROUND_STEADY);
  Serial.print(F(",\"seq\":"));
  Serial.print(seq);
  Serial.print(F(",\"claim\":"));
  Serial.print(claim);
  Serial.print(F(",\"actual\":"));
  if (ok) {
    Serial.print(tremorRmsMg(), 1);
  } else {
    Serial.print(F("null"));
  }
  Serial.print(F(",\"unit\":\"mg_rms\",\"peak\":"));
  if (ok) {
    Serial.print(tremorPeakMg(), 1);
  } else {
    Serial.print(F("null"));
  }
  Serial.print(F(",\"samples\":"));
  Serial.print(tremor.n);
  Serial.print(F(",\"false_start\":false,\"timeout\":false"));
  if (error != NULL) {
    Serial.print(F(",\"error\":\""));
    Serial.print(error);
    Serial.print('"');
  }
  Serial.println(F("}"));
}

void steadyCountdownFrame(uint8_t step, bool ledOn) {
  digitalWrite(CUE_LED_PIN, ledOn ? HIGH : LOW);
#if defined(ARDUINO_UNOR4_WIFI)
  matrix.loadFrame(MATRIX_COUNTDOWN[step]);
#else
  (void)step;
#endif
}

void steadyHoldOn() {
  digitalWrite(CUE_LED_PIN, HIGH);
#if defined(ARDUINO_UNOR4_WIFI)
  matrix.loadFrame(MATRIX_ALL_ON);
#endif
}

void playSteadyRound(int claim) {
  tremorReset();
  if (accelKind == ACCEL_NONE) {
    detectAccel();                   // one more try: maybe it was plugged in late
  }
  if (accelKind == ACCEL_NONE) {
    printSteadyResult(claim, false, "no_accel");
    waitForRelease();
    printStatus("ready");
    return;
  }

  // 3. Get-ready countdown: 3 frames. The L LED blinks once per frame.
  printStatus("countdown");
  const unsigned long stepMs = STEADY_COUNTDOWN_MS / 3;
  for (uint8_t step = 0; step < 3; step++) {
    unsigned long stepStart = millis();
    steadyCountdownFrame(step, true);
    while (millis() - stepStart < stepMs / 2) {}
    steadyCountdownFrame(step, false);
    while (millis() - stepStart < stepMs) {}
  }

  // 4. Hold window: fixed-rate sampling. Button presses are ignored.
  steadyHoldOn();
  printStatus("hold");
  const unsigned long holdUs = STEADY_HOLD_MS * 1000UL;
  const unsigned long expected = holdUs / STEADY_SAMPLE_US;
  const unsigned long startUs = micros();
  for (unsigned long i = 0; i < expected; i++) {
    const unsigned long dueUs = i * STEADY_SAMPLE_US;         // fixed schedule from the window start
    while (micros() - startUs < dueUs) {}
    if (micros() - startUs >= dueUs + STEADY_SAMPLE_US) {
      continue;                      // a slow read made us miss this slot entirely: skip it, don't burst
    }
    int16_t v[3];
    if (readAccel(v)) {
      tremorAdd(v);
    }
  }
  while (micros() - startUs < holdUs) {}                       // hold lasts the full window
  cueOff();
#if USE_BUZZER
  tone(BUZZER_PIN, BUZZER_FREQ_HZ, BUZZER_MS);    // "done" beep, after sampling ended
#endif

  // 5. Report.
  if ((unsigned long)tremor.n * 100UL < expected * STEADY_MIN_SAMPLE_PCT) {
    printSteadyResult(claim, false, "accel_read");
    accelKind = ACCEL_NONE;          // unplugged or flaky: probe the bus again next round
  } else {
    printSteadyResult(claim, true, NULL);
  }
  waitForRelease();
  printStatus("ready");
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

  ACCEL_WIRE.begin();
#if defined(ARDUINO_ARCH_AVR) || defined(ARDUINO_ARCH_RENESAS)
  ACCEL_WIRE.setWireTimeout(I2C_TIMEOUT_US, true);
#endif
  detectAccel();

  Serial.print(F("{\"type\":\"status\",\"state\":\"ready\",\"accel\":\""));
  printAccelLabel();
  Serial.println(F("\"}"));
}

void printLocked(int claim) {
  Serial.print(F("{\"type\":\"status\",\"state\":\"locked\",\"claim\":"));
  Serial.print(claim);
  Serial.println(F("}"));
}

void loop() {
  pollSerialCommands();              // R1 / R2 / ? from the Pi, only between rounds
  updateLiveDial();                  // {"type":"dial"} while the claim is being set

  // 1-2. Wait for the lock press; the dial value at that moment is the claim.
  unsigned long lockAt = 0;
  if (!confirmedPress(lockAt)) {
    return;  // not pressed, or bounce / noise
  }
  int claim = readClaim();
  seq++;
  printLocked(claim);
  waitForRelease();

  if (roundMode == ROUND_STEADY) {
    playSteadyRound(claim);
  } else {
    playReflexRound(claim);
  }
  dialPrime();                       // back to setting a claim: catch up with the knob
  dialRequestReport();               // and send the current value
}
