// 0.05 node: CoreS3 SE + Unit DMX.
// USB serial frames from the laptop -> wired DMX + ESP-NOW to AtomS3 receivers.
// Relays receiver heartbeats to the laptop. Runs the stored fallback looks when the laptop is away.
// Protocol: docs/PROTOCOL.md (v1.1).
//
// Every universe the laptop sends is kept: its last frame (resent to the receivers as a keep-alive),
// its own radio sequence number (so receivers on one universe don't count another universe's
// packets as lost), and up to MAX_FALLBACKS universes have their own fallback look. Fallback and
// blackout cover every universe, not just the node's own.

#include <Arduino.h>
#include <M5Unified.h>
#include <Preferences.h>

#include "config.h"
#include "dmx_out.h"
#include "proto.h"
#include "radio.h"

using namespace proto;

static Parser parser;
static DmxOut dmx;
static Preferences prefs;

static uint8_t my_mac[6];
static char my_name[NAME_LEN] = {0};
static uint8_t my_universe = 0;
static uint32_t net_id;
static uint8_t channel = RADIO_CHANNEL;

// per universe
static uint8_t frames[MAX_UNIVERSES][DMX_CHANNELS];  // last frame sent to each universe
static uint32_t seen_ms[MAX_UNIVERSES];             // when the laptop last sent it (0 = never)
static uint8_t radio_seq[MAX_UNIVERSES];

// fallback looks: slot i is for universe fb_universe[i]
static Fallback fallbacks[MAX_FALLBACKS];
static uint8_t fb_universe[MAX_FALLBACKS];
static uint8_t n_fallbacks = 0;

static uint8_t out_frame[DMX_CHANNELS];
static Mode mode = FALLBACK;  // boot straight into the safe default
static uint32_t boot_ms, last_frame_ms = 0, fallback_start_ms = 0;
static bool have_frame = false;

static uint32_t frames_rx = 0, other_errors = 0;
static uint32_t rate_count = 0, rate_window_start = 0;
static uint16_t frame_rate_x10 = 0;
static uint32_t next_beat_ms = 0;
static uint32_t radio_last_ms = 0;
static uint32_t identify_until_ms = 0;

// a channel change: keep telling the receivers on the old channel, then move
static uint8_t move_to = 0;
static uint32_t move_at_ms = 0, move_next_tell_ms = 0;

// ------------------------------------------------------------------ receivers (filled from the Wi-Fi task)

struct Receiver {
  uint8_t mac[6];
  uint32_t last_seen_ms;
  bool announced;
};
static Receiver receivers[MAX_RECEIVERS];
static int n_receivers = 0;

static constexpr int BEAT_QUEUE = 16;
static Heartbeat beat_queue[BEAT_QUEUE];
static volatile int beat_head = 0, beat_tail = 0;
static portMUX_TYPE beat_mux = portMUX_INITIALIZER_UNLOCKED;

static void on_radio(const uint8_t* mac, const uint8_t* data, int len) {
  if (!radio::valid(data, len, net_id)) return;
  const radio::Header* h = (const radio::Header*)data;
  if (h->kind != radio::HEARTBEAT || len != (int)sizeof(radio::Beat)) return;
  portENTER_CRITICAL(&beat_mux);
  int next = (beat_head + 1) % BEAT_QUEUE;
  if (next != beat_tail) {  // drop if full
    beat_queue[beat_head] = ((const radio::Beat*)data)->hb;
    beat_head = next;
  }
  portEXIT_CRITICAL(&beat_mux);
}

static Receiver* find_receiver(const uint8_t* mac) {
  for (int i = 0; i < n_receivers; i++)
    if (!memcmp(receivers[i].mac, mac, 6)) return &receivers[i];
  return nullptr;
}

// ------------------------------------------------------------------ USB out

static void usb_send(uint8_t type, const void* payload, uint16_t len) {
  static uint8_t buf[MAX_PAYLOAD + 6];
  size_t n = encode(buf, type, (const uint8_t*)payload, len);
  if (Serial.availableForWrite() >= (int)n) Serial.write(buf, n);  // never block DMX on a dead USB link
}

static void send_ack(uint8_t type, uint8_t code, bool has_req = false, uint8_t req = 0) {
  if (code != ACK_OK) other_errors++;
  uint8_t p[3] = {type, code, req};
  usb_send(MSG_ACK, p, has_req ? 3 : 2);  // v1.1: the request id comes back when one was sent
}

static void usb_log(const char* msg) { usb_send(MSG_LOG, msg, strlen(msg)); }

static uint8_t receivers_online() {
  uint8_t n = 0;
  uint32_t now = millis();
  for (int i = 0; i < n_receivers; i++)
    if (now - receivers[i].last_seen_ms < RECEIVER_ONLINE_MS) n++;
  return n;
}

static uint8_t status_flags() {
  return (PAIRING_KEY_DEV ? FLAG_DEV_KEY : 0) | (dmx.ok() ? 0 : FLAG_DMX_FAIL);
}

static void send_status() {
  Status s;
  s.uptime_ms = millis() - boot_ms;
  s.frames_rx = frames_rx;
  s.frame_rate_x10 = frame_rate_x10;
  s.crc_errors = parser.crc_errors;
  s.other_errors = other_errors;
  s.mode = mode;
  s.receivers_online = receivers_online();
  s.flags = status_flags();
  s.channel = channel;
  usb_send(MSG_STATUS, &s, sizeof(s));
}

static void send_own_beat(bool announce) {
  Heartbeat hb = {};
  memcpy(hb.mac, my_mac, 6);
  hb.node_type = DMX_TX;
  hb.fw[0] = FW_MAJOR; hb.fw[1] = FW_MINOR; hb.fw[2] = FW_PATCH;
  hb.uptime_s = (millis() - boot_ms) / 1000;
  hb.rssi = RSSI_NA;
  hb.loss_pct = LOSS_NA;
  hb.last_data_age_ms = have_frame ? millis() - last_frame_ms : AGE_NEVER;
  hb.universe = my_universe;
  memcpy(hb.name, my_name, NAME_LEN);
  usb_send(announce ? MSG_ANNOUNCE : MSG_HEARTBEAT, &hb, sizeof(hb));
}

// ------------------------------------------------------------------ radio out

static void radio_frame(uint8_t universe, const uint8_t* ch) {
  if (universe >= MAX_UNIVERSES) return;
  radio::DmxChunk c;
  radio::header(c.h, radio::DMX_CHUNK, net_id);
  c.universe = universe;
  c.seq = radio_seq[universe]++;  // per universe: receivers count gaps in their own universe only
  for (uint16_t off = 0; off < DMX_CHANNELS; off += radio::CHUNK_SIZE) {
    uint16_t len = min<uint16_t>(radio::CHUNK_SIZE, DMX_CHANNELS - off);
    c.offset = off;
    c.len = len;
    memcpy(c.data, ch + off, len);
    if (!radio_link::send(&c, offsetof(radio::DmxChunk, data) + len)) other_errors++;
  }
  radio_last_ms = millis();
}

// universes to keep alive: sent by the laptop lately, or with a fallback look of their own
static bool universe_active(uint8_t u, uint32_t now) {
  if (seen_ms[u] && now - seen_ms[u] < UNIVERSE_FORGET_MS) return true;
  for (uint8_t i = 0; i < n_fallbacks; i++)
    if (fb_universe[i] == u) return true;
  return false;
}

static Fallback* fallback_for(uint8_t u) {
  for (uint8_t i = 0; i < n_fallbacks; i++)
    if (fb_universe[i] == u) return &fallbacks[i];
  return nullptr;
}

static void tell_channel(uint8_t ch) {
  radio::SetChannel m;
  radio::header(m.h, radio::SET_CHANNEL, net_id);
  m.channel = ch;
  radio_link::send(&m, sizeof(m));
}

// ------------------------------------------------------------------ storage

static void load_prefs() {
  prefs.begin("node", true);
  prefs.getBytes("name", my_name, NAME_LEN);
  my_universe = prefs.getUChar("universe", 0);
  channel = prefs.getUChar("channel", RADIO_CHANNEL);
  if (!radio_link::valid_channel(channel)) channel = RADIO_CHANNEL;
  static uint8_t buf[1 + MAX_PAYLOAD];
  char key[4] = "fb0";
  for (uint8_t i = 0; i < MAX_FALLBACKS; i++) {
    key[2] = '0' + i;
    size_t len = prefs.getBytesLength(key);
    if (!len || len > sizeof(buf)) continue;
    prefs.getBytes(key, buf, len);
    if (fallbacks[n_fallbacks].parse(buf + 1, len - 1) == ACK_OK) fb_universe[n_fallbacks++] = buf[0];
  }
  if (!n_fallbacks) {  // firmware 0.1 kept one look, for the node's own universe
    size_t len = prefs.getBytesLength("fallback");
    if (len && len <= MAX_PAYLOAD) {
      prefs.getBytes("fallback", buf, len);
      if (fallbacks[0].parse(buf, len) == ACK_OK) fb_universe[n_fallbacks++] = my_universe;
    }
  }
  prefs.end();
}

static bool save_bytes(const char* key, const void* data, size_t len) {
  prefs.begin("node", false);
  bool ok = prefs.putBytes(key, data, len) == len;
  prefs.end();
  return ok;
}

// Store a fallback look for one universe (replacing its old one). Returns an AckCode.
static uint8_t set_fallback(uint8_t universe, const uint8_t* p, uint16_t len) {
  if (universe >= MAX_UNIVERSES) return ACK_BAD_VALUE;
  Fallback fb;
  uint8_t code = fb.parse(p, len);
  if (code != ACK_OK) return code;
  uint8_t slot = MAX_FALLBACKS;
  for (uint8_t i = 0; i < n_fallbacks; i++)
    if (fb_universe[i] == universe) slot = i;
  if (slot == MAX_FALLBACKS) {
    if (n_fallbacks == MAX_FALLBACKS) return ACK_BAD_VALUE;  // full: the laptop says which universes
    slot = n_fallbacks;
  }
  static uint8_t buf[1 + MAX_PAYLOAD];
  buf[0] = universe;
  memcpy(buf + 1, p, len);
  char key[4] = {'f', 'b', (char)('0' + slot), 0};
  if (!save_bytes(key, buf, len + 1)) return ACK_STORAGE_ERROR;
  fallbacks[slot] = fb;
  fb_universe[slot] = universe;
  if (slot == n_fallbacks) n_fallbacks++;
  return ACK_OK;
}

// ------------------------------------------------------------------ USB in

static void handle(uint8_t type, const uint8_t* p, uint16_t len) {
  uint32_t now = millis();
  bool has_req = false;
  uint8_t req = 0;
  switch (type) {
    case MSG_DMX_FRAME: {
      if (len < 2 || len > 1 + DMX_CHANNELS) return send_ack(type, ACK_BAD_LENGTH);
      uint8_t universe = p[0];
      static uint8_t frame[DMX_CHANNELS];
      memset(frame, 0, sizeof(frame));
      memcpy(frame, p + 1, len - 1);
      frames_rx++;
      rate_count++;
      have_frame = true;
      last_frame_ms = now;
      mode = LIVE;
      if (universe == my_universe) dmx.set(frame);  // immediate: drum hits don't wait for the tick
      if (universe < MAX_UNIVERSES) {
        memcpy(frames[universe], frame, DMX_CHANNELS);
        seen_ms[universe] = now ? now : 1;
        radio_frame(universe, frame);  // receivers on that universe
      }
      return;
    }
    case MSG_BLACKOUT: {
      if (len != 1) return send_ack(type, ACK_BAD_LENGTH);
      static const uint8_t black[DMX_CHANNELS] = {0};
      mode = BLACKOUT_MODE;
      have_frame = true;
      last_frame_ms = now;
      for (uint8_t u = 0; u < MAX_UNIVERSES; u++) {
        if (p[0] != UNIVERSE_ALL && p[0] != u) continue;
        memset(frames[u], 0, DMX_CHANNELS);  // the keep-alive goes on sending black
        if (u == my_universe) dmx.set(frames[u]);
        if (p[0] == u || universe_active(u, now)) radio_frame(u, black);  // every universe, not just ours
      }
      return;
    }
    case MSG_PING:
      if (len != 4) return send_ack(type, ACK_BAD_LENGTH);
      usb_send(MSG_PONG, p, 4);
      return;
    case MSG_STATUS_REQ:
      send_status();
      return;
    case MSG_SET_FALLBACK: {  // v1: the node's own universe
      uint16_t want = Fallback::size(p, len);
      if (!want || !request_len(len, want, p, has_req, req)) return send_ack(type, ACK_BAD_LENGTH);
      return send_ack(type, set_fallback(my_universe, p, want), has_req, req);
    }
    case MSG_SET_FALLBACK_U: {
      uint16_t want = len ? Fallback::size(p + 1, len - 1) : 0;
      if (!want || !request_len(len, want + 1, p, has_req, req)) return send_ack(type, ACK_BAD_LENGTH);
      return send_ack(type, set_fallback(p[0], p + 1, want), has_req, req);
    }
    case MSG_SET_CHANNEL: {
      if (!request_len(len, 1, p, has_req, req)) return send_ack(type, ACK_BAD_LENGTH);
      if (!radio_link::valid_channel(p[0])) return send_ack(type, ACK_BAD_VALUE, has_req, req);
      if (p[0] != channel) {
        prefs.begin("node", false);
        bool ok = prefs.putUChar("channel", p[0]);
        prefs.end();
        if (!ok) return send_ack(type, ACK_STORAGE_ERROR, has_req, req);
        move_to = p[0];  // tell the receivers on this channel first, then move (loop)
        move_at_ms = now + CHANNEL_MOVE_MS;
        move_next_tell_ms = now;
      }
      return send_ack(type, ACK_OK, has_req, req);
    }
    case MSG_ASSIGN: {
      if (!request_len(len, 6 + 1 + NAME_LEN, p, has_req, req)) return send_ack(type, ACK_BAD_LENGTH);
      if (!memcmp(p, my_mac, 6)) {
        memcpy(my_name, p + 7, NAME_LEN);
        my_universe = p[6] == UNIVERSE_NONE ? 0 : p[6];
        prefs.begin("node", false);
        bool ok = prefs.putBytes("name", my_name, NAME_LEN) == NAME_LEN && prefs.putUChar("universe", my_universe);
        prefs.end();
        return send_ack(type, ok ? ACK_OK : ACK_STORAGE_ERROR, has_req, req);
      }
      if (!find_receiver(p)) return send_ack(type, ACK_UNKNOWN_TARGET, has_req, req);
      radio::Assign a;
      radio::header(a.h, radio::ASSIGN, net_id);
      memcpy(a.mac, p, 6);
      a.universe = p[6];
      memcpy(a.name, p + 7, NAME_LEN);
      for (int i = 0; i < 3; i++) radio_link::send(&a, sizeof(a));  // broadcast is unacknowledged: repeat
      return send_ack(type, ACK_OK, has_req, req);  // the receiver's next heartbeat confirms it
    }
    case MSG_IDENTIFY: {
      if (!request_len(len, 7, p, has_req, req)) return send_ack(type, ACK_BAD_LENGTH);
      if (!memcmp(p, my_mac, 6)) {
        identify_until_ms = now + p[6] * 1000UL;  // the screen flashes
        return send_ack(type, ACK_OK, has_req, req);
      }
      if (!find_receiver(p)) return send_ack(type, ACK_UNKNOWN_TARGET, has_req, req);
      radio::Identify m;
      radio::header(m.h, radio::IDENTIFY, net_id);
      memcpy(m.mac, p, 6);
      m.seconds = p[6];
      for (int i = 0; i < 3; i++) radio_link::send(&m, sizeof(m));
      return send_ack(type, ACK_OK, has_req, req);
    }
    default:
      return send_ack(type, ACK_UNKNOWN_TYPE);
  }
}

// ------------------------------------------------------------------ screen

static void draw_screen(uint32_t now) {
  static uint32_t next_ms = 0;
  static char last[160] = "";
  if ((int32_t)(now - next_ms) < 0) return;
  next_ms = now + SCREEN_MS;
  bool ident = (int32_t)(identify_until_ms - now) > 0;
  static const char* modes[] = {"LIVE", "FALLBACK", "BLACKOUT"};
  char state[160];
  snprintf(state, sizeof(state), "%d|%s|%s|%u|%u|%u|%u|%d|%d", ident ? (int)((now / 250) % 2) : -1, my_name,
           modes[mode], my_universe, frame_rate_x10 / 10, receivers_online(), channel, (int)PAIRING_KEY_DEV,
           (int)dmx.ok());
  if (!strcmp(state, last)) return;  // nothing changed: don't spend time on the SPI bus
  strcpy(last, state);
  auto& d = M5.Display;
  if (ident) {
    d.fillScreen((now / 250) % 2 ? TFT_WHITE : TFT_BLACK);
    return;
  }
  d.startWrite();
  d.fillScreen(TFT_BLACK);
  d.setTextColor(TFT_WHITE, TFT_BLACK);
  d.setTextSize(3);
  d.setCursor(8, 8);
  d.print("0.05");
  d.setTextSize(2);
  d.setCursor(110, 14);
  d.print(my_name[0] ? my_name : "(new node)");
  uint16_t colour = mode == LIVE ? TFT_GREEN : mode == FALLBACK ? TFT_ORANGE : TFT_RED;
  d.setTextColor(colour, TFT_BLACK);
  d.setTextSize(4);
  d.setCursor(8, 56);
  d.print(modes[mode]);
  d.setTextColor(TFT_WHITE, TFT_BLACK);
  d.setTextSize(2);
  d.setCursor(8, 112);
  d.printf("Universe %u  %u fps", my_universe, frame_rate_x10 / 10);
  d.setCursor(8, 138);
  d.printf("Receivers %u  Ch %u", receivers_online(), channel);
  d.setCursor(8, 164);
  d.printf("Firmware %d.%d.%d", FW_MAJOR, FW_MINOR, FW_PATCH);
  if (!dmx.ok()) {
    d.setTextColor(TFT_RED, TFT_BLACK);
    d.setCursor(8, 190);
    d.print("DMX OUTPUT FAILED");
  }
  if (PAIRING_KEY_DEV) {
    d.setTextColor(TFT_YELLOW, TFT_BLACK);
    d.setCursor(8, 214);
    d.print("DEV PAIRING KEY");
  }
  d.endWrite();
}

// ------------------------------------------------------------------ main

void setup() {
  boot_ms = millis();
  auto cfg = M5.config();
  cfg.output_power = true;  // 5 V out on the Grove ports: the Unit DMX on PORT.C needs it
  cfg.serial_baudrate = 0;  // USB CDC below
  M5.begin(cfg);
  M5.Display.setRotation(1);
  Serial.setTxTimeoutMs(0);
  Serial.setRxBufferSize(4096);
  Serial.begin(115200);
  net_id = radio_link::net_id();
  load_prefs();
  if (!radio_link::begin(on_radio, channel)) other_errors++;
  radio_link::own_mac(my_mac);
  if (!dmx.begin()) other_errors++;
  fallback_start_ms = millis();
  send_own_beat(true);
  if (!dmx.ok()) usb_log("DMX driver failed to start: check DMX_TX_PIN / DMX_RX_PIN");
  if (PAIRING_KEY_DEV) usb_log("built with the development pairing key: set PAIRING_KEY for the gig");
}

void loop() {
  uint32_t now = millis();
  M5.update();
  if (M5.Touch.getCount() && M5.Touch.getDetail().wasPressed()) identify_until_ms = now + 3000;  // tap: show it's alive

  // USB in: drain everything available, handle each complete message immediately
  int n = Serial.available();
  while (n-- > 0) {
    parser.push(Serial.read());
    while (parser.next()) handle(parser.type, parser.payload, parser.len);
  }

  // channel change: tell the receivers a few times on the old channel, then move
  if (move_to) {
    if ((int32_t)(now - move_next_tell_ms) >= 0) {
      tell_channel(move_to);
      move_next_tell_ms = now + 50;
    }
    if ((int32_t)(now - move_at_ms) >= 0) {
      channel = move_to;
      move_to = 0;
      radio_link::set_channel(channel);
    }
  }

  // live -> fallback when the laptop goes quiet (blackout stays black: it's the panic button)
  Fallback* own = fallback_for(my_universe);
  uint16_t hold = own ? own->hold_ms : 2000;
  if (mode == LIVE && have_frame && now - last_frame_ms > hold) {
    mode = FALLBACK;
    fallback_start_ms = now;
    usb_log("no frames: fallback look running");
  }
  if (mode == FALLBACK && now - radio_last_ms >= DMX_REFRESH_MS) {
    for (uint8_t u = 0; u < MAX_UNIVERSES; u++) {  // every universe: its own look, or black
      if (u != my_universe && !universe_active(u, now)) continue;
      Fallback* fb = fallback_for(u);
      static Fallback none;  // invalid = black
      render_fallback(fb ? *fb : none, now - fallback_start_ms, out_frame);
      if (u == my_universe) dmx.set(out_frame);
      radio_frame(u, out_frame);
    }
  }
  dmx.service();

  // keep receivers fed when the laptop's frames are unchanged / slow (blackout: sends the black)
  if (mode != FALLBACK && now - radio_last_ms >= RADIO_KEEPALIVE_MS) {
    for (uint8_t u = 0; u < MAX_UNIVERSES; u++)
      if (u == my_universe || universe_active(u, now)) radio_frame(u, frames[u]);
  }

  // receiver heartbeats -> USB
  while (beat_tail != beat_head) {
    Heartbeat hb;
    portENTER_CRITICAL(&beat_mux);
    hb = beat_queue[beat_tail];
    beat_tail = (beat_tail + 1) % BEAT_QUEUE;
    portEXIT_CRITICAL(&beat_mux);
    Receiver* r = find_receiver(hb.mac);
    if (!r && n_receivers < MAX_RECEIVERS) {
      r = &receivers[n_receivers++];
      memcpy(r->mac, hb.mac, 6);
      r->announced = false;
    }
    bool announce = r && !r->announced;
    if (r) {
      r->last_seen_ms = now;
      r->announced = true;
    }
    usb_send(announce ? MSG_ANNOUNCE : MSG_HEARTBEAT, &hb, sizeof(hb));
  }

  // own heartbeat + status every second
  if ((int32_t)(now - next_beat_ms) >= 0) {
    next_beat_ms = now + HEARTBEAT_MS;
    uint32_t span = now - rate_window_start;
    frame_rate_x10 = span ? (uint16_t)min<uint32_t>(rate_count * 10000 / span, 65535) : 0;
    rate_count = 0;
    rate_window_start = now;
    send_own_beat(false);
    send_status();
  }
  draw_screen(now);
}
